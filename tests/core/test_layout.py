"""Lattice generation and layout validation tests (BLK-03, CFG-11, GEO-03, OBS-05)."""

from __future__ import annotations

import pytest

from thermavisualizer.core.layout import (
    LayoutError,
    generate_lattice,
    unique_logger_ids,
    validate_layout,
    duplicate_logger_ids,
)
from thermavisualizer.core.models import (
    BoxFootprint,
    Layer,
    Logger,
    Obstacle,
    ObstacleShape,
    ObstacleType,
    Severity,
    Space,
)


def test_generate_lattice_positions_and_ids() -> None:
    loggers = generate_lattice(
        rows=2,
        columns=3,
        spacing_x=0.5,
        spacing_y=1.0,
        height=1.5,
        offset_x=1.0,
        offset_y=2.0,
    )
    assert len(loggers) == 6
    assert [logger.logger_id for logger in loggers] == ["L1", "L2", "L3", "L4", "L5", "L6"]
    assert loggers[0].x == pytest.approx(1.0)
    assert loggers[0].y == pytest.approx(2.0)
    assert loggers[3].x == pytest.approx(1.0)  # second row, first column
    assert loggers[3].y == pytest.approx(3.0)
    assert all(logger.z == 1.5 for logger in loggers)


def test_generate_lattice_skips_existing_ids() -> None:
    loggers = generate_lattice(
        rows=1,
        columns=3,
        spacing_x=1.0,
        spacing_y=1.0,
        height=0.0,
        existing_ids=frozenset({"L2"}),
    )
    assert [logger.logger_id for logger in loggers] == ["L1", "L3", "L4"]


def test_generate_lattice_rejects_invalid_parameters() -> None:
    with pytest.raises(LayoutError):
        generate_lattice(rows=0, columns=1, spacing_x=1.0, spacing_y=1.0, height=0.0)
    with pytest.raises(LayoutError):
        generate_lattice(rows=1, columns=1, spacing_x=0.0, spacing_y=1.0, height=0.0)


def test_unique_logger_ids() -> None:
    assert unique_logger_ids("P", 3) == ["P1", "P2", "P3"]
    assert unique_logger_ids("P", 2, frozenset({"P1"})) == ["P2", "P3"]


def _valid_space() -> Space:
    space = Space(footprint=BoxFootprint(0.0, 0.0, 4.0, 3.0), height=2.0)
    low = Layer(
        name="low",
        height=0.5,
        loggers=[
            Logger("A", 0.5, 0.5, 0.5),
            Logger("B", 3.5, 0.5, 0.5),
            Logger("C", 0.5, 2.5, 0.5),
        ],
    )
    high = Layer(name="high", height=1.5, loggers=[Logger("D", 3.5, 2.5, 1.5)])
    space.layers = [low, high]
    return space


def test_valid_layout_has_no_issues() -> None:
    assert validate_layout(_valid_space()) == []


def test_duplicate_ids_are_flagged() -> None:
    space = _valid_space()
    space.layers[1].loggers[0].logger_id = "A"
    assert any(issue.code == "duplicate-id" for issue in validate_layout(space))


def test_logger_outside_space_is_flagged() -> None:
    space = _valid_space()
    space.layers[0].loggers.append(Logger("E", 10.0, 0.5, 0.5))
    issues = validate_layout(space)
    assert any(issue.code == "outside-space" and issue.logger_id == "E" for issue in issues)


def test_duplicate_coordinates_are_flagged() -> None:
    space = _valid_space()
    space.layers[0].loggers.append(Logger("E", 0.5, 0.5, 0.5))
    assert any(issue.code == "duplicate-coordinates" for issue in validate_layout(space))


def test_fewer_than_four_loggers_is_flagged() -> None:
    space = _valid_space()
    space.layers[1].loggers = []
    assert any(issue.code == "insufficient-loggers" for issue in validate_layout(space))


def test_coplanar_loggers_are_flagged() -> None:
    space = _valid_space()
    space.layers[1].loggers[0].z = 0.5  # all four loggers now on z = 0.5 m
    assert any(issue.code == "insufficient-loggers" for issue in validate_layout(space))


def test_logger_inside_solid_obstacle_warns() -> None:
    space = _valid_space()
    space.obstacles.append(
        Obstacle(
            name="rack",
            obstacle_type=ObstacleType.RACK,
            shape=ObstacleShape.BOX,
            x=0.5,
            y=0.5,
            z=0.5,
            size_x=0.8,
            size_y=0.8,
            size_z=0.8,
            solid=True,
        )
    )
    issues = validate_layout(space)
    assert any(
        issue.code == "logger-in-obstacle" and issue.severity is Severity.WARNING
        for issue in issues
    )


def test_obstacle_outside_space_is_flagged() -> None:
    space = _valid_space()
    space.obstacles.append(
        Obstacle(
            name="rack",
            obstacle_type=ObstacleType.RACK,
            shape=ObstacleShape.BOX,
            x=4.2,
            y=0.5,
            z=0.5,
            size_x=1.0,
            size_y=1.0,
            size_z=1.0,
        )
    )
    assert any(issue.code == "obstacle-outside-space" for issue in validate_layout(space))


def test_duplicate_logger_ids() -> None:
    assert duplicate_logger_ids(["A", "B"], frozenset()) == ["A_c", "B_c"]
    assert duplicate_logger_ids(["A"], frozenset({"A_c"})) == ["A_c2"]
    assert duplicate_logger_ids(["A", "A"], frozenset()) == ["A_c", "A_c2"]
