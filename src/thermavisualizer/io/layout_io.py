"""CSV/XLSX import/export for logger layouts and footprint vertices.

Covers BLK-01 (import with mapping, preview data, validation, error report),
BLK-02 (export + template), and GEO-05 (footprint vertices). Headless: no Qt
imports (AGENTS rule). Units: metres for all coordinates.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from thermavisualizer.core.models import Layer, Logger, Severity

DEFAULT_LAYER_NAME = "Imported"
LAYOUT_COLUMNS = ("ID", "X", "Y", "Z", "Layer", "Notes")

_ID_ALIASES = ("id", "logger", "logger id", "logger_id", "label")
_X_ALIASES = ("x", "x (m)", "x_m")
_Y_ALIASES = ("y", "y (m)", "y_m")
_Z_ALIASES = ("z", "z (m)", "z_m", "height", "height (m)")
_LAYER_ALIASES = ("layer", "layer name", "level")
_NOTES_ALIASES = ("notes", "note", "comment", "remarks")

_TEMPLATE_EXAMPLE = ("L1", 0.5, 0.5, 0.5, "Layer 1", "example logger")


class LayoutIOError(ValueError):
    """Raised when a layout or footprint file cannot be read or interpreted."""


@dataclass(frozen=True)
class LayoutTable:
    """Raw tabular layout data: column names plus string cells."""

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    source: str = ""


@dataclass(frozen=True)
class LayoutMapping:
    """Maps logical layout fields to source column names (None = absent)."""

    logger_id: str | None = None
    x: str | None = None
    y: str | None = None
    z: str | None = None
    layer: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class LayoutRecord:
    """One parsed logger row ready for import. Units: metres."""

    logger_id: str
    x: float
    y: float
    z: float
    layer: str
    notes: str = ""


@dataclass(frozen=True)
class RowIssue:
    """Validation finding for one source row (BLK-01 error report)."""

    row: int  # 1-based data row, excluding the header
    severity: Severity
    code: str
    message: str


# ------------------------------------------------------------------ reading


def read_layout_table(
    path: Path, delimiter: str | None = None, sheet: int | str = 0
) -> LayoutTable:
    """Read a CSV/TXT/XLSX file into a LayoutTable of string cells.

    Delimited text uses UTF-8 (BOM tolerated); the delimiter is sniffed when
    ``delimiter`` is None. Excel reads the given sheet. Raises LayoutIOError
    for empty or unreadable files.
    """
    suffix = path.suffix.lower()
    try:
        if suffix in (".xlsx", ".xls"):
            frame = pd.read_excel(path, dtype=str, sheet_name=sheet).fillna("")
        else:
            text = path.read_text(encoding="utf-8-sig")
            if delimiter is None:
                delimiter = _detect_delimiter(text)
            frame = pd.read_csv(
                io.StringIO(text),
                sep=delimiter,
                dtype=str,
                keep_default_na=False,
            )
    except (OSError, pd.errors.ParserError, ValueError) as error:
        raise LayoutIOError(f"cannot read '{path.name}': {error}") from error
    columns = tuple(str(column).strip() for column in frame.columns)
    rows = tuple(
        tuple("" if value is None else str(value) for value in row)
        for row in frame.itertuples(index=False, name=None)
    )
    if not columns or not rows:
        raise LayoutIOError(f"'{path.name}' contains no data rows")
    return LayoutTable(columns=columns, rows=rows, source=path.name)


def _detect_delimiter(sample: str) -> str:
    """Detect the field delimiter.

    Prefers counting candidate delimiters in the header line (deterministic)
    and falls back to ``csv.Sniffer`` only for header-less files, since the
    sniffer is unreliable on small files with decimal commas in values.
    """
    candidates = (",", ";", "\t")
    header = sample.splitlines()[0] if sample else ""
    counts = {delimiter: header.count(delimiter) for delimiter in candidates}
    best = max(candidates, key=lambda delimiter: counts[delimiter])
    if counts[best] > 0:
        return best
    try:
        return csv.Sniffer().sniff(sample[:4096], delimiters=",;\t").delimiter
    except csv.Error:
        return ","


def suggest_mapping(columns: Sequence[str]) -> LayoutMapping:
    """Auto-suggest a field-to-column mapping from header names (BLK-01)."""
    lowered: dict[str, str] = {}
    for column in columns:
        lowered.setdefault(column.strip().lower(), column)

    def find(aliases: tuple[str, ...]) -> str | None:
        for alias in aliases:
            if alias in lowered:
                return lowered[alias]
        return None

    return LayoutMapping(
        logger_id=find(_ID_ALIASES),
        x=find(_X_ALIASES),
        y=find(_Y_ALIASES),
        z=find(_Z_ALIASES),
        layer=find(_LAYER_ALIASES),
        notes=find(_NOTES_ALIASES),
    )


def parse_layout_records(
    table: LayoutTable,
    mapping: LayoutMapping,
    *,
    decimal: str = ".",
    existing_ids: frozenset[str] = frozenset(),
) -> tuple[list[LayoutRecord], list[RowIssue]]:
    """Parse the table into records plus a row-level error report (BLK-01).

    Invalid rows are excluded from the records and reported as issues.
    ``decimal`` selects the decimal separator ('.' or ',').
    """
    required = {
        "logger ID": mapping.logger_id,
        "X": mapping.x,
        "Y": mapping.y,
        "Z": mapping.z,
    }
    missing = [label for label, column in required.items() if column is None]
    if missing:
        raise LayoutIOError(f"map the {', '.join(missing)} column(s) before importing")
    for column in (
        mapping.logger_id,
        mapping.x,
        mapping.y,
        mapping.z,
        mapping.layer,
        mapping.notes,
    ):
        if column is not None and column not in table.columns:
            raise LayoutIOError(f"mapped column '{column}' not found in file")

    index_of = {name: position for position, name in enumerate(table.columns)}
    records: list[LayoutRecord] = []
    issues: list[RowIssue] = []
    seen_ids = set(existing_ids)
    seen_positions: set[tuple[float, float, float]] = set()

    for row_number, row in enumerate(table.rows, start=1):

        def cell(column: str | None) -> str:
            if column is None:
                return ""
            position = index_of[column]
            return row[position].strip() if position < len(row) else ""

        if not any(value.strip() for value in row):
            continue  # skip blank lines silently
        raw_id = cell(mapping.logger_id)
        if not raw_id:
            issues.append(RowIssue(row_number, Severity.ERROR, "missing-id", "missing logger ID"))
            continue
        coordinates: list[float] = []
        failed = False
        for label, raw in (("X", cell(mapping.x)), ("Y", cell(mapping.y)), ("Z", cell(mapping.z))):
            value = _parse_number(raw, decimal)
            if value is None:
                code = "missing-coordinate" if not raw else "invalid-number"
                issues.append(
                    RowIssue(row_number, Severity.ERROR, code, f"invalid {label} value '{raw}'")
                )
                failed = True
            else:
                coordinates.append(value)
        if failed:
            continue
        if raw_id in seen_ids:
            issues.append(
                RowIssue(
                    row_number, Severity.ERROR, "duplicate-id", f"logger ID '{raw_id}' already used"
                )
            )
            continue
        position_key = (
            round(coordinates[0], 6),
            round(coordinates[1], 6),
            round(coordinates[2], 6),
        )
        if position_key in seen_positions:
            issues.append(
                RowIssue(
                    row_number,
                    Severity.ERROR,
                    "duplicate-coordinates",
                    f"position duplicates logger '{raw_id}'",
                )
            )
            continue
        seen_ids.add(raw_id)
        seen_positions.add(position_key)
        records.append(
            LayoutRecord(
                logger_id=raw_id,
                x=coordinates[0],
                y=coordinates[1],
                z=coordinates[2],
                layer=cell(mapping.layer) or DEFAULT_LAYER_NAME,
                notes=cell(mapping.notes),
            )
        )
    return records, issues


def _parse_number(raw: str, decimal: str) -> float | None:
    text = raw.strip().replace(" ", "")
    if not text:
        return None
    if decimal == ",":
        if "." in text:
            text = text.replace(".", "")  # thousands separator
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def records_to_layers(records: Sequence[LayoutRecord]) -> list[Layer]:
    """Group records into layers in first-appearance order.

    The layer height is the Z of its first logger; each logger keeps its own
    Z (CFG-05 override semantics).
    """
    layers: list[Layer] = []
    by_name: dict[str, Layer] = {}
    for record in records:
        layer = by_name.get(record.layer)
        if layer is None:
            layer = Layer(name=record.layer, height=record.z)
            by_name[record.layer] = layer
            layers.append(layer)
        layer.loggers.append(
            Logger(
                logger_id=record.logger_id,
                x=record.x,
                y=record.y,
                z=record.z,
                notes=record.notes,
            )
        )
    return layers


# ----------------------------------------------------------------- writing


def layout_rows(layers: Sequence[Layer]) -> list[tuple[str, float, float, float, str, str]]:
    """Flatten layers into export rows ``(ID, X, Y, Z, Layer, Notes)``."""
    rows: list[tuple[str, float, float, float, str, str]] = []
    for layer in layers:
        for logger in layer.loggers:
            rows.append((logger.logger_id, logger.x, logger.y, logger.z, layer.name, logger.notes))
    return rows


def export_layout_csv(path: Path, layers: Sequence[Layer]) -> None:
    """Write the layout to CSV (BLK-02)."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(LAYOUT_COLUMNS)
        writer.writerows(layout_rows(layers))


