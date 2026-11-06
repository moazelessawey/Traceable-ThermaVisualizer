"""VAL-06: spike/outlier detection."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from thermavisualizer.core.models import ImportProfile, LoggerMapping
from thermavisualizer.core.validation import (
    ValidationOptions,
    validate_files,
    validate_path,
)


def _mapping(parsed) -> LoggerMapping:
    return LoggerMapping(logger_id="L1", temperature_file=parsed.path, temperature_column="T1")


def test_spikes_warned(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("val06_spikes.csv"), ImportProfile())
    assert parsed is not None
    report = validate_files([parsed], [_mapping(parsed)])
    spikes = [f for f in report.findings if f.code == "VAL-06"]
    assert len(spikes) == 1
    assert "2 jump(s)" in spikes[0].message


def test_spike_threshold_configurable(data_path: Callable[[str], Path]) -> None:
    parsed, _ = validate_path(data_path("val06_spikes.csv"), ImportProfile())
    assert parsed is not None
    options = ValidationOptions(spike_delta=30.0)
    report = validate_files([parsed], [_mapping(parsed)], options)
    assert "VAL-06" not in report.codes()
