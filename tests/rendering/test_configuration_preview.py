"""ConfigurationPreview wiring tests with a fake renderer (CFG-10, OBS-03)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

import thermavisualizer.rendering.configuration_preview as preview_module
from thermavisualizer.core.models import (
    Layer,
    Logger,
    Obstacle,
    ObstacleShape,
    ObstacleType,
    Space,
)
from thermavisualizer.rendering.configuration_preview import ConfigurationPreview
from thermavisualizer.rendering.scene import ObstacleStyle, SceneRenderer
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import (
    AddLayerCommand,
    AddLoggersCommand,
    AddObstacleCommand,
    SetObstacleVisibleCommand,
)
from conftest import FakeSceneRenderer  # tests/rendering/conftest.py


@pytest.fixture
def preview(
    qtbot: QtBot, project_model: ProjectModel, fake_renderer: FakeSceneRenderer
) -> ConfigurationPreview:
    widget = ConfigurationPreview(project_model, renderer=fake_renderer)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _obstacle(**overrides: object) -> Obstacle:
    kwargs: dict[str, object] = {
        "name": "rack",
        "obstacle_type": ObstacleType.RACK,
        "shape": ObstacleShape.BOX,
        "x": 1.0,
        "y": 1.0,
        "z": 1.0,
        "size_x": 1.0,
        "size_y": 0.6,
        "size_z": 2.0,
    }
    kwargs.update(overrides)
    return Obstacle(**kwargs)  # type: ignore[arg-type]


def test_initial_refresh(preview: ConfigurationPreview, project_model: ProjectModel) -> None:
    fake = preview.renderer()
    assert isinstance(fake, FakeSceneRenderer)
    assert fake.space_calls[-1] is project_model.space
    assert fake.logger_calls[-1] == (0, None)


def test_logger_updates_reach_renderer(
    preview: ConfigurationPreview, project_model: ProjectModel
) -> None:
    fake = preview.renderer()
    assert isinstance(fake, FakeSceneRenderer)
    layer = Layer(name="low", height=0.5)
    project_model.apply(AddLayerCommand(project_model, layer))
    project_model.apply(
        AddLoggersCommand(project_model, layer.layer_id, [Logger("L1", 0.1, 0.1, 0.5)])
    )
    assert fake.logger_calls[-1][0] == 1


def test_selection_reaches_renderer(
    preview: ConfigurationPreview, project_model: ProjectModel
) -> None:
    fake = preview.renderer()
    assert isinstance(fake, FakeSceneRenderer)
    layer = Layer(name="low", height=0.5)
    project_model.apply(AddLayerCommand(project_model, layer))
    project_model.apply(
        AddLoggersCommand(project_model, layer.layer_id, [Logger("L1", 0.1, 0.1, 0.5)])
    )
    project_model.select_logger("L1")
    assert fake.logger_calls[-1] == (1, "L1")


def test_obstacles_and_style_toggle(
    preview: ConfigurationPreview, project_model: ProjectModel
) -> None:
    fake = preview.renderer()
    assert isinstance(fake, FakeSceneRenderer)
    obstacle = _obstacle()
    project_model.apply(AddObstacleCommand(project_model, obstacle))
    assert fake.obstacle_calls[-1] == (1, ObstacleStyle.SOLID)
    preview.style_combo.setCurrentIndex(list(ObstacleStyle).index(ObstacleStyle.WIREFRAME))
    assert fake.obstacle_calls[-1] == (1, ObstacleStyle.WIREFRAME)


def test_hidden_obstacles_excluded(
    preview: ConfigurationPreview, project_model: ProjectModel
) -> None:
    fake = preview.renderer()
    assert isinstance(fake, FakeSceneRenderer)
    obstacle = _obstacle()
    project_model.apply(AddObstacleCommand(project_model, obstacle))
    project_model.apply(SetObstacleVisibleCommand(project_model, obstacle.obstacle_id, False))
    assert fake.obstacle_calls[-1] == (0, ObstacleStyle.SOLID)


def test_reset_camera_button(preview: ConfigurationPreview, qtbot: QtBot) -> None:
    fake = preview.renderer()
    assert isinstance(fake, FakeSceneRenderer)
    qtbot.mouseClick(preview.reset_camera_button, Qt.MouseButton.LeftButton)
    assert fake.reset_calls == 1


def test_offscreen_platform_shows_placeholder(
    qtbot: QtBot, project_model: ProjectModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    widget = ConfigurationPreview(project_model)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    assert widget.is_active() is False
    assert widget.fallback_label is not None
    assert "offscreen" in widget.fallback_label.text()


def test_missing_backend_shows_placeholder(
    qtbot: QtBot, project_model: ProjectModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(preview_module, "_pyvista_available", lambda: (False, "no pyvista here"))
    widget = ConfigurationPreview(project_model)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    assert widget.is_active() is False
    assert widget.fallback_label is not None
    assert "no pyvista here" in widget.fallback_label.text()
