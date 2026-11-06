"""Time-base alignment of logger series (DAT-06, DAT-07).

Pure Python, headless (no Qt). Timestamps are naive-UTC datetime64[ns];
temperatures are converted to °C, humidity stays %RH (canonical units).
Input arrays are never modified (data-integrity rule).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from thermavisualizer.core.models import (
    ColumnType,
    LoggerMapping,
    ParsedFile,
    Quantity,
)
from thermavisualizer.core.units import to_celsius

DEFAULT_GAP_MULTIPLE = 3.0


class ResampleMethod(StrEnum):
    """Resampling method for alignment (DAT-07)."""

    NEAREST = "nearest"
    LINEAR = "linear"


class AlignmentError(ValueError):
    """Raised when alignment inputs are missing or degenerate."""


@dataclass(frozen=True)
class AlignmentOptions:
    """Alignment settings (DAT-07)."""

    interval: np.timedelta64 | None = None  # None = most frequent interval
    method: ResampleMethod = ResampleMethod.LINEAR
    max_gap: np.timedelta64 | None = None  # None = 3 x interval


@dataclass(frozen=True)
class AlignedDataset:
    """Logger series resampled onto one common time base (DAT-06/07).

    ``times`` is datetime64[ns] UTC; ``values`` is (n_times, n_loggers) in
    °C or %RH depending on ``quantity``; NaN marks missing/masked samples.
    """

    times: np.ndarray
    logger_ids: tuple[str, ...]
    quantity: Quantity
    values: np.ndarray
    interval: np.timedelta64
    method: ResampleMethod


# --------------------------------------------------------------- primitives


def detect_interval(stamp_arrays: Sequence[np.ndarray]) -> np.timedelta64:
    """Return the most frequent positive sampling interval (DAT-07 default).

    Ties are broken toward the shorter interval. Raises AlignmentError when
    no interval can be determined.
    """
    parts: list[np.ndarray] = []
    for stamps in stamp_arrays:
        valid = stamps[~np.isnat(stamps)]
        if valid.size < 2:
            continue
        diffs = np.diff(np.sort(valid))
        diffs = diffs[diffs > np.timedelta64(0, "ns")]
        if diffs.size:
            parts.append(diffs.astype("int64"))
    if not parts:
        raise AlignmentError("not enough timestamps to detect an interval")
    all_diffs = np.concatenate(parts)
    unique, counts = np.unique(all_diffs, return_counts=True)
    candidates = unique[counts == counts.max()]
    return np.timedelta64(int(candidates.min()), "ns")


def build_time_base(
    start: np.datetime64, end: np.datetime64, interval: np.timedelta64
) -> np.ndarray:
    """Return the inclusive datetime64 grid from ``start`` to ``end``."""
    if interval <= np.timedelta64(0, "ns"):
        raise AlignmentError("interval must be positive")
    if end < start:
        raise AlignmentError("end precedes start")
    times = np.arange(start, end + interval, interval, dtype="datetime64[ns]")
    times.flags.writeable = False
    return times


def resample_series(
    stamps: np.ndarray,
    values: np.ndarray,
    times: np.ndarray,
    method: ResampleMethod,
    max_gap: np.timedelta64,
) -> np.ndarray:
    """Resample one series onto ``times`` and return a new float64 array.

    NaT/NaN source samples are skipped. LINEAR interpolates only across
    source gaps up to ``max_gap`` and never extrapolates; NEAREST uses the
    closest sample when it lies within ``max_gap / 2`` (ties go to the
    earlier sample). All other target times are NaN. Units are preserved.
    """
    out = np.full(times.shape, np.nan, dtype="float64")
    ok = ~np.isnat(stamps) & np.isfinite(values)
    x = stamps[ok].astype("int64")
    y = values[ok]
    if x.size == 0:
        return out
    order = np.argsort(x, kind="stable")
    x, y = x[order], y[order]
    t = times.astype("int64")
    gap_ns = int(max_gap / np.timedelta64(1, "ns"))

    # Exact matches on measured samples always inherit the source value —
    # that is recorded data, not interpolation, so the gap rule does not apply.
    position = np.searchsorted(x, t)
    position_clipped = np.clip(position, 0, x.size - 1)
    exact = (position < x.size) & (x[position_clipped] == t)
    out[exact] = y[position_clipped[exact]]

    if method is ResampleMethod.NEAREST:
        index = np.searchsorted(x, t)
        right = np.clip(index, 0, x.size - 1)
        left = np.clip(index - 1, 0, x.size - 1)
        dist_right = np.abs(t - x[right])
        dist_left = np.abs(t - x[left])
        use_left = dist_left <= dist_right  # ties go to the earlier sample
        chosen = np.where(use_left, left, right)
        distance = np.where(use_left, dist_left, dist_right)
        valid = (~exact) & (distance <= gap_ns // 2)
        out[valid] = y[chosen[valid]]
        return out

    # Linear interpolation between samples; never extrapolates.
    if x.size == 1:
        return out
    segment_ok = np.diff(x) <= gap_ns
    index = np.searchsorted(x, t, side="right") - 1
    in_segment = (index >= 0) & (index < x.size - 1)
    clipped = np.clip(index, 0, x.size - 2)
    span = (x[clipped + 1] - x[clipped]).astype("float64")
    fraction = (t - x[clipped]).astype("float64") / np.maximum(span, 1.0)
    interpolated = y[clipped] + fraction * (y[clipped + 1] - y[clipped])
    valid = (~exact) & in_segment & segment_ok[clipped]
    out[valid] = interpolated[valid]
    return out


# ---------------------------------------------------------------- pipeline


def align_loggers(
    files: Sequence[ParsedFile],
    mappings: Sequence[LoggerMapping],
    quantity: Quantity = Quantity.TEMPERATURE,
    options: AlignmentOptions = AlignmentOptions(),
) -> AlignedDataset:
    """Align every mapped logger of ``quantity`` onto one common time base.

    Files are merged on timestamp (DAT-06); series are resampled with the
    chosen method and gap rule (DAT-07). The time base covers the union of
    all series; temperature is converted to °C (DAT-08). Raises
    AlignmentError for missing files/columns or empty inputs.
    """
    by_path = {file.path: file for file in files}
    series: list[tuple[str, np.ndarray, np.ndarray]] = []
    for mapping in mappings:
        if mapping.excluded:
            continue
        file_ref, column_name = _reference_for(mapping, quantity)
        if not file_ref or not column_name:
            continue
        file = by_path.get(file_ref)
        if file is None:
            raise AlignmentError(
                f"mapped file '{file_ref}' is not loaded (logger '{mapping.logger_id}')"
            )
        column = file.column(column_name)
        if column is None or column.column_type is not ColumnType.NUMERIC:
            raise AlignmentError(
                f"mapped column '{column_name}' not found in '{file.name}' "
                f"(logger '{mapping.logger_id}')"
            )
        stamps = file.timestamp_array()
        if stamps is None:
            raise AlignmentError(f"'{file.name}' has no timestamp column")
        values = np.array(column.values, dtype="float64")
        if quantity is Quantity.TEMPERATURE:
            values = to_celsius(values, file.temperature_unit)
        series.append((mapping.logger_id, stamps, values))
    if not series:
        raise AlignmentError(f"no loggers are mapped for {quantity.value}")

    if options.interval is not None:
        interval = options.interval
    else:
        interval = detect_interval([stamps for _, stamps, _ in series])
    if options.max_gap is not None:
        max_gap = options.max_gap
    else:
        gap_ns = float(interval / np.timedelta64(1, "ns")) * DEFAULT_GAP_MULTIPLE
        max_gap = np.timedelta64(int(gap_ns), "ns")

    starts: list[np.datetime64] = []
    ends: list[np.datetime64] = []
    for _, stamps, _ in series:
        valid = stamps[~np.isnat(stamps)]
        if valid.size:
            starts.append(valid.min())
            ends.append(valid.max())
    if not starts:
        raise AlignmentError("no valid timestamps to align")
    times = build_time_base(min(starts), max(ends), interval)

    columns = [
        resample_series(stamps, values, times, options.method, max_gap)
        for _, stamps, values in series
    ]
    matrix = np.column_stack(columns)
    matrix.flags.writeable = False
    return AlignedDataset(
        times=times,
        logger_ids=tuple(logger_id for logger_id, _, _ in series),
        quantity=quantity,
        values=matrix,
        interval=interval,
        method=options.method,
    )


def _reference_for(mapping: LoggerMapping, quantity: Quantity) -> tuple[str, str]:
    """(file, column) reference of a mapping for the given quantity."""
    if quantity is Quantity.TEMPERATURE:
        return mapping.temperature_file, mapping.temperature_column
    return mapping.humidity_file, mapping.humidity_column


def time_range_indices(
    times: np.ndarray,
    start: np.datetime64 | None,
    end: np.datetime64 | None,
) -> tuple[int, int] | None:
    """Sample indices covering ``[start, end]`` inclusive.

    ``None`` on either side means "open" (no bound there); both ``None`` means
    the full range. Returns None only when the time base is empty or a bounded
    window does not overlap the data at all (never silently clamps a disjoint
    window onto samples).
    """
    if times.size == 0:
        return None
    if start is None and end is None:
        return 0, times.size - 1
    if end is not None and end < times[0]:
        return None
    if start is not None and start > times[-1]:
        return None
    low = 0 if start is None else int(np.searchsorted(times, start, side="left"))
    high = times.size - 1 if end is None else int(np.searchsorted(times, end, side="right")) - 1
    low = max(0, min(low, times.size - 1))
    high = max(0, min(high, times.size - 1))
    if low > high:
        return None
    return low, high


def nearest_time_index(times: np.ndarray, time: np.datetime64) -> int:
    """Index of the sample nearest to ``time``; ties go to the earlier sample."""
    if times.size == 0:
        raise AlignmentError("nearest_time_index needs a non-empty time base")
    index = int(np.searchsorted(times, time))
    if index <= 0:
        return 0
    if index >= times.size:
        return times.size - 1
    return index - 1 if (time - times[index - 1]) <= (times[index] - time) else index


def select_time_window(
    times: np.ndarray,
    values: np.ndarray,
    start: np.datetime64 | None,
    end: np.datetime64 | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Slice ``(times, values)`` to ``[start, end]`` inclusive (PLT-01/07).

    ``None`` bounds keep that side open; units are preserved.
    """
    mask = np.ones(times.size, dtype=bool)
    if start is not None:
        mask &= times >= start
    if end is not None:
        mask &= times <= end
    return times[mask], values[mask]
