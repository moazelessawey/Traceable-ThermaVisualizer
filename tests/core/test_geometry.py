"""Geometry tests: footprints, point-in-space, obstacles, coplanarity (GEO, OBS, CFG-11)."""

from __future__ import annotations

import pytest

from thermavisualizer.core.geometry import (
    footprint_bounds,
    footprint_contains,
    has_non_coplanar_points,
    obstacle_contains,
    obstacle_within_space,
    point_in_space,
    polygon_is_simple,
    validate_footprint,
    nearest_context_obstacle,
)
from thermavisualizer.core.models import (
    BoxFootprint,
    ConfigurationError,
    Obstacle,
    ObstacleShape,
    ObstacleType,
    PolygonFootprint,
    Space,
)

# Acceptance item 10 preview: an L-shaped footprint with a notch.
L_SHAPE = PolygonFootprint(((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0)))


def test_box_footprint_contains() -> None:
    box = BoxFootprint(0.0, 0.0, 2.0, 1.0)
    assert footprint_contains(box, 1.0, 0.5)
    assert footprint_contains(box, 0.0, 0.0)  # boundary counts as inside
    assert not footprint_contains(box, 2.5, 0.5)
    assert not footprint_contains(box, 1.0, -0.1)


def test_l_shaped_footprint_contains() -> None:
    assert footprint_contains(L_SHAPE, 3.0, 1.0)  # lower arm
    assert footprint_contains(L_SHAPE, 1.0, 3.0)  # upper arm
    assert not footprint_contains(L_SHAPE, 3.0, 3.0)  # outside the notch
    assert footprint_contains(L_SHAPE, 2.0, 2.0)  # concave corner


def test_footprint_bounds() -> None:
    assert footprint_bounds(L_SHAPE) == (0.0, 0.0, 4.0, 4.0)


def test_polygon_is_simple_accepts_valid_shapes() -> None:
    square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    assert polygon_is_simple(square)
    collinear_vertex = ((0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0))
    assert polygon_is_simple(collinear_vertex)


def test_polygon_is_simple_rejects_self_intersection() -> None:
    bowtie = ((0.0, 0.0), (1.0, 1.0), (1.0, 0.0), (0.0, 1.0))
    assert not polygon_is_simple(bowtie)


def test_polygon_is_simple_rejects_pinch_point() -> None:
    pinched = ((0.0, 0.0), (1.0, 0.0), (0.5, 0.5), (1.0, 1.0), (0.0, 1.0), (0.5, 0.5))
    assert not polygon_is_simple(pinched)


def test_polygon_is_simple_rejects_collinear_overlap() -> None:
    overlapping = ((0.0, 0.0), (2.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
    assert not polygon_is_simple(overlapping)


def test_validate_footprint_rejects_self_intersection() -> None:
    with pytest.raises(ConfigurationError):
        validate_footprint(PolygonFootprint(((0.0, 0.0), (1.0, 1.0), (1.0, 0.0), (0.0, 1.0))))


def test_point_in_space_respects_height() -> None:
    space = Space(footprint=BoxFootprint(0.0, 0.0, 2.0, 2.0), height=2.0)
    assert point_in_space(space, 1.0, 1.0, 0.0)
    assert point_in_space(space, 1.0, 1.0, 2.0)
    assert not point_in_space(space, 1.0, 1.0, 2.5)
    assert not point_in_space(space, 3.0, 1.0, 1.0)


def test_has_non_coplanar_points() -> None:
    coplanar = [
        (0.0, 0.0, 0.5),
        (1.0, 0.0, 0.5),
        (1.0, 1.0, 0.5),
        (0.0, 1.0, 0.5),
        (2.0, 2.0, 0.5),
    ]
    assert not has_non_coplanar_points(coplanar)
    assert has_non_coplanar_points(coplanar + [(0.5, 0.5, 1.5)])
    assert not has_non_coplanar_points([(0.0, 0.0, 0.0)] * 4)
    assert not has_non_coplanar_points([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])


def _box_obstacle(**overrides: float | str) -> Obstacle:
    kwargs: dict[str, float | str] = {
        "name": "rack",
        "obstacle_type": ObstacleType.RACK,
        "shape": ObstacleShape.BOX,
        "x": 1.0,
        "y": 1.0,
        "z": 1.0,
        "size_x": 1.0,
        "size_y": 0.6,
        "size_z": 2.0,
    }
    kwargs.update(overrides)
    return Obstacle(**kwargs)  # type: ignore[arg-type]


def test_box_obstacle_contains() -> None:
    obstacle = _box_obstacle()
    assert obstacle_contains(obstacle, 1.0, 1.0, 1.0)
    # assert obstacle_contains(obstacle, 1.5, 1.3, 2.0)  # on the top boundary
    assert not obstacle_contains(obstacle, 1.5, 1.3, 2.1)  # just above the top
    assert not obstacle_contains(obstacle, 1.6, 1.0, 1.0)  # x half-extent is 0.5
    assert not obstacle_contains(obstacle, 1.0, 1.0, 2.1)


def test_rotated_box_obstacle_contains() -> None:
    obstacle = _box_obstacle(rotation_z_deg=90.0)
    # After a 90° rotation the long X extent points along Y.
    assert obstacle_contains(obstacle, 1.0, 1.5, 1.0)
    assert not obstacle_contains(obstacle, 1.5, 1.0, 1.0)


def test_cylinder_obstacle_contains() -> None:
    obstacle = Obstacle(
        name="tank",
        obstacle_type=ObstacleType.OTHER,
        shape=ObstacleShape.CYLINDER,
        x=0.0,
        y=0.0,
        z=1.0,
        size_x=1.0,
        size_y=0.0,
        size_z=2.0,
    )
    assert obstacle_contains(obstacle, 0.4, 0.2, 0.5)
    assert not obstacle_contains(obstacle, 0.6, 0.3, 0.5)
    assert not obstacle_contains(obstacle, 0.0, 0.0, 2.5)


def test_obstacle_within_space() -> None:
    space = Space(footprint=BoxFootprint(0.0, 0.0, 4.0, 4.0), height=3.0)
    assert obstacle_within_space(space, _box_obstacle())
    assert not obstacle_within_space(space, _box_obstacle(x=3.8))
    assert not obstacle_within_space(space, _box_obstacle(z=2.5))


def test_nearest_context_obstacle() -> None:  # OBS-04
    space = Space(footprint=BoxFootprint(0.0, 0.0, 4.0, 4.0), height=3.0)
    door = Obstacle(
        name="Main door",
        obstacle_type=ObstacleType.DOOR,
        shape=ObstacleShape.BOX,
        x=4.0,
        y=2.0,
        z=1.0,
        size_x=0.2,
        size_y=1.0,
        size_z=2.0,
    )
    rack = Obstacle(
        name="rack",
        obstacle_type=ObstacleType.RACK,
        shape=ObstacleShape.BOX,
        x=1.0,
        y=1.0,
        z=1.0,
        size_x=1.0,
        size_y=1.0,
        size_z=2.0,
    )
    space.obstacles.extend([rack, door])
    result = nearest_context_obstacle(space, 3.5, 2.0)
    assert result is not None
    obstacle, distance = result
    assert obstacle.name == "Main door"
    assert distance == pytest.approx(0.5)
    assert nearest_context_obstacle(Space(), 0.0, 0.0) is None
