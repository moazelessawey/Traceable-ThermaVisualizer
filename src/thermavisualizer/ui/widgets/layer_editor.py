"""2D top-down editor for the active layer (CFG-03, CFG-09, GEO-02).

Painting only; every mutation goes through ProjectModel commands (AGENTS
architecture rules). All coordinates in metres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum, auto

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPalette,
    QPen,
)
from PySide6.QtWidgets import QWidget

from thermavisualizer.core.geometry import (
    footprint_bounds,
    obstacle_contains,
    polygon_is_simple,
)
from thermavisualizer.core.layout import unique_logger_ids
from thermavisualizer.core.models import (
    BoxFootprint,
    Logger,
    ObstacleShape,
    PolygonFootprint,
    Space,
)
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import (
    AddLoggersCommand,
    RemoveLoggersCommand,
    RemoveObstacleCommand,
    SetSpacePropertiesCommand,
    UpdateLoggerCommand,
    UpdateObstacleCommand,
)


class EditorMode(Enum):
    """Interaction mode of the 2D editor."""

    SELECT = auto()
    ADD_LOGGER = auto()
    EDIT_FOOTPRINT = auto()


class _DragKind(Enum):
    LOGGER = auto()
    OBSTACLE = auto()
    VERTEX = auto()


@dataclass
class _Transform:
    scale: float
    origin_x: float
    origin_y: float

    def to_widget(self, x: float, y: float) -> QPointF:
        return QPointF(self.origin_x + x * self.scale, self.origin_y - y * self.scale)

    def to_world(self, px: float, py: float) -> tuple[float, float]:
        return ((px - self.origin_x) / self.scale, (self.origin_y - py) / self.scale)


@dataclass
class _DragState:
    kind: _DragKind
    key: str | int
    original: tuple[float, float]
    candidate: tuple[float, float]


def _segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance from point (px, py) to segment (a, b). Units: metres."""
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class Layer2DEditor(QWidget):
    """Top-down editor for loggers, obstacles, and footprint vertices."""

    edit_rejected = Signal(str)
    mode_changed = Signal(object)

    _LOGGER_RADIUS = 6
    _HIT_TOLERANCE_PX = 10.0
    _VERTEX_SIZE = 8.0

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._mode = EditorMode.SELECT
        self._snap_step = 0.1
        self._drag: _DragState | None = None
        self._selected_vertex: int | None = None
        self.setMinimumSize(320, 240)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        for signal in (
            model.layers_changed,
            model.loggers_changed,
            model.obstacles_changed,
            model.space_changed,
            model.active_layer_changed,
            model.logger_selected,
            model.obstacle_selected,
        ):
            signal.connect(self.update)

    # ------------------------------------------------------------- public API

    def mode(self) -> EditorMode:
        """Current interaction mode."""
        return self._mode

    def set_mode(self, mode: EditorMode) -> None:
        """Switch interaction mode."""
        if mode is self._mode:
            return
        self._mode = mode
        self._selected_vertex = None
        cursor = (
            Qt.CursorShape.CrossCursor
            if mode is EditorMode.ADD_LOGGER
            else Qt.CursorShape.ArrowCursor
        )
        self.setCursor(cursor)
        self.mode_changed.emit(mode)
        self.update()

    def snap_step(self) -> float:
        """Grid snap step in metres; 0 disables snapping."""
        return self._snap_step

    def set_snap_step(self, step: float) -> None:
        """Set the grid snap step in metres; 0 disables snapping."""
        self._snap_step = max(0.0, step)

    def world_to_widget(self, x: float, y: float) -> QPointF:
        """Map space coordinates (metres) to widget pixels."""
        return self._compute_transform().to_widget(x, y)

    def widget_to_world(self, position: QPointF) -> tuple[float, float]:
        """Map widget pixels to space coordinates (metres)."""
        return self._compute_transform().to_world(position.x(), position.y())

    # -------------------------------------------------------------- geometry

    def _compute_transform(self) -> _Transform:
        space = self._model.space
        x_min, y_min, x_max, y_max = footprint_bounds(space.footprint)
        margin = 0.12 * max(x_max - x_min, y_max - y_min, 0.1) + 0.2
        x_min -= margin
        y_min -= margin
        x_max += margin
        y_max += margin
        available_w = max(self.width() - 8, 10)
        available_h = max(self.height() - 8, 10)
        scale = min(available_w / (x_max - x_min), available_h / (y_max - y_min))
        center_x = (x_min + x_max) / 2.0
        center_y = (y_min + y_max) / 2.0
        return _Transform(
            scale, self.width() / 2.0 - center_x * scale, self.height() / 2.0 + center_y * scale
        )

    def _snap(self, value: float) -> float:
        if self._snap_step <= 0.0:
            return value
        return round(value / self._snap_step) * self._snap_step

    def _snap_point(self, world: tuple[float, float]) -> tuple[float, float]:
        return self._snap(world[0]), self._snap(world[1])

    def _footprint_path(self, space: Space, transform: _Transform) -> QPainterPath:
        path = QPainterPath()
        footprint = space.footprint
        if isinstance(footprint, BoxFootprint):
            top_left = transform.to_widget(footprint.x_min, footprint.y_max)
            bottom_right = transform.to_widget(footprint.x_max, footprint.y_min)
            path.addRect(QRectF(top_left, bottom_right))
            return path
        first = transform.to_widget(*footprint.vertices[0])
        path.moveTo(first)
        for vertex in footprint.vertices[1:]:
            path.lineTo(transform.to_widget(*vertex))
        path.closeSubpath()
        return path

    # -------------------------------------------------------------- hit tests

    def _logger_at(self, widget_pos: QPointF, transform: _Transform) -> str | None:
        layer = self._model.active_layer()
        if layer is None:
            return None
        best: str | None = None
        best_distance = self._HIT_TOLERANCE_PX
        for logger in layer.loggers:
            point = transform.to_widget(logger.x, logger.y)
            distance = math.hypot(point.x() - widget_pos.x(), point.y() - widget_pos.y())
            if distance <= best_distance:
                best, best_distance = logger.logger_id, distance
        return best

    def _obstacle_at(self, world: tuple[float, float]) -> str | None:
        for obstacle in reversed(self._model.space.obstacles):
            if obstacle.visible and obstacle_contains(obstacle, world[0], world[1], obstacle.z):
                return obstacle.obstacle_id
        return None

    def _vertex_at(self, widget_pos: QPointF, transform: _Transform) -> int | None:
        footprint = self._model.space.footprint
        if not isinstance(footprint, PolygonFootprint):
            return None
        for index, vertex in enumerate(footprint.vertices):
            point = transform.to_widget(*vertex)
            if math.hypot(point.x() - widget_pos.x(), point.y() - widget_pos.y()) <= (
                self._HIT_TOLERANCE_PX
            ):
                return index
        return None

    def _edge_insert_index(self, world: tuple[float, float], transform: _Transform) -> int | None:
        footprint = self._model.space.footprint
        if not isinstance(footprint, PolygonFootprint):
            return None
        tolerance = max(0.1, 8.0 / transform.scale)
        vertices = footprint.vertices
        best: int | None = None
        best_distance = tolerance
        for index in range(len(vertices)):
            ax, ay = vertices[index]
            bx, by = vertices[(index + 1) % len(vertices)]
            distance = _segment_distance(world[0], world[1], ax, ay, bx, by)
            if distance <= best_distance:
                best, best_distance = (index + 1) % len(vertices), distance
        return best

    # ---------------------------------------------------------------- events

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle selection, drag start, logger add, and vertex editing."""
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        transform = self._compute_transform()
        world = self.widget_to_world(event.position())
        if self._mode is EditorMode.EDIT_FOOTPRINT:
            self._footprint_press(event.position(), world, transform)
            event.accept()
            return
        if self._mode is EditorMode.ADD_LOGGER:
            self._add_logger_at(world)
            event.accept()
            return
        logger_id = self._logger_at(event.position(), transform)
        if logger_id is not None:
            layer = self._model.active_layer()
            assert layer is not None
            self._model.select_logger(logger_id)
            logger = self._model.logger_by_id(layer.layer_id, logger_id)
            self._drag = _DragState(
                _DragKind.LOGGER, logger_id, (logger.x, logger.y), (logger.x, logger.y)
            )
            event.accept()
            return
        obstacle_id = self._obstacle_at(world)
        if obstacle_id is not None:
            self._model.select_obstacle(obstacle_id)
            obstacle = self._model.obstacle_by_id(obstacle_id)
            self._drag = _DragState(
                _DragKind.OBSTACLE,
                obstacle_id,
                (obstacle.x, obstacle.y),
                (obstacle.x, obstacle.y),
            )
            event.accept()
            return
        self._model.select_logger(None)
        self._model.select_obstacle(None)

    def _footprint_press(
        self, widget_pos: QPointF, world: tuple[float, float], transform: _Transform
    ) -> None:
        footprint = self._model.space.footprint
        if not isinstance(footprint, PolygonFootprint):
            self.edit_rejected.emit("Switch the footprint shape to Polygon to edit vertices")
            return
        vertex_index = self._vertex_at(widget_pos, transform)
        if vertex_index is not None:
            self._selected_vertex = vertex_index
            vertex = footprint.vertices[vertex_index]
            self._drag = _DragState(_DragKind.VERTEX, vertex_index, vertex, vertex)
            return
        insert_index = self._edge_insert_index(world, transform)
        if insert_index is not None:
            snapped = self._snap_point(world)
            new_vertices = list(footprint.vertices)
            new_vertices.insert(insert_index, snapped)
            if polygon_is_simple(new_vertices):
                self._model.apply(
                    SetSpacePropertiesCommand(
                        self._model, footprint=PolygonFootprint(tuple(new_vertices))
                    )
                )
                self._selected_vertex = insert_index
            else:
                self.edit_rejected.emit("Vertex not added: polygon would self-intersect")

    def _add_logger_at(self, world: tuple[float, float]) -> None:
        layer = self._model.active_layer()
        if layer is None:
            self.edit_rejected.emit("Add a layer before adding loggers")
            return
        x, y = self._snap_point(world)
        existing = frozenset(
            item.logger_id for any_layer in self._model.space.layers for item in any_layer.loggers
        )
        new_id = unique_logger_ids("L", 1, existing)[0]
        self._model.apply(
            AddLoggersCommand(self._model, layer.layer_id, [Logger(new_id, x, y, layer.height)])
        )
        self._model.select_logger(new_id)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Update the drag candidate position (snapped)."""
        if self._drag is None:
            super().mouseMoveEvent(event)
            return
        world = self._snap_point(self.widget_to_world(event.position()))
        self._drag.candidate = world
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Commit the current drag as a single undo step."""
        if self._drag is None:
            super().mouseReleaseEvent(event)
            return
        drag, self._drag = self._drag, None
        if drag.kind is _DragKind.LOGGER and drag.candidate != drag.original:
            layer = self._model.active_layer()
            if layer is not None:
                logger = self._model.logger_by_id(layer.layer_id, str(drag.key))
                self._model.apply(
                    UpdateLoggerCommand(
                        self._model,
                        layer.layer_id,
                        replace(logger, x=drag.candidate[0], y=drag.candidate[1]),
                    )
                )
        elif drag.kind is _DragKind.OBSTACLE and drag.candidate != drag.original:
            obstacle = self._model.obstacle_by_id(str(drag.key))
            self._model.apply(
                UpdateObstacleCommand(
                    self._model,
                    replace(obstacle, x=drag.candidate[0], y=drag.candidate[1]),
                )
            )
        elif drag.kind is _DragKind.VERTEX:
            self._commit_vertex_drag(drag)
        self.update()

    def _commit_vertex_drag(self, drag: _DragState) -> None:
        footprint = self._model.space.footprint
        if not isinstance(footprint, PolygonFootprint):
            return
        new_vertices = list(footprint.vertices)
        new_vertices[int(drag.key)] = drag.candidate
        if polygon_is_simple(new_vertices):
            self._model.apply(
                SetSpacePropertiesCommand(
                    self._model, footprint=PolygonFootprint(tuple(new_vertices))
                )
            )
        else:
            self.edit_rejected.emit("Vertex move rejected: polygon would self-intersect")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Delete the selected logger, obstacle, or footprint vertex."""
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self._mode is EditorMode.EDIT_FOOTPRINT and self._selected_vertex is not None:
                self._delete_selected_vertex()
            else:
                logger_id = self._model.selected_logger_id()
                if logger_id is not None:
                    layer = self._model.active_layer()
                    assert layer is not None
                    self._model.apply(
                        RemoveLoggersCommand(self._model, layer.layer_id, [logger_id])
                    )
                    return
                obstacle_id = self._model.selected_obstacle_id()
                if obstacle_id is not None:
                    self._model.apply(RemoveObstacleCommand(self._model, obstacle_id))
            event.accept()
            return
        super().keyPressEvent(event)

    def _delete_selected_vertex(self) -> None:
        footprint = self._model.space.footprint
        if not isinstance(footprint, PolygonFootprint):
            return
        if len(footprint.vertices) <= 3:
            self.edit_rejected.emit("A polygon footprint needs at least 3 vertices")
            return
        assert self._selected_vertex is not None
        new_vertices = list(footprint.vertices)
        new_vertices.pop(self._selected_vertex)
        self._selected_vertex = None
        self._model.apply(
            SetSpacePropertiesCommand(self._model, footprint=PolygonFootprint(tuple(new_vertices)))
        )

    # --------------------------------------------------------------- painting

    def paintEvent(self, event: QPaintEvent) -> None:
        """Paint footprint, obstacles, loggers, vertex handles, and drag ghosts."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.color(QPalette.ColorRole.Window))
        transform = self._compute_transform()
        space = self._model.space

        path = self._footprint_path(space, transform)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.color(QPalette.ColorRole.AlternateBase))
        painter.drawPath(path)
        painter.setPen(QPen(palette.color(QPalette.ColorRole.WindowText), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        selected_obstacle = self._model.selected_obstacle_id()
        for obstacle in space.obstacles:
            if obstacle.visible:
                self._paint_obstacle(
                    painter,
                    transform,
                    obstacle.obstacle_id,
                    obstacle.obstacle_id == selected_obstacle,
                )

        active = self._model.active_layer()
        for layer in space.layers:
            if layer is active:
                continue
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(160, 160, 160))
            for logger in layer.loggers:
                painter.drawEllipse(transform.to_widget(logger.x, logger.y), 3.0, 3.0)

        if active is not None:
            selected_logger = self._model.selected_logger_id()
            for logger in active.loggers:
                position = transform.to_widget(logger.x, logger.y)
                selected = logger.logger_id == selected_logger
                painter.setBrush(
                    palette.color(QPalette.ColorRole.Highlight)
                    if selected
                    else palette.color(QPalette.ColorRole.Base)
                )
                painter.setPen(QPen(palette.color(QPalette.ColorRole.WindowText), 1.2))
                painter.drawEllipse(
                    position, float(self._LOGGER_RADIUS), float(self._LOGGER_RADIUS)
                )
                if selected:
                    painter.drawText(
                        position.x() + self._LOGGER_RADIUS + 3,
                        position.y() - self._LOGGER_RADIUS - 3,
                        logger.logger_id,
                    )

        footprint = space.footprint
        if self._mode is EditorMode.EDIT_FOOTPRINT and isinstance(footprint, PolygonFootprint):
            for index, vertex in enumerate(footprint.vertices):
                point = transform.to_widget(*vertex)
                rect = QRectF(
                    point.x() - self._VERTEX_SIZE / 2,
                    point.y() - self._VERTEX_SIZE / 2,
                    self._VERTEX_SIZE,
                    self._VERTEX_SIZE,
                )
                painter.setBrush(
                    palette.color(QPalette.ColorRole.Highlight)
                    if index == self._selected_vertex
                    else palette.color(QPalette.ColorRole.Base)
                )
                painter.setPen(QPen(palette.color(QPalette.ColorRole.WindowText), 1.2))
                painter.drawRect(rect)

        if self._drag is not None and self._drag.candidate != self._drag.original:
            self._paint_drag_ghost(painter, transform)

        if not space.layers:
            painter.setPen(QPen(palette.color(QPalette.ColorRole.PlaceholderText), 1.0))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No layers yet — add one in the left panel",
            )
        painter.end()

    def _paint_obstacle(
        self, painter: QPainter, transform: _Transform, obstacle_id: str, selected: bool
    ) -> None:
        obstacle = self._model.obstacle_by_id(obstacle_id)
        color = QColor(obstacle.colour)
        fill = QColor(color)
        fill.setAlpha(140)
        painter.save()
        center = transform.to_widget(obstacle.x, obstacle.y)
        painter.translate(center)
        painter.rotate(-obstacle.rotation_z_deg)
        if obstacle.shape == ObstacleShape.CYLINDER:
            diameter = obstacle.size_x * transform.scale
            rect = QRectF(-diameter / 2, -diameter / 2, diameter, diameter)
        else:
            width = obstacle.size_x * transform.scale
            height = obstacle.size_y * transform.scale
            rect = QRectF(-width / 2, -height / 2, width, height)
        painter.setPen(QPen(color.darker(130), 1.5))
        painter.setBrush(fill)
        if obstacle.shape == ObstacleShape.CYLINDER:
            painter.drawEllipse(rect)
        else:
            painter.drawRect(rect)
        if selected:
            pen = QPen(self.palette().color(QPalette.ColorRole.Highlight), 2.0)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 3.0, 3.0)
        painter.restore()

    def _paint_drag_ghost(self, painter: QPainter, transform: _Transform) -> None:
        assert self._drag is not None
        pen = QPen(self.palette().color(QPalette.ColorRole.Highlight), 1.5)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        point = transform.to_widget(*self._drag.candidate)
        if self._drag.kind is _DragKind.LOGGER:
            painter.drawEllipse(point, float(self._LOGGER_RADIUS), float(self._LOGGER_RADIUS))
        elif self._drag.kind is _DragKind.VERTEX:
            painter.drawRect(
                QRectF(
                    point.x() - self._VERTEX_SIZE / 2,
                    point.y() - self._VERTEX_SIZE / 2,
                    self._VERTEX_SIZE,
                    self._VERTEX_SIZE,
                )
            )
        else:
            obstacle = self._model.obstacle_by_id(str(self._drag.key))
            width = obstacle.size_x * transform.scale
            height = (
                obstacle.size_x if obstacle.shape == ObstacleShape.CYLINDER else obstacle.size_y
            ) * transform.scale
            painter.drawEllipse(
                QRectF(point.x() - width / 2, point.y() - height / 2, width, height)
            )
