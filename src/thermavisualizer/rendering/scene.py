"""SceneRenderer abstraction (PRD section 3, AGENTS architecture rule).

Everything outside ``rendering/`` talks to this interface only; the PyVista
implementation lives in ``pyvista_backend.py``. Units: metres; scalar values
in °C or %RH depending on quantity.
"""

from __future__ import annotations

import abc
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QWidget

from thermavisualizer.core.models import Layer, Obstacle, Space
from thermavisualizer.core.slicing import SliceData


class ObstacleStyle(StrEnum):
    """Obstacle render style (OBS-03)."""

    SOLID = "solid"
    TRANSPARENT = "transparent"
    WIREFRAME = "wireframe"


class PresetView(StrEnum):
    """Camera preset views (VIS-01)."""

    TOP = "top"
    FRONT = "front"
    SIDE = "side"
    ISOMETRIC = "isometric"


class SceneRenderer(abc.ABC):
    """Backend-agnostic 3D scene used by previews, the 3D View tab, and exports."""

    @abc.abstractmethod
    def widget(self) -> QWidget:
        """Return the embeddable Qt widget showing the scene."""

    @abc.abstractmethod
    def set_space(self, space: Space) -> None:
        """Draw the footprint outline extruded to the space height (VIS-02)."""

    @abc.abstractmethod
    def set_loggers(self, layers: Sequence[Layer], selected_logger_id: str | None) -> None:
        """Draw logger markers for all layers, highlighting the selection."""

    @abc.abstractmethod
    def set_obstacles(self, obstacles: Sequence[Obstacle], style: ObstacleStyle) -> None:
        """Draw the given obstacles in the given render style (OBS-03)."""

    @abc.abstractmethod
    def set_logger_scalars(
        self,
        positions: np.ndarray,
        logger_ids: Sequence[str],
        values: np.ndarray | None,
        colormap: str | Sequence[str],
        clim: tuple[float, float] | None,
        scalar_title: str = "",
    ) -> None:
        """Render logger markers colored by ``values`` (VIS-03).

        ``values`` is None for neutral markers; one value per position. Units
        match the quantity (°C / %RH).
        """

    @abc.abstractmethod
    def set_labels_visible(self, visible: bool) -> None:
        """Show/hide logger ID labels (VIS-03 optional labels)."""

    @abc.abstractmethod
    def show_slice(
        self,
        key: str,
        slice_data: SliceData,
        colormap: str | Sequence[str],
        clim: tuple[float, float] | None,
        opacity: float,
        scalar_title: str = "",
    ) -> None:
        """Show one color-mapped slice surface, replacing ``key`` (SLC-01/02)."""

    @abc.abstractmethod
    def remove_slice(self, key: str) -> None:
        """Remove the slice surface stored under ``key``."""

    @abc.abstractmethod
    def clear_slices(self) -> None:
        """Remove all slice surfaces."""

    @abc.abstractmethod
    def set_axes_visible(self, visible: bool) -> None:
        """Show/hide axes with dimension labels (VIS-02)."""

    @abc.abstractmethod
    def preset_view(self, view: PresetView) -> None:
        """Apply a preset camera view (VIS-01)."""

    @abc.abstractmethod
    def reset_camera(self) -> None:
        """Reset the camera to fit the scene."""

    @abc.abstractmethod
    def shutdown(self) -> None:
        """Release backend resources (safe to call once)."""

    @abc.abstractmethod
    def set_space_visible(self, visible: bool) -> None:
        """Show/hide the space outline (VIS-02 overlay toggle)."""

    @abc.abstractmethod
    def save_screenshot(self, path: Path, scale: int = 1) -> None:
        """Save the current view as an image (EXP-03), optionally upscaled."""

    @abc.abstractmethod
    def set_colorbar_visible(self, visible: bool) -> None:
        """Show/hide the scalar color bar (VIS-04; movie burn-in option)."""

    @abc.abstractmethod
    def camera_state(self) -> dict | None:
        """Serializable camera pose (position/focal_point/up), metres."""

    @abc.abstractmethod
    def set_camera_state(self, state: dict | None) -> None:
        """Restore a camera pose from ``camera_state``."""
    @abc.abstractmethod
    def render(self) -> None:
        """Force a frame render (kick-starts native canvases after layout changes)."""
