"""Reader tests: profiles, timestamps, encodings, immutability (DAT-01/02/08/09)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from thermavisualizer.core.models import ColumnType, ImportProfile, TemperatureUnit
from thermavisualizer.io.readers import ReaderError, read_data_file

DATA = Path(__file__).resolve().parents[1] / "data"


def test_read_simple_csv() -> None:
    parsed = read_data_file(DATA / "data_simple.csv", ImportProfile())
    assert parsed.row_count == 6
    assert parsed.encoding == "utf-8-sig"
    names = [column.name for column in parsed.columns]
    assert names == ["Timestamp", "T1", "T2", "T3", "RH1", "Notes"]
    assert parsed.column("Timestamp").column_type is ColumnType.TIMESTAMP
    assert parsed.column("T1").column_type is ColumnType.NUMERIC
    assert parsed.column("Notes").column_type is ColumnType.TEXT
    stamps = parsed.timestamp_array()
    assert stamps[0] == np.datetime64("2024-03-01T08:00:00")
    assert stamps[-1] == np.datetime64("2024-03-01T08:05:00")
    assert parsed.column("T1").values[0] == pytest.approx(20.1)


def test_raw_arrays_are_immutable() -> None:
    parsed = read_data_file(DATA / "data_simple.csv", ImportProfile())
    assert not parsed.column("T1").values.flags.writeable
    assert not parsed.timestamp_array().flags.writeable


def test_preview_row_limit() -> None:  # DAT-02
    parsed = read_data_file(DATA / "data_simple.csv", ImportProfile(), max_rows=2)
    assert parsed.row_count == 2


def test_euro_delimiter_decimal_and_strptime() -> None:
    profile = ImportProfile(
        delimiter=";",
        decimal=",",
        timestamp_column="Zeitstempel",
        timestamp_format="%d.%m.%Y %H:%M",
        timezone="Europe/Berlin",  # 2024-03-01 is winter time (UTC+1)
    )
    parsed = read_data_file(DATA / "data_euro.csv", profile)
    assert parsed.timestamp_array()[0] == np.datetime64("2024-03-01T08:00:00")
    assert parsed.column("S1").values[1] == pytest.approx(5.6)


def test_tz_aware_iso_converts_to_utc(tmp_path: Path) -> None:
    path = tmp_path / "aware.csv"
    path.write_text("Timestamp,T1\n2024-03-01T10:00:00+02:00,1.0\n", encoding="utf-8")
    parsed = read_data_file(path, ImportProfile())
    assert parsed.timestamp_array()[0] == np.datetime64("2024-03-01T08:00:00")


def test_excel_serial_timestamps() -> None:  # AGENTS pitfall: serial numbers
    profile = ImportProfile(timestamp_column="Time", timestamp_format="excel")
    parsed = read_data_file(DATA / "data_excel_serial.csv", profile)
    stamps = parsed.timestamp_array()
    assert stamps[0] == np.datetime64("2024-03-01T00:00:00")
    assert stamps[1] == np.datetime64("2024-03-01T06:00:00")
    assert stamps[2] == np.datetime64("2024-03-01T12:00:00")


def test_header_row_offset(tmp_path: Path) -> None:
    path = tmp_path / "junk.csv"
    path.write_text(
        "exported by tool\nversion 2\nTimestamp,T1\n2024-01-01 00:00:00,1.0\n",
        encoding="utf-8",
    )
    profile = ImportProfile(header_row=2)
    parsed = read_data_file(path, profile)
    assert parsed.row_count == 1
    assert parsed.column("T1").values[0] == pytest.approx(1.0)


def test_xlsx_roundtrip(tmp_path: Path) -> None:
    source = read_data_file(DATA / "data_simple.csv", ImportProfile())
    rows = [
        ["2024-03-01 08:00:00", "20.1", "45.2"],
        ["2024-03-01 08:01:00", "20.2", "45.1"],
    ]
    xlsx = tmp_path / "data.xlsx"
    pd.DataFrame(rows, columns=["Timestamp", "T1", "RH1"]).to_excel(xlsx, index=False)
    parsed = read_data_file(xlsx, ImportProfile())
    assert parsed.encoding == "excel"
    assert parsed.row_count == 2
    assert parsed.timestamp_array()[0] == np.datetime64("2024-03-01T08:00:00")
    assert parsed.column("T1").values[1] == pytest.approx(20.2)
    assert source.profile_name == parsed.profile_name


def test_encoding_fallback(tmp_path: Path) -> None:
    path = tmp_path / "cp1252.csv"
    path.write_bytes(
        "Timestamp,T1,Notes\n2024-01-01 00:00:00,1.0,pr\xe8s du capteur\n".encode("cp1252")
    )
    parsed = read_data_file(path, ImportProfile())
    assert parsed.encoding == "cp1252"
    assert parsed.column("T1").column_type is ColumnType.NUMERIC
    assert parsed.column("Notes").column_type is ColumnType.TEXT


def test_missing_timestamp_column_raises(tmp_path: Path) -> None:
    path = tmp_path / "no_ts.csv"
    path.write_text("Time,T1\n2024-01-01,1.0\n", encoding="utf-8")
    with pytest.raises(ReaderError, match="timestamp column 'Timestamp' not found"):
        read_data_file(path, ImportProfile())


def test_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("Timestamp,T1\n", encoding="utf-8")
    with pytest.raises(ReaderError, match="no data rows"):
        read_data_file(path, ImportProfile())


def test_unsupported_suffix_raises(tmp_path: Path) -> None:
    path = tmp_path / "notes.docx"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(ReaderError, match="DAT-09"):
        read_data_file(path, ImportProfile())


def test_xls_without_xlrd_gives_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "legacy.xls"
    path.write_bytes(b"\x00")

    def raise_import_error(*args: object, **kwargs: object) -> None:
        raise ImportError("Missing optional dependency 'xlrd'")

    monkeypatch.setattr(pd, "read_excel", raise_import_error)
    with pytest.raises(ReaderError, match="xlrd"):
        read_data_file(path, ImportProfile())


def test_unknown_timezone_raises(tmp_path: Path) -> None:
    path = tmp_path / "tz.csv"
    path.write_text("Timestamp,T1\n2024-01-01 00:00:00,1.0\n", encoding="utf-8")
    profile = ImportProfile(timezone="Not/AZone")
    with pytest.raises(ReaderError, match="timezone"):
        read_data_file(path, profile)


def test_temperature_unit_carried_from_profile() -> None:
    profile = ImportProfile(temperature_unit=TemperatureUnit.FAHRENHEIT)
    parsed = read_data_file(DATA / "data_simple.csv", profile)
    assert parsed.temperature_unit is TemperatureUnit.FAHRENHEIT
