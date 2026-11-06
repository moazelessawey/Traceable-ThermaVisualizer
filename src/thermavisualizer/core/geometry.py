"""Spatial queries and checks for footprints, spaces, and obstacles.

Pure Python, no Qt imports (AGENTS rule 4). All coordinates in metres.
Geometry is never assumed to be a box: every spatial check goes through the
``Space`` footprint (AGENTS architecture rule).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from thermavisualizer.core.models import (
    BoxFootprint,
    ConfigurationError,
    Footprint,
    Obstacle,
    ObstacleShape,
    ObstacleType,
    PolygonFootprint,
    Space,
)

TOLERANCE = 1e-9

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]


def polygon_is_simple(vertices: Sequence[Point2], tolerance: float = TOLERANCE) -> bool:
    """Return True if the polygon is simple (GEO-02).

    Rejects fewer than 3 vertices, duplicate vertices (including pinch
    points), crossing edges, and overlapping collinear edges.
    """
    n = len(vertices)
    if n < 3:
        return False
    for i in range(n):
        for j in range(i + 1, n):
            if _close_2d(vertices[i], vertices[j], tolerance):
                return False
    for i in range(n):
        a, b = vertices[i], vertices[(i + 1) % n]
        for j in range(i + 1, n):
            c, d = vertices[j], vertices[(j + 1) % n]
            if _properly_intersect(a, b, c, d):
                return False
            if _collinear_overlap(a, b, c, d, tolerance):
                return False
    return True


def validate_footprint(footprint: Footprint) -> None:
    """Raise ConfigurationError if the footprint is not usable (GEO-02)."""
    if isinstance(footprint, PolygonFootprint) and not polygon_is_simple(footprint.vertices):
        raise ConfigurationError("polygon footprint must be simple (no self-intersections)")


def footprint_contains(
    footprint: Footprint, x: float, y: float, tolerance: float = TOLERANCE
) -> bool:
    """Return True if ``(x, y)`` lies inside or on the boundary of the footprint."""
    if isinstance(footprint, BoxFootprint):
        return (
            footprint.x_min - tolerance <= x <= footprint.x_max + tolerance
            and footprint.y_min - tolerance <= y <= footprint.y_max + tolerance
        )
    return _point_in_polygon(footprint.vertices, x, y, tolerance)


def footprint_bounds(footprint: Footprint) -> tuple[float, float, float, float]:
    """Return ``(x_min, y_min, x_max, y_max)`` of the footprint. Units: metres."""
    if isinstance(footprint, BoxFootprint):
        return footprint.x_min, footprint.y_min, footprint.x_max, footprint.y_max
    xs = [v[0] for v in footprint.vertices]
    ys = [v[1] for v in footprint.vertices]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_space(
    space: Space, x: float, y: float, z: float, tolerance: float = TOLERANCE
) -> bool:
    """Return True if the point lies inside the extruded space volume (GEO-03)."""
    return footprint_contains(space.footprint, x, y, tolerance) and (
        -tolerance <= z <= space.height + tolerance
    )


def obstacle_contains(obstacle: Obstacle, x: float, y: float, z: float) -> bool:
    """Return True if the point lies inside the obstacle volume (OBS-05)."""
    dx = x - obstacle.x
    dy = y - obstacle.y
    dz = z - obstacle.z
    if obstacle.shape is ObstacleShape.CYLINDER:
        radius = obstacle.size_x / 2.0
        return dx * dx + dy * dy <= radius * radius and abs(dz) <= obstacle.size_z / 2.0
    angle = math.radians(-obstacle.rotation_z_deg)
    local_x = dx * math.cos(angle) - dy * math.sin(angle)
    local_y = dx * math.sin(angle) + dy * math.cos(angle)
    return (
        abs(local_x) <= obstacle.size_x / 2.0
        and abs(local_y) <= obstacle.size_y / 2.0
        and abs(dz) <= obstacle.size_z / 2.0
    )


def obstacle_within_space(space: Space, obstacle: Obstacle) -> bool:
    """Return True if the obstacle lies fully inside the space (GEO-03).

    Uses representative surface sample points (corners for boxes, cardinal
    rim points for cylinders), which is exact for the primitives supported.
    """
    return all(point_in_space(space, *point) for point in _obstacle_sample_points(obstacle))


def has_non_coplanar_points(points: Sequence[Point3], tolerance: float = 1e-9) -> bool:
    """Return True if at least four points do not lie on a single plane (CFG-11)."""
    if len(points) < 4:
        return False
    p0 = points[0]
    baseline: Point3 | None = None
    normal: Point3 | None = None
    for point in points[1:]:
        vector = _sub(point, p0)
        if _norm(vector) <= tolerance:
            continue
        if baseline is None:
            baseline = vector
            continue
        if normal is None:
            candidate = _cross(baseline, vector)
            if _norm(candidate) > tolerance:
                normal = candidate
            continue
        if abs(_dot(normal, vector)) > tolerance:
            return True
    return False


# ------------------------------------------------------------- internals


def _close_2d(p: Point2, q: Point2, tolerance: float) -> bool:
    return math.hypot(p[0] - q[0], p[1] - q[1]) <= tolerance


def _point_in_polygon(vertices: Sequence[Point2], x: float, y: float, tolerance: float) -> bool:
    n = len(vertices)
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        if _on_segment(x, y, x1, y1, x2, y2, tolerance):
            return True
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = vertices[i]
        xj, yj = vertices[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _on_segment(
    x: float, y: float, x1: float, y1: float, x2: float, y2: float, tolerance: float
) -> bool:
    length = math.hypot(x2 - x1, y2 - y1)
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if length > 0.0 and abs(cross) > tolerance * max(1.0, length):
        return False
    return (
        min(x1, x2) - tolerance <= x <= max(x1, x2) + tolerance
        and min(y1, y2) - tolerance <= y <= max(y1, y2) + tolerance
    )


def _orient(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def _properly_intersect(a: Point2, b: Point2, c: Point2, d: Point2) -> bool:
    """True if the open segments (a,b) and (c,d) cross in their interiors."""
    o1 = _orient(*a, *b, *c)
    o2 = _orient(*a, *b, *d)
    o3 = _orient(*c, *d, *a)
    o4 = _orient(*c, *d, *b)
    return o1 * o2 < 0.0 and o3 * o4 < 0.0


def _collinear_overlap(a: Point2, b: Point2, c: Point2, d: Point2, tolerance: float) -> bool:
    """True if two collinear segments overlap with positive length."""
    orientations = (
        _orient(*a, *b, *c),
        _orient(*a, *b, *d),
        _orient(*c, *d, *a),
        _orient(*c, *d, *b),
    )
    if any(abs(value) > tolerance for value in orientations):
        return False
    if abs(b[0] - a[0]) >= abs(b[1] - a[1]):
        first = sorted((a[0], b[0]))
        second = sorted((c[0], d[0]))
    else:
        first = sorted((a[1], b[1]))
        second = sorted((c[1], d[1]))
    return min(first[1], second[1]) - max(first[0], second[0]) > tolerance


def _obstacle_sample_points(obstacle: Obstacle) -> list[Point3]:
    if obstacle.shape is ObstacleShape.CYLINDER:
        radius = obstacle.size_x / 2.0
        half_height = obstacle.size_z / 2.0
        points: list[Point3] = []
        for dz in (-half_height, half_height):
            points.append((obstacle.x, obstacle.y, obstacle.z + dz))
            for angle in (0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0):
                points.append(
                    (
                        obstacle.x + radius * math.cos(angle),
                        obstacle.y + radius * math.sin(angle),
                        obstacle.z + dz,
                    )
                )
        return points
    corners: list[Point3] = []
    angle = math.radians(obstacle.rotation_z_deg)
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                local_x = sx * obstacle.size_x / 2.0
                local_y = sy * obstacle.size_y / 2.0
                local_z = sz * obstacle.size_z / 2.0
                corners.append(
                    (
                        obstacle.x + local_x * math.cos(angle) - local_y * math.sin(angle),
                        obstacle.y + local_x * math.sin(angle) + local_y * math.cos(angle),
                        obstacle.z + local_z,
                    )
                )
    return corners


def _sub(a: Point3, b: Point3) -> Point3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Point3, b: Point3) -> Point3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Point3, b: Point3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: Point3) -> float:
    return math.sqrt(_dot(a, a))


# Vectorized spatial checks for grid masking (INT-10, GEO-04, OBS-05). Units: metres.


def _polygon_contains_xy(
    vertices: Sequence[Point2], xs: np.ndarray, ys: np.ndarray, tolerance: float
) -> np.ndarray:
    """Vectorized ray-casting point-in-polygon; boundary counts as inside.

    Parity with the scalar ``_point_in_polygon`` matters for masks: grid points
    exactly on a wall must stay inside (GEO-04).
    """
    inside = np.zeros(xs.shape, dtype=bool)
    on_edge = np.zeros(xs.shape, dtype=bool)
    n = len(vertices)
    vx = np.array([v[0] for v in vertices], dtype=float)
    vy = np.array([v[1] for v in vertices], dtype=float)
    for i in range(n):
        x1, y1 = vx[i], vy[i]
        x2, y2 = vx[(i + 1) % n], vy[(i + 1) % n]
        crossing = (y1 > ys) != (y2 > ys)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_intersect = (x2 - x1) * (ys - y1) / (y2 - y1) + x1
        inside ^= crossing & (xs < x_intersect)
        length = math.hypot(x2 - x1, y2 - y1)
        cross = (xs - x1) * (y2 - y1) - (ys - y1) * (x2 - x1)
        collinear = np.abs(cross) <= tolerance * max(1.0, length)
        within = (
            (np.minimum(x1, x2) - tolerance <= xs)
            & (xs <= np.maximum(x1, x2) + tolerance)
            & (np.minimum(y1, y2) - tolerance <= ys)
            & (ys <= np.maximum(y1, y2) + tolerance)
        )
        on_edge |= collinear & within
    return inside | on_edge


def footprint_contains_xy(
    footprint: Footprint, xs: np.ndarray, ys: np.ndarray, tolerance: float = TOLERANCE
) -> np.ndarray:
    """Vectorized 2D containment for a footprint. Units: metres."""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    if isinstance(footprint, BoxFootprint):
        return (
            (xs >= footprint.x_min - tolerance)
            & (xs <= footprint.x_max + tolerance)
            & (ys >= footprint.y_min - tolerance)
            & (ys <= footprint.y_max + tolerance)
        )
    return _polygon_contains_xy(footprint.vertices, xs, ys, tolerance)


def point_in_space_xyz(
    space: Space,
    xs: np.ndarray,
    ys: np.ndarray,
    zs: np.ndarray,
    tolerance: float = TOLERANCE,
) -> np.ndarray:
    """Vectorized containment inside the extruded space volume (GEO-04)."""
    zs = np.asarray(zs, dtype=float)
    return (
        footprint_contains_xy(space.footprint, xs, ys, tolerance)
        & (zs >= -tolerance)
        & (zs <= space.height + tolerance)
    )


def obstacle_contains_xyz(
    obstacle: Obstacle, xs: np.ndarray, ys: np.ndarray, zs: np.ndarray
) -> np.ndarray:
    """Vectorized containment inside one obstacle (OBS-05). Units: metres."""
    dx = np.asarray(xs, dtype=float) - obstacle.x
    dy = np.asarray(ys, dtype=float) - obstacle.y
    dz = np.asarray(zs, dtype=float) - obstacle.z
    if obstacle.shape is ObstacleShape.CYLINDER:
        radius = obstacle.size_x / 2.0
        return (dx * dx + dy * dy <= radius * radius) & (np.abs(dz) <= obstacle.size_z / 2.0)
    angle = math.radians(-obstacle.rotation_z_deg)
    local_x = dx * math.cos(angle) - dy * math.sin(angle)
    local_y = dx * math.sin(angle) + dy * math.cos(angle)
    return (
        (np.abs(local_x) <= obstacle.size_x / 2.0)
        & (np.abs(local_y) <= obstacle.size_y / 2.0)
        & (np.abs(dz) <= obstacle.size_z / 2.0)
    )


def build_volume_mask(
    space: Space,
    obstacles: Sequence[Obstacle],
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    z_coords: np.ndarray,
) -> np.ndarray:
    """Boolean volume (nx, ny, nz): True inside the space, outside solid obstacles.

    Enforces GEO-04 (footprint/height) and OBS-05 (solid obstacle masking) so
    no interpolated value is produced outside the walls (INT-10). Units: metres.
    """
    xs, ys, zs = np.meshgrid(x_coords, y_coords, z_coords, indexing="ij")
    mask = point_in_space_xyz(space, xs, ys, zs)
    for obstacle in obstacles:
        if obstacle.solid:
            mask &= ~obstacle_contains_xyz(obstacle, xs, ys, zs)
    return mask


_CONTEXT_OBSTACLE_TYPES: tuple[ObstacleType, ...] = (
    ObstacleType.DOOR,
    ObstacleType.VENT,
    ObstacleType.EVAPORATOR,
)


def nearest_context_obstacle(
    space: Space,
    x: float,
    y: float,
    types: Sequence[ObstacleType] = _CONTEXT_OBSTACLE_TYPES,
) -> tuple[Obstacle, float] | None:
    """Nearest door/vent/evaporator obstacle in the XY plane (OBS-04).

    Distance is measured to the obstacle centre — sufficient for plot/report
    context, not for spatial analysis. Units: metres.
    """
    best: tuple[Obstacle, float] | None = None
    for obstacle in space.obstacles:
        if obstacle.obstacle_type not in types:
            continue
        distance = math.hypot(obstacle.x - x, obstacle.y - y)
        if best is None or distance < best[1]:
            best = (obstacle, distance)
    return best
