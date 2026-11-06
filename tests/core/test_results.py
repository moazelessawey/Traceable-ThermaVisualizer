"""Acceptance criteria and results tests (RES-01..05, RES-08), hand-computed."""

from __future__ import annotations

import numpy as np
import pytest

from thermavisualizer.core.models import Quantity
from thermavisualizer.core.results import (
    AcceptanceCriteria,
    ExcursionKind,
    ResultsError,
    evaluate_dataset,
)

CRITERIA = AcceptanceCriteria(name="2-8", temperature_min=2.0, temperature_max=8.0)
TIMES = np.datetime64("2024-03-01T08:00", "ns") + np.arange(5) * np.timedelta64(10, "m")
LOGGER_IDS = ("A", "B", "C")
VALUES = np.array(
    [
        [4.0, 5.0, 3.0],
        [5.0, 6.0, 1.0],
        [6.0, 9.0, 1.0],
        [5.0, 9.0, 3.0],
        [4.0, 5.0, 3.0],
    ]
)


def test_per_logger_statistics_hand_computed() -> None:  # RES-03
    results = evaluate_dataset(TIMES, LOGGER_IDS, VALUES, CRITERIA)
    by_id = {result.logger_id: result for result in results.logger_results}
    a = by_id["A"]
    assert a.samples == 5
    assert a.minimum == pytest.approx(4.0)
    assert a.maximum == pytest.approx(6.0)
    assert a.mean == pytest.approx(4.8)
    assert a.std == pytest.approx(0.748331, abs=1e-5)  # population std of 4,5,6,5,4
    assert a.mkt is not None
    assert a.mean <= a.mkt <= a.maximum
    assert a.passed is True
    assert a.excursion_count == 0


def test_excursions_detected_with_peak_and_duration() -> None:  # RES-05
    results = evaluate_dataset(TIMES, LOGGER_IDS, VALUES, CRITERIA)
    by_logger = {}
    for excursion in results.excursions:
        by_logger.setdefault(excursion.logger_id, []).append(excursion)
    high = by_logger["B"]
    assert len(high) == 1
    assert high[0].kind is ExcursionKind.HIGH
    assert high[0].peak == pytest.approx(9.0)
    assert high[0].start == TIMES[2]
    assert high[0].end == TIMES[3]
    assert high[0].duration_seconds == pytest.approx(600.0)
    low = by_logger["C"]
    assert len(low) == 1
    assert low[0].kind is ExcursionKind.LOW
    assert low[0].peak == pytest.approx(1.0)
    out = {r.logger_id: r for r in results.logger_results}
    assert out["B"].out_of_limits_samples == 2
    assert out["B"].out_of_limits_pct == pytest.approx(40.0)
    assert out["B"].passed is False
    assert out["C"].passed is False


def test_overall_result_hand_computed() -> None:  # RES-04
    results = evaluate_dataset(TIMES, LOGGER_IDS, VALUES, CRITERIA)
    overall = results.overall
    assert overall.passed is False
    assert "2 of 3" in overall.reason
    assert overall.hottest_logger == "B"
    assert overall.hottest_value == pytest.approx(9.0)
    assert overall.hottest_time == TIMES[2]
    assert overall.coldest_logger == "C"
    assert overall.coldest_value == pytest.approx(1.0)
    assert overall.coldest_time == TIMES[1]
    assert overall.largest_spread == pytest.approx(8.0)  # 9 - 1 at t2 (and t3)
    assert overall.largest_spread_time == TIMES[2]


def test_period_selection_limits_samples() -> None:  # RES-02
    results = evaluate_dataset(TIMES, LOGGER_IDS, VALUES, CRITERIA, start=TIMES[1], end=TIMES[3])
    assert results.period_start == TIMES[1]
    assert results.period_end == TIMES[3]
    assert all(result.samples == 3 for result in results.logger_results)


def test_humidity_evaluation_has_no_mkt() -> None:
    rh_criteria = AcceptanceCriteria(
        name="RH",
        temperature_min=2.0,
        temperature_max=8.0,
        humidity_min=35.0,
        humidity_max=65.0,
    )
    rh = np.array([[50.0, 70.0], [55.0, 60.0]])
    results = evaluate_dataset(TIMES[:2], ("H1", "H2"), rh, rh_criteria, quantity=Quantity.HUMIDITY)
    assert results.logger_results[0].mkt is None
    assert results.logger_results[1].passed is False


def test_missing_limits_and_empty_selection_raise() -> None:
    with pytest.raises(ResultsError):
        evaluate_dataset(
            TIMES[:2], ("H1",), np.array([[50.0], [55.0]]), CRITERIA, quantity=Quantity.HUMIDITY
        )
    with pytest.raises(ResultsError):
        evaluate_dataset(
            TIMES, LOGGER_IDS, VALUES, CRITERIA, start=np.datetime64("2030-01-01", "ns")
        )


def test_results_are_stamped_with_inputs() -> None:  # RES-08
    results = evaluate_dataset(TIMES, LOGGER_IDS, VALUES, CRITERIA)
    assert results.criteria is CRITERIA
    assert results.quantity is Quantity.TEMPERATURE
    assert results.period_start == TIMES[0]
    assert results.period_end == TIMES[-1]
