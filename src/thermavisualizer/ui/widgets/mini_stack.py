"""Side mini-view of the vertical layer stack (CFG-09)."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QMouseEvent, QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QWidget

from thermavisualizer.services.project_model import ProjectModel


class MiniStackView(QWidget):
    """Elevation view of layer heights; clicking a band activates its layer."""

    _BAND_HEIGHT = 14.0

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self.setMinimumWidth(170)
        for signal in (
            model.layers_changed,
            model.loggers_changed,
            model.space_changed,
            model.active_layer_changed,
        ):
            signal.connect(self.update)

    def _bands(self) -> list[tuple[str, QRectF]]:
        """Return ``(layer_id, band rectangle)`` pairs, top-most first by height."""
        space = self._model.space
        height = max(space.height, 0.1)
        top = 22.0
        bottom = max(self.height() - 26.0, top + 10.0)
        bands: list[tuple[str, QRectF]] = []
        for layer in space.layers:
            fraction = 1.0 - min(max(layer.height / height, 0.0), 1.0)
            y = top + fraction * (bottom - top)
            rect = QRectF(
                34.0, y - self._BAND_HEIGHT / 2.0, max(self.width() - 44.0, 40.0), self._BAND_HEIGHT
            )
            bands.append((layer.layer_id, rect))
        return bands

    def layer_rect(self, index: int) -> QRectF:
        """Band rectangle of the layer at ``index`` (for tests and overlays)."""
        return self._bands()[index][1]

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the Z axis and one band per layer."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.color(QPalette.ColorRole.Window))
        space = self._model.space
        top = 22.0
        bottom = max(self.height() - 26.0, top + 10.0)

        painter.setPen(QPen(palette.color(QPalette.ColorRole.WindowText), 1.0))
        painter.drawText(6, 14, f"Stack (0–{space.height:.2f} m)")
        painter.drawLine(28, int(top), 28, int(bottom))

        active_id = self._model.active_layer_id()
        for (layer_id, rect), layer in zip(self._bands(), space.layers):
            active = layer_id == active_id
            painter.setBrush(
                palette.color(QPalette.ColorRole.Highlight)
                if active
                else palette.color(QPalette.ColorRole.Button)
            )
            painter.setPen(QPen(palette.color(QPalette.ColorRole.WindowText), 1.0))
            painter.drawRoundedRect(rect, 3.0, 3.0)
            painter.drawText(2, int(rect.center().y() + 4), f"{layer.height:.2f}")
            text_color = (
                palette.color(QPalette.ColorRole.HighlightedText)
                if active
                else palette.color(QPalette.ColorRole.WindowText)
            )
            painter.setPen(text_color)
            painter.drawText(
                QRectF(rect.x() + 4, rect.y(), rect.width() - 6, rect.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"{layer.name} ({len(layer.loggers)})",
            )
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Activate the clicked layer."""
        if event.button() == Qt.MouseButton.LeftButton:
            for layer_id, rect in self._bands():
                if rect.contains(event.position()):
                    self._model.set_active_layer(layer_id)
                    event.accept()
                    return
        super().mousePressEvent(event)
