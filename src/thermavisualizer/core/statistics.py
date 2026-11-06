"""Descriptive statistics, time aggregation, and temporal smoothing.

Covers INT-04 (temporal smoothing) and INT-05 (range aggregation). Pure Python,
headless. Units preserved: temperature °C, humidity %RH.
"""

from __future__ import annotations

from enum import StrEnum

import numpy as np


class AggregationMethod(StrEnum):
    """How to reduce the time dimension before interpolation (INT-05)."""

    INSTANT = "instant"
    MEAN = "mean"
    MIN = "min"
    MAX = "max"
    STD = "std"


class StatisticsError(ValueError):
    """Raised for invalid statistics inputs."""


def aggregate_series(
    values: np.ndarray, method: AggregationMethod, index: int = 0
) -> np.ndarray | float:
    """Aggregate a ``(T,)`` or ``(T, N)`` array along time (axis 0).

    ``INSTANT`` selects the single time step ``index``; the other methods reduce
    the whole time axis ignoring NaNs. Units are preserved (°C / %RH).
    """
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        raise StatisticsError("cannot aggregate an empty series")
    if method is AggregationMethod.INSTANT:
        if values.ndim == 0 or not 0 <= index < values.shape[0]:
            raise StatisticsError(f"instant index {index} out of range")
        return values[index] if values.ndim == 1 else values[index, :]
    axis = 0 if values.ndim > 1 else None
    if method is AggregationMethod.MEAN:
        return np.nanmean(values, axis=axis)
    if method is AggregationMethod.MIN:
        return np.nanmin(values, axis=axis)
    if method is AggregationMethod.MAX:
        return np.nanmax(values, axis=axis)
    if method is AggregationMethod.STD:
        return np.nanstd(values, axis=axis)
    raise StatisticsError(f"unknown aggregation method '{method}'")


def moving_average(values: np.ndarray, window: int) -> np.ndarray:
    """Centered moving average along the time axis, NaN-aware (INT-04).

    ``window <= 1`` returns a copy unchanged. Units preserved (°C / %RH).
    """
    values = np.asarray(values, dtype=float)
    if window <= 1:
        return values.copy()
    valid = ~np.isnan(values)
    filled = np.where(valid, values, 0.0)
    kernel = np.ones(window, dtype=float)

    def _convolve(column: np.ndarray) -> np.ndarray:
        return np.convolve(column, kernel, mode="same")

    if values.ndim == 1:
        numerator = _convolve(filled)
        denominator = _convolve(valid.astype(float))
    else:
        numerator = np.column_stack([_convolve(filled[:, i]) for i in range(values.shape[1])])
        denominator = np.column_stack(
            [_convolve(valid[:, i].astype(float)) for i in range(values.shape[1])]
        )
    with np.errstate(divide="ignore", invalid="ignore"):
        result = numerator / np.where(denominator > 0, denominator, 1.0)
    return np.where(denominator > 0, result, np.nan)


MKT_ACTIVATION_CONSTANT = 10000.0  # ΔH/R in kelvin (common pharma convention)


def mean_kinetic_temperature(
    values_celsius: np.ndarray, activation: float = MKT_ACTIVATION_CONSTANT
) -> float:
    """Mean kinetic temperature from °C samples (PLT-03, RES-03).

    MKT = -a / ln(mean(exp(-a / T_kelvin))) with a = ΔH/R. NaNs are ignored.
    Raises StatisticsError for empty input or temperatures at/below 0 K.
    """
    values = np.asarray(values_celsius, dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise StatisticsError("MKT needs at least one finite value")
    kelvin = finite + 273.15
    if bool((kelvin <= 0.0).any()):
        raise StatisticsError("MKT requires temperatures above absolute zero")
    return float(-activation / np.log(np.mean(np.exp(-activation / kelvin)))) - 273.15
