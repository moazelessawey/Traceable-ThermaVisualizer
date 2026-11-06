"""VAL-10: duplicate column mappings, conflicting quantities, mixed units."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from thermavisualizer.core.models import (
    ImportProfile,
    LoggerMapping,
    TemperatureUnit,
)
from thermavisualizer.core.validation import validate_files, validate_path


def test_duplicate_mapping_error(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("data_simple.csv"), ImportProfile())
    assert parsed is not None
    mappings = [
        LoggerMapping(logger_id="L1", temperature_file=parsed.path, temperature_column="T1"),
        LoggerMapping(logger_id="L2", temperature_file=parsed.path, temperature_column="T1"),
    ]
    report = validate_files([parsed], mappings)
    dupes = [f for f in report.findings if f.code == "VAL-10"]
    assert any("multiple loggers" in f.message for f in dupes)


def test_conflicting_quantities_error(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("data_simple.csv"), ImportProfile())
    assert parsed is not None
    mappings = [
        LoggerMapping(logger_id="L1", temperature_file=parsed.path, temperature_column="T1"),
        LoggerMapping(logger_id="L2", humidity_file=parsed.path, humidity_column="T1"),
    ]
    report = validate_files([parsed], mappings)
    assert any(
        f.code == "VAL-10" and "conflicting quantities" in f.message for f in report.findings
    )


def test_mixed_temperature_units_error(data_path: Callable[[str], Path]) -> None:
    celsius, _ = validate_path(data_path("data_simple.csv"), ImportProfile())
    fahrenheit, _ = validate_path(
        data_path("val10_units.csv"),
        ImportProfile(temperature_unit=TemperatureUnit.FAHRENHEIT),
    )
    assert celsius is not None and fahrenheit is not None
    mappings = [
        LoggerMapping(logger_id="L1", temperature_file=celsius.path, temperature_column="T1"),
        LoggerMapping(logger_id="L2", temperature_file=fahrenheit.path, temperature_column="F1"),
    ]
    report = validate_files([celsius, fahrenheit], mappings)
    assert any(f.code == "VAL-10" and "mixed units" in f.message for f in report.findings)
