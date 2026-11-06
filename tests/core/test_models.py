"""Model construction rules (PRD 5.1, GEO-01, OBS-01)."""

from __future__ import annotations

import pytest

from thermavisualizer.core.models import (
    BoxFootprint,
    ConfigurationError,
    Layer,
    LengthUnit,
    Logger,
    LoggerRole,
    Obstacle,
    ObstacleShape,
    ObstacleType,
    PolygonFootprint,
    Severity,
    Space,
    SpaceType,
    new_id,
)


def test_new_ids_are_unique() -> None:
    ids = {new_id() for _ in range(1000)}
    assert len(ids) == 1000


def test_box_footprint_rejects_degenerate_bounds() -> None:
    with pytest.raises(ConfigurationError):
        BoxFootprint(1.0, 0.0, 0.5, 1.0)


def test_polygon_footprint_requires_three_vertices() -> None:
    with pytest.raises(ConfigurationError):
        PolygonFootprint(((0.0, 0.0), (1.0, 0.0)))


def test_space_defaults() -> None:
    space = Space()
    assert space.space_type is SpaceType.WAREHOUSE
    assert space.length_unit is LengthUnit.METRES
    assert space.layers == []
    assert space.obstacles == []


def test_space_default_collections_are_independent() -> None:
    first = Space()
    first.layers.append(Layer(name="A"))
    assert Space().layers == []


def test_logger_defaults() -> None:
    logger = Logger(logger_id="L1", x=0.0, y=0.0, z=0.0)
    assert logger.role is LoggerRole.NONE
    assert logger.notes == ""


def test_obstacle_defaults() -> None:
    obstacle = Obstacle(
        name="rack",
        obstacle_type=ObstacleType.RACK,
        shape=ObstacleShape.BOX,
        x=1.0,
        y=1.0,
        z=0.5,
        size_x=1.0,
        size_y=0.5,
        size_z=1.0,
    )
    assert obstacle.visible is True
    assert obstacle.solid is False
    assert obstacle.obstacle_id


def test_severity_values_match_prd() -> None:
    assert Severity.ERROR == "error"
    assert Severity.WARNING == "warning"
    assert Severity.INFO == "info"


def test_enum_fields_normalize_from_strings() -> None:
    logger = Logger(logger_id="L1", x=0.0, y=0.0, z=0.0, role="corner")
    assert logger.role is LoggerRole.CORNER
    obstacle = Obstacle(
        name="rack",
        obstacle_type="rack",
        shape="box",
        x=0.0,
        y=0.0,
        z=0.0,
        size_x=1.0,
        size_y=1.0,
        size_z=1.0,
    )
    assert obstacle.obstacle_type is ObstacleType.RACK
    assert obstacle.shape is ObstacleShape.BOX
    space = Space(space_type="chamber", length_unit="mm")
    assert space.space_type is SpaceType.CHAMBER
    assert space.length_unit is LengthUnit.MILLIMETRES
