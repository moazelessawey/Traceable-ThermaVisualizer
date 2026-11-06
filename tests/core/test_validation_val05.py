"""VAL-05: physical plausibility ranges."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from thermavisualizer.core.models import ImportProfile, LoggerMapping, Severity
from thermavisualizer.core.validation import validate_files, validate_path


def test_out_of_range_values_flagged(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("val05_ranges.csv"), ImportProfile())
    assert parsed is not None
    mapping = LoggerMapping(
        logger_id="L1",
        temperature_file=parsed.path,
        temperature_column="Temp",
        humidity_file=parsed.path,
        humidity_column="RH",
    )
    report = validate_files([parsed], [mapping])
    val05 = [f for f in report.findings if f.code == "VAL-05"]
    assert len(val05) == 2
    assert all(f.severity is Severity.ERROR for f in val05)
    assert any(f.column == "Temp" and "2 value(s)" in f.message for f in val05)
    assert any(f.column == "RH" and "2 value(s)" in f.message for f in val05)


def test_unmapped_columns_skip_range_checks(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("val05_ranges.csv"), ImportProfile())
    assert parsed is not None
    assert "VAL-05" not in validate_files([parsed], []).codes()
