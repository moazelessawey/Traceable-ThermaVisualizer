"""VAL-03: sampling interval consistency and gaps."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from thermavisualizer.core.models import ImportProfile, Severity
from thermavisualizer.core.validation import validate_files, validate_path


def test_large_gap_warns(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("val03_gaps.csv"), ImportProfile())
    assert parsed is not None
    report = validate_files([parsed], [])
    gaps = [f for f in report.findings if f.code == "VAL-03"]
    assert len(gaps) == 1
    assert gaps[0].severity is Severity.WARNING
    assert "1 gap(s)" in gaps[0].message


def test_consistent_data_has_no_gap_finding(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("data_simple.csv"), ImportProfile())
    assert parsed is not None
    assert "VAL-03" not in validate_files([parsed], []).codes()
