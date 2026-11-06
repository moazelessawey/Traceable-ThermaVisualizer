"""Live 3D preview of the configured layout for the Configuration tab (CFG-10).

Startup is lazy and defensive: on the offscreen platform, when PyVista is
missing, or when no OpenGL context can be created, a labeled placeholder is
shown instead (PRD risk table: software-fallback detection). Units: metres.
"""

from __future__ import annotations

import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.rendering.scene import ObstacleStyle, SceneRenderer
from thermavisualizer.services.project_model import ProjectModel

logger = logging.getLogger(__name__)


def _pyvista_available() -> tuple[bool, str]:
    """Import-check the PyVista backend without creating any GL context."""
    try:
        import pyvista  # noqa: F401
        import pyvistaqt  # noqa: F401
    except ImportError as error:
        return False, f"PyVista not importable: {error}"
    return True, ""


class ConfigurationPreview(QWidget):
    """Live 3D preview of loggers, space outline, and obstacles (CFG-10, OBS-03)."""

    def __init__(
        self,
        model: ProjectModel,
        parent: QWidget | None = None,
        renderer: SceneRenderer | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._renderer: SceneRenderer | None = renderer
        self._started = False
        self.fallback_label: QLabel | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        toolbar = QHBoxLayout()
        self.reset_camera_button = QToolButton(self)
        self.reset_camera_button.setText("Reset camera")
        self.reset_camera_button.clicked.connect(self._on_reset_camera)
        toolbar.addWidget(self.reset_camera_button)
        toolbar.addWidget(QLabel("Obstacles", self))
        self.style_combo = QComboBox(self)
        for style in ObstacleStyle:
            self.style_combo.addItem(style.value, style)
        self.style_combo.currentIndexChanged.connect(self._refresh_obstacles)
        toolbar.addWidget(self.style_combo)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._content = QVBoxLayout()
        layout.addLayout(self._content, 1)

        model.config_changed.connect(self._refresh_all)
        model.logger_selected.connect(self._refresh_loggers)
        if renderer is not None:
            self._install_renderer(renderer)

    # -------------------------------------------------------------- state

    def is_active(self) -> bool:
        """True when a real renderer is installed."""
        return self._renderer is not None

    def renderer(self) -> SceneRenderer | None:
        """The installed renderer, if any (used by tests and overlays)."""
        return self._renderer

    # ------------------------------------------------------------ startup

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt virtual
        """Create the renderer lazily on first show."""
        super().showEvent(event)
        self._ensure_started()

    def _ensure_started(self) -> None:
        if self._started:
            return
        self._started = True
        if self._renderer is not None:
            return
        if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
            self._show_fallback("3D preview disabled on the offscreen platform")
            return
        available, reason = _pyvista_available()
        if not available:
            self._show_fallback(f"3D preview unavailable: {reason}")
            return
        try:
            from thermavisualizer.rendering.pyvista_backend import PyVistaScene

            self._renderer = PyVistaScene(self)
        except Exception as error:  # GL context failure — fall back, never crash
            logger.warning("3D preview disabled: %s", error)
            self._show_fallback(f"3D preview unavailable: {error}")
            return
        self._install_renderer(self._renderer)

    def _install_renderer(self, renderer: SceneRenderer) -> None:
        self._content.addWidget(renderer.widget(), 1)
        self._refresh_all()

    def _show_fallback(self, message: str) -> None:
        self.fallback_label = QLabel(message, self)
        self.fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fallback_label.setWordWrap(True)
        self._content.addWidget(self.fallback_label, 1)

    # ------------------------------------------------------------ refresh

    def _obstacle_style(self) -> ObstacleStyle:
        data = self.style_combo.currentData()
        return ObstacleStyle(str(data)) if data is not None else ObstacleStyle.SOLID

    def _refresh_all(self) -> None:
        if self._renderer is None:
            return
        self._renderer.set_space(self._model.space)
        self._refresh_loggers()
        self._refresh_obstacles()
        self._renderer.render()
        
    def _refresh_loggers(self) -> None:
        if self._renderer is None:
            return
        self._renderer.set_loggers(self._model.space.layers, self._model.selected_logger_id())

    def _refresh_obstacles(self) -> None:
        if self._renderer is None:
            return
        visible = [o for o in self._model.space.obstacles if o.visible]
        self._renderer.set_obstacles(visible, self._obstacle_style())

    def _on_reset_camera(self) -> None:
        if self._renderer is not None:
            self._renderer.reset_camera()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt virtual
        """Release renderer resources when the preview closes."""
        if self._renderer is not None:
            self._renderer.shutdown()
        super().closeEvent(event)
