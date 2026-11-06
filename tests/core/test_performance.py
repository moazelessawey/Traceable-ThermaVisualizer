"""Performance guardrails (PRD §7 targets, INT-09, NFR scalability).

Fixed synthetic workloads with generous bounds: catch order-of-magnitude
regressions without flaking on modest CI hardware.
"""

from __future__ import annotations

import time

import numpy as np

from thermavisualizer.core.alignment import ResampleMethod, resample_series
from thermavisualizer.core.geometry import build_volume_mask
from thermavisualizer.core.interpolation import (
    InterpolationSettings,
    Interpolator,
    build_voxel_grid,
)
from thermavisualizer.core.models import BoxFootprint, Space


def test_idw_timestep_meets_target() -> None:  # INT-09, PRD hardware target
    space = Space(footprint=BoxFootprint(0.0, 0.0, 6.0, 4.0), height=3.0)
    rng = np.random.default_rng(42)
    positions = np.column_stack([
        rng.uniform(0.1, 5.9, 100),
        rng.uniform(0.1, 3.9, 100),
        rng.uniform(0.2, 2.8, 100),
    ])
    grid = build_voxel_grid(space, 0.15)  # ~41 x 27 x 21 voxels
    mask = build_volume_mask(space, [], grid.x_coords, grid.y_coords, grid.z_coords)
    built = time.perf_counter()
    interpolator = Interpolator(grid, positions, InterpolationSettings(), mask)
    assert time.perf_counter() - built < 10.0  # one-time weight precompute

    values = rng.normal(20.0, 1.0, 100)
    interpolator.interpolate(values)  # warm-up
    start = time.perf_counter()
    for _ in range(5):
        interpolator.interpolate(values)
    per_step = (time.perf_counter() - start) / 5.0
    assert per_step < 0.1  # PRD target: well under 100 ms per time step


def test_resampling_scales_to_large_series() -> None:  # NFR scalability
    rng = np.random.default_rng(7)
    count = 200_000
    stamps = (
        np.datetime64("2024-01-01T00:00", "ns")
        + np.arange(count) * np.timedelta64(60, "s")
    )
    values = rng.normal(20.0, 1.0, count)
    target = stamps[::2]
    start = time.perf_counter()
    out = resample_series(
        stamps, values, target, ResampleMethod.LINEAR, np.timedelta64(300, "s")
    )
    elapsed = time.perf_counter() - start
    assert out.shape == target.shape
    assert elapsed < 5.0