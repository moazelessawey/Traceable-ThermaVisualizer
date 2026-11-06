"""Vectorized mask correctness (GEO-04, OBS-05, INT-10)."""

from __future__ import annotations

import numpy as np

from thermavisualizer.core.geometry import (
    build_volume_mask,
    footprint_contains,
    footprint_contains_xy,
)
from thermavisualizer.core.models import (
    BoxFootprint,
    Obstacle,
    ObstacleShape,
    ObstacleType,
    Space,
    PolygonFootprint,
)


def test_box_space_mask() -> None:
    space = Space(footprint=BoxFootprint(0.0, 0.0, 2.0, 2.0), height=2.0)
    mask = build_volume_mask(
        space,
        [],
        np.array([0.0, 1.0, 2.0]),
        np.array([0.0, 1.0, 2.0]),
        np.array([0.0, 1.0, 2.0]),
    )
    assert mask.all()  # all sample points lie inside the box


def test_solid_obstacle_is_masked_out() -> None:  # OBS-05
    space = Space(footprint=BoxFootprint(0.0, 0.0, 2.0, 2.0), height=2.0)
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
    coords = np.array([0.4, 1.0, 1.6])
    mask = build_volume_mask(space, [obstacle], coords, coords, coords)
    assert not mask[1, 1, 1]  # centre of the solid rack
    assert mask[0, 0, 0]  # (0.4, 0.4, 0.4) strictly outside the rack
    assert mask[2, 2, 2]  # (1.6, 1.6, 1.6) strictly outside the rack


def test_non_solid_obstacle_does_not_mask() -> None:
    space = Space(footprint=BoxFootprint(0.0, 0.0, 2.0, 2.0), height=2.0)
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
        solid=False,
    )
    coords = np.array([0.5, 1.0, 1.5])
    mask = build_volume_mask(space, [obstacle], coords, coords, coords)
    assert mask.all()


L_SHAPE = PolygonFootprint(((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0)))


def test_vectorized_footprint_boundary_parity() -> None:
    """Vectorized containment must match the scalar rule: boundary = inside."""
    xs = np.array([2.0, 3.0, 0.0, 3.0, 1.0])
    ys = np.array([2.0, 2.0, 3.0, 3.0, 1.0])
    vectorized = footprint_contains_xy(L_SHAPE, xs, ys)
    scalar = np.array([footprint_contains(L_SHAPE, float(x), float(y)) for x, y in zip(xs, ys)])
    assert (vectorized == scalar).all()
    assert vectorized[0] and vectorized[1] and vectorized[2]  # boundary: inside
    assert not vectorized[3]  # notch interior: outside
    assert vectorized[4]  # deep interior
