"""Generic CSV/TXT/XLSX readers driven by import profiles (DAT-01/02/09).

Headless (no Qt). Timestamps are returned as naive-UTC datetime64; raw
arrays are read-only (data-integrity rule). Numeric values stay raw here —
unit conversion to °C happens via ``core.units`` at mapping time (DAT-08).
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from thermavisualizer.core.models import (
    ColumnType,
    DataColumn,
    ImportProfile,
    ParsedFile,
    TemperatureUnit,
)

logger = logging.getLogger(__name__)

_ENCODING_CANDIDATES = ("utf-8-sig", "cp1252", "latin-1")
_EXCEL_EPOCH = pd.Timestamp("1899-12-30")


class ReaderError(ValueError):
    """Raised when a data file cannot be read or lacks required structure."""


class TimestampError(ReaderError):
    """Raised when the timestamp column is missing or cannot be localized (VAL-02)."""


def read_data_file(path: Path, profile: ImportProfile, max_rows: int | None = None) -> ParsedFile:
    """Read one data file using ``profile`` (DAT-01).

    ``max_rows`` limits parsed data rows (used for previews, DAT-02).
    Raises ReaderError for unreadable, empty, or unsupported input (VAL-01).
    """
    path = Path(path)
    if not path.exists():
        raise ReaderError(f"file not found: {path}")
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        frame, encoding = _read_excel(path, profile, max_rows)
    elif suffix in (".csv", ".txt", ".dat", ""):
        frame, encoding = _read_delimited(path, profile, max_rows)
    else:
        raise ReaderError(f"unsupported file type '{suffix}' — only CSV, TXT, and XLSX (DAT-09)")
    if frame.empty:
        raise ReaderError(f"'{path.name}' contains no data rows (VAL-01)")

    if profile.timestamp_column not in {str(c) for c in frame.columns}:
        raise ReaderError(
            f"'{path.name}': timestamp column '{profile.timestamp_column}' not found "
            f"(available: {', '.join(str(c) for c in frame.columns)}) (VAL-02)"
        )

    columns = _build_columns(frame, profile, path)
    logger.info("read %s: %d row(s), %d column(s)", path.name, len(frame), len(columns))
    return ParsedFile(
        path=str(path),
        columns=tuple(columns),
        row_count=len(frame),
        encoding=encoding,
        profile_name=profile.name,
        temperature_unit=TemperatureUnit(str(profile.temperature_unit)),
    )


# ------------------------------------------------------------------ sources


def _read_excel(
    path: Path, profile: ImportProfile, max_rows: int | None
) -> tuple[pd.DataFrame, str]:
    try:
        frame = pd.read_excel(
            path, sheet_name=0, header=profile.header_row, dtype=str, nrows=max_rows
        )
    except ImportError as error:
        raise ReaderError(
            f"reading '{path.name}' (.xls) requires the 'xlrd' package; "
            "install xlrd or convert the file to .xlsx"
        ) from error
    except (OSError, ValueError) as error:
        raise ReaderError(f"cannot read '{path.name}': {error}") from error
    frame = frame.fillna("")
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame, "excel"


def _read_delimited(
    path: Path, profile: ImportProfile, max_rows: int | None
) -> tuple[pd.DataFrame, str]:
    raw = path.read_bytes()
    encoding = _detect_encoding(raw)
    text = raw.decode(encoding)
    try:
        frame = pd.read_csv(
            io.StringIO(text),
            sep=profile.delimiter,
            header=profile.header_row,
            dtype=str,
            keep_default_na=False,
            nrows=max_rows,
        )
    except (OSError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        raise ReaderError(f"cannot parse '{path.name}': {error}") from error
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame, encoding


def _detect_encoding(raw: bytes) -> str:
    """Return the first encoding that decodes the file (VAL-01)."""
    for candidate in _ENCODING_CANDIDATES:
        try:
            raw.decode(candidate)
            return candidate
        except UnicodeDecodeError:
            continue
    return "latin-1"


# ----------------------------------------------------------------- columns


def _build_columns(frame: pd.DataFrame, profile: ImportProfile, path: Path) -> list[DataColumn]:
    columns: list[DataColumn] = []
    for name in frame.columns:
        raw = frame[name]
        if str(name) == profile.timestamp_column:
            values = _parse_timestamps(raw, profile, path)
            columns.append(DataColumn(str(name), ColumnType.TIMESTAMP, values, unit="UTC"))
            continue
        numeric = _numeric_series(raw, profile.decimal)
        non_empty = raw.str.strip() != ""
        non_empty_count = int(non_empty.sum())
        parsed_count = int(numeric[non_empty].notna().sum())
        if non_empty_count > 0 and parsed_count * 2 > non_empty_count:
            array = numeric.to_numpy(dtype="float64")
            array.flags.writeable = False
            columns.append(DataColumn(str(name), ColumnType.NUMERIC, array))
            continue
        text = raw.to_numpy(dtype=object)
        text.flags.writeable = False
        columns.append(DataColumn(str(name), ColumnType.TEXT, text))
    return columns


def _numeric_series(series: pd.Series, decimal: str) -> pd.Series:
    text = series.str.strip()
    if decimal == ",":
        has_dot = text.str.contains(".", regex=False, na=False)
        has_comma = text.str.contains(",", regex=False, na=False)
        text = text.mask(has_dot & has_comma, text.str.replace(".", "", regex=False))
        text = text.str.replace(",", ".", regex=False)
    return pd.to_numeric(text, errors="coerce")


# -------------------------------------------------------------- timestamps


def _parse_timestamps(raw: pd.Series, profile: ImportProfile, path: Path) -> np.ndarray:
    """Parse the timestamp column; result is naive-UTC datetime64[ns]."""
    text = raw.str.strip()
    fmt = profile.timestamp_format
    try:
        if fmt == "excel":
            numbers = pd.to_numeric(text, errors="coerce")
            stamps = _EXCEL_EPOCH + pd.to_timedelta(numbers, unit="D")
        elif fmt in ("iso", ""):
            stamps = pd.to_datetime(text, errors="coerce")
        else:
            stamps = pd.to_datetime(text, errors="coerce", format=fmt)
    except (ValueError, TypeError) as error:
        raise ReaderError(
            f"'{path.name}': cannot parse timestamp column '{profile.timestamp_column}': {error}"
        ) from error
    stamps = _to_utc(stamps, profile.timezone, path)
    array = stamps.to_numpy(dtype="datetime64[ns]")
    array.flags.writeable = False
    return array


def _to_utc(stamps: pd.Series, timezone: str, path: Path) -> pd.Series:
    """Localize naive timestamps to ``timezone`` and convert to UTC."""
    if getattr(stamps.dt, "tz", None) is None:
        try:
            stamps = stamps.dt.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
        except Exception as error:
            raise ReaderError(
                f"'{path.name}': timezone '{timezone}' is unknown or the data "
                f"contains ambiguous/nonexistent DST times: {error}"
            ) from error
    return stamps.dt.tz_convert("UTC").dt.tz_localize(None)
