"""VAL-02: timestamp column present, parseable, strictly increasing."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from thermavisualizer.core.models import ImportProfile
from thermavisualizer.core.validation import validate_files, validate_path


def test_duplicate_out_of_order_and_unparseable(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("val02_timestamps.csv"), ImportProfile())
    assert parsed is not None
    report = validate_files([parsed], [])
    val02 = [f for f in report.findings if f.code == "VAL-02"]
    text = " | ".join(f.message for f in val02)
    assert len(val02) == 3
    assert "1 unparseable" in text
    assert "1 duplicate" in text
    assert "1 out-of-order" in text


def test_missing_timestamp_column_reports_val02(tmp_path: Path) -> None:
    path = tmp_path / "no_ts.csv"
    path.write_text("Time,T1\n2024-01-01 00:00:00,1.0\n", encoding="utf-8")
    parsed, report = validate_path(path, ImportProfile())
    assert parsed is None
    assert report.codes() == {"VAL-01"}
