"""3D View tab: canvas, floating overlay, and model wiring (PRD 4.2)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Signal
from PySide6.QtWidgets import QFileDialog, QVBoxLayout, QWidget

from thermavisualizer.rendering.scene import SceneRenderer
from thermavisualizer.rendering.view3d import View3DWidget
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.workers import InterpolationResult
from thermavisualizer.ui.widgets.canvas_overlay import CanvasOverlay


class View3DTab(QWidget):
    """The 3D heat-map canvas with its top-right overlay action strip."""

    status_message = Signal(str)
    color_scale_clicked = Signal()

    def __init__(
        self,
        model: ProjectModel,
        parent: QWidget | None = None,
        renderer: SceneRenderer | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.view = View3DWidget(self, renderer=renderer)
        layout.addWidget(self.view, 1)

        self.overlay = CanvasOverlay(self.view)
        self.overlay.reset_camera_clicked.connect(self.view.reset_camera)
        self.overlay.preset_selected.connect(self.view.preset_view)
        self.overlay.markers_toggled.connect(self.view.set_markers_visible)
        self.overlay.labels_toggled.connect(self.view.set_labels_visible)
        self.overlay.bounding_box_toggled.connect(self.view.set_outline_visible)
        self.overlay.slices_toggled.connect(self.view.set_slices_visible)
        self.overlay.screenshot_clicked.connect(self._on_screenshot)
        self.overlay.color_scale_clicked.connect(self.color_scale_clicked)
        self.view.installEventFilter(self)
        self._position_overlay()

        model.volume_ready.connect(self._on_volume_ready)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt virtual
        """Keep the overlay pinned to the top-right and above the VTK surface."""
        if obj is self.view and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.WindowActivate,
            QEvent.Type.Paint,
        ):
            self._position_overlay()
        return super().eventFilter(obj, event)

    def _position_overlay(self) -> None:
        self.overlay.adjustSize()
        x = max(self.view.width() - self.overlay.width() - 8, 0)
        self.overlay.move(x, 8)
        self.overlay.raise_()

    def _on_volume_ready(self, result: object) -> None:
        if not isinstance(result, InterpolationResult):
            return
        space = self._model.space
        self.view.update_volume(result, space, space.obstacles)
        self.view.set_logger_values(self._model.current_logger_values(result.quantity))

    def _on_screenshot(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save screenshot", "view3d.png", "PNG (*.png);;JPEG (*.jpg)"
        )
        if not path:
            return
        if self.view.save_screenshot(__import__("pathlib").Path(path)):
            self.status_message.emit(f"Screenshot saved to {path}")
        else:
            self.status_message.emit("Screenshot unavailable (no active 3D renderer)")

