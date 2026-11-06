"""Core domain models for study configuration (PRD 5.1, GEO-01, OBS-01).

All lengths are stored in canonical metres; temperature in °C and relative
humidity in %RH wherever they appear (AGENTS domain rules). Display
conversion happens at the UI edge. No Qt imports (AGENTS rule 4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import numpy as np


class ConfigurationError(ValueError):
    """Raised when a model object is constructed with invalid values."""


def new_id() -> str:
    """Return a new unique object identifier (short UUID hex)."""
    return uuid.uuid4().hex


class Severity(StrEnum):
    """Validation issue severity (PRD 5.3)."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class SpaceType(StrEnum):
    """Space type (CFG-01)."""

    WAREHOUSE = "warehouse"
    CABINET = "cabinet"
    CHAMBER = "chamber"
    OTHER = "other"


class LengthUnit(StrEnum):
    """Display unit for lengths; internal storage is always metres."""

    METRES = "m"
    CENTIMETRES = "cm"
    MILLIMETRES = "mm"


class LoggerRole(StrEnum):
    """Optional role flag for a logger (CFG-05)."""

    NONE = "none"
    CORNER = "corner"
    CENTER = "center"
    NEAR_DOOR = "near_door"
    NEAR_EVAPORATOR = "near_evaporator"
    OTHER = "other"


class ObstacleType(StrEnum):
    """Reference-object type (OBS-01)."""

    RACK = "rack"
    SHELF = "shelf"
    PALLET = "pallet"
    DOOR = "door"
    EVAPORATOR = "evaporator"
    VENT = "vent"
    HEAT_SOURCE = "heat_source"
    FAN = "fan"
    WINDOW = "window"
    OTHER = "other"


class ObstacleShape(StrEnum):
    """Obstacle primitive shape (OBS-01)."""

    BOX = "box"
    CYLINDER = "cylinder"


@dataclass(frozen=True)
class BoxFootprint:
    """Axis-aligned rectangular footprint. Units: metres."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    def __post_init__(self) -> None:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ConfigurationError(
                f"box footprint is degenerate: x [{self.x_min}, {self.x_max}], "
                f"y [{self.y_min}, {self.y_max}]"
            )


@dataclass(frozen=True)
class PolygonFootprint:
    """Polygonal footprint (GEO-01). Vertices in metres, ordered around the outline.

    Construction enforces only structural rules (at least 3 vertices).
    Simplicity (no self-intersections, GEO-02) is checked by
    ``geometry.polygon_is_simple`` / ``geometry.validate_footprint`` and by
    layout validation.
    """

    vertices: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.vertices) < 3:
            raise ConfigurationError("polygon footprint needs at least 3 vertices")


Footprint = BoxFootprint | PolygonFootprint


@dataclass
class Logger:
    """A data-logger position in space coordinates (CFG-05). Units: metres."""

    logger_id: str
    x: float
    y: float
    z: float
    role: LoggerRole = LoggerRole.NONE
    notes: str = ""

    def __post_init__(self) -> None:
        """Normalize enum fields that may arrive as raw strings at boundaries."""
        if not isinstance(self.role, LoggerRole):
            self.role = LoggerRole(self.role)


@dataclass
class Layer:
    """Horizontal plane at a given height holding loggers (CFG-02).

    ``height`` is the nominal Z of the layer in metres; each logger may
    override its own Z (CFG-05).
    """

    name: str = "Layer"
    height: float = 0.0
    layer_id: str = field(default_factory=new_id)
    completed: bool = False
    loggers: list[Logger] = field(default_factory=list)


@dataclass
class Obstacle:
    """Reference object such as a rack, door, or evaporator (OBS-01).

    Position ``(x, y, z)`` is the obstacle centre in metres. For ``BOX``
    shape, ``size_x/size_y/size_z`` are the full extents. For ``CYLINDER``,
    ``size_x`` is the diameter, ``size_y`` is unused, and ``size_z`` is the
    height. ``rotation_z_deg`` rotates the footprint about Z.
    """

    name: str
    obstacle_type: ObstacleType
    shape: ObstacleShape
    x: float
    y: float
    z: float
    size_x: float
    size_y: float
    size_z: float
    obstacle_id: str = field(default_factory=new_id)
    rotation_z_deg: float = 0.0
    colour: str = "#8a8a8a"
    visible: bool = True
    solid: bool = False

    def __post_init__(self) -> None:
        """Normalize enum fields that may arrive as raw strings at boundaries."""
        if not isinstance(self.obstacle_type, ObstacleType):
            self.obstacle_type = ObstacleType(self.obstacle_type)
        if not isinstance(self.shape, ObstacleShape):
            self.shape = ObstacleShape(self.shape)


@dataclass
class Space:
    """The mapped space: footprint extruded to ``height`` (GEO-01). Units: metres.

    The Z axis runs from 0 (floor) to ``height``. ``length_unit`` is a
    display preference only; stored coordinates are always metres.
    """

    name: str = "Space"
    space_type: SpaceType = SpaceType.WAREHOUSE
    footprint: Footprint = field(default_factory=lambda: BoxFootprint(0.0, 0.0, 1.0, 1.0))
    height: float = 3.0
    length_unit: LengthUnit = LengthUnit.METRES
    layers: list[Layer] = field(default_factory=list)
    obstacles: list[Obstacle] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalize enum fields that may arrive as raw strings at boundaries."""
        if not isinstance(self.space_type, SpaceType):
            self.space_type = SpaceType(self.space_type)
        if not isinstance(self.length_unit, LengthUnit):
            self.length_unit = LengthUnit(self.length_unit)


