"""Acceptance criteria evaluation and study results (RES-01..05, RES-08).

Pure Python, headless. Results are derived data: always recomputed from raw
(aligned) data plus criteria and selection — never stored as truth (AGENTS §4).
Units: temperature °C, humidity %RH, durations in seconds, timestamps naive-UTC.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from thermavisualizer.core.models import Quantity
from thermavisualizer.core.statistics import mean_kinetic_temperature


class ResultsError(ValueError):
    """Raised when results cannot be evaluated."""


class ExcursionKind(StrEnum):
    """Direction of an out-of-limits excursion (RES-05)."""

    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class AcceptanceCriteria:
    """Acceptance limits (RES-01). Units: °C and %RH; None = not limited."""

    name: str = "Default"
    temperature_min: float = 2.0
    temperature_max: float = 8.0
    humidity_min: float | None = None
    humidity_max: float | None = None


@dataclass(frozen=True)
class Excursion:
    """One continuous out-of-limits period (RES-05)."""

    logger_id: str
    kind: ExcursionKind
    start: np.datetime64
    end: np.datetime64
    duration_seconds: float  # first to last out-of-limit sample
    peak: float  # max for HIGH, min for LOW


@dataclass(frozen=True)
class LoggerResult:
    """Per-logger evaluation (RES-03). Population std; NaNs excluded."""

    logger_id: str
    samples: int
    minimum: float
    maximum: float
    mean: float
    std: float
    mkt: float | None  # temperature only
    out_of_limits_samples: int
    out_of_limits_pct: float
    excursion_count: int
    longest_excursion_seconds: float
    passed: bool


@dataclass(frozen=True)
class OverallResult:
    """Study-level summary (RES-04)."""

    passed: bool
    reason: str
    hottest_logger: str
    hottest_value: float
    hottest_time: np.datetime64
    coldest_logger: str
    coldest_value: float
    coldest_time: np.datetime64
    largest_spread: float  # max minus min across loggers at one time step
    largest_spread_time: np.datetime64


@dataclass(frozen=True)
class StudyResults:
    """Full evaluation output, stamped with its inputs (RES-08)."""

    quantity: Quantity
    criteria: AcceptanceCriteria
    period_start: np.datetime64
    period_end: np.datetime64
    logger_results: tuple[LoggerResult, ...]
    excursions: tuple[Excursion, ...]
    overall: OverallResult


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive (start, end) index ranges of the True runs in ``mask``."""
    if mask.size == 0:
        return []
    padded = np.concatenate(([False], mask, [False]))
    diff = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1) - 1
    return list(zip(starts.tolist(), ends.tolist()))


def evaluate_logger(
    logger_id: str,
    times: np.ndarray,
    values: np.ndarray,
    low: float,
    high: float,
    quantity: Quantity,
) -> tuple[LoggerResult, list[Excursion]]:
    """Evaluate one logger's series against limits (RES-03, RES-05).

    NaN samples are excluded from statistics and break excursions; they are
    never counted as out-of-limits. Durations are in seconds.
    """
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    sample_count = int(finite.sum())
    if sample_count == 0:
        raise ResultsError(f"logger '{logger_id}' has no finite samples in the period")
    evaluated = values[finite]
    high_mask = finite & (values > high)
    low_mask = finite & (values < low)
    excursions: list[Excursion] = []
    for kind, mask in ((ExcursionKind.HIGH, high_mask), (ExcursionKind.LOW, low_mask)):
        for start_index, end_index in _runs(mask):
            segment = values[start_index : end_index + 1]
            peak = float(np.max(segment)) if kind is ExcursionKind.HIGH else float(np.min(segment))
            duration = (times[end_index] - times[start_index]) / np.timedelta64(1, "s")
            excursions.append(
                Excursion(
                    logger_id=logger_id,
                    kind=kind,
                    start=times[start_index],
                    end=times[end_index],
                    duration_seconds=float(duration),
                    peak=peak,
                )
            )
    excursions.sort(key=lambda excursion: excursion.start)
    out_count = int(high_mask.sum() + low_mask.sum())
    result = LoggerResult(
        logger_id=logger_id,
        samples=sample_count,
        minimum=float(np.min(evaluated)),
        maximum=float(np.max(evaluated)),
        mean=float(np.mean(evaluated)),
        std=float(np.std(evaluated)),
        mkt=mean_kinetic_temperature(evaluated) if quantity is Quantity.TEMPERATURE else None,
        out_of_limits_samples=out_count,
        out_of_limits_pct=100.0 * out_count / sample_count,
        excursion_count=len(excursions),
        longest_excursion_seconds=max((e.duration_seconds for e in excursions), default=0.0),
        passed=out_count == 0,
    )
    return result, excursions


