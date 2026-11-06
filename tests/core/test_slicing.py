"""Slice extraction and isosurface tests (SLC-01/04/05, GEO-04, OBS-05)."""

from __future__ import annotations

import numpy as np
import pytest

from thermavisualizer.core.interpolation import VoxelGrid, build_voxel_grid
from thermavisualizer.core.models import (
    BoxFootprint,
    Obstacle,
    ObstacleShape,
    ObstacleType,
    PolygonFootprint,
    Space,
)
from thermavisualizer.core.slicing import (
    SliceAxis,
    SliceError,
    extract_axis_slice,
    extract_isosurface,
    extract_plane_slice,
)

L_SHAPE = PolygonFootprint(((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0)))


def _box_space() -> Space:
    return Space(footprint=BoxFootprint(0.0, 0.0, 1.0, 1.0), height=1.0)


def _linear_volume(grid: VoxelGrid) -> np.ndarray:
    xs, ys, zs = grid.meshgrid()
    return xs + 2.0 * ys + 3.0 * zs


def test_axis_slice_reproduces_linear_field_exactly() -> None:  # SLC-01, §8
    space = _box_space()
    grid = build_voxel_grid(space, 0.25)
    volume = _linear_volume(grid)
    sliced = extract_axis_slice(volume, grid, space, [], SliceAxis.Z, 0.5)
    expected = sliced.points[:, 0] + 2.0 * sliced.points[:, 1] + 3.0 * 0.5
    assert np.allclose(sliced.values, expected, atol=1e-9)
    assert sliced.u_count == grid.x_coords.size
    assert sliced.v_count == grid.y_coords.size
    assert sliced.points.shape == (sliced.u_count * sliced.v_count, 3)


def test_axis_slice_outside_grid_raises() -> None:
    space = _box_space()
    grid = build_voxel_grid(space, 0.25)
    volume = _linear_volume(grid)
    with pytest.raises(SliceError):
        extract_axis_slice(volume, grid, space, [], SliceAxis.Z, 5.0)


def test_plane_slice_horizontal_matches_field() -> None:  # SLC-04
    space = _box_space()
    grid = build_voxel_grid(space, 0.25)
    volume = _linear_volume(grid)
    sliced = extract_plane_slice(
        volume, grid, space, [], point=(0.5, 0.5, 0.5), normal=(0.0, 0.0, 1.0)
    )
    assert np.allclose(sliced.points[:, 2], 0.5, atol=1e-9)
    expected = sliced.points[:, 0] + 2.0 * sliced.points[:, 1] + 3.0 * 0.5
    finite = np.isfinite(sliced.values)
    assert finite.any()
    assert np.allclose(sliced.values[finite], expected[finite], atol=1e-9)


def test_plane_slice_rejects_zero_normal() -> None:
    space = _box_space()
    grid = build_voxel_grid(space, 0.5)
    volume = _linear_volume(grid)
    with pytest.raises(SliceError):
        extract_plane_slice(volume, grid, space, [], point=(0.5, 0.5, 0.5), normal=(0.0, 0.0, 0.0))


def test_axis_slice_masks_l_shaped_notch() -> None:  # GEO-04 / INT-10
    space = Space(footprint=L_SHAPE, height=1.0)
    grid = build_voxel_grid(space, 0.5)
    volume = np.ones(grid.shape())
    sliced = extract_axis_slice(volume, grid, space, [], SliceAxis.Z, 0.5)
    xs, ys = sliced.points[:, 0], sliced.points[:, 1]
    notch = (xs > 2.0) & (ys > 2.0)
    interior = (xs < 1.5) & (ys < 1.5)
    assert notch.any() and interior.any()
    assert np.isnan(sliced.values[notch]).all()
    assert np.allclose(sliced.values[interior], 1.0)


