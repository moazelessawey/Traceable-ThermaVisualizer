"""Alignment engine tests (DAT-06, DAT-07)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from thermavisualizer.core.alignment import (
    AlignmentError,
    AlignmentOptions,
    ResampleMethod,
    align_loggers,
    build_time_base,
    detect_interval,
    resample_series,
    time_range_indices,
    nearest_time_index,
    select_time_window,
)
from thermavisualizer.core.models import (
    ColumnType,
    DataColumn,
    ImportProfile,
    LoggerMapping,
    ParsedFile,
    Quantity,
    TemperatureUnit,
)
from thermavisualizer.io.readers import read_data_file

DATA = Path(__file__).resolve().parents[1] / "data"
MINUTE = np.timedelta64(60, "s")


def _stamps(start: str, count: int, step_minutes: int = 1) -> np.ndarray:
    base = np.datetime64(start, "ns")
    return base + np.arange(count) * np.timedelta64(step_minutes * 60, "s")


def _series_file(
    name: str,
    stamps: np.ndarray,
    values: np.ndarray,
    column: str = "T1",
    unit: TemperatureUnit = TemperatureUnit.CELSIUS,
) -> ParsedFile:
    stamps = np.asarray(stamps, dtype="datetime64[ns]")
    values = np.asarray(values, dtype="float64")
    return ParsedFile(
        path=f"/mem/{name}",
        columns=(
            DataColumn("Timestamp", ColumnType.TIMESTAMP, stamps, unit="UTC"),
            DataColumn(column, ColumnType.NUMERIC, values),
        ),
        row_count=stamps.size,
        encoding="memory",
        profile_name="test",
        temperature_unit=unit,
    )


# ------------------------------------------------------------- primitives


def test_detect_interval_returns_mode() -> None:
    minute = _stamps("2024-03-01T08:00", 5)  # 4 x 60 s
    two_minute = _stamps("2024-03-02T08:00", 4, 2)  # 3 x 120 s
    combined = np.concatenate([minute, two_minute])
    assert detect_interval([combined]) == MINUTE


def test_detect_interval_requires_data() -> None:
    with pytest.raises(AlignmentError):
        detect_interval([np.array([], dtype="datetime64[ns]")])


def test_build_time_base_is_inclusive() -> None:
    times = build_time_base(
        np.datetime64("2024-03-01T08:00", "ns"),
        np.datetime64("2024-03-01T08:05", "ns"),
        MINUTE,
    )
    assert times.size == 6
    assert times[0] == np.datetime64("2024-03-01T08:00")
    assert times[-1] == np.datetime64("2024-03-01T08:05")


def test_linear_reproduces_linear_field_exactly() -> None:  # AGENTS §8
    stamps = _stamps("2024-03-01T08:00", 5)
    values = np.array([0.0, 2.0, 4.0, 6.0, 8.0])  # 2 °C per minute
    times = build_time_base(stamps[0], stamps[-1], np.timedelta64(30, "s"))
    out = resample_series(stamps, values, times, ResampleMethod.LINEAR, np.timedelta64(180, "s"))
    assert np.allclose(out, np.arange(times.size) * 1.0, atol=1e-12)


def test_linear_does_not_bridge_large_gaps_or_extrapolate() -> None:
    stamps = np.array(
        ["2024-03-01T08:00", "2024-03-01T08:01", "2024-03-01T08:11", "2024-03-01T08:12"],
        dtype="datetime64[ns]",
    )
    values = np.array([10.0, 10.5, 20.0, 20.5])
    times = build_time_base(stamps[0], stamps[-1], MINUTE)
    out = resample_series(stamps, values, times, ResampleMethod.LINEAR, np.timedelta64(180, "s"))
    assert out[0] == pytest.approx(10.0)
    assert out[1] == pytest.approx(10.5)
    assert np.isnan(out[2:11]).all()  # 10-min gap > 3-min max gap
    assert out[11] == pytest.approx(20.0)
    assert out[12] == pytest.approx(20.5)


def test_linear_bridges_nan_samples_within_max_gap() -> None:
    stamps = _stamps("2024-03-01T08:00", 5)
    values = np.array([10.0, np.nan, np.nan, 13.0, 14.0])
    times = stamps
    out = resample_series(stamps, values, times, ResampleMethod.LINEAR, np.timedelta64(300, "s"))
    assert out[1] == pytest.approx(11.0)
    assert out[2] == pytest.approx(12.0)


def test_nearest_picks_closer_sample_and_masks_far_points() -> None:
    stamps = np.array(["2024-03-01T08:00", "2024-03-01T08:10"], dtype="datetime64[ns]")
    values = np.array([10.0, 20.0])
    times = np.array(
        ["2024-03-01T08:04", "2024-03-01T08:06", "2024-03-01T08:30"],
        dtype="datetime64[ns]",
    )
    out = resample_series(stamps, values, times, ResampleMethod.NEAREST, np.timedelta64(600, "s"))
    assert out[0] == 10.0  # 4 min to the left sample
    assert out[1] == 20.0  # 4 min to the right sample
    assert np.isnan(out[2])  # 20 min from any sample > max_gap / 2


def test_nearest_tie_goes_to_earlier_sample() -> None:
    stamps = np.array(["2024-03-01T08:00", "2024-03-01T08:10"], dtype="datetime64[ns]")
    values = np.array([10.0, 20.0])
    times = np.array(["2024-03-01T08:05"], dtype="datetime64[ns]")
    out = resample_series(stamps, values, times, ResampleMethod.NEAREST, np.timedelta64(1200, "s"))
    assert out[0] == 10.0


# --------------------------------------------------------------- pipeline


def test_align_merges_multiple_files() -> None:  # DAT-06
    file_a = _series_file(
        "a.csv", _stamps("2024-03-01T08:00", 4), np.array([20.0, 20.2, 20.4, 20.6])
    )
    file_b = _series_file(
        "b.csv", _stamps("2024-03-01T08:00", 4), np.array([21.0, 21.2, 21.4, 21.6])
    )
    mappings = [
        LoggerMapping(logger_id="L1", temperature_file="/mem/a.csv", temperature_column="T1"),
        LoggerMapping(logger_id="L2", temperature_file="/mem/b.csv", temperature_column="T1"),
    ]
    aligned = align_loggers([file_a, file_b], mappings)
    assert aligned.logger_ids == ("L1", "L2")
    assert aligned.quantity is Quantity.TEMPERATURE
    assert aligned.interval == MINUTE
    assert aligned.times.size == 4
    assert aligned.values[:, 0] == pytest.approx([20.0, 20.2, 20.4, 20.6])
    assert aligned.values[:, 1] == pytest.approx([21.0, 21.2, 21.4, 21.6])


def test_time_base_covers_union_and_masks_outside_ranges() -> None:
    early = _series_file("early.csv", _stamps("2024-03-01T08:00", 3), np.array([1.0, 2.0, 3.0]))
    late = _series_file("late.csv", _stamps("2024-03-01T08:05", 3), np.array([4.0, 5.0, 6.0]))
    mappings = [
        LoggerMapping(logger_id="LE", temperature_file="/mem/early.csv", temperature_column="T1"),
        LoggerMapping(logger_id="LL", temperature_file="/mem/late.csv", temperature_column="T1"),
    ]
    aligned = align_loggers([early, late], mappings)
    assert aligned.times.size == 8  # 08:00..08:07 union at 60 s
    assert aligned.values[:3, 0] == pytest.approx([1.0, 2.0, 3.0])
    assert np.isnan(aligned.values[3:, 0]).all()
    assert np.isnan(aligned.values[:5, 1]).all()
    assert aligned.values[5:, 1] == pytest.approx([4.0, 5.0, 6.0])


def test_temperature_converted_to_celsius() -> None:  # DAT-08
    fahrenheit = _series_file(
        "f.csv",
        _stamps("2024-03-01T08:00", 2),
        np.array([32.0, 212.0]),
        unit=TemperatureUnit.FAHRENHEIT,
    )
    mapping = LoggerMapping(logger_id="L1", temperature_file="/mem/f.csv", temperature_column="T1")
    aligned = align_loggers([fahrenheit], [mapping])
    assert aligned.values[:, 0] == pytest.approx([0.0, 100.0])


def test_explicit_interval_and_method() -> None:
    file = _series_file("c.csv", _stamps("2024-03-01T08:00", 4), np.array([1.0, 2.0, 3.0, 4.0]))
    mapping = LoggerMapping(logger_id="L1", temperature_file="/mem/c.csv", temperature_column="T1")
    options = AlignmentOptions(interval=np.timedelta64(30, "s"), method=ResampleMethod.NEAREST)
    aligned = align_loggers([file], [mapping], options=options)
    assert aligned.interval == np.timedelta64(30, "s")
    assert aligned.method is ResampleMethod.NEAREST
    assert aligned.times.size == 7  # 0..180 s at 30 s


def test_humidity_quantity_not_converted() -> None:
    file = _series_file(
        "h.csv", _stamps("2024-03-01T08:00", 2), np.array([45.0, 46.0]), column="RH1"
    )
    mapping = LoggerMapping(logger_id="L1", humidity_file="/mem/h.csv", humidity_column="RH1")
    aligned = align_loggers([file], [mapping], Quantity.HUMIDITY)
    assert aligned.quantity is Quantity.HUMIDITY
    assert aligned.values[:, 0] == pytest.approx([45.0, 46.0])


def test_excluded_and_unmapped_loggers_skipped() -> None:
    file = _series_file("s.csv", _stamps("2024-03-01T08:00", 2), np.array([1.0, 2.0]))
    mappings = [
        LoggerMapping(logger_id="L1", temperature_file="/mem/s.csv", temperature_column="T1"),
        LoggerMapping(logger_id="LX", excluded=True),
    ]
    aligned = align_loggers([file], mappings)
    assert aligned.logger_ids == ("L1",)


def test_error_cases() -> None:
    file = _series_file("e.csv", _stamps("2024-03-01T08:00", 2), np.array([1.0, 2.0]))
    with pytest.raises(AlignmentError):
        align_loggers([file], [])
    with pytest.raises(AlignmentError, match="not loaded"):
        align_loggers([file], [LoggerMapping("L", "/mem/absent.csv", "T1")])
    with pytest.raises(AlignmentError, match="not found"):
        align_loggers([file], [LoggerMapping("L", "/mem/e.csv", "NOPE")])
    humidity_only = LoggerMapping(logger_id="L", humidity_file="/mem/e.csv", humidity_column="T1")
    with pytest.raises(AlignmentError, match="no loggers are mapped"):
        align_loggers([file], [humidity_only], Quantity.TEMPERATURE)


def test_unsorted_input_is_sorted_defensively() -> None:
    stamps = np.array(
        ["2024-03-01T08:02", "2024-03-01T08:00", "2024-03-01T08:01"],
        dtype="datetime64[ns]",
    )
    values = np.array([3.0, 1.0, 2.0])
    file = _series_file("u.csv", stamps, values)
    mapping = LoggerMapping(logger_id="L", temperature_file="/mem/u.csv", temperature_column="T1")
    aligned = align_loggers([file], [mapping])
    assert aligned.values[:, 0] == pytest.approx([1.0, 2.0, 3.0])


def test_outputs_are_immutable() -> None:
    file = _series_file("i.csv", _stamps("2024-03-01T08:00", 2), np.array([1.0, 2.0]))
    mapping = LoggerMapping(logger_id="L", temperature_file="/mem/i.csv", temperature_column="T1")
    aligned = align_loggers([file], [mapping])
    assert not aligned.times.flags.writeable
    assert not aligned.values.flags.writeable


def test_align_real_csv_file() -> None:
    parsed = read_data_file(DATA / "data_simple.csv", ImportProfile())
    mappings = [
        LoggerMapping(logger_id="L1", temperature_file=parsed.path, temperature_column="T1"),
        LoggerMapping(logger_id="L2", temperature_file=parsed.path, temperature_column="T2"),
    ]
    aligned = align_loggers([parsed], mappings)
    assert aligned.logger_ids == ("L1", "L2")
    assert aligned.times.size == 6
    assert aligned.values[0, 0] == pytest.approx(20.1)
    assert aligned.values[0, 1] == pytest.approx(20.4)


def test_time_range_indices() -> None:
    times = _stamps("2024-03-01T08:00", 6)
    assert time_range_indices(times, times[1], times[4]) == (1, 4)
    assert time_range_indices(times, times[0], times[-1]) == (0, 5)
    far_past = (np.datetime64("1999-01-01", "ns"), np.datetime64("1999-02-01", "ns"))
    assert time_range_indices(times, *far_past) is None
    assert time_range_indices(times, times[0] - np.timedelta64(1, "h"), times[2]) == (0, 2)


def test_nearest_time_index() -> None:
    times = _stamps("2024-03-01T08:00", 6)
    assert nearest_time_index(times, times[3]) == 3
    assert nearest_time_index(times, times[2] + np.timedelta64(20, "s")) == 2
    assert nearest_time_index(times, times[2] + np.timedelta64(40, "s")) == 3
    assert nearest_time_index(times, times[2] + np.timedelta64(30, "s")) == 2  # tie -> earlier
    assert nearest_time_index(times, np.datetime64("1999-01-01", "ns")) == 0
    assert nearest_time_index(times, np.datetime64("2030-01-01", "ns")) == 5


def test_select_time_window() -> None:
    times = _stamps("2024-03-01T08:00", 6)
    values = np.arange(12, dtype=float).reshape(6, 2)
    t, v = select_time_window(times, values, times[1], times[4])
    assert t.size == 4 and v.shape == (4, 2)
    assert t[0] == times[1] and t[-1] == times[4]
    t_all, _ = select_time_window(times, values, None, None)
    assert t_all.size == 6
    t_open, _ = select_time_window(times, values, None, times[2])
    assert t_open.size == 3


def test_time_range_indices_none_bounds() -> None:
    times = _stamps("2024-03-01T08:00", 6)
    assert time_range_indices(times, None, None) == (0, 5)
    assert time_range_indices(times, None, times[3]) == (0, 3)
    assert time_range_indices(times, times[2], None) == (2, 5)
