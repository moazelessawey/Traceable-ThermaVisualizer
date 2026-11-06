"""VAL-01: file readable, encoding detected, non-empty."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from thermavisualizer.core.models import ImportProfile
from thermavisualizer.core.validation import validate_path


def test_empty_file_reports_val01(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("Timestamp,T1\n", encoding="utf-8")
    parsed, report = validate_path(path, ImportProfile())
    assert parsed is None
    assert report.codes() == {"VAL-01"}


def test_unsupported_suffix_reports_val01(tmp_path: Path) -> None:
    path = tmp_path / "notes.docx"
    path.write_text("x", encoding="utf-8")
    parsed, report = validate_path(path, ImportProfile())
    assert parsed is None
    assert report.codes() == {"VAL-01"}


def test_readable_file_has_no_structural_findings(data_path: Callable[[str], Path]) -> None:
    parsed, report = validate_path(data_path("data_simple.csv"), ImportProfile())
    assert parsed is not None
    assert report.findings == ()
