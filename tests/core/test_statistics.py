"""Aggregation and temporal smoothing tests (INT-04, INT-05)."""

from __future__ import annotations

import numpy as np
import pytest

from thermavisualizer.core.statistics import (
    AggregationMethod,
    StatisticsError,
    aggregate_series,
    moving_average,
    mean_kinetic_temperature,
)


def test_aggregate_instant() -> None:
    values = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    assert np.array_equal(aggregate_series(values, AggregationMethod.INSTANT, 1), [3.0, 4.0])


def test_aggregate_mean_min_max_std() -> None:
    values = np.array([[1.0], [3.0], [5.0]])
    assert aggregate_series(values, AggregationMethod.MEAN)[0] == pytest.approx(3.0)
    assert aggregate_series(values, AggregationMethod.MIN)[0] == pytest.approx(1.0)
    assert aggregate_series(values, AggregationMethod.MAX)[0] == pytest.approx(5.0)
    assert aggregate_series(values, AggregationMethod.STD)[0] == pytest.approx(np.std([1, 3, 5]))


def test_aggregate_ignores_nan() -> None:
    values = np.array([1.0, np.nan, 3.0])
    assert aggregate_series(values, AggregationMethod.MEAN) == pytest.approx(2.0)


def test_aggregate_empty_raises() -> None:
    with pytest.raises(StatisticsError):
        aggregate_series(np.array([]), AggregationMethod.MEAN)


def test_moving_average_hand_computed() -> None:
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    result = moving_average(values, 3)
    assert result[1] == pytest.approx(2.0)
    assert result[2] == pytest.approx(3.0)
    assert result[3] == pytest.approx(4.0)


def test_moving_average_window_one_is_identity() -> None:
    values = np.array([1.0, 2.0, 3.0])
    assert np.array_equal(moving_average(values, 1), values)


def test_mkt_constant_series_equals_constant() -> None:
    assert mean_kinetic_temperature(np.full(10, 5.0)) == pytest.approx(5.0, abs=1e-9)


def test_mkt_hand_computed_two_points() -> None:
    # 20 °C and 30 °C, ΔH/R = 10000 K -> 299.4096 K = 26.26 °C
    result = mean_kinetic_temperature(np.array([20.0, 30.0]))
    assert result == pytest.approx(26.26, abs=0.05)
    assert result > 25.0  # MKT of a varying series exceeds the arithmetic mean


def test_mkt_ignores_nan_and_validates() -> None:
    assert mean_kinetic_temperature(np.array([5.0, np.nan, 5.0])) == pytest.approx(5.0)
    with pytest.raises(StatisticsError):
        mean_kinetic_temperature(np.array([np.nan]))
    with pytest.raises(StatisticsError):
        mean_kinetic_temperature(np.array([-300.0]))
