"""Study comparison (CMP-01/02): A vs B statistics and difference volumes.

Pure Python, headless (no Qt). Units: °C / %RH for values, metres for geometry.
Difference volumes are (B - A) on a common grid.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from thermavisualizer.core.models import BoxFootprint, PolygonFootprint, Space
from thermavisualizer.core.results import StudyResults


class ComparisonError(ValueError):
    """Raised when two studies cannot be compared."""


@dataclass(frozen=True)
class LoggerComparison:
    """Per-logger A/B comparison row (CMP-01). Units: °C / %RH."""

    logger_id: str
    mean_a: float | None
    mean_b: float | None
    delta_mean: float | None
    max_a: float | None
    max_b: float | None
    delta_max: float | None
    passed_a: bool | None
    passed_b: bool | None


def compare_results(results_a: StudyResults, results_b: StudyResults) -> list[LoggerComparison]:
    """Align per-logger results from two studies by logger ID (CMP-01)."""
    by_a = {lr.logger_id: lr for lr in results_a.logger_results}
    by_b = {lr.logger_id: lr for lr in results_b.logger_results}
    rows: list[LoggerComparison] = []
    for logger_id in sorted(set(by_a) | set(by_b)):
        a = by_a.get(logger_id)
        b = by_b.get(logger_id)
        rows.append(
            LoggerComparison(
                logger_id=logger_id,
                mean_a=a.mean if a else None,
                mean_b=b.mean if b else None,
                delta_mean=(b.mean - a.mean) if (a and b) else None,
                max_a=a.maximum if a else None,
                max_b=b.maximum if b else None,
                delta_max=(b.maximum - a.maximum) if (a and b) else None,
                passed_a=a.passed if a else None,
                passed_b=b.passed if b else None,
            )
        )
    return rows


def geometries_match(space_a: Space, space_b: Space) -> bool:
    """True when two spaces share footprint and height (needed for CMP-02)."""
    if abs(space_a.height - space_b.height) > 1e-9:
        return False
    fa, fb = space_a.footprint, space_b.footprint
    if type(fa) is not type(fb):
        return False
    if isinstance(fa, BoxFootprint):
        return (
            fa.x_min == fb.x_min
            and fa.x_max == fb.x_max
            and fa.y_min == fb.y_min
            and fa.y_max == fb.y_max
        )
    if isinstance(fa, PolygonFootprint):
        return fa.vertices == fb.vertices
    return False


def difference_volume(volume_a: np.ndarray, volume_b: np.ndarray) -> np.ndarray:
    """Return (B - A) element-wise on a common grid (CMP-02). Units preserved."""
    if volume_a.shape != volume_b.shape:
        raise ComparisonError(f"volumes differ in shape: {volume_a.shape} vs {volume_b.shape}")
    return volume_b - volume_a
