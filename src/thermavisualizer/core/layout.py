"""Bulk layout generation and configuration validation (BLK-03, CFG-11, GEO-03)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from thermavisualizer.core.geometry import (
    has_non_coplanar_points,
    obstacle_contains,
    obstacle_within_space,
    point_in_space,
)
from thermavisualizer.core.models import Logger, Severity, Space

_COORDINATE_DECIMALS = 6  # positions equal within 1 µm count as duplicates


class LayoutError(ValueError):
    """Raised for invalid bulk layout generation parameters."""


@dataclass(frozen=True)
class LayoutIssue:
    """One configuration validation finding (CFG-11, GEO-03, OBS-05).

    ``code`` is stable for UI grouping and tests: ``duplicate-id``,
    ``outside-space``, ``duplicate-coordinates``, ``insufficient-loggers``,
    ``obstacle-outside-space``, ``logger-in-obstacle``.
    """

    severity: Severity
    code: str
    message: str
    logger_id: str | None = None


def unique_logger_ids(prefix: str, count: int, existing: frozenset[str] = frozenset()) -> list[str]:
    """Return ``count`` IDs ``<prefix>1, <prefix>2, ...`` skipping ``existing``."""
    ids: list[str] = []
    taken = set(existing)
    counter = 0
    while len(ids) < count:
        counter += 1
        candidate = f"{prefix}{counter}"
        if candidate not in taken:
            taken.add(candidate)
            ids.append(candidate)
    return ids


def generate_lattice(
    *,
    rows: int,
    columns: int,
    spacing_x: float,
    spacing_y: float,
    height: float,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    id_prefix: str = "L",
    existing_ids: frozenset[str] = frozenset(),
) -> list[Logger]:
    """Generate a regular grid of loggers on one layer (BLK-03).

    Positions: ``x = offset_x + column * spacing_x`` and
    ``y = offset_y + row * spacing_y``, all at ``z = height``. Units: metres.
    Multi-layer lattices call this once per layer height.
    """
    if rows < 1 or columns < 1:
        raise LayoutError("rows and columns must be >= 1")
    if spacing_x <= 0.0 or spacing_y <= 0.0:
        raise LayoutError("spacing must be > 0 metres")
    ids = unique_logger_ids(id_prefix, rows * columns, existing_ids)
    loggers: list[Logger] = []
    index = 0
    for row in range(rows):
        for column in range(columns):
            loggers.append(
                Logger(
                    logger_id=ids[index],
                    x=offset_x + column * spacing_x,
                    y=offset_y + row * spacing_y,
                    z=height,
                )
            )
            index += 1
    return loggers


def validate_layout(space: Space) -> list[LayoutIssue]:
    """Validate the configured layout (CFG-11, GEO-03, OBS-05).

    Returns all findings; an empty list means the layout is valid. Raw model
    data is never mutated (AGENTS data-integrity rule).
    """
    issues: list[LayoutIssue] = []
    all_loggers = [logger for layer in space.layers for logger in layer.loggers]

    seen_ids: set[str] = set()
    for logger in all_loggers:
        if logger.logger_id in seen_ids:
            issues.append(
                LayoutIssue(
                    Severity.ERROR,
                    "duplicate-id",
                    f"logger ID '{logger.logger_id}' is used more than once",
                    logger.logger_id,
                )
            )
        else:
            seen_ids.add(logger.logger_id)

    for logger in all_loggers:
        if not point_in_space(space, logger.x, logger.y, logger.z):
            issues.append(
                LayoutIssue(
                    Severity.ERROR,
                    "outside-space",
                    f"logger '{logger.logger_id}' at ({logger.x:.3f}, {logger.y:.3f}, "
                    f"{logger.z:.3f}) m lies outside the space",
                    logger.logger_id,
                )
            )

    seen_positions: dict[tuple[float, float, float], str] = {}
    for logger in all_loggers:
        key = (
            round(logger.x, _COORDINATE_DECIMALS),
            round(logger.y, _COORDINATE_DECIMALS),
            round(logger.z, _COORDINATE_DECIMALS),
        )
        if key in seen_positions:
            issues.append(
                LayoutIssue(
                    Severity.ERROR,
                    "duplicate-coordinates",
                    f"loggers '{seen_positions[key]}' and '{logger.logger_id}' share "
                    "the same position",
                    logger.logger_id,
                )
            )
        else:
            seen_positions[key] = logger.logger_id

    if all_loggers:
        points = [(logger.x, logger.y, logger.z) for logger in all_loggers]
        if len(points) < 4:
            issues.append(
                LayoutIssue(
                    Severity.ERROR,
                    "insufficient-loggers",
                    f"interpolation needs at least 4 loggers, found {len(points)}",
                )
            )
        elif not has_non_coplanar_points(points):
            issues.append(
                LayoutIssue(
                    Severity.ERROR,
                    "insufficient-loggers",
                    "all loggers are coplanar; interpolation needs at least 4 non-coplanar loggers",
                )
            )

    for obstacle in space.obstacles:
        if not obstacle_within_space(space, obstacle):
            issues.append(
                LayoutIssue(
                    Severity.ERROR,
                    "obstacle-outside-space",
                    f"obstacle '{obstacle.name}' extends outside the space",
                )
            )
        if obstacle.solid:
            for logger in all_loggers:
                if obstacle_contains(obstacle, logger.x, logger.y, logger.z):
                    issues.append(
                        LayoutIssue(
                            Severity.WARNING,
                            "logger-in-obstacle",
                            f"logger '{logger.logger_id}' is inside solid obstacle "
                            f"'{obstacle.name}'",
                            logger.logger_id,
                        )
                    )

    return issues


def duplicate_logger_ids(originals: Sequence[str], existing: frozenset[str]) -> list[str]:
    """Return collision-free logger IDs for a duplicated layer (CFG-06).

    Each original ID gets a ``_c`` suffix (``_c2``, ``_c3``, ...) when it
    collides with ``existing`` or an earlier result.
    """
    taken = set(existing)
    result: list[str] = []
    for original in originals:
        candidate = f"{original}_c"
        counter = 1
        while candidate in taken:
            counter += 1
            candidate = f"{original}_c{counter}"
        taken.add(candidate)
        result.append(candidate)
    return result
