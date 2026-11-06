"""Study comparison tests (CMP-01/02), hand-computed."""

from __future__ import annotations

import numpy as np
import pytest

from thermavisualizer.core.comparison import (
    ComparisonError,
    compare_results,
    difference_volume,
    geometries_match,
)
from thermavisualizer.core.models import BoxFootprint, PolygonFootprint, Quantity, Space
from thermavisualizer.core.results import AcceptanceCriteria, evaluate_dataset

CRITERIA = AcceptanceCriteria(name="2-8", temperature_min=2.0, temperature_max=8.0)
TIMES = np.datetime64("2024-03-01T08:00", "ns") + np.arange(3) * np.timedelta64(10, "m")


def _results(values: np.ndarray, logger_ids=("L1",)):
    return evaluate_dataset(TIMES, logger_ids, values, CRITERIA, Quantity.TEMPERATURE)


def test_compare_results_hand_computed() -> None:
    a = _results(np.array([[5.0], [6.0], [7.0]]))  # mean 6.0, max 7.0
    b = _results(np.array([[6.0], [8.0], [10.0]]))  # mean 8.0, max 10.0
    rows = compare_results(a, b)
    assert len(rows) == 1
    row = rows[0]
    assert row.mean_a == pytest.approx(6.0)
    assert row.mean_b == pytest.approx(8.0)
    assert row.delta_mean == pytest.approx(2.0)
    assert row.delta_max == pytest.approx(3.0)


def test_compare_results_unmatched_loggers() -> None:
    a = _results(np.array([[5.0], [6.0], [7.0]]), ("L1",))
    b = _results(np.array([[5.0], [6.0], [7.0]]), ("L2",))
    rows = compare_results(a, b)
    assert [r.logger_id for r in rows] == ["L1", "L2"]
    assert rows[0].mean_b is None
    assert rows[1].mean_a is None


def test_geometries_match_box_and_polygon() -> None:
    box = BoxFootprint(0.0, 0.0, 2.0, 2.0)
    assert geometries_match(Space(footprint=box, height=2.0), Space(footprint=box, height=2.0))
    assert not geometries_match(
        Space(footprint=box, height=2.0), Space(footprint=box, height=3.0)
    )
    poly = PolygonFootprint(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)))
    assert not geometries_match(Space(footprint=box), Space(footprint=poly))


def test_difference_volume_b_minus_a() -> None:
    a = np.array([[[1.0, 2.0], [3.0, 4.0]]])
    b = np.array([[[2.0, 2.0], [5.0, 1.0]]])
    diff = difference_volume(a, b)
    assert diff.tolist() == [[[1.0, 0.0], [2.0, -3.0]]]


def test_difference_volume_shape_mismatch_raises() -> None:
    with pytest.raises(ComparisonError):
        difference_volume(np.zeros((2, 2, 2)), np.zeros((3, 3, 3)))