def evaluate_dataset(
    times: np.ndarray,
    logger_ids: Sequence[str],
    values: np.ndarray,
    criteria: AcceptanceCriteria,
    quantity: Quantity = Quantity.TEMPERATURE,
    start: np.datetime64 | None = None,
    end: np.datetime64 | None = None,
) -> StudyResults:
    """Evaluate criteria over [start, end] inclusive (RES-02).

    ``times`` is (T,) naive-UTC; ``values`` is (T, N) in °C or %RH matching
    ``logger_ids`` order. Defaults to the full range when start/end are None.
    """
    times = np.asarray(times)
    values = np.asarray(values, dtype=float)
    if values.ndim != 2 or values.shape[0] != times.size or values.shape[1] != len(logger_ids):
        raise ResultsError("values must have shape (n_times, n_loggers)")
    if quantity is Quantity.TEMPERATURE:
        low, high = criteria.temperature_min, criteria.temperature_max
    else:
        low, high = criteria.humidity_min, criteria.humidity_max
    if low is None or high is None:
        raise ResultsError(f"{quantity.value} criteria limits are not defined")

    selection = np.ones(times.size, dtype=bool)
    if start is not None:
        selection &= times >= start
    if end is not None:
        selection &= times <= end
    selected_times = times[selection]
    selected_values = values[selection]
    if selected_times.size == 0:
        raise ResultsError("the selected period contains no samples")

    logger_results: list[LoggerResult] = []
    excursions: list[Excursion] = []
    for index, logger_id in enumerate(logger_ids):
        result, found = evaluate_logger(
            logger_id, selected_times, selected_values[:, index], low, high, quantity
        )
        logger_results.append(result)
        excursions.extend(found)
    excursions.sort(key=lambda excursion: (excursion.start, excursion.logger_id))

    finite = np.isfinite(selected_values)
    if not finite.any():
        raise ResultsError("no finite samples in the selected period")
    max_index = int(np.nanargmax(np.where(finite, selected_values, -np.inf)))
    min_index = int(np.nanargmin(np.where(finite, selected_values, np.inf)))
    max_row, max_col = divmod(max_index, selected_values.shape[1])
    min_row, min_col = divmod(min_index, selected_values.shape[1])
    spread = np.nanmax(selected_values, axis=1) - np.nanmin(selected_values, axis=1)
    spread_row = int(np.nanargmax(spread))

    failed = [result for result in logger_results if not result.passed]
    overall = OverallResult(
        passed=not failed,
        reason=(
            f"all {len(logger_results)} logger(s) within limits"
            if not failed
            else f"{len(failed)} of {len(logger_results)} logger(s) out of limits"
        ),
        hottest_logger=logger_ids[max_col],
        hottest_value=float(selected_values[max_row, max_col]),
        hottest_time=selected_times[max_row],
        coldest_logger=logger_ids[min_col],
        coldest_value=float(selected_values[min_row, min_col]),
        coldest_time=selected_times[min_row],
        largest_spread=float(spread[spread_row]),
        largest_spread_time=selected_times[spread_row],
    )
    return StudyResults(
        quantity=quantity,
        criteria=criteria,
        period_start=selected_times[0],
        period_end=selected_times[-1],
        logger_results=tuple(logger_results),
        excursions=tuple(excursions),
        overall=overall,
    )


@dataclass(frozen=True)
class StudyPeriod:
    """A named period of the study for targeted evaluation (RES-02)."""

    name: str
    start: np.datetime64
    end: np.datetime64
