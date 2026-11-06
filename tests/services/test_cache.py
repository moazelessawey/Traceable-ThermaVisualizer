"""Interpolation cache keys and LRU behavior (INT-07, INT-09)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from thermavisualizer.core.interpolation import (
    InterpolationSettings,
    VoxelGrid,
    build_voxel_grid,
)
from thermavisualizer.core.models import BoxFootprint, Quantity, Space
from thermavisualizer.core.statistics import AggregationMethod
from thermavisualizer.services.cache import (
    InterpolationCache,
    array_fingerprint,
    interpolator_key,
    settings_key,
    volume_cache_key,
)


def _grid() -> VoxelGrid:
    space = Space(footprint=BoxFootprint(0.0, 0.0, 1.0, 1.0), height=1.0)
    return build_voxel_grid(space, 0.5)


def _positions() -> np.ndarray:
    return np.array([[0.2, 0.2, 0.5], [0.8, 0.8, 0.5]])


def test_array_fingerprint_stable_and_sensitive() -> None:
    a = np.array([1.0, 2.0, 3.0])
    assert array_fingerprint(a) == array_fingerprint(a.copy())
    assert array_fingerprint(a) != array_fingerprint(a + 1.0)


def test_settings_key_sensitive() -> None:
    base = InterpolationSettings()
    assert settings_key(base) == settings_key(replace(base))
    assert settings_key(base) != settings_key(replace(base, idw_power=3.0))
    assert settings_key(base) != settings_key(replace(base, resolution=0.5))


def test_interpolator_key_reuses_weights_across_per_step_options() -> None:  # INT-09
    from thermavisualizer.core.interpolation import ExtrapolationPolicy

    grid = _grid()
    positions = _positions()
    mask = np.ones(grid.shape(), dtype=bool)
    base = InterpolationSettings()
    key_a = interpolator_key(base, positions, grid, mask)
    same = interpolator_key(
        replace(base, extrapolation=ExtrapolationPolicy.CLAMP, smoothing_sigma=2.0),
        positions,
        grid,
        mask,
    )
    assert key_a == same  # extrapolation/smoothing are per-step, weights reusable
    different = interpolator_key(replace(base, idw_power=3.0), positions, grid, mask)
    assert key_a != different


def test_volume_key_changes_with_time_and_settings() -> None:
    grid = _grid()
    positions = _positions()
    settings = InterpolationSettings()
    instant_0 = volume_cache_key(
        Quantity.TEMPERATURE,
        settings,
        positions,
        grid,
        AggregationMethod.INSTANT,
        ("instant", 0),
    )
    instant_1 = volume_cache_key(
        Quantity.TEMPERATURE,
        settings,
        positions,
        grid,
        AggregationMethod.INSTANT,
        ("instant", 1),
    )
    assert instant_0 != instant_1
    mean_0 = volume_cache_key(
        Quantity.TEMPERATURE,
        settings,
        positions,
        grid,
        AggregationMethod.MEAN,
        ("range", 0, 5),
    )
    assert instant_0 != mean_0
    other_settings = volume_cache_key(
        Quantity.TEMPERATURE,
        replace(settings, idw_power=3.0),
        positions,
        grid,
        AggregationMethod.INSTANT,
        ("instant", 0),
    )
    assert instant_0 != other_settings


def test_lru_eviction() -> None:
    cache = InterpolationCache(max_volumes=2)
    cache.put_volume(("a",), np.zeros(2))
    cache.put_volume(("b",), np.zeros(2))
    cache.put_volume(("c",), np.zeros(2))
    assert len(cache) == 2
    assert cache.get_volume(("a",)) is None
    assert cache.get_volume(("b",)) is not None
    assert cache.get_volume(("c",)) is not None


def test_clear_and_counts() -> None:
    cache = InterpolationCache()
    cache.put_volume(("a",), np.zeros(2))
    assert len(cache) == 1
    cache.clear_volumes()
    assert len(cache) == 0
    cache.clear()
    assert cache.interpolator_count == 0
