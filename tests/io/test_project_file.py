"""Project file round-trip, integrity, and migration tests (EXP-05, PRD §6)."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest

import thermavisualizer.io.project_file as project_file
from thermavisualizer.core.alignment import AlignedDataset, ResampleMethod
from thermavisualizer.core.interpolation import InterpolationSettings
from thermavisualizer.core.models import (
    ColumnType,
    DataColumn,
    ImportProfile,
    Layer,
    Logger,
    LoggerMapping,
    LoggerRole,
    Obstacle,
    ObstacleShape,
    ObstacleType,
    ParsedFile,
    PolygonFootprint,
    Quantity,
    Severity,
    Space,
    Study,
    StudyType,
    TemperatureUnit,
)
from thermavisualizer.core.results import AcceptanceCriteria, StudyPeriod, evaluate_dataset
from thermavisualizer.core.slicing import SliceSpec, slice_spec_to_dict
from thermavisualizer.core.validation import ValidationFinding
from thermavisualizer.io.project_file import (
    ProjectFileError,
    ProjectSnapshot,
    load_project,
    save_project,
)
from thermavisualizer.rendering.colormaps import ColorScale, color_scale_to_dict
from thermavisualizer.services.audit import AuditAction, AuditService

L_SHAPE = PolygonFootprint(((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0)))


def _snapshot() -> ProjectSnapshot:
    space = Space(
        name="WH",
        footprint=L_SHAPE,
        height=3.0,
        layers=[
            Layer(
                name="low",
                height=0.5,
                loggers=[
                    Logger("L1", 0.5, 0.5, 0.5),
                    Logger("L2", 1.5, 0.5, 0.5, role=LoggerRole.CORNER, notes="near door"),
                ],
            )
        ],
        obstacles=[
            Obstacle(
                name="rack",
                obstacle_type=ObstacleType.RACK,
                shape=ObstacleShape.BOX,
                x=1.0,
                y=1.0,
                z=1.0,
                size_x=1.0,
                size_y=1.0,
                size_z=2.0,
                solid=True,
            )
        ],
    )
    stamps = np.array(["2024-03-01T08:00", "2024-03-01T08:01"], dtype="datetime64[ns]")
    stamps.flags.writeable = False
    numeric = np.array([20.0, 20.5])
    numeric.flags.writeable = False
    text = np.array(["a", "b"], dtype=object)
    text.flags.writeable = False
    raw = ParsedFile(
        path="/orig/data.csv",
        columns=(
            DataColumn("Timestamp", ColumnType.TIMESTAMP, stamps, unit="UTC"),
            DataColumn("T1", ColumnType.NUMERIC, numeric),
            DataColumn("Notes", ColumnType.TEXT, text),
        ),
        row_count=2,
        encoding="utf-8-sig",
        profile_name="Default",
        temperature_unit=TemperatureUnit.CELSIUS,
    )
    values = np.array([[20.0], [20.5]])
    values.flags.writeable = False
    aligned = AlignedDataset(
        times=stamps,
        logger_ids=("L1",),
        quantity=Quantity.TEMPERATURE,
        values=values,
        interval=np.timedelta64(60, "s"),
        method=ResampleMethod.LINEAR,
    )
    audit = AuditService("tester")
    audit.record(AuditAction.PROJECT_CREATE, "project", "create")
    audit.record(AuditAction.SPACE_CHANGED, "space", "edit")
    results = evaluate_dataset(stamps, ("L1",), values, AcceptanceCriteria(), Quantity.TEMPERATURE)
    return ProjectSnapshot(
        space=space,
        study=Study(title="Mapping Q1", protocol_id="P-1", study_type=StudyType.MAPPING),
        criteria=AcceptanceCriteria(),
        study_periods=(StudyPeriod("door", stamps[0], stamps[1]),),
        mappings=(LoggerMapping("L1", temperature_file="/orig/data.csv", temperature_column="T1"),),
        import_profiles=(ImportProfile(),),
        raw_files=(raw,),
        aligned=((Quantity.TEMPERATURE, aligned),),
        interpolation_settings=InterpolationSettings(),
        view_state={
            "slices": [slice_spec_to_dict(SliceSpec(spec_id="z"))],
            "color_scale": color_scale_to_dict(ColorScale()),
        },
        validation_findings=(
            ValidationFinding(Severity.INFO, "VAL-11", "coverage ok", file="data.csv"),
        ),
        results=results,
        audit_jsonl=audit.to_jsonl(),
    )


def _rewrite(path: Path, mutate: Callable[[dict[str, bytes], dict], None]) -> None:
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    mutate(members, manifest)
    members["manifest.json"] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


def test_save_load_roundtrip(tmp_path: Path) -> None:  # acceptance item 8
    snapshot = _snapshot()
    path = tmp_path / "study.tmap"
    save_project(path, snapshot, author="tester")
    loaded, warnings = load_project(path)
    assert warnings == []
    assert loaded.space == snapshot.space
    assert loaded.study == snapshot.study
    assert loaded.criteria == snapshot.criteria
    assert loaded.study_periods == snapshot.study_periods
    assert loaded.mappings == snapshot.mappings
    assert loaded.import_profiles == snapshot.import_profiles
    assert loaded.interpolation_settings == snapshot.interpolation_settings
    assert loaded.view_state == snapshot.view_state
    assert loaded.validation_findings == snapshot.validation_findings
    assert loaded.results == snapshot.results
    assert loaded.audit_jsonl == snapshot.audit_jsonl
    raw = loaded.raw_files[0]
    assert raw.path == "/orig/data.csv"
    assert not raw.column("T1").values.flags.writeable  # raw stays immutable
    assert np.array_equal(raw.column("T1").values, [20.0, 20.5])
    assert list(raw.column("Notes").values) == ["a", "b"]
    quantity, aligned = loaded.aligned[0]
    assert quantity is Quantity.TEMPERATURE
    assert aligned.logger_ids == ("L1",)
    assert np.array_equal(aligned.values[:, 0], [20.0, 20.5])


def test_no_temp_file_left_after_save(tmp_path: Path) -> None:
    save_project(tmp_path / "s.tmap", _snapshot(), author="tester")
    assert list(tmp_path.glob("*.tmp")) == []


def test_tampered_member_warns(tmp_path: Path) -> None:  # integrity
    path = tmp_path / "study.tmap"
    save_project(path, _snapshot(), author="tester")

    def mutate(members: dict[str, bytes], manifest: dict) -> None:
        members["config.json"] = members["config.json"] + b" "

    _rewrite(path, mutate)
    _snapshot_data, warnings = load_project(path)
    assert any("config.json" in w and "mismatch" in w for w in warnings)


def test_tampered_audit_chain_warns(tmp_path: Path) -> None:  # AUD-05
    path = tmp_path / "study.tmap"
    save_project(path, _snapshot(), author="tester")

    def mutate(members: dict[str, bytes], manifest: dict) -> None:
        text = members["audit_trail.jsonl"].decode("utf-8")
        text = text.replace('"summary": "create"', '"summary": "tampered"')
        members["audit_trail.jsonl"] = text.encode("utf-8")
        manifest["members"]["audit_trail.jsonl"] = hashlib.sha256(
            members["audit_trail.jsonl"]
        ).hexdigest()

    _rewrite(path, mutate)
    _snapshot_data, warnings = load_project(path)
    assert any("audit" in w and "chain" in w for w in warnings)


def test_newer_schema_rejected(tmp_path: Path) -> None:
    path = tmp_path / "future.tmap"
    save_project(path, _snapshot(), author="tester")

    def mutate(members: dict[str, bytes], manifest: dict) -> None:
        manifest["schema_version"] = 99

    _rewrite(path, mutate)
    with pytest.raises(ProjectFileError, match="newer"):
        load_project(path)


def test_migration_path_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "old.tmap"
    save_project(path, _snapshot(), author="tester")

    def mutate(members: dict[str, bytes], manifest: dict) -> None:
        manifest["schema_version"] = 0

    _rewrite(path, mutate)
    monkeypatch.setitem(project_file.MIGRATIONS, 0, lambda sections: sections)
    loaded, warnings = load_project(path)
    assert loaded.space.name == "WH"
    assert any("migrated" in w for w in warnings)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ProjectFileError):
        load_project(tmp_path / "absent.tmap")
