"""VAL-07: flat-line detection."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from thermavisualizer.core.models import ImportProfile, LoggerMapping
from thermavisualizer.core.validation import (
    ValidationOptions,
    validate_files,
    validate_path,
)


def test_flat_line_warned(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("val07_flatline.csv"), ImportProfile())
    assert parsed is not None
    mapping = LoggerMapping(logger_id="L1", temperature_file=parsed.path, temperature_column="T1")
    report = validate_files([parsed], [mapping])
    flat = [f for f in report.findings if f.code == "VAL-07"]
    assert len(flat) == 1
    assert "12 identical" in flat[0].message


def test_flat_line_length_configurable(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("val07_flatline.csv"), ImportProfile())
    assert parsed is not None
    mapping = LoggerMapping(logger_id="L1", temperature_file=parsed.path, temperature_column="T1")
    options = ValidationOptions(flatline_length=20)
    assert "VAL-07" not in validate_files([parsed], [mapping], options).codes()
