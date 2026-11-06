"""Auto-suggest and duplicate-detection tests (DAT-04, DAT-05)."""

from __future__ import annotations

import numpy as np

from thermavisualizer.core.mapping import (
    find_duplicate_column_mappings,
    suggest_logger_mappings,
)
from thermavisualizer.core.models import (
    ColumnType,
    DataColumn,
    LoggerMapping,
    ParsedFile,
    Quantity,
)


def _file(path: str, columns: list[str]) -> ParsedFile:
    cols = tuple(DataColumn(name, ColumnType.NUMERIC, np.zeros(2)) for name in columns)
    return ParsedFile(path=path, columns=cols, row_count=2, encoding="utf-8", profile_name="test")


def test_suggest_matches_logger_id_in_column_name() -> None:
    files = [_file("/a.csv", ["Timestamp", "L1", "L2"])]
    mappings = suggest_logger_mappings(["L1", "L2"], files)
    assert mappings[0].temperature_column == "L1"
    assert mappings[1].temperature_column == "L2"


def test_suggest_skips_non_numeric_columns() -> None:
    file = _file("/a.csv", ["Timestamp"])
    mappings = suggest_logger_mappings(["L1"], [file])
    assert mappings[0].temperature_column == ""


def test_suggest_no_match_gives_unmapped() -> None:
    files = [_file("/a.csv", ["Timestamp", "other"])]
    mappings = suggest_logger_mappings(["L1"], files)
    assert not mappings[0].has_temperature()
    assert not mappings[0].is_satisfied()


def test_suggest_does_not_assign_one_column_twice() -> None:
    files = [_file("/a.csv", ["L1"])]
    mappings = suggest_logger_mappings(["L1", "L1copy"], files)
    assert mappings[0].temperature_column == "L1"
    assert mappings[1].temperature_column == ""


def test_duplicate_detection() -> None:
    mappings = [
        LoggerMapping(logger_id="A", temperature_file="/a.csv", temperature_column="T1"),
        LoggerMapping(logger_id="B", temperature_file="/a.csv", temperature_column="T1"),
    ]
    duplicates = find_duplicate_column_mappings(mappings)
    assert len(duplicates) == 1
    file, column, quantity, ids = duplicates[0]
    assert (file, column, quantity) == ("/a.csv", "T1", Quantity.TEMPERATURE)
    assert sorted(ids) == ["A", "B"]


def test_duplicate_detection_ignores_excluded_and_distinct_quantities() -> None:
    mappings = [
        LoggerMapping(logger_id="A", temperature_file="/a.csv", temperature_column="T1"),
        LoggerMapping(
            logger_id="B", temperature_file="/a.csv", temperature_column="T1", excluded=True
        ),
        LoggerMapping(logger_id="C", humidity_file="/a.csv", humidity_column="T1"),
    ]
    assert find_duplicate_column_mappings(mappings) == []
