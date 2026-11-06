"""Data-loading model tests (DAT-01/03/05)."""

from __future__ import annotations

import numpy as np

from thermavisualizer.core.models import (
    ColumnType,
    DataColumn,
    ImportProfile,
    LoggerMapping,
    ParsedFile,
    TemperatureUnit,
)


def test_import_profile_defaults_match_dat01() -> None:
    profile = ImportProfile()
    assert profile.delimiter == ","
    assert profile.decimal == "."
    assert profile.header_row == 0
    assert profile.timestamp_format == "iso"
    assert profile.timezone == "UTC"
    assert profile.temperature_unit is TemperatureUnit.CELSIUS


def test_logger_mapping_gate() -> None:  # DAT-03
    unmapped = LoggerMapping(logger_id="L1")
    assert not unmapped.is_satisfied()
    mapped = LoggerMapping(logger_id="L1", temperature_file="f.csv", temperature_column="T1")
    assert mapped.is_satisfied()
    excluded = LoggerMapping(logger_id="L2", excluded=True)
    assert excluded.is_satisfied()


def test_mapping_duplicate_pairs() -> None:  # DAT-05
    mapping = LoggerMapping(
        logger_id="L1",
        temperature_file="f.csv",
        temperature_column="T1",
        humidity_file="f.csv",
        humidity_column="RH1",
    )
    assert mapping.mapped_columns() == [("f.csv", "T1"), ("f.csv", "RH1")]


def test_parsed_file_helpers() -> None:
    stamps = np.array(["2024-01-01T00:00:00"], dtype="datetime64[ns]")
    parsed = ParsedFile(
        path="/tmp/a.csv",
        columns=(
            DataColumn("Timestamp", ColumnType.TIMESTAMP, stamps, unit="UTC"),
            DataColumn("T1", ColumnType.NUMERIC, np.array([20.0])),
            DataColumn("Notes", ColumnType.TEXT, np.array([""], dtype=object)),
        ),
        row_count=1,
        encoding="utf-8-sig",
        profile_name="Default",
    )
    assert parsed.name == "a.csv"
    assert parsed.timestamp_array() is stamps
    assert parsed.numeric_column_names() == ["T1"]
    assert parsed.column("missing") is None
