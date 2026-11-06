"""Interpolation caches (INT-07, INT-09): volumes per (parameters, time) key.

Thread-safe: worker threads write while the GUI thread reads. Geometry keys
are in metres; volumes carry the quantity unit (°C / %RH).
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Hashable
from threading import Lock
from typing import Any

import numpy as np

from thermavisualizer.core.interpolation import (
    InterpolationSettings,
    Interpolator,
    VoxelGrid,
)
from thermavisualizer.core.models import Quantity
from thermavisualizer.core.statistics import AggregationMethod

CacheKey = tuple[Any, ...]


def array_fingerprint(array: np.ndarray) -> str:
    """Short content hash (shape + bytes) of an array for cache keys."""
    digest = hashlib.sha256()
    digest.update(np.asarray(array.shape, dtype=np.int64).tobytes())
    digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()[:16]


def grid_key(grid: VoxelGrid) -> tuple[float | int, ...]:
    """Fingerprint of a voxel grid (bounds, counts). Units: metres."""
    return (
        float(grid.x_coords[0]),
        float(grid.x_coords[-1]),
        int(grid.x_coords.size),
        float(grid.y_coords[0]),
        float(grid.y_coords[-1]),
        int(grid.y_coords.size),
        float(grid.z_coords[0]),
        float(grid.z_coords[-1]),
        int(grid.z_coords.size),
    )


def settings_key(settings: InterpolationSettings) -> tuple[Hashable, ...]:
    """Fingerprint of every setting that can change a volume."""
    return (
        settings.method.value,
        settings.idw_power,
        settings.rbf_kernel.value,
        settings.rbf_epsilon,
        settings.rbf_smoothing,
        settings.smoothing_sigma,
        settings.extrapolation.value,
        settings.resolution,
    )


def interpolator_key(
    settings: InterpolationSettings,
    positions: np.ndarray,
    grid: VoxelGrid,
    mask: np.ndarray,
) -> CacheKey:
    """Key for a precomputed interpolator (INT-09): layout, method, geometry, grid.

    Per-step options (extrapolation policy, output smoothing) are excluded
    because they are applied after the weights, so weights stay reusable.
    """
    return (
        settings.method.value,
        settings.idw_power,
        settings.rbf_kernel.value,
        settings.rbf_epsilon,
        settings.rbf_smoothing,
        array_fingerprint(positions),
        grid_key(grid),
        array_fingerprint(mask),
    )


def volume_cache_key(
    quantity: Quantity,
    settings: InterpolationSettings,
    positions: np.ndarray,
    grid: VoxelGrid,
    aggregation: AggregationMethod,
    time_key: Hashable,
) -> CacheKey:
    """Key for one cached volume per (parameters, time) (INT-07)."""
    return (
        quantity.value,
        settings_key(settings),
        array_fingerprint(positions),
        grid_key(grid),
        aggregation.value,
        time_key,
    )


class InterpolationCache:
    """Thread-safe LRU caches for volumes and precomputed interpolators."""

    def __init__(self, max_volumes: int = 64, max_interpolators: int = 4) -> None:
        self._lock = Lock()
        self._volumes: OrderedDict[CacheKey, np.ndarray] = OrderedDict()
        self._interpolators: OrderedDict[CacheKey, Interpolator] = OrderedDict()
        self._max_volumes = max(1, max_volumes)
        self._max_interpolators = max(1, max_interpolators)

    def get_volume(self, key: CacheKey) -> np.ndarray | None:
        """Return the cached volume for ``key``, refreshing its recency."""
        with self._lock:
            if key in self._volumes:
                self._volumes.move_to_end(key)
                return self._volumes[key]
        return None

    def put_volume(self, key: CacheKey, volume: np.ndarray) -> None:
        """Store a volume, evicting the least-recently-used entry when full."""
        with self._lock:
            self._volumes[key] = volume
            self._volumes.move_to_end(key)
            while len(self._volumes) > self._max_volumes:
                self._volumes.popitem(last=False)

    def get_interpolator(self, key: CacheKey) -> Interpolator | None:
        """Return the cached interpolator for ``key``, refreshing recency."""
        with self._lock:
            if key in self._interpolators:
                self._interpolators.move_to_end(key)
                return self._interpolators[key]
        return None

    def put_interpolator(self, key: CacheKey, interpolator: Interpolator) -> None:
        """Store a precomputed interpolator (INT-09 weight reuse)."""
        with self._lock:
            self._interpolators[key] = interpolator
            self._interpolators.move_to_end(key)
            while len(self._interpolators) > self._max_interpolators:
                self._interpolators.popitem(last=False)

    def clear_volumes(self) -> None:
        """Drop cached volumes (keep interpolator weights)."""
        with self._lock:
            self._volumes.clear()

    def clear(self) -> None:
        """Drop everything (layout/settings changed)."""
        with self._lock:
            self._volumes.clear()
            self._interpolators.clear()

    def __len__(self) -> int:
        """Number of cached volumes."""
        with self._lock:
            return len(self._volumes)

    @property
    def interpolator_count(self) -> int:
        """Number of cached interpolators."""
        with self._lock:
            return len(self._interpolators)
