"""VAL-11: row count and coverage summary per logger."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from thermavisualizer.core.models import ImportProfile, LoggerMapping, Severity
from thermavisualizer.core.validation import validate_files, validate_path


def test_coverage_summary(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("data_simple.csv"), ImportProfile())
    assert parsed is not None
    mapping = LoggerMapping(logger_id="L1", temperature_file=parsed.path, temperature_column="T1")
    report = validate_files([parsed], [mapping])
    infos = [f for f in report.findings if f.code == "VAL-11"]
    assert len(infos) == 1
    assert infos[0].severity is Severity.INFO
    assert "6 of 6 samples valid" in infos[0].message
    assert "->" in infos[0].message


def test_excluded_logger_not_summarized(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("data_simple.csv"), ImportProfile())
    assert parsed is not None
    mappings = [
        LoggerMapping(logger_id="L1", temperature_file=parsed.path, temperature_column="T1"),
        LoggerMapping(logger_id="LX", excluded=True),
    ]
    report = validate_files([parsed], mappings)
    assert len([f for f in report.findings if f.code == "VAL-11"]) == 1
