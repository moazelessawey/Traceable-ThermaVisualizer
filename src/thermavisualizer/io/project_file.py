"""Project file (.tmap) read/write (EXP-05, PRD section 6).

Zip container: JSON sections plus Parquet data members. Versioned schema with
explicit forward migrations, SHA-256 integrity per member (warn on mismatch),
atomic saves (temp file then replace). No Qt, no pickle/eval (AGENTS §4).
Units are canonical: metres, °C, %RH, naive-UTC timestamps.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from thermavisualizer import __version__
from thermavisualizer.core.alignment import AlignedDataset, ResampleMethod
from thermavisualizer.core.interpolation import (
    ExtrapolationPolicy,
    InterpolationMethod,
    InterpolationSettings,
    RBFKernel,
)
from thermavisualizer.core.models import (
    BoxFootprint,
    ColumnType,
    DataColumn,
    ImportProfile,
    Layer,
    Logger,
    LoggerMapping,
    Obstacle,
    ParsedFile,
    PolygonFootprint,
    Quantity,
    Severity,
    Space,
    Study,
    TemperatureUnit,
)
from thermavisualizer.core.results import (
    AcceptanceCriteria,
    Excursion,
    ExcursionKind,
    LoggerResult,
    OverallResult,
    StudyPeriod,
    StudyResults,
)
from thermavisualizer.core.validation import ValidationFinding
from thermavisualizer.io.presets import (
    criteria_from_dict,
    criteria_to_dict,
)
from thermavisualizer.io.profile_store import (
    profile_from_dict,
    profile_to_dict,
)

SCHEMA_VERSION = 1
APP_NAME = "Traceable.ThermaVisualizer"
MANIFEST_NAME = "manifest.json"


class ProjectFileError(ValueError):
    """Raised when a project file is missing, corrupt, or unsupported."""


Migration = Callable[[dict], dict]
MIGRATIONS: dict[int, Migration] = {}  # schema version -> migration to next


@dataclass(frozen=True)
class ProjectSnapshot:
    """Everything a .tmap file stores, as plain data (no Qt)."""

    space: Space
    study: Study
    criteria: AcceptanceCriteria
    study_periods: tuple[StudyPeriod, ...]
    mappings: tuple[LoggerMapping, ...]
    import_profiles: tuple[ImportProfile, ...]
    raw_files: tuple[ParsedFile, ...]
    aligned: tuple[tuple[Quantity, AlignedDataset], ...]
    interpolation_settings: InterpolationSettings
    view_state: dict
    validation_findings: tuple[ValidationFinding, ...]
    results: StudyResults | None
    audit_jsonl: str


# ------------------------------------------------------------ serialization


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, indent=1, ensure_ascii=False, default=str).encode("utf-8")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def space_to_dict(space: Space) -> dict:
    """JSON-safe space incl. footprint, layers, loggers, obstacles (metres)."""
    footprint = space.footprint
    if isinstance(footprint, BoxFootprint):
        footprint_data = {
            "kind": "box",
            "x_min": footprint.x_min,
            "y_min": footprint.y_min,
            "x_max": footprint.x_max,
            "y_max": footprint.y_max,
        }
    else:
        footprint_data = {
            "kind": "polygon",
            "vertices": [[x, y] for x, y in footprint.vertices],
        }
    return {
        "name": space.name,
        "space_type": space.space_type.value,
        "height": space.height,
        "length_unit": space.length_unit.value,
        "footprint": footprint_data,
        "layers": [
            {
                "layer_id": layer.layer_id,
                "name": layer.name,
                "height": layer.height,
                "completed": layer.completed,
                "loggers": [
                    {
                        "logger_id": logger.logger_id,
                        "x": logger.x,
                        "y": logger.y,
                        "z": logger.z,
                        "role": logger.role.value,
                        "notes": logger.notes,
                    }
                    for logger in layer.loggers
                ],
            }
            for layer in space.layers
        ],
        "obstacles": [
            {
                "obstacle_id": obstacle.obstacle_id,
                "name": obstacle.name,
                "obstacle_type": obstacle.obstacle_type.value,
                "shape": obstacle.shape.value,
                "x": obstacle.x,
                "y": obstacle.y,
                "z": obstacle.z,
                "size_x": obstacle.size_x,
                "size_y": obstacle.size_y,
                "size_z": obstacle.size_z,
                "rotation_z_deg": obstacle.rotation_z_deg,
                "colour": obstacle.colour,
                "visible": obstacle.visible,
                "solid": obstacle.solid,
            }
            for obstacle in space.obstacles
        ],
    }


def space_from_dict(data: dict) -> Space:
    """Rebuild the space; enum fields normalize in model __post_init__."""
    footprint_data = data["footprint"]
    if footprint_data.get("kind") == "polygon":
        footprint = PolygonFootprint(
            tuple((float(x), float(y)) for x, y in footprint_data["vertices"])
        )
    else:
        footprint = BoxFootprint(
            float(footprint_data["x_min"]),
            float(footprint_data["y_min"]),
            float(footprint_data["x_max"]),
            float(footprint_data["y_max"]),
        )
    layers = [
        Layer(
            name=layer_data["name"],
            height=float(layer_data["height"]),
            layer_id=str(layer_data["layer_id"]),
            completed=bool(layer_data.get("completed", False)),
            loggers=[
                Logger(
                    logger_id=str(logger_data["logger_id"]),
                    x=float(logger_data["x"]),
                    y=float(logger_data["y"]),
                    z=float(logger_data["z"]),
                    role=logger_data.get("role", "none"),
                    notes=str(logger_data.get("notes", "")),
                )
                for logger_data in layer_data.get("loggers", [])
            ],
        )
        for layer_data in data.get("layers", [])
    ]
    obstacles = [
        Obstacle(
            name=str(o["name"]),
            obstacle_type=o["obstacle_type"],
            shape=o["shape"],
            x=float(o["x"]),
            y=float(o["y"]),
            z=float(o["z"]),
            size_x=float(o["size_x"]),
            size_y=float(o["size_y"]),
            size_z=float(o["size_z"]),
            obstacle_id=str(o["obstacle_id"]),
            rotation_z_deg=float(o.get("rotation_z_deg", 0.0)),
            colour=str(o.get("colour", "#8a8a8a")),
            visible=bool(o.get("visible", True)),
            solid=bool(o.get("solid", False)),
        )
        for o in data.get("obstacles", [])
    ]
    return Space(
        name=str(data.get("name", "Space")),
        space_type=data.get("space_type", "warehouse"),
        footprint=footprint,
        height=float(data.get("height", 3.0)),
        length_unit=data.get("length_unit", "m"),
        layers=layers,
        obstacles=obstacles,
    )


def study_to_dict(study: Study) -> dict:
    """JSON-safe study metadata (STY-01)."""
    return {
        "title": study.title,
        "protocol_id": study.protocol_id,
        "equipment_id": study.equipment_id,
        "location": study.location,
        "study_type": study.study_type.value,
        "performed_by": study.performed_by,
        "reviewer": study.reviewer,
        "start_date": study.start_date,
        "end_date": study.end_date,
        "notes": study.notes,
    }


def study_from_dict(data: dict) -> Study:
    """Rebuild study metadata."""
    return Study(
        title=str(data.get("title", "")),
        protocol_id=str(data.get("protocol_id", "")),
        equipment_id=str(data.get("equipment_id", "")),
        location=str(data.get("location", "")),
        study_type=data.get("study_type", "mapping"),
        performed_by=str(data.get("performed_by", "")),
        reviewer=str(data.get("reviewer", "")),
        start_date=str(data.get("start_date", "")),
        end_date=str(data.get("end_date", "")),
        notes=str(data.get("notes", "")),
    )


def _period_to_dict(period: StudyPeriod) -> dict:
    return {"name": period.name, "start": str(period.start), "end": str(period.end)}


def _period_from_dict(data: dict) -> StudyPeriod:
    return StudyPeriod(
        name=str(data["name"]),
        start=np.datetime64(data["start"]),
        end=np.datetime64(data["end"]),
    )


def mapping_to_dict(mapping: LoggerMapping) -> dict:
    return {
        "logger_id": mapping.logger_id,
        "temperature_file": mapping.temperature_file,
        "temperature_column": mapping.temperature_column,
        "humidity_file": mapping.humidity_file,
        "humidity_column": mapping.humidity_column,
        "excluded": mapping.excluded,
    }


def mapping_from_dict(data: dict) -> LoggerMapping:
    return LoggerMapping(
        logger_id=str(data["logger_id"]),
        temperature_file=str(data.get("temperature_file", "")),
        temperature_column=str(data.get("temperature_column", "")),
        humidity_file=str(data.get("humidity_file", "")),
        humidity_column=str(data.get("humidity_column", "")),
        excluded=bool(data.get("excluded", False)),
    )


def settings_to_dict(settings: InterpolationSettings) -> dict:
    return {
        "method": settings.method.value,
        "idw_power": settings.idw_power,
        "rbf_kernel": settings.rbf_kernel.value,
        "rbf_epsilon": settings.rbf_epsilon,
        "rbf_smoothing": settings.rbf_smoothing,
        "smoothing_sigma": settings.smoothing_sigma,
        "extrapolation": settings.extrapolation.value,
        "resolution": settings.resolution,
    }


def settings_from_dict(data: dict) -> InterpolationSettings:
    if not data:
        return InterpolationSettings()
    return InterpolationSettings(
        method=InterpolationMethod(str(data.get("method", "idw"))),
        idw_power=float(data.get("idw_power", 2.0)),
        rbf_kernel=RBFKernel(str(data.get("rbf_kernel", "thin_plate_spline"))),
        rbf_epsilon=float(data.get("rbf_epsilon", 1.0)),
        rbf_smoothing=float(data.get("rbf_smoothing", 0.0)),
        smoothing_sigma=float(data.get("smoothing_sigma", 0.0)),
        extrapolation=ExtrapolationPolicy(str(data.get("extrapolation", "mask"))),
        resolution=float(data.get("resolution", 0.2)),
    )


def _finding_to_dict(finding: ValidationFinding) -> dict:
    return {
        "severity": finding.severity.value,
        "code": finding.code,
        "message": finding.message,
        "file": finding.file,
        "column": finding.column,
    }


def _finding_from_dict(data: dict) -> ValidationFinding:
    return ValidationFinding(
        Severity(str(data["severity"])),
        str(data["code"]),
        str(data["message"]),
        file=str(data.get("file", "")),
        column=str(data.get("column", "")),
    )


def results_to_dict(results: StudyResults) -> dict:
    """Serialize results with their criteria/period stamp (RES-08)."""
    overall = results.overall
    return {
        "quantity": results.quantity.value,
        "criteria": criteria_to_dict(results.criteria),
        "period_start": str(results.period_start),
        "period_end": str(results.period_end),
        "logger_results": [
            {
                "logger_id": lr.logger_id,
                "samples": lr.samples,
                "minimum": lr.minimum,
                "maximum": lr.maximum,
                "mean": lr.mean,
                "std": lr.std,
                "mkt": lr.mkt,
                "out_of_limits_samples": lr.out_of_limits_samples,
                "out_of_limits_pct": lr.out_of_limits_pct,
                "excursion_count": lr.excursion_count,
                "longest_excursion_seconds": lr.longest_excursion_seconds,
                "passed": lr.passed,
            }
            for lr in results.logger_results
        ],
        "excursions": [
            {
                "logger_id": ex.logger_id,
                "kind": ex.kind.value,
                "start": str(ex.start),
                "end": str(ex.end),
                "duration_seconds": ex.duration_seconds,
                "peak": ex.peak,
            }
            for ex in results.excursions
        ],
        "overall": {
            "passed": overall.passed,
            "reason": overall.reason,
            "hottest_logger": overall.hottest_logger,
            "hottest_value": overall.hottest_value,
            "hottest_time": str(overall.hottest_time),
            "coldest_logger": overall.coldest_logger,
            "coldest_value": overall.coldest_value,
            "coldest_time": str(overall.coldest_time),
            "largest_spread": overall.largest_spread,
            "largest_spread_time": str(overall.largest_spread_time),
        },
    }


def results_from_dict(data: dict) -> StudyResults:
    """Rebuild results (stored as derived data; recomputable — RES-08)."""
    overall = data["overall"]
    return StudyResults(
        quantity=Quantity(str(data["quantity"])),
        criteria=criteria_from_dict(data["criteria"]),
        period_start=np.datetime64(data["period_start"]),
        period_end=np.datetime64(data["period_end"]),
        logger_results=tuple(
            LoggerResult(
                logger_id=str(lr["logger_id"]),
                samples=int(lr["samples"]),
                minimum=float(lr["minimum"]),
                maximum=float(lr["maximum"]),
                mean=float(lr["mean"]),
                std=float(lr["std"]),
                mkt=None if lr["mkt"] is None else float(lr["mkt"]),
                out_of_limits_samples=int(lr["out_of_limits_samples"]),
                out_of_limits_pct=float(lr["out_of_limits_pct"]),
                excursion_count=int(lr["excursion_count"]),
                longest_excursion_seconds=float(lr["longest_excursion_seconds"]),
                passed=bool(lr["passed"]),
            )
            for lr in data.get("logger_results", [])
        ),
        excursions=tuple(
            Excursion(
                logger_id=str(ex["logger_id"]),
                kind=ExcursionKind(str(ex["kind"])),
                start=np.datetime64(ex["start"]),
                end=np.datetime64(ex["end"]),
                duration_seconds=float(ex["duration_seconds"]),
                peak=float(ex["peak"]),
            )
            for ex in data.get("excursions", [])
        ),
        overall=OverallResult(
            passed=bool(overall["passed"]),
            reason=str(overall["reason"]),
            hottest_logger=str(overall["hottest_logger"]),
            hottest_value=float(overall["hottest_value"]),
            hottest_time=np.datetime64(overall["hottest_time"]),
            coldest_logger=str(overall["coldest_logger"]),
            coldest_value=float(overall["coldest_value"]),
            coldest_time=np.datetime64(overall["coldest_time"]),
            largest_spread=float(overall["largest_spread"]),
            largest_spread_time=np.datetime64(overall["largest_spread_time"]),
        ),
    )


# ---------------------------------------------------------- parquet members


def _raw_file_members(parsed: ParsedFile, index: int) -> tuple[dict[str, bytes], dict]:
    """Parquet + meta members for one raw file (raw data unmodified)."""
    frame: dict[str, np.ndarray] = {}
    columns_meta = []
    for column in parsed.columns:
        if column.column_type is ColumnType.TEXT:
            frame[column.name] = column.values.astype(str)
        else:
            frame[column.name] = column.values
        columns_meta.append(
            {"name": column.name, "type": column.column_type.value, "unit": column.unit}
        )
    buffer = io.BytesIO()
    pd.DataFrame(frame).to_parquet(buffer, index=False)
    meta = {
        "source_path": parsed.path,
        "profile_name": parsed.profile_name,
        "encoding": parsed.encoding,
        "temperature_unit": parsed.temperature_unit.value,
        "row_count": parsed.row_count,
        "columns": columns_meta,
    }
    members = {
        f"data/raw_{index}.parquet": buffer.getvalue(),
        f"data/raw_{index}.json": _json_bytes(meta),
    }
    return members, meta


def _raw_file_from_members(archive: zipfile.ZipFile, index: int, meta: dict) -> ParsedFile:
    frame = pd.read_parquet(io.BytesIO(archive.read(f"data/raw_{index}.parquet")))
    columns = []
    for column_meta in meta["columns"]:
        name = column_meta["name"]
        column_type = ColumnType(str(column_meta["type"]))
        series = frame[name]
        if column_type is ColumnType.TIMESTAMP:
            if getattr(series.dt, "tz", None) is not None:
                series = series.dt.tz_convert("UTC").dt.tz_localize(None)
            values = series.to_numpy(dtype="datetime64[ns]")
        elif column_type is ColumnType.NUMERIC:
            values = series.to_numpy(dtype="float64")
        else:
            values = series.astype(str).to_numpy(dtype=object)
        values.flags.writeable = False  # raw data stays immutable
        columns.append(DataColumn(name, column_type, values, unit=column_meta.get("unit", "")))
    return ParsedFile(
        path=str(meta["source_path"]),
        columns=tuple(columns),
        row_count=int(meta["row_count"]),
        encoding=str(meta["encoding"]),
        profile_name=str(meta["profile_name"]),
        temperature_unit=TemperatureUnit(str(meta["temperature_unit"])),
    )


def _aligned_members(quantity: Quantity, dataset: AlignedDataset) -> dict[str, bytes]:
    frame: dict[str, np.ndarray] = {"Timestamp": dataset.times}
    for index, logger_id in enumerate(dataset.logger_ids):
        frame[logger_id] = dataset.values[:, index]
    buffer = io.BytesIO()
    pd.DataFrame(frame).to_parquet(buffer, index=False)
    meta = {
        "logger_ids": list(dataset.logger_ids),
        "interval_ns": int(dataset.interval / np.timedelta64(1, "ns")),
        "method": dataset.method.value,
    }
    base = f"data/aligned_{quantity.value}"
    return {f"{base}.parquet": buffer.getvalue(), f"{base}.json": _json_bytes(meta)}


def _aligned_from_members(archive: zipfile.ZipFile, quantity: Quantity) -> AlignedDataset:
    base = f"data/aligned_{quantity.value}"
    meta = json.loads(archive.read(f"{base}.json"))
    frame = pd.read_parquet(io.BytesIO(archive.read(f"{base}.parquet")))
    series = frame["Timestamp"]
    if getattr(series.dt, "tz", None) is not None:
        series = series.dt.tz_convert("UTC").dt.tz_localize(None)
    times = series.to_numpy(dtype="datetime64[ns]")
    logger_ids = [str(logger_id) for logger_id in meta["logger_ids"]]
    values = np.column_stack([frame[lid].to_numpy(dtype="float64") for lid in logger_ids])
    times.flags.writeable = False
    values.flags.writeable = False
    return AlignedDataset(
        times=times,
        logger_ids=tuple(logger_ids),
        quantity=quantity,
        values=values,
        interval=np.timedelta64(int(meta["interval_ns"]), "ns"),
        method=ResampleMethod(str(meta["method"])),
    )


# ------------------------------------------------------------- save / load


def save_project(path: Path, snapshot: ProjectSnapshot, author: str) -> dict:
    """Write the .tmap atomically and return the manifest (EXP-05)."""
    members: dict[str, bytes] = {
        "config.json": _json_bytes({"space": space_to_dict(snapshot.space)}),
        "study.json": _json_bytes(
            {
                "study": study_to_dict(snapshot.study),
                "criteria": criteria_to_dict(snapshot.criteria),
                "periods": [_period_to_dict(p) for p in snapshot.study_periods],
                "event_markers": [],  # RES-06 structure; UI in a later milestone
            }
        ),
        "import_profiles.json": _json_bytes([profile_to_dict(p) for p in snapshot.import_profiles]),
        "processing.json": _json_bytes(
            {"interpolation": settings_to_dict(snapshot.interpolation_settings)}
        ),
        "view_state.json": _json_bytes(snapshot.view_state),
        "validation.json": _json_bytes(
            {"findings": [_finding_to_dict(f) for f in snapshot.validation_findings]}
        ),
        "results.json": _json_bytes(
            results_to_dict(snapshot.results) if snapshot.results is not None else None
        ),
        "audit_trail.jsonl": snapshot.audit_jsonl.encode("utf-8"),
    }
    raw_metas = []
    for index, parsed in enumerate(snapshot.raw_files):
        member_bytes, meta = _raw_file_members(parsed, index)
        members.update(member_bytes)
        raw_metas.append(meta)
    members["mapping.json"] = _json_bytes(
        {
            "files": raw_metas,
            "mappings": [mapping_to_dict(m) for m in snapshot.mappings],
        }
    )
    for quantity, dataset in snapshot.aligned:
        members.update(_aligned_members(quantity, dataset))

    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in members.items()}
    manifest = {
        "app": APP_NAME,
        "app_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "created": _utc_now_iso(),
        "modified": _utc_now_iso(),
        "author": author,
        "members": hashes,
    }
    members[MANIFEST_NAME] = _json_bytes(manifest)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    os.replace(temporary, path)  # atomic (AGENTS §4)
    return manifest


def apply_migrations(sections: dict, version: int) -> dict:
    """Apply explicit forward migrations up to SCHEMA_VERSION (PRD §6)."""
    while version < SCHEMA_VERSION:
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise ProjectFileError(f"no migration path from schema v{version}")
        sections = migration(sections)
        version += 1
    return sections


def _audit_chain_ok(text: str) -> bool:
    """True when the trail parses and its hash chain verifies (tamper check).

    Malformed trails (broken JSON, unknown action values) count as broken —
    integrity problems must degrade to warnings, never crashes (AGENTS §6).
    """
    from thermavisualizer.services.audit import AuditService  # pure module, no Qt

    try:
        return AuditService.from_jsonl(text, user_name="integrity-check").verify_chain()
    except (ValueError, KeyError, TypeError):
        return False


def load_project(path: Path) -> tuple[ProjectSnapshot, list[str]]:
    """Load and verify a .tmap; returns ``(snapshot, warnings)``.

    Hash mismatches, migrations, and audit-chain problems are warnings
    (acceptance item 8); unreadable/unknown files raise ProjectFileError.
    """
    path = Path(path)
    if not path.exists():
        raise ProjectFileError(f"project file not found: {path}")
    warnings: list[str] = []
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as error:
        raise ProjectFileError(f"'{path.name}' is not a valid .tmap archive") from error
    with archive:
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME))
        except KeyError as error:
            raise ProjectFileError("manifest.json is missing") from error
        version = int(manifest.get("schema_version", 0))
        if version > SCHEMA_VERSION:
            raise ProjectFileError(
                f"schema v{version} is newer than supported v{SCHEMA_VERSION}; "
                "update the application"
            )
        for name, expected in manifest.get("members", {}).items():
            try:
                data = archive.read(name)
            except KeyError:
                warnings.append(f"integrity: member '{name}' is missing")
                continue
            if hashlib.sha256(data).hexdigest() != expected:
                warnings.append(f"integrity: SHA-256 mismatch for '{name}'")

        def read_json(name: str, default: object = None) -> object:
            try:
                return json.loads(archive.read(name))
            except KeyError:
                return default

        sections = {
            "config": read_json("config.json"),
            "study": read_json("study.json", {}),
            "mapping": read_json("mapping.json", {"files": [], "mappings": []}),
            "import_profiles": read_json("import_profiles.json", []),
            "processing": read_json("processing.json", {}),
            "view_state": read_json("view_state.json", {}),
            "validation": read_json("validation.json", {"findings": []}),
            "results": read_json("results.json"),
        }
        if sections["config"] is None:
            raise ProjectFileError("config.json is missing")
        if version < SCHEMA_VERSION:
            sections = apply_migrations(sections, version)
            warnings.append(f"project migrated from schema v{version} to v{SCHEMA_VERSION}")

        audit_text = ""
        try:
            audit_text = archive.read("audit_trail.jsonl").decode("utf-8")
        except KeyError:
            warnings.append("audit trail is missing from the project file")
        if audit_text and not _audit_chain_ok(audit_text):
            warnings.append("audit trail hash chain is broken (possible tampering)")

        mapping_section = sections["mapping"]
        raw_files = [
            _raw_file_from_members(archive, index, meta)
            for index, meta in enumerate(mapping_section.get("files", []))
        ]
        aligned = []
        names = set(archive.namelist())
        for quantity in (Quantity.TEMPERATURE, Quantity.HUMIDITY):
            if f"data/aligned_{quantity.value}.parquet" in names:
                aligned.append((quantity, _aligned_from_members(archive, quantity)))

        study_section = sections["study"] or {}
        snapshot = ProjectSnapshot(
            space=space_from_dict(sections["config"]["space"]),
            study=study_from_dict(study_section.get("study", {})),
            criteria=criteria_from_dict(study_section.get("criteria", {})),
            study_periods=tuple(_period_from_dict(p) for p in study_section.get("periods", [])),
            mappings=tuple(mapping_from_dict(m) for m in mapping_section.get("mappings", [])),
            import_profiles=tuple(profile_from_dict(p) for p in sections["import_profiles"] or []),
            raw_files=tuple(raw_files),
            aligned=tuple(aligned),
            interpolation_settings=settings_from_dict(
                (sections["processing"] or {}).get("interpolation", {})
            ),
            view_state=sections["view_state"] or {},
            validation_findings=tuple(
                _finding_from_dict(f) for f in (sections["validation"] or {}).get("findings", [])
            ),
            results=results_from_dict(sections["results"]) if sections["results"] else None,
            audit_jsonl=audit_text,
        )
        return snapshot, warnings
