"""VAL-04: non-numeric/empty/NaN counts and percentages."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from thermavisualizer.core.models import ImportProfile, Severity
from thermavisualizer.core.validation import (
    ValidationOptions,
    validate_files,
    validate_path,
)


def test_nan_percentages_by_column(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("val04_nan.csv"), ImportProfile())
    assert parsed is not None
    report = validate_files([parsed], [])
    by_column = {(f.column, f.severity): f.message for f in report.findings if f.code == "VAL-04"}
    assert ("T_bad", Severity.ERROR) in by_column
    assert "60.0%" in by_column[("T_bad", Severity.ERROR)]
    assert ("T_mid", Severity.WARNING) in by_column
    assert "10.0%" in by_column[("T_mid", Severity.WARNING)]


def test_thresholds_are_configurable(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("val04_nan.csv"), ImportProfile())
    assert parsed is not None
    options = ValidationOptions(nan_error_pct=100.0)
    report = validate_files([parsed], [], options)
    severities = {f.column: f.severity for f in report.findings if f.code == "VAL-04"}
    assert severities["T_bad"] is Severity.WARNING
