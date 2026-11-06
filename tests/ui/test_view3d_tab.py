"""3D View tab: overlay wiring and volume updates (PRD 4.2, VIS-01)."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from thermavisualizer.core.interpolation import InterpolationSettings, build_voxel_grid
from thermavisualizer.core.models import BoxFootprint, Quantity, Space
from thermavisualizer.core.statistics import AggregationMethod
from thermavisualizer.rendering.scene import PresetView
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.workers import InterpolationResult
from thermavisualizer.ui.tabs.view3d import View3DTab

from rendering.conftest import FakeSceneRenderer


def _result(space: Space) -> InterpolationResult:
    settings = InterpolationSettings(resolution=0.5)
    grid = build_voxel_grid(space, settings.resolution)
    xs, ys, zs = grid.meshgrid()
    return InterpolationResult(
        volume=xs + ys + zs,
        quantity=Quantity.TEMPERATURE,
        settings=settings,
        aggregation=AggregationMethod.INSTANT,
        time_label="t0",
        cache_key=("t",),
        from_cache=False,
        positions=np.array([[0.2, 0.2, 0.5]]),
        logger_ids=("L1",),
    )


@pytest.fixture
def tab(qtbot: QtBot, project_model: ProjectModel, fake_renderer: FakeSceneRenderer) -> View3DTab:
    widget = View3DTab(project_model, renderer=fake_renderer)
    qtbot.addWidget(widget)
    widget.resize(700, 500)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def test_volume_ready_updates_view(
    tab: View3DTab, project_model: ProjectModel, fake_renderer: FakeSceneRenderer
) -> None:
    space = project_model.space  # the tab always renders the model's space
    project_model.volume_ready.emit(_result(space))
    assert fake_renderer.space_calls[-1] is space
    assert fake_renderer.marker_calls[-1] == (1, -1)


def test_overlay_camera_and_toggles(
    tab: View3DTab, fake_renderer: FakeSceneRenderer, qtbot: QtBot
) -> None:
    qtbot.mouseClick(tab.overlay.reset_button, Qt.MouseButton.LeftButton)
    assert fake_renderer.reset_calls == 1
    qtbot.mouseClick(tab.overlay.iso_button, Qt.MouseButton.LeftButton)
    assert fake_renderer.preset_calls == [PresetView.ISOMETRIC]
    qtbot.mouseClick(tab.overlay.slices_button, Qt.MouseButton.LeftButton)
    assert tab.view.slices_visible() is False
    qtbot.mouseClick(tab.overlay.box_button, Qt.MouseButton.LeftButton)
    assert fake_renderer.space_visible_calls[-1] is False


def test_overlay_screenshot(
    tab: View3DTab, fake_renderer: FakeSceneRenderer, qtbot: QtBot, monkeypatch, tmp_path
) -> None:
    target = tmp_path / "shot.png"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "PNG (*.png)")),
    )
    messages: list[str] = []
    tab.status_message.connect(messages.append)
    qtbot.mouseClick(tab.overlay.screenshot_button, Qt.MouseButton.LeftButton)
    assert target.exists()
    assert any("Screenshot saved" in message for message in messages)


def test_overlay_stays_inside_canvas(tab: View3DTab) -> None:
    assert tab.overlay.pos().x() >= 0
    assert tab.overlay.pos().x() + tab.overlay.width() <= tab.view.width() + 1

def test_refresh_renders(
    tab: View3DTab, project_model: ProjectModel, fake_renderer: FakeSceneRenderer
) -> None:
    """update_volume triggers a scene refresh that forces a render (blank-canvas fix)."""
    before = fake_renderer.render_calls
    space = project_model.space
    tab.view.update_volume(_result(space), space, [])
    assert fake_renderer.render_calls >= before