def test_axis_slice_masks_solid_obstacle() -> None:  # OBS-05
    space = Space(footprint=BoxFootprint(0.0, 0.0, 2.0, 2.0), height=2.0)
    grid = build_voxel_grid(space, 0.5)
    volume = np.ones(grid.shape())
    obstacle = Obstacle(
        name="rack",
        obstacle_type=ObstacleType.RACK,
        shape=ObstacleShape.BOX,
        x=1.0,
        y=1.0,
        z=1.0,
        size_x=1.0,
        size_y=1.0,
        size_z=1.0,
        solid=True,
    )
    sliced = extract_axis_slice(volume, grid, space, [obstacle], SliceAxis.X, 1.0)
    ys, zs = sliced.points[:, 1], sliced.points[:, 2]
    centre = (np.abs(ys - 1.0) < 0.4) & (np.abs(zs - 1.0) < 0.4)
    corner = (ys < 0.3) & (zs < 0.3)
    assert centre.any() and corner.any()
    assert np.isnan(sliced.values[centre]).all()
    assert np.allclose(sliced.values[corner], 1.0)


def test_isosurface_of_linear_field_is_plane() -> None:  # SLC-05
    space = _box_space()
    grid = build_voxel_grid(space, 0.25)
    _, _, zs = grid.meshgrid()
    iso = extract_isosurface(zs, grid, space, [], level=0.47)
    assert iso.vertices.shape[0] > 0
    assert iso.faces.shape[0] > 0
    assert np.allclose(iso.vertices[:, 2], 0.47, atol=1e-6)
    assert iso.faces.min() >= 0
    assert iso.faces.max() < iso.vertices.shape[0]


def test_isosurface_level_not_crossed_is_empty() -> None:
    space = _box_space()
    grid = build_voxel_grid(space, 0.25)
    volume = np.zeros(grid.shape())
    iso = extract_isosurface(volume, grid, space, [], level=5.0)
    assert iso.vertices.shape == (0, 3)
    assert iso.faces.shape == (0, 3)


def test_isosurface_excludes_solid_obstacle_interior() -> None:  # OBS-05
    space = Space(footprint=BoxFootprint(0.0, 0.0, 2.0, 2.0), height=2.0)
    grid = build_voxel_grid(space, 0.5)
    _, _, zs = grid.meshgrid()
    obstacle = Obstacle(
        name="rack",
        obstacle_type=ObstacleType.RACK,
        shape=ObstacleShape.BOX,
        x=1.0,
        y=1.0,
        z=1.0,
        size_x=1.0,
        size_y=1.0,
        size_z=1.0,
        solid=True,
    )
    iso = extract_isosurface(zs, grid, space, [obstacle], level=0.9)
    assert iso.faces.shape[0] > 0
    centroids = iso.vertices[iso.faces].mean(axis=1)
    interior = (
        (centroids[:, 0] > 0.55)
        & (centroids[:, 0] < 1.45)
        & (centroids[:, 1] > 0.55)
        & (centroids[:, 1] < 1.45)
    )
    assert not interior.any()


def test_sample_volume_probe() -> None:  # SLC-06
    space = _box_space()
    grid = build_voxel_grid(space, 0.25)
    volume = _linear_volume(grid)
    from thermavisualizer.core.slicing import sample_volume

    value = sample_volume(volume, grid, (0.25, 0.5, 0.75))
    assert value == pytest.approx(0.25 + 2.0 * 0.5 + 3.0 * 0.75, abs=1e-9)
    assert np.isnan(sample_volume(volume, grid, (5.0, 5.0, 5.0)))


def test_slice_spec_dict_roundtrip() -> None:
    from thermavisualizer.core.slicing import SliceSpec, slice_spec_from_dict, slice_spec_to_dict

    spec = SliceSpec(
        spec_id="plane",
        axis=None,
        point=(1.0, 2.0, 3.0),
        normal=(0.0, 0.0, 1.0),
        opacity=0.5,
        visible=False,
    )
    assert slice_spec_from_dict(slice_spec_to_dict(spec)) == spec
