"""Slice extraction and isosurfaces from interpolated volumes (SLC-01/04/05).

Pure Python, headless (numpy/scipy/scikit-image). Coordinates in metres;
values in °C or %RH depending on the input volume's quantity. Samples outside
the space geometry or inside solid obstacles are NaN (GEO-04, OBS-05, INT-10).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import distance_transform_edt
from skimage.measure import marching_cubes

from thermavisualizer.core.geometry import (
    footprint_bounds,
    obstacle_contains_xyz,
    point_in_space_xyz,
)
from thermavisualizer.core.interpolation import VoxelGrid
from thermavisualizer.core.models import Obstacle, Space


class SliceError(ValueError):
    """Raised when a slice or isosurface cannot be extracted."""


class SliceAxis(StrEnum):
    """Axis-aligned slice plane orientation (SLC-01)."""

    X = "x"
    Y = "y"
    Z = "z"


@dataclass(frozen=True)
class SliceData:
    """Sampled slice on a regular (u, v) grid (SLC-01/04).

    ``points`` has shape ``(u_count * v_count, 3)`` ordered u-major with v
    varying fastest (reshape to ``(u_count, v_count, 3)``); ``values`` matches.
    NaN marks samples outside the geometry. Units: metres; °C or %RH.
    """

    points: np.ndarray
    values: np.ndarray
    u_count: int
    v_count: int


@dataclass(frozen=True)
class Isosurface:
    """Triangular isosurface mesh (SLC-05). Units: metres."""

    vertices: np.ndarray  # (V, 3)
    faces: np.ndarray  # (F, 3) integer vertex indices


@dataclass(frozen=True)
class SliceSpec:
    """User-facing slice definition (SLC-01/02/04). Units: metres."""

    spec_id: str
    axis: SliceAxis | None = SliceAxis.Z  # None = arbitrary plane
    position: float = 0.0
    point: tuple[float, float, float] = (0.0, 0.0, 0.0)
    normal: tuple[float, float, float] = (0.0, 0.0, 1.0)
    opacity: float = 1.0
    visible: bool = True


# ------------------------------------------------------------------ helpers


def _geometry_mask_xyz(
    space: Space,
    obstacles: Sequence[Obstacle],
    xs: np.ndarray,
    ys: np.ndarray,
    zs: np.ndarray,
) -> np.ndarray:
    mask = point_in_space_xyz(space, xs, ys, zs)
    for obstacle in obstacles:
        if obstacle.solid:
            mask &= ~obstacle_contains_xyz(obstacle, xs, ys, zs)
    return mask


def _filled_volume(volume: np.ndarray) -> np.ndarray:
    """Replace NaN voxels with their nearest valid neighbour (sampling only).

    The source volume is never mutated (data-integrity rule).
    """
    invalid = np.isnan(volume)
    if not invalid.any() or invalid.all():
        return volume
    indices = distance_transform_edt(invalid, return_distances=False, return_indices=True)
    return volume[tuple(indices)]


def _volume_interpolator(volume: np.ndarray, grid: VoxelGrid) -> RegularGridInterpolator:
    return RegularGridInterpolator(
        (grid.x_coords, grid.y_coords, grid.z_coords),
        _filled_volume(volume),
        method="linear",
        bounds_error=False,
        fill_value=np.nan,
    )


def _mask_values(
    space: Space, obstacles: Sequence[Obstacle], points: np.ndarray, values: np.ndarray
) -> np.ndarray:
    valid = _geometry_mask_xyz(space, obstacles, points[:, 0], points[:, 1], points[:, 2])
    return np.where(valid, values, np.nan)


def _grid_spacing(grid: VoxelGrid) -> float:
    return float(
        min(
            np.diff(grid.x_coords).min(),
            np.diff(grid.y_coords).min(),
            np.diff(grid.z_coords).min(),
        )
    )


# ------------------------------------------------------------------- slices


def extract_axis_slice(
    volume: np.ndarray,
    grid: VoxelGrid,
    space: Space,
    obstacles: Sequence[Obstacle],
    axis: SliceAxis,
    position: float,
) -> SliceData:
    """Extract an axis-aligned slice plane at ``position`` metres (SLC-01).

    u runs along the first remaining axis and v along the second: for X slices
    (u, v) = (y, z); for Y slices (x, z); for Z slices (x, y). Units: metres.
    """
    if axis is SliceAxis.X:
        fixed, first, second = grid.x_coords, grid.y_coords, grid.z_coords
    elif axis is SliceAxis.Y:
        fixed, first, second = grid.y_coords, grid.x_coords, grid.z_coords
    else:
        fixed, first, second = grid.z_coords, grid.x_coords, grid.y_coords
    if not (float(fixed.min()) <= position <= float(fixed.max())):
        raise SliceError(f"slice position {position} m is outside the grid along '{axis.value}'")
    uu, vv = np.meshgrid(first, second, indexing="ij")
    flat_u = uu.ravel()
    flat_v = vv.ravel()
    constant = np.full(flat_u.shape, float(position))
    if axis is SliceAxis.X:
        points = np.column_stack([constant, flat_u, flat_v])
    elif axis is SliceAxis.Y:
        points = np.column_stack([flat_u, constant, flat_v])
    else:
        points = np.column_stack([flat_u, flat_v, constant])
    values = np.asarray(_volume_interpolator(volume, grid)(points), dtype=float)
    values = _mask_values(space, obstacles, points, values)
    return SliceData(points=points, values=values, u_count=first.size, v_count=second.size)


def extract_plane_slice(
    volume: np.ndarray,
    grid: VoxelGrid,
    space: Space,
    obstacles: Sequence[Obstacle],
    point: tuple[float, float, float],
    normal: tuple[float, float, float],
) -> SliceData:
    """Extract an arbitrary slice plane through ``point`` with ``normal`` (SLC-04).

    The plane is sampled on a regular (u, v) grid covering the projected space
    bounding box, at the voxel grid spacing. Units: metres.
    """
    normal_vector = np.asarray(normal, dtype=float)
    norm = float(np.linalg.norm(normal_vector))
    if norm <= 0.0:
        raise SliceError("slice plane normal must be non-zero")
    n = normal_vector / norm
    helper = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u_dir = np.cross(n, helper)
    u_dir = u_dir / np.linalg.norm(u_dir)
    v_dir = np.cross(n, u_dir)

    x_min, y_min, x_max, y_max = footprint_bounds(space.footprint)
    corners = np.array(
        [[x, y, z] for x in (x_min, x_max) for y in (y_min, y_max) for z in (0.0, space.height)]
    )
    relative = corners - np.asarray(point, dtype=float)
    u_proj = relative @ u_dir
    v_proj = relative @ v_dir
    spacing = _grid_spacing(grid)
    u_count = max(2, int(np.ceil((u_proj.max() - u_proj.min()) / spacing)) + 1)
    v_count = max(2, int(np.ceil((v_proj.max() - v_proj.min()) / spacing)) + 1)
    u_values = np.linspace(u_proj.min(), u_proj.max(), u_count)
    v_values = np.linspace(v_proj.min(), v_proj.max(), v_count)
    uu, vv = np.meshgrid(u_values, v_values, indexing="ij")
    origin = np.asarray(point, dtype=float)
    points = (
        origin[None, :]
        + uu.ravel()[:, None] * u_dir[None, :]
        + vv.ravel()[:, None] * v_dir[None, :]
    )
    values = np.asarray(_volume_interpolator(volume, grid)(points), dtype=float)
    values = _mask_values(space, obstacles, points, values)
    return SliceData(points=points, values=values, u_count=u_count, v_count=v_count)


# -------------------------------------------------------------- isosurfaces


def extract_isosurface(
    volume: np.ndarray,
    grid: VoxelGrid,
    space: Space,
    obstacles: Sequence[Obstacle],
    level: float,
) -> Isosurface:
    """Extract an isosurface at ``level`` via marching cubes (SLC-05).

    Masked voxels cannot contribute surface: they are flattened to the level
    before extraction, and any face whose centroid lies outside the geometry
    (walls or solid obstacles) is removed. Returns empty arrays when the level
    is not crossed. Units: metres; level in the volume's quantity unit.
    """
    filled = _filled_volume(volume)
    masked = np.isnan(volume)
    working = filled.copy()
    working[masked] = level
    spacing = (
        float(grid.x_coords[1] - grid.x_coords[0]),
        float(grid.y_coords[1] - grid.y_coords[0]),
        float(grid.z_coords[1] - grid.z_coords[0]),
    )
    try:
        vertices, faces, _, _ = marching_cubes(working, level=level, spacing=spacing)
    except (RuntimeError, ValueError):
        return Isosurface(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    origin = np.array([grid.x_coords[0], grid.y_coords[0], grid.z_coords[0]], dtype=float)
    vertices = vertices + origin
    centroids = vertices[faces].mean(axis=1)
    keep = _geometry_mask_xyz(space, obstacles, centroids[:, 0], centroids[:, 1], centroids[:, 2])
    faces = faces[keep]
    if faces.size == 0:
        return Isosurface(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    used = np.unique(faces)
    remap = np.full(vertices.shape[0], -1, dtype=np.int64)
    remap[used] = np.arange(used.size)
    return Isosurface(vertices[used], remap[faces])


def sample_volume(volume: np.ndarray, grid: VoxelGrid, point: tuple[float, float, float]) -> float:
    """Trilinearly sample the volume at ``point`` (SLC-06 probe).

    Returns NaN outside the grid extent. Masked gaps are nearest-filled for
    sampling continuity; callers must check space geometry themselves. Units:
    metres; value in the volume's quantity unit (°C / %RH).
    """
    interpolator = RegularGridInterpolator(
        (grid.x_coords, grid.y_coords, grid.z_coords),
        _filled_volume(volume),
        method="linear",
        bounds_error=False,
        fill_value=np.nan,
    )
    sample = np.asarray(point, dtype=float).reshape(1, 3)
    return float(interpolator(sample)[0])


def slice_spec_to_dict(spec: SliceSpec) -> dict:
    """JSON-safe representation of a slice spec (view state)."""
    return {
        "spec_id": spec.spec_id,
        "axis": None if spec.axis is None else spec.axis.value,
        "position": spec.position,
        "point": list(spec.point),
        "normal": list(spec.normal),
        "opacity": spec.opacity,
        "visible": spec.visible,
    }


def slice_spec_from_dict(data: dict) -> SliceSpec:
    """Build a slice spec from stored view state (StrEnums re-wrapped)."""
    return SliceSpec(
        spec_id=str(data["spec_id"]),
        axis=None if data.get("axis") is None else SliceAxis(str(data["axis"])),
        position=float(data.get("position", 0.0)),
        point=tuple(float(v) for v in data.get("point", (0.0, 0.0, 0.0))),
        normal=tuple(float(v) for v in data.get("normal", (0.0, 0.0, 1.0))),
        opacity=float(data.get("opacity", 1.0)),
        visible=bool(data.get("visible", True)),
    )