def export_layout_xlsx(path: Path, layers: Sequence[Layer]) -> None:
    """Write the layout to XLSX (BLK-02)."""
    frame = pd.DataFrame(layout_rows(layers), columns=list(LAYOUT_COLUMNS))
    frame.to_excel(path, index=False)


def export_layout(path: Path, layers: Sequence[Layer]) -> None:
    """Write the layout, choosing CSV or XLSX by file suffix (BLK-02)."""
    if path.suffix.lower() in (".xlsx", ".xls"):
        export_layout_xlsx(path, layers)
    else:
        export_layout_csv(path, layers)


def write_layout_template(path: Path) -> None:
    """Write a one-example import template (BLK-02)."""
    if path.suffix.lower() in (".xlsx", ".xls"):
        frame = pd.DataFrame([_TEMPLATE_EXAMPLE], columns=list(LAYOUT_COLUMNS))
        frame.to_excel(path, index=False)
        return
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(LAYOUT_COLUMNS)
        writer.writerow(_TEMPLATE_EXAMPLE)


# --------------------------------------------------------------- footprint


def read_footprint_vertices(path: Path, decimal: str = ".") -> list[tuple[float, float]]:
    """Read footprint vertices (x, y) in metres from CSV/TXT/XLSX (GEO-05).

    Uses columns named X/Y when present, otherwise the first two columns.
    Raises LayoutIOError for unreadable, too-small, or non-numeric input.
    """
    table = read_layout_table(path)
    mapping = suggest_mapping(table.columns)
    x_column, y_column = mapping.x, mapping.y
    if x_column is None or y_column is None:
        if len(table.columns) < 2:
            raise LayoutIOError("expected at least two columns (x, y)")
        x_column, y_column = table.columns[0], table.columns[1]
    x_index = table.columns.index(x_column)
    y_index = table.columns.index(y_column)
    vertices: list[tuple[float, float]] = []
    for row_number, row in enumerate(table.rows, start=1):
        raw_x = row[x_index].strip() if x_index < len(row) else ""
        raw_y = row[y_index].strip() if y_index < len(row) else ""
        if not raw_x and not raw_y:
            continue
        x = _parse_number(raw_x, decimal)
        y = _parse_number(raw_y, decimal)
        if x is None or y is None:
            raise LayoutIOError(
                f"row {row_number}: invalid vertex coordinates '{raw_x}', '{raw_y}'"
            )
        vertices.append((x, y))
    if len(vertices) < 3:
        raise LayoutIOError(f"footprint needs at least 3 vertices, found {len(vertices)}")
    return vertices


# ------------------------------------------------------------------ hashes


def file_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of a file (AUD-03 export records)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
