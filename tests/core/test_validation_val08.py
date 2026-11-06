"""VAL-08: time overlap across mapped files."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from thermavisualizer.core.models import ImportProfile, LoggerMapping, Severity
from thermavisualizer.core.validation import validate_files, validate_path


def test_disjoint_periods_warn(data_path: Callable[[str], Path]) -> None:
    file_a, _ = validate_path(data_path("val08_a.csv"), ImportProfile())
    file_b, _ = validate_path(data_path("val08_b.csv"), ImportProfile())
    assert file_a is not None and file_b is not None
    mappings = [
        LoggerMapping(logger_id="LA", temperature_file=file_a.path, temperature_column="T1"),
        LoggerMapping(logger_id="LB", temperature_file=file_b.path, temperature_column="T2"),
    ]
    report = validate_files([file_a, file_b], mappings)
    val08 = [f for f in report.findings if f.code == "VAL-08"]
    assert len(val08) == 1
    assert val08[0].severity is Severity.WARNING


def test_overlapping_periods_report_common_window(data_path: Callable[[str], Path]) -> None:
    file_a, _ = validate_path(data_path("val08_a.csv"), ImportProfile())
    simple, _ = validate_path(data_path("data_simple.csv"), ImportProfile())
    assert file_a is not None and simple is not None
    mappings = [
        LoggerMapping(logger_id="LA", temperature_file=file_a.path, temperature_column="T1"),
        LoggerMapping(logger_id="LB", temperature_file=simple.path, temperature_column="T1"),
    ]
    report = validate_files([file_a, simple], mappings)
    infos = [f for f in report.findings if f.code == "VAL-08"]
    assert len(infos) == 1
    assert infos[0].severity is Severity.INFO
    assert "common window" in infos[0].message


def test_single_mapped_file_has_no_overlap_finding(data_path: Callable[[str], Path]) -> None:
    file_a, _ = validate_path(data_path("val08_a.csv"), ImportProfile())
    assert file_a is not None
    mapping = LoggerMapping(logger_id="LA", temperature_file=file_a.path, temperature_column="T1")
    assert "VAL-08" not in validate_files([file_a], [mapping]).codes()
