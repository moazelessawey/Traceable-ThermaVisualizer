"""3D heat-map view widget (VIS-01..04/06, SLC-01/02).

All PyVista access stays inside ``rendering/`` (AGENTS rule); the 3D View tab
embeds this widget and drives it with model data. Units: metres; scalar units
follow the quantity (°C / %RH).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QShowEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from thermavisualizer.core.interpolation import build_voxel_grid
from thermavisualizer.core.models import Obstacle, Quantity, Space
from thermavisualizer.core.slicing import (
    SliceAxis,
    SliceData,
    SliceError,
    SliceSpec,
    extract_axis_slice,
    extract_plane_slice,
)
from thermavisualizer.rendering.colormaps import (
    ColorScale,
    color_limits,
    colormap_for,
)
from thermavisualizer.rendering.pyvista_backend import try_create_scene
from thermavisualizer.rendering.scene import (
    ObstacleStyle,
    PresetView,
    SceneRenderer,
)
from thermavisualizer.services.workers import InterpolationResult

logger = logging.getLogger(__name__)

_LIMIT_COLORS = ["#d62728", "#d62728"]  # red highlight for out-of-limit regions

_LIMIT_OFFSET = 0.002  # metres; keeps the highlight just above the slice (no Z-fighting)


def _limit_offset(spec: SliceSpec) -> np.ndarray:
    """Tiny offset along the slice normal so the highlight does not Z-fight."""
    if spec.axis is SliceAxis.X:
        return np.array([_LIMIT_OFFSET, 0.0, 0.0])
    if spec.axis is SliceAxis.Y:
        return np.array([0.0, _LIMIT_OFFSET, 0.0])
    if spec.axis is SliceAxis.Z:
        return np.array([0.0, 0.0, _LIMIT_OFFSET])
    normal = np.asarray(spec.normal, dtype=float)
    norm = float(np.linalg.norm(normal))
    if norm <= 0.0:
        return np.zeros(3)
    return normal / norm * _LIMIT_OFFSET


class View3DWidget(QWidget):
    """Embeddable 3D heat-map view driven by interpolation results."""

    def __init__(
        self, parent: QWidget | None = None, renderer: SceneRenderer | None = None
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        self._renderer = renderer
        self._started = False
        self.fallback_label: QLabel | None = None
        self._volume_result: InterpolationResult | None = None
        self._space: Space | None = None
        self._obstacles: tuple[Obstacle, ...] = ()
        self._obstacle_style = ObstacleStyle.TRANSPARENT
        self._color_scale = ColorScale()
        self._slices: dict[str, SliceSpec] = {}
        self._logger_values: np.ndarray | None = None
        self._labels_visible = False
        self._axes_visible = True

        self._markers_visible = True
        self._slices_visible = True
        self._limits: tuple[float, float] | None = None

        self._content = QVBoxLayout(self)
        self._content.setContentsMargins(0, 0, 0, 0)
        if renderer is not None:
            self._install(renderer)

    # -------------------------------------------------------------- startup

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
        renderer, reason = try_create_scene(self)
        if renderer is None:
            self.fallback_label = QLabel(f"3D view unavailable: {reason}", self)
            self.fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.fallback_label.setWordWrap(True)
            self._content.addWidget(self.fallback_label, 1)
            return
        self._install(renderer)

    def _install(self, renderer: SceneRenderer) -> None:
        renderer.render()
        self._renderer = renderer
        self._content.addWidget(renderer.widget(), 1)
        self.refresh()
        QTimer.singleShot(0, self.refresh)  # deferred kick once the event loop runs

    def is_active(self) -> bool:
        """True when a real renderer is installed."""
        return self._renderer is not None

    def renderer(self) -> SceneRenderer | None:
        """The installed renderer, if any (tests and overlays)."""
        return self._renderer

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt virtual
        """Release renderer resources when the view closes."""
        if self._renderer is not None:
            self._renderer.shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------ view state

    def update_volume(
        self,
        result: InterpolationResult,
        space: Space,
        obstacles: Sequence[Obstacle],
    ) -> None:
        """Show a new interpolation result (VIS-06 switches quantity here)."""
        self._volume_result = result
        self._space = space
        self._obstacles = tuple(obstacles)
        self.refresh()

    def set_slices(self, specs: Sequence[SliceSpec]) -> None:
        """Replace the visible slice set (SLC-02: multiple, toggleable)."""
        self._slices = {spec.spec_id: spec for spec in specs}
        self._refresh_slices()

    def set_color_scale(self, scale: ColorScale) -> None:
        """Change color map / range and re-render (VIS-04)."""
        self._color_scale = scale
        self._refresh_slices()
        self._refresh_markers()

    def set_obstacle_style(self, style: ObstacleStyle) -> None:
        """Change obstacle render style (OBS-03)."""
        self._obstacle_style = style
        if self._renderer is not None and self._space is not None:
            self._renderer.set_obstacles([o for o in self._obstacles if o.visible], style)

    def set_logger_values(self, values: np.ndarray | None) -> None:
        """Color logger markers by these values; None for neutral markers."""
        self._logger_values = None if values is None else np.asarray(values, dtype=float)
        self._refresh_markers()

    def set_labels_visible(self, visible: bool) -> None:
        """Toggle logger ID labels (VIS-03)."""
        self._labels_visible = visible
        if self._renderer is not None:
            self._renderer.set_labels_visible(visible)

    def set_axes_visible(self, visible: bool) -> None:
        """Toggle dimension axes (VIS-02)."""
        self._axes_visible = visible
        if self._renderer is not None:
            self._renderer.set_axes_visible(visible)

    def preset_view(self, view: PresetView) -> None:
        """Apply a preset camera view (VIS-01)."""
        if self._renderer is not None:
            self._renderer.preset_view(view)

    def reset_camera(self) -> None:
        """Fit the camera to the scene (VIS-01)."""
        if self._renderer is not None:
            self._renderer.reset_camera()

    def color_scale(self) -> ColorScale:
        """Current color scale."""
        return self._color_scale

    def markers_visible(self) -> bool:
        """True when logger markers are shown."""
        return self._markers_visible

    def slices_visible(self) -> bool:
        """True when slice surfaces are shown."""
        return self._slices_visible

    def set_markers_visible(self, visible: bool) -> None:
        """Toggle logger markers (overlay action, VIS-03)."""
        self._markers_visible = visible
        self._refresh_markers()

    def set_slices_visible(self, visible: bool) -> None:
        """Toggle all slice surfaces (overlay action, SLC-02)."""
        self._slices_visible = visible
        self._refresh_slices()

    def set_outline_visible(self, visible: bool) -> None:
        """Toggle the space outline (overlay action, VIS-02)."""
        if self._renderer is not None:
            self._renderer.set_space_visible(visible)

    def set_limits(self, limits: tuple[float, float] | None) -> None:
        """Highlight slice regions outside ``(low, high)`` (SLC-07); None disables."""
        self._limits = limits
        self._refresh_slices()

    def save_screenshot(self, path: Path, scale: int = 1) -> bool:
        """Save a screenshot of the current view (EXP-03). Returns success."""
        if self._renderer is None:
            return False
        self._renderer.save_screenshot(Path(path), scale)
        return True

    def labels_visible(self) -> bool:
        """True when logger labels are shown."""
        return self._labels_visible

    def obstacle_style(self) -> ObstacleStyle:
        """Current obstacle render style."""
        return self._obstacle_style

    def camera_state(self) -> dict | None:
        """Camera pose from the active renderer, if any."""
        return self._renderer.camera_state() if self._renderer is not None else None

    def set_camera_state(self, state: dict | None) -> None:
        """Restore the camera pose on the active renderer."""
        if state and self._renderer is not None:
            self._renderer.set_camera_state(state)

    # --------------------------------------------------------------- refresh

    def refresh(self) -> None:
        """Re-render everything from current state."""
        renderer = self._renderer
        if renderer is None:
            return
        if self._space is not None:
            renderer.set_space(self._space)
        renderer.set_obstacles([o for o in self._obstacles if o.visible], self._obstacle_style)
        renderer.set_axes_visible(self._axes_visible)
        self._refresh_slices()
        self._refresh_markers()

    def _quantity_title(self) -> str:
        result = self._volume_result
        if result is None:
            return ""
        if result.quantity is Quantity.TEMPERATURE:
            return "Temperature (°C)"
        return "Humidity (%RH)"

    def _refresh_slices(self) -> None:
        renderer = self._renderer
        if renderer is None:
            return
        renderer.clear_slices()
        if not self._slices_visible:
            return
        result, space = self._volume_result, self._space
        if result is None or space is None:
            return
        grid = build_voxel_grid(space, result.settings.resolution)
        clim = color_limits(self._color_scale, result.volume)
        cmap = colormap_for(self._color_scale)
        title = self._quantity_title()
        for spec in self._slices.values():
            if not spec.visible:
                renderer.remove_slice(spec.spec_id)
                continue
            try:
                if spec.axis is not None:
                    data = extract_axis_slice(
                        result.volume,
                        grid,
                        space,
                        list(self._obstacles),
                        spec.axis,
                        spec.position,
                    )
                else:
                    data = extract_plane_slice(
                        result.volume,
                        grid,
                        space,
                        list(self._obstacles),
                        spec.point,
                        spec.normal,
                    )
            except SliceError as error:
                logger.warning("slice '%s' skipped: %s", spec.spec_id, error)
                renderer.remove_slice(spec.spec_id)
                continue
            renderer.show_slice(spec.spec_id, data, cmap, clim, spec.opacity, title)

            if self._limits is not None:
                low, high = self._limits
                exceedance = np.where((data.values < low) | (data.values > high), 1.0, np.nan)
                limit_data = SliceData(
                    points=data.points + _limit_offset(spec),
                    values=exceedance,
                    u_count=data.u_count,
                    v_count=data.v_count,
                )
                renderer.show_slice(
                    f"{spec.spec_id}:limits",
                    limit_data,
                    _LIMIT_COLORS,
                    (0.0, 1.0),
                    min(0.65, spec.opacity),
                    "Outside limits",
                )

    def _refresh_markers(self) -> None:
        renderer = self._renderer
        result = self._volume_result
        if renderer is None or result is None:
            return
        if not self._markers_visible:
            renderer.set_logger_scalars(
                np.zeros((0, 3)), (), None, colormap_for(self._color_scale), None, ""
            )
            return
        renderer.set_logger_scalars(
            result.positions,
            result.logger_ids,
            self._logger_values,
            colormap_for(self._color_scale),
            color_limits(self._color_scale, result.volume),
            self._quantity_title(),
        )
        renderer.set_labels_visible(self._labels_visible)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        """Re-render after layout changes (fixes blank canvas until first move)."""
        super().resizeEvent(event)
        if self._renderer is not None:
            QTimer.singleShot(0, self._renderer.render)

