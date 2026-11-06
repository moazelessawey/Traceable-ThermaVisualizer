"""VAL-09: mapped columns exist; unmapped columns reported."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from thermavisualizer.core.models import ImportProfile, LoggerMapping, Severity
from thermavisualizer.core.validation import validate_files, validate_path


def test_missing_column_error(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("data_simple.csv"), ImportProfile())
    assert parsed is not None
    mapping = LoggerMapping(logger_id="L1", temperature_file=parsed.path, temperature_column="NOPE")
    report = validate_files([parsed], [mapping])
    errors = [f for f in report.findings if f.code == "VAL-09" and f.severity is Severity.ERROR]
    assert len(errors) == 1
    assert "NOPE" in errors[0].message


def test_missing_file_error(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("data_simple.csv"), ImportProfile())
    assert parsed is not None
    mapping = LoggerMapping(
        logger_id="L1", temperature_file="/absent/file.csv", temperature_column="T1"
    )
    report = validate_files([parsed], [mapping])
    errors = [f for f in report.findings if f.code == "VAL-09" and f.severity is Severity.ERROR]
    assert any("not loaded" in f.message for f in errors)


def test_unmapped_columns_info(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("data_simple.csv"), ImportProfile())
    assert parsed is not None
    mapping = LoggerMapping(logger_id="L1", temperature_file=parsed.path, temperature_column="T1")
    report = validate_files([parsed], [mapping])
    infos = [f for f in report.findings if f.code == "VAL-09" and f.severity is Severity.INFO]
    assert len(infos) == 1
    assert "T2" in infos[0].message and "T3" in infos[0].message
