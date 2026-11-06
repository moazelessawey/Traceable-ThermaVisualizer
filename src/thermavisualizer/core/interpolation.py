"""Spatial interpolation engine onto a voxel grid (INT-01..06, INT-09, INT-10).

Pure Python, headless (numpy/scipy only). Produces a masked 3D volume of
estimated values in °C or %RH. Interpolated values are estimates; the method is
carried in ``InterpolationSettings`` so the UI/exports can label it (AGENTS §9).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from scipy.interpolate import interpn
from scipy.linalg import lu_factor, lu_solve
from scipy.ndimage import gaussian_filter
from scipy.sparse import csr_matrix
from scipy.spatial import Delaunay, QhullError, cKDTree

from thermavisualizer.core.geometry import build_volume_mask, footprint_bounds
from thermavisualizer.core.models import Obstacle, Space

logger = logging.getLogger(__name__)


class InterpolationError(ValueError):
    """Raised when interpolation cannot be performed."""


class InterpolationMethod(StrEnum):
    """Interpolation method (INT-02)."""

    IDW = "idw"
    RBF = "rbf"
    LINEAR = "linear"
    TRILINEAR = "trilinear"


class ExtrapolationPolicy(StrEnum):
    """Behaviour outside the logger convex hull (INT-06)."""

    CLAMP = "clamp"  # nearest logger value
    MASK = "mask"  # NaN outside the hull


class RBFKernel(StrEnum):
    """Radial basis function kernel (INT-02)."""

    THIN_PLATE_SPLINE = "thin_plate_spline"
    MULTIQUADRIC = "multiquadric"
    INVERSE_MULTIQUADRIC = "inverse_multiquadric"
    GAUSSIAN = "gaussian"
    LINEAR = "linear"
    CUBIC = "cubic"


@dataclass(frozen=True)
class VoxelGrid:
    """A regular 3D grid over the space. Units: metres."""

    x_coords: np.ndarray
    y_coords: np.ndarray
    z_coords: np.ndarray

    def shape(self) -> tuple[int, int, int]:
        """Grid dimensions ``(nx, ny, nz)``."""
        return (self.x_coords.size, self.y_coords.size, self.z_coords.size)

    def meshgrid(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Coordinate arrays broadcast to the full grid shape."""
        return np.meshgrid(self.x_coords, self.y_coords, self.z_coords, indexing="ij")

    def points(self) -> np.ndarray:
        """Flattened ``(M, 3)`` grid points in C order matching ``shape()``."""
        xs, ys, zs = self.meshgrid()
        return np.column_stack([xs.ravel(), ys.ravel(), zs.ravel()])


def build_voxel_grid(space: Space, resolution: float | tuple[float, float, float]) -> VoxelGrid:
    """Discretize the space bounding box into a regular grid (INT-01). Units: metres."""
    x_min, y_min, x_max, y_max = footprint_bounds(space.footprint)
    if isinstance(resolution, (int, float)):
        rx = ry = rz = float(resolution)
    else:
        rx, ry, rz = (float(v) for v in resolution)
    if rx <= 0 or ry <= 0 or rz <= 0:
        raise InterpolationError("voxel resolution must be positive")
    nx = max(2, int(math.ceil((x_max - x_min) / rx)) + 1)
    ny = max(2, int(math.ceil((y_max - y_min) / ry)) + 1)
    nz = max(2, int(math.ceil(space.height / rz)) + 1)
    return VoxelGrid(
        np.linspace(x_min, x_max, nx),
        np.linspace(y_min, y_max, ny),
        np.linspace(0.0, space.height, nz),
    )


def _pairwise_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a[:, None, :] - b[None, :, :]
    return np.sqrt((diff**2).sum(axis=2))


def _rbf_phi(r: np.ndarray, kernel: RBFKernel, epsilon: float) -> np.ndarray:
    if kernel is RBFKernel.THIN_PLATE_SPLINE:
        safe = np.where(r > 0, r, 1.0)
        return np.where(r > 0, r * r * np.log(safe), 0.0)
    if kernel is RBFKernel.MULTIQUADRIC:
        return np.sqrt(1.0 + (epsilon * r) ** 2)
    if kernel is RBFKernel.INVERSE_MULTIQUADRIC:
        return 1.0 / np.sqrt(1.0 + (epsilon * r) ** 2)
    if kernel is RBFKernel.GAUSSIAN:
        return np.exp(-((epsilon * r) ** 2))
    if kernel is RBFKernel.LINEAR:
        return r
    if kernel is RBFKernel.CUBIC:
        return r**3
    raise InterpolationError(f"unknown RBF kernel '{kernel}'")


