"""Custom two-handle range slider (Qt has no native one) — PRD 4.4."""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

_GRAB_RADIUS = 10


class _Part(Enum):
    """Draggable parts of the slider."""

    NONE = auto()
    LOW = auto()
    HIGH = auto()
    PLAYHEAD = auto()


def _clamp(value: int, low: int, high: int) -> int:
    """Clamp ``value`` into the inclusive range ``[low, high]``."""
    return max(low, min(high, value))


class RangeSlider(QWidget):
    """Horizontal two-handle integer slider with an optional playhead marker.

    The low handle can never cross the high handle, and both are clamped to
    ``[minimum, maximum]``. Emits ``range_changed(low, high)`` whenever the
    selected range changes and ``playhead_changed(value)`` when the playhead
    moves (PRD 4.4, AGENTS testing guidance).
    """

    range_changed = Signal(int, int)
    playhead_changed = Signal(int)

    _HANDLE_RADIUS = 7
    _GROOVE_HEIGHT = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum = 0
        self._maximum = 100
        self._low = 0
        self._high = 100
        self._playhead = 0
        self._playhead_visible = False
        self._dragging = _Part.NONE
        self._active = _Part.LOW
        self._single_step = 1
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._ambiguous_drag = False
        self._press_x = 0.0

    # ------------------------------------------------------------------ API

    @property
    def minimum(self) -> int:
        """Lower bound of the slider scale."""
        return self._minimum

    @property
    def maximum(self) -> int:
        """Upper bound of the slider scale."""
        return self._maximum

    @property
    def low_value(self) -> int:
        """Current low (start) handle value."""
        return self._low

    @property
    def high_value(self) -> int:
        """Current high (end) handle value."""
        return self._high

    @property
    def playhead(self) -> int:
        """Current playhead value."""
        return self._playhead

    def selected_range(self) -> tuple[int, int]:
        """Return the selected ``(low, high)`` range."""
        return self._low, self._high

    def playhead_is_visible(self) -> bool:
        """Return whether the playhead marker is drawn."""
        return self._playhead_visible

    def set_playhead_visible(self, visible: bool) -> None:
        """Show or hide the playhead marker."""
        self._playhead_visible = visible
        self.update()

    def set_bounds(self, minimum: int, maximum: int) -> None:
        """Set the scale bounds and clamp current values into them."""
        if maximum < minimum:
            raise ValueError(f"maximum ({maximum}) must be >= minimum ({minimum})")
        self._minimum = minimum
        self._maximum = maximum
        self._low = _clamp(self._low, minimum, maximum)
        self._high = _clamp(self._high, minimum, maximum)
        self._playhead = _clamp(self._playhead, minimum, maximum)
        self.update()
        self.range_changed.emit(self._low, self._high)

    def set_range(self, low: int, high: int) -> None:
        """Set the selected range. Requires ``low <= high``; values are clamped."""
        if low > high:
            raise ValueError(f"low ({low}) must be <= high ({high})")
        new_low = _clamp(low, self._minimum, self._maximum)
        new_high = _clamp(high, self._minimum, self._maximum)
        changed = (new_low, new_high) != (self._low, self._high)
        self._low, self._high = new_low, new_high
        self.update()
        if changed:
            self.range_changed.emit(new_low, new_high)

    def set_playhead(self, value: int) -> None:
        """Move the playhead, clamped to the current bounds."""
        new_value = _clamp(value, self._minimum, self._maximum)
        if new_value != self._playhead:
            self._playhead = new_value
            self.update()
            self.playhead_changed.emit(new_value)

    # ------------------------------------------------------------ geometry

    def _usable_width(self) -> int:
        return max(1, self.width() - 2 * self._HANDLE_RADIUS - 1)

    def value_to_x(self, value: int) -> int:
        """Convert a scale value to a widget x coordinate."""
        span = max(1, self._maximum - self._minimum)
        fraction = (value - self._minimum) / span
        return self._HANDLE_RADIUS + round(fraction * self._usable_width())

    def x_to_value(self, x: int) -> int:
        """Convert a widget x coordinate to the nearest scale value."""
        span = max(1, self._maximum - self._minimum)
        fraction = (x - self._HANDLE_RADIUS) / self._usable_width()
        fraction = min(1.0, max(0.0, fraction))
        return self._minimum + round(fraction * span)

    # --------------------------------------------------------------- input

    def _part_at(self, position: QPoint) -> _Part:
        """Hit-test the handles; deterministic when two are equally close."""
        if not 0 <= position.y() <= self.height():
            return _Part.NONE
        low_x = self.value_to_x(self._low)
        high_x = self.value_to_x(self._high)
        prefer_high = position.x() >= low_x
        if self._low == self._high:
            # Overlapping handles: grab the side that still has room to move.
            if self._high >= self._maximum and self._low > self._minimum:
                prefer_high = False
            elif self._low <= self._minimum and self._high < self._maximum:
                prefer_high = True
        candidates: list[tuple[int, int, _Part]] = [
            (abs(position.x() - low_x), 1 if prefer_high else 0, _Part.LOW),
            (abs(position.x() - high_x), 0 if prefer_high else 1, _Part.HIGH),
        ]
        if self._playhead_visible:
            candidates.append(
                (abs(position.x() - self.value_to_x(self._playhead)), 2, _Part.PLAYHEAD)
            )
        _distance, _priority, part = min(candidates)
        return part

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Grab the nearest handle; overlapping handles resolve by drag direction."""
        if event.button() == Qt.MouseButton.LeftButton:
            part = self._part_at(event.position().toPoint())
            if part is not _Part.NONE:
                self._dragging = part
                if part is not _Part.PLAYHEAD:
                    self._active = part
                self._press_x = event.position().x()
                self._ambiguous_drag = (
                    part in (_Part.LOW, _Part.HIGH)
                    and self._low == self._high
                    and self._minimum < self._low < self._maximum
                )
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Drag the grabbed handle; handles can never cross."""
        if self._dragging is _Part.NONE:
            super().mouseMoveEvent(event)
            return
        if self._ambiguous_drag:
            delta = event.position().x() - self._press_x
            if delta > 0:
                self._dragging = _Part.HIGH
                self._ambiguous_drag = False
            elif delta < 0:
                self._dragging = _Part.LOW
                self._ambiguous_drag = False

        value = self.x_to_value(round(event.position().x()))
        if self._dragging is _Part.LOW:
            self.set_range(min(value, self._high), self._high)
        elif self._dragging is _Part.HIGH:
            self.set_range(self._low, max(value, self._low))
        else:
            self.set_playhead(value)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """End the current drag."""
        self._dragging = _Part.NONE
        self._ambiguous_drag = False
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Move the active handle with arrow / page keys."""
        key = event.key()
        step = self._single_step
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            step = max(1, (self._maximum - self._minimum) // 10)
        delta = 0
        if key in (Qt.Key.Key_Left, Qt.Key.Key_PageDown):
            delta = -step
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_PageUp):
            delta = step
        if delta == 0:
            super().keyPressEvent(event)
            return
        self._move_active(delta)
        event.accept()

    def _move_active(self, delta: int) -> None:
        if self._active is _Part.HIGH:
            self.set_range(self._low, _clamp(self._high + delta, self._low, self._maximum))
        else:
            self.set_range(_clamp(self._low + delta, self._minimum, self._high), self._high)

    # ------------------------------------------------------------- drawing

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the groove, selected range, handles, and optional playhead."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()

        groove_y = self.height() // 2
        groove_height = self._GROOVE_HEIGHT
        groove = QRect(
            self._HANDLE_RADIUS,
            groove_y - groove_height // 2,
            self._usable_width(),
            groove_height,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.color(QPalette.ColorRole.Mid))
        painter.drawRoundedRect(groove, 2.0, 2.0)

        low_x = self.value_to_x(self._low)
        high_x = self.value_to_x(self._high)
        selected = QRect(
            low_x, groove_y - groove_height // 2, max(0, high_x - low_x), groove_height
        )
        painter.setBrush(palette.color(QPalette.ColorRole.Highlight))
        painter.drawRoundedRect(selected, 2.0, 2.0)

        painter.setPen(QPen(palette.color(QPalette.ColorRole.Highlight), 1.5))
        painter.setBrush(palette.color(QPalette.ColorRole.Base))
        for value in (self._low, self._high):
            painter.drawEllipse(
                QPoint(self.value_to_x(value), groove_y),
                self._HANDLE_RADIUS,
                self._HANDLE_RADIUS,
            )

        if self._playhead_visible:
            x = self.value_to_x(self._playhead)
            painter.setPen(QPen(palette.color(QPalette.ColorRole.WindowText), 2.0))
            painter.drawLine(x, 2, x, self.height() - 2)

        painter.end()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        """Preferred size."""
        return QSize(220, 28)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method name
        """Minimum size."""
        return QSize(120, 28)
