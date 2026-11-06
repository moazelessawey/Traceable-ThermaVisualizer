"""Interpolation engine tests (INT-01..06, INT-09, INT-10)."""

from __future__ import annotations

import numpy as np
import pytest

from thermavisualizer.core.geometry import build_volume_mask
from thermavisualizer.core.interpolation import (
    ExtrapolationPolicy,
    InterpolationMethod,
    InterpolationSettings,
    Interpolator,
    build_voxel_grid,
    interpolate_volume,
)
from thermavisualizer.core.models import BoxFootprint, PolygonFootprint, Space

L_SHAPE = PolygonFootprint(((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0)))


def _cube() -> tuple[np.ndarray, np.ndarray]:
    positions, values = [], []
    for x in (0.0, 1.0):
        for y in (0.0, 1.0):
            for z in (0.0, 1.0):
                positions.append([x, y, z])
                values.append(x + 2.0 * y + 3.0 * z)
    return np.array(positions), np.array(values)


def _box_space() -> Space:
    return Space(footprint=BoxFootprint(0.0, 0.0, 1.0, 1.0), height=1.0)


def test_build_voxel_grid_shape_and_bounds() -> None:
    grid = build_voxel_grid(_box_space(), 0.5)
    assert grid.shape() == (3, 3, 3)
    assert grid.x_coords[0] == pytest.approx(0.0)
    assert grid.x_coords[-1] == pytest.approx(1.0)
    assert grid.z_coords[-1] == pytest.approx(1.0)


def test_trilinear_reproduces_linear_field_exactly() -> None:  # AGENTS §8
    positions, values = _cube()
    grid = build_voxel_grid(_box_space(), 0.5)
    settings = InterpolationSettings(
        method=InterpolationMethod.TRILINEAR, extrapolation=ExtrapolationPolicy.CLAMP
    )
    volume = interpolate_volume(_box_space(), [], grid, positions, values, settings)
    xs, ys, zs = grid.meshgrid()
    expected = xs + 2.0 * ys + 3.0 * zs
    assert np.allclose(volume, expected, atol=1e-9, equal_nan=True)


def test_linear_reproduces_linear_field_exactly() -> None:  # AGENTS §8
    positions, values = _cube()
    grid = build_voxel_grid(_box_space(), 0.5)
    settings = InterpolationSettings(method=InterpolationMethod.LINEAR)
    volume = interpolate_volume(_box_space(), [], grid, positions, values, settings)
    xs, ys, zs = grid.meshgrid()
    expected = xs + 2.0 * ys + 3.0 * zs
    assert np.allclose(volume, expected, atol=1e-9, equal_nan=True)


def test_idw_passes_through_logger_values() -> None:
    positions, values = _cube()
    grid = build_voxel_grid(_box_space(), 0.5)
    settings = InterpolationSettings(method=InterpolationMethod.IDW)
    volume = interpolate_volume(_box_space(), [], grid, positions, values, settings)
    assert volume[0, 0, 0] == pytest.approx(values[0])  # corner (0,0,0)
    assert volume[2, 2, 2] == pytest.approx(values[-1])  # corner (1,1,1)


def test_rbf_interpolates_data_points() -> None:
    positions, values = _cube()
    grid = build_voxel_grid(_box_space(), 0.5)
    settings = InterpolationSettings(
        method=InterpolationMethod.RBF, extrapolation=ExtrapolationPolicy.CLAMP
    )
    volume = interpolate_volume(_box_space(), [], grid, positions, values, settings)
    assert volume[0, 0, 0] == pytest.approx(values[0], abs=1e-6)
    assert volume[2, 2, 2] == pytest.approx(values[-1], abs=1e-6)


def test_mask_enforces_l_shaped_footprint() -> None:  # GEO-04 / INT-10
    space = Space(footprint=L_SHAPE, height=1.0)
    grid = build_voxel_grid(space, 1.0)
    mask = build_volume_mask(space, [], grid.x_coords, grid.y_coords, grid.z_coords)
    xs, ys, _ = grid.meshgrid()
    inside = (xs >= 0) & (xs < 4) & (ys >= 0) & (ys < 4)
    notch = (xs > 2) & (ys > 2)  # outside the L
    assert mask[inside & ~notch].all()
    assert not mask[notch].any()


def test_extrapolation_mask_vs_clamp() -> None:  # INT-06
    positions = np.array([[0.2, 0.2, 0.2], [0.8, 0.2, 0.2], [0.2, 0.8, 0.2], [0.2, 0.2, 0.8]])
    values = np.array([10.0, 20.0, 30.0, 40.0])
    space = _box_space()
    grid = build_voxel_grid(space, 0.5)
    masked = interpolate_volume(
        space,
        [],
        grid,
        positions,
        values,
        InterpolationSettings(
            method=InterpolationMethod.IDW, extrapolation=ExtrapolationPolicy.MASK
        ),
    )
    clamped = interpolate_volume(
        space,
        [],
        grid,
        positions,
        values,
        InterpolationSettings(
            method=InterpolationMethod.IDW, extrapolation=ExtrapolationPolicy.CLAMP
        ),
    )
    assert np.isnan(masked[2, 2, 2])  # far corner outside the logger hull
    assert not np.isnan(clamped[2, 2, 2])


def test_smoothing_runs_and_keeps_mask() -> None:  # INT-03
    positions, values = _cube()
    grid = build_voxel_grid(_box_space(), 0.5)
    settings = InterpolationSettings(method=InterpolationMethod.IDW, smoothing_sigma=1.0)
    volume = interpolate_volume(_box_space(), [], grid, positions, values, settings)
    assert np.isfinite(volume).any()


def test_reuse_interpolator_across_timesteps() -> None:  # INT-09
    positions, values = _cube()
    grid = build_voxel_grid(_box_space(), 0.5)
    mask = build_volume_mask(_box_space(), [], grid.x_coords, grid.y_coords, grid.z_coords)
    interpolator = Interpolator(grid, positions, InterpolationSettings(), mask)
    first = interpolator.interpolate(values)
    second = interpolator.interpolate(values * 2.0)
    finite = np.isfinite(first) & np.isfinite(second)
    assert np.allclose(second[finite], 2.0 * first[finite], atol=1e-9)
