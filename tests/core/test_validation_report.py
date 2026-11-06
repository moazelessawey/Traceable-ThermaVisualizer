"""ValidationReport helpers and export rows (EXP-06 ground)."""

from __future__ import annotations

from thermavisualizer.core.models import Severity
from thermavisualizer.core.validation import ValidationFinding, ValidationReport


def _report() -> ValidationReport:
    return ValidationReport(
        (
            ValidationFinding(Severity.ERROR, "VAL-02", "bad stamps", file="a.csv"),
            ValidationFinding(Severity.WARNING, "VAL-03", "gap", file="a.csv"),
            ValidationFinding(Severity.INFO, "VAL-11", "coverage", file="a.csv"),
        )
    )


def test_accessors() -> None:
    report = _report()
    assert len(report.errors()) == 1
    assert len(report.warnings()) == 1
    assert len(report.infos()) == 1
    assert report.has_errors() is True
    assert report.codes() == {"VAL-02", "VAL-03", "VAL-11"}


def test_csv_rows() -> None:
    header, rows = _report().to_csv_rows()
    assert header == ("Severity", "Code", "File", "Column", "Message")
    assert rows[0] == ("error", "VAL-02", "a.csv", "", "bad stamps")
    assert len(rows) == 3