class Quantity(StrEnum):
    """Measured quantity for logger-to-column mapping (DAT-03)."""

    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"


class TemperatureUnit(StrEnum):
    """Temperature unit of imported columns; canonical storage is °C (DAT-08)."""

    CELSIUS = "C"
    FAHRENHEIT = "F"
    KELVIN = "K"


class ColumnType(StrEnum):
    """Parsed column type (DAT-02)."""

    TIMESTAMP = "timestamp"
    NUMERIC = "numeric"
    TEXT = "text"


@dataclass(frozen=True)
class ImportProfile:
    """Reusable file-format profile (DAT-01). All fields are JSON-serializable."""

    name: str = "Default"
    delimiter: str = ","
    decimal: str = "."
    header_row: int = 0
    timestamp_column: str = "Timestamp"
    timestamp_format: str = "iso"  # "iso", "excel", or a strptime pattern
    timezone: str = "UTC"  # applied to naive timestamps; stored as UTC
    temperature_unit: TemperatureUnit = TemperatureUnit.CELSIUS


@dataclass(frozen=True)
class DataColumn:
    """One parsed column. Numeric values are raw; timestamps are naive-UTC."""

    name: str
    column_type: ColumnType
    values: np.ndarray  # float64 | datetime64[ns] (UTC) | object[str]
    unit: str = ""


@dataclass(frozen=True)
class ParsedFile:
    """Result of reading one data file with a profile (raw, immutable)."""

    path: str
    columns: tuple[DataColumn, ...]
    row_count: int
    encoding: str
    profile_name: str
    temperature_unit: TemperatureUnit = TemperatureUnit.CELSIUS

    @property
    def name(self) -> str:
        """File name portion of the path."""
        return Path(self.path).name

    def column(self, name: str) -> DataColumn | None:
        """Return the column with ``name``, or None."""
        for column in self.columns:
            if column.name == name:
                return column
        return None

    def timestamp_array(self) -> np.ndarray | None:
        """Values of the first TIMESTAMP column, or None."""
        for column in self.columns:
            if column.column_type is ColumnType.TIMESTAMP:
                return column.values
        return None

    def numeric_column_names(self) -> list[str]:
        """Names of all NUMERIC columns in file order."""
        return [c.name for c in self.columns if c.column_type is ColumnType.NUMERIC]


@dataclass
class LoggerMapping:
    """Logger-to-column association (DAT-03, DAT-05)."""

    logger_id: str
    temperature_file: str = ""
    temperature_column: str = ""
    humidity_file: str = ""
    humidity_column: str = ""
    excluded: bool = False

    def has_temperature(self) -> bool:
        """True when a temperature column is assigned."""
        return bool(self.temperature_file and self.temperature_column)

    def has_humidity(self) -> bool:
        """True when a humidity column is assigned."""
        return bool(self.humidity_file and self.humidity_column)

    def is_satisfied(self) -> bool:
        """True when this logger needs no further mapping (DAT-03 gate)."""
        return self.excluded or self.has_temperature()

    def mapped_columns(self) -> list[tuple[str, str]]:
        """(file, column) pairs in use, for duplicate detection (DAT-05)."""
        pairs: list[tuple[str, str]] = []
        if self.has_temperature():
            pairs.append((self.temperature_file, self.temperature_column))
        if self.has_humidity():
            pairs.append((self.humidity_file, self.humidity_column))
        return pairs


class TimelineMode(StrEnum):
    """Timeline display mode (PRD open question 1: both, default aggregate)."""

    AGGREGATE = "aggregate"
    INSTANT = "instant"


class StudyType(StrEnum):
    """Study type (STY-01)."""

    MAPPING = "mapping"
    EMPTY = "empty"
    LOADED = "loaded"
    DOOR_OPEN = "door_open"
    POWER_FAILURE = "power_failure"
    SEASONAL = "seasonal"
    OTHER = "other"


@dataclass
class Study:
    """Study metadata (STY-01). Dates are ISO calendar strings ('' = unset)."""

    title: str = ""
    protocol_id: str = ""
    equipment_id: str = ""
    location: str = ""
    study_type: StudyType = StudyType.MAPPING
    performed_by: str = ""
    reviewer: str = ""
    start_date: str = ""
    end_date: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        """Normalize enum fields that may arrive as raw strings."""
        if not isinstance(self.study_type, StudyType):
            self.study_type = StudyType(self.study_type)
