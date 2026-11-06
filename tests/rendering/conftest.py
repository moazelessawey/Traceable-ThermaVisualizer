"""Shared fake renderer for headless rendering tests."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest
from pathlib import Path
from PySide6.QtWidgets import QWidget

from thermavisualizer.core.models import Layer, Obstacle, Space
from thermavisualizer.core.slicing import SliceData
from thermavisualizer.rendering.scene import ObstacleStyle, PresetView, SceneRenderer


class FakeSceneRenderer(SceneRenderer):
    """Records every call; renders nothing."""

    def __init__(self) -> None:
        self._widget = QWidget()
        self.space_calls: list[Space] = []
        self.logger_calls: list[tuple[int, str | None]] = []
        self.obstacle_calls: list[tuple[int, ObstacleStyle]] = []
        self.marker_calls: list[tuple[int, int]] = []  # (positions, values count; -1 = None)
        self.marker_titles: list[str] = []
        self.slice_calls: list[tuple[str, float, tuple[float, float] | None]] = []
        self.removed_slices: list[str] = []
        self.clear_slices_calls = 0
        self.labels_calls: list[bool] = []
        self.axes_calls: list[bool] = []
        self.preset_calls: list[PresetView] = []
        self.reset_calls = 0
        self.shutdown_calls = 0
        self.space_visible_calls: list[bool] = []
        self.screenshot_calls: list[str] = []
        self.colorbar_calls: list[bool] = []
        self.camera_calls: list[dict | None] = []
        self.render_calls = 0

    def widget(self) -> QWidget:
        return self._widget

    def set_space(self, space: Space) -> None:
        self.space_calls.append(space)

    def set_loggers(self, layers: Sequence[Layer], selected_logger_id: str | None) -> None:
        self.logger_calls.append((sum(len(layer.loggers) for layer in layers), selected_logger_id))

    def set_obstacles(self, obstacles: Sequence[Obstacle], style: ObstacleStyle) -> None:
        self.obstacle_calls.append((len(obstacles), style))

    def set_logger_scalars(
        self, positions, logger_ids, values, colormap, clim, scalar_title=""
    ) -> None:
        self.marker_calls.append((positions.shape[0], -1 if values is None else values.size))
        self.marker_titles.append(scalar_title)

    def set_labels_visible(self, visible: bool) -> None:
        self.labels_calls.append(visible)

    def show_slice(self, key, slice_data, colormap, clim, opacity, scalar_title="") -> None:
        self.slice_calls.append((key, opacity, clim))

    def remove_slice(self, key: str) -> None:
        self.removed_slices.append(key)

    def clear_slices(self) -> None:
        self.clear_slices_calls += 1

    def set_axes_visible(self, visible: bool) -> None:
        self.axes_calls.append(visible)

    def set_space_visible(self, visible: bool) -> None:
        self.space_visible_calls.append(visible)

    def save_screenshot(self, path) -> None:
        from pathlib import Path

        Path(path).write_bytes(b"FAKE-IMAGE")
        self.screenshot_calls.append(str(path))

    def preset_view(self, view: PresetView) -> None:
        self.preset_calls.append(view)

    def reset_camera(self) -> None:
        self.reset_calls += 1

    def save_screenshot(self, path, scale: int = 1) -> None:
        Path(path).write_bytes(b"FAKE-IMAGE")
        self.screenshot_calls.append(str(path))

    def set_colorbar_visible(self, visible: bool) -> None:
        self.colorbar_calls.append(visible)

    def camera_state(self) -> dict | None:
        return {"position": [0.0, 0.0, 5.0], "focal_point": [0.0, 0.0, 0.0], "up": [0.0, 0.0, 1.0]}

    def set_camera_state(self, state) -> None:
        self.camera_calls.append(state)

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def render(self) -> None:
        self.render_calls += 1

@pytest.fixture
def fake_renderer() -> FakeSceneRenderer:
    return FakeSceneRenderer()