def _smooth_volume(volume: np.ndarray, sigma: float) -> np.ndarray:
    """NaN-aware Gaussian smoothing (INT-03). Units preserved."""
    valid = ~np.isnan(volume)
    if not valid.any():
        return volume
    numerator = gaussian_filter(np.where(valid, volume, 0.0), sigma, mode="nearest")
    denominator = gaussian_filter(valid.astype(float), sigma, mode="nearest")
    with np.errstate(divide="ignore", invalid="ignore"):
        smoothed = numerator / np.where(denominator > 0, denominator, 1.0)
    return np.where(denominator > 0, smoothed, np.nan)


class Interpolator:
    """Interpolates logger values onto a fixed voxel grid (INT-02, INT-09).

    Geometry that is constant across time steps (weights, hull, nearest index)
    is precomputed once; each call to :meth:`interpolate` is then a matrix
    product plus masking, which keeps animation and movie export fast (INT-09).
    """

    def __init__(
        self,
        grid: VoxelGrid,
        positions: np.ndarray,
        settings: InterpolationSettings,
        mask: np.ndarray | None = None,
    ) -> None:
        self._grid = grid
        self._positions = np.asarray(positions, dtype=float)
        self._settings = settings
        self._mask = mask
        if self._positions.ndim != 2 or self._positions.shape[1] != 3:
            raise InterpolationError("logger positions must be an (N, 3) array")
        self._grid_points = grid.points()
        self._idw_weights: np.ndarray | None = None
        self._linear_weights: csr_matrix | None = None
        self._rbf_eval: np.ndarray | None = None
        self._rbf_lu: tuple[np.ndarray, np.ndarray] | None = None
        self._tri_axes: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        self._tri_index: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        self._nearest_index: np.ndarray | None = None
        self._hull_mask: np.ndarray | None = None
        self._precompute()

    # ----------------------------------------------------------- precompute

    def _precompute(self) -> None:
        grid_points = self._grid_points
        positions = self._positions
        self._nearest_index = cKDTree(positions).query(grid_points)[1]
        self._hull_mask = self._compute_hull_mask(grid_points, positions)
        method = self._settings.method
        if method is InterpolationMethod.IDW:
            self._idw_weights = self._idw_weight_matrix(
                grid_points, positions, self._settings.idw_power
            )
        elif method is InterpolationMethod.LINEAR:
            self._linear_weights = self._linear_weight_matrix(grid_points, positions)
        elif method is InterpolationMethod.RBF:
            self._rbf_precompute(grid_points, positions)
        elif method is InterpolationMethod.TRILINEAR:
            self._trilinear_precompute(positions)
        else:
            raise InterpolationError(f"unknown interpolation method '{method}'")

    def _compute_hull_mask(self, grid_points: np.ndarray, positions: np.ndarray) -> np.ndarray:
        if positions.shape[0] < 4:
            return np.ones(grid_points.shape[0], dtype=bool)
        try:
            hull = Delaunay(positions)
            return hull.find_simplex(grid_points) >= 0
        except QhullError as error:
            logger.warning("convex hull unavailable (%s); skipping hull mask", error)
            return np.ones(grid_points.shape[0], dtype=bool)

    def _idw_weight_matrix(
        self, grid_points: np.ndarray, positions: np.ndarray, power: float
    ) -> np.ndarray:
        if power <= 0:
            raise InterpolationError("IDW power must be positive")
        distance = _pairwise_distance(grid_points, positions)
        epsilon = 1e-12
        coincident = distance < epsilon
        safe = np.where(distance < epsilon, epsilon, distance)
        inverse = 1.0 / safe**power
        weights = inverse / inverse.sum(axis=1, keepdims=True)
        rows = coincident.any(axis=1)
        if rows.any():
            weights[rows] = 0.0
            weights[rows, coincident[rows].argmax(axis=1)] = 1.0
        return weights

    def _linear_weight_matrix(self, grid_points: np.ndarray, positions: np.ndarray) -> csr_matrix:
        n_points, dim = positions.shape
        n_grid = grid_points.shape[0]
        try:
            triangulation = Delaunay(positions)
        except QhullError as error:
            raise InterpolationError(f"linear interpolation needs a valid hull: {error}")
        simplex = triangulation.find_simplex(grid_points)
        inside = simplex >= 0
        if not inside.any():
            return csr_matrix((n_grid, n_points))
        transform = triangulation.transform[simplex[inside]]
        delta = grid_points[inside] - transform[:, dim, :]
        barycentric = np.einsum("ijk,ik->ij", transform[:, :dim, :], delta)
        full = np.column_stack([barycentric, 1.0 - barycentric.sum(axis=1)])
        rows = np.repeat(np.where(inside)[0], dim + 1)
        cols = triangulation.simplices[simplex[inside]].ravel()
        return csr_matrix((full.ravel(), (rows, cols)), shape=(n_grid, n_points))

    def _rbf_precompute(self, grid_points: np.ndarray, positions: np.ndarray) -> None:
        settings = self._settings
        self._rbf_eval = _rbf_phi(
            _pairwise_distance(grid_points, positions),
            settings.rbf_kernel,
            settings.rbf_epsilon,
        )
        system = _rbf_phi(
            _pairwise_distance(positions, positions),
            settings.rbf_kernel,
            settings.rbf_epsilon,
        )
        if settings.rbf_smoothing > 0:
            system = system + settings.rbf_smoothing * np.eye(positions.shape[0])
        self._rbf_lu = lu_factor(system)

    def _trilinear_precompute(self, positions: np.ndarray) -> None:
        xs = np.unique(np.round(positions[:, 0], 9))
        ys = np.unique(np.round(positions[:, 1], 9))
        zs = np.unique(np.round(positions[:, 2], 9))
        if xs.size * ys.size * zs.size != positions.shape[0]:
            raise InterpolationError("trilinear interpolation requires loggers on a regular grid")
        self._tri_axes = (xs, ys, zs)
        self._tri_index = (
            np.searchsorted(xs, np.round(positions[:, 0], 9)),
            np.searchsorted(ys, np.round(positions[:, 1], 9)),
            np.searchsorted(zs, np.round(positions[:, 2], 9)),
        )

    # ------------------------------------------------------------ evaluation

    def _evaluate(self, values: np.ndarray) -> np.ndarray:
        method = self._settings.method
        if method is InterpolationMethod.IDW:
            assert self._idw_weights is not None
            return np.asarray(self._idw_weights @ values, dtype=float)
        if method is InterpolationMethod.LINEAR:
            assert self._linear_weights is not None
            return np.asarray(self._linear_weights @ values, dtype=float)
        if method is InterpolationMethod.RBF:
            assert self._rbf_eval is not None and self._rbf_lu is not None
            coefficients = lu_solve(self._rbf_lu, values)
            return np.asarray(self._rbf_eval @ coefficients, dtype=float)
        if method is InterpolationMethod.TRILINEAR:
            assert self._tri_axes is not None and self._tri_index is not None
            xs, ys, zs = self._tri_axes
            data = np.full((xs.size, ys.size, zs.size), np.nan)
            i, j, k = self._tri_index
            data[i, j, k] = values
            return np.asarray(
                interpn(
                    (xs, ys, zs),
                    data,
                    self._grid_points,
                    method="linear",
                    bounds_error=False,
                    fill_value=np.nan,
                ),
                dtype=float,
            )
        raise InterpolationError(f"unknown interpolation method '{method}'")

    def _apply_extrapolation(self, flat: np.ndarray, values: np.ndarray) -> np.ndarray:
        assert self._hull_mask is not None and self._nearest_index is not None
        if self._settings.extrapolation is ExtrapolationPolicy.CLAMP:
            nearest_values = values[self._nearest_index]
            outside = (~self._hull_mask) | np.isnan(flat)
            return np.where(outside, nearest_values, flat)
        return np.where(self._hull_mask, flat, np.nan)

    def interpolate(self, values: np.ndarray) -> np.ndarray:
        """Interpolate one time step's per-logger values into a masked volume.

        ``values`` has one entry per logger (same order as the positions given
        to the constructor). Returns an ``(nx, ny, nz)`` float array with NaN
        where masked or outside the hull. Units match the input (°C / %RH).
        """
        values = np.asarray(values, dtype=float)
        if values.shape[0] != self._positions.shape[0]:
            raise InterpolationError(
                f"expected {self._positions.shape[0]} values, got {values.shape[0]}"
            )
        flat = self._evaluate(values)
        flat = self._apply_extrapolation(flat, values)
        volume = flat.reshape(self._grid.shape())
        if self._mask is not None:
            volume = np.where(self._mask, volume, np.nan)
        if self._settings.smoothing_sigma > 0:
            volume = _smooth_volume(volume, self._settings.smoothing_sigma)
        return volume


def interpolate_volume(
    space: Space,
    obstacles: list[Obstacle],
    grid: VoxelGrid,
    positions: np.ndarray,
    values: np.ndarray,
    settings: InterpolationSettings,
) -> np.ndarray:
    """Convenience: build the geometry mask and interpolate one time step."""
    mask = build_volume_mask(space, obstacles, grid.x_coords, grid.y_coords, grid.z_coords)
    interpolator = Interpolator(grid, positions, settings, mask)
    return interpolator.interpolate(values)


@dataclass(frozen=True)
class InterpolationSettings:
    """Interpolation parameters (INT-01/02/03/06). Units: metres."""

    method: InterpolationMethod = InterpolationMethod.IDW
    idw_power: float = 2.0
    rbf_kernel: RBFKernel = RBFKernel.THIN_PLATE_SPLINE
    rbf_epsilon: float = 1.0
    rbf_smoothing: float = 0.0
    smoothing_sigma: float = 0.0  # 0 disables Gaussian spatial smoothing
    extrapolation: ExtrapolationPolicy = ExtrapolationPolicy.MASK
    resolution: float = 0.2  # voxel edge length in metres (INT-01)
