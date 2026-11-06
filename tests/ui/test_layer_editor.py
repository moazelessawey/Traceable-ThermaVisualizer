"""2D editor interaction tests (CFG-03, CFG-09, GEO-02)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from thermavisualizer.core.models import Layer, Logger, PolygonFootprint
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import (
    AddLayerCommand,
    AddLoggersCommand,
    SetSpacePropertiesCommand,
)
from thermavisualizer.ui.widgets.layer_editor import EditorMode, Layer2DEditor


@pytest.fixture
def editor(qtbot: QtBot, project_model: ProjectModel) -> Layer2DEditor:
    widget = Layer2DEditor(project_model)
    qtbot.addWidget(widget)
    widget.resize(480, 360)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _add_active_layer(model: ProjectModel, name: str = "low", height: float = 0.5) -> str:
    layer = Layer(name=name, height=height)
    model.apply(AddLayerCommand(model, layer))
    return layer.layer_id


def test_add_logger_click(project_model: ProjectModel, editor: Layer2DEditor, qtbot: QtBot) -> None:
    layer_id = _add_active_layer(project_model)
    editor.set_mode(EditorMode.ADD_LOGGER)
    qtbot.mouseClick(
        editor, Qt.MouseButton.LeftButton, pos=editor.world_to_widget(0.5, 0.5).toPoint()
    )
    loggers = project_model.space.layers[0].loggers
    assert len(loggers) == 1
    assert loggers[0].x == pytest.approx(0.5, abs=0.11)
    assert loggers[0].y == pytest.approx(0.5, abs=0.11)
    assert loggers[0].z == 0.5  # layer height
    assert project_model.selected_logger_id() == loggers[0].logger_id


def test_add_logger_without_layer_rejected(
    project_model: ProjectModel, editor: Layer2DEditor, qtbot: QtBot
) -> None:
    editor.set_mode(EditorMode.ADD_LOGGER)
    with qtbot.waitSignal(editor.edit_rejected, timeout=500):
        qtbot.mouseClick(
            editor, Qt.MouseButton.LeftButton, pos=editor.world_to_widget(0.5, 0.5).toPoint()
        )


def test_drag_logger_moves_and_undoes(
    project_model: ProjectModel, editor: Layer2DEditor, qtbot: QtBot
) -> None:
    layer_id = _add_active_layer(project_model)
    project_model.apply(AddLoggersCommand(project_model, layer_id, [Logger("L1", 0.2, 0.2, 0.5)]))
    editor.set_mode(EditorMode.SELECT)
    start = editor.world_to_widget(0.2, 0.2).toPoint()
    target = editor.world_to_widget(0.7, 0.3).toPoint()
    qtbot.mousePress(editor, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(editor, target)
    qtbot.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=target)
    assert project_model.logger_by_id(layer_id, "L1").x == pytest.approx(0.7, abs=0.11)
    assert project_model.logger_by_id(layer_id, "L1").y == pytest.approx(0.3, abs=0.11)
    project_model.undo()
    assert project_model.logger_by_id(layer_id, "L1").x == pytest.approx(0.2, abs=1e-9)


def test_delete_key_removes_selected_logger(
    project_model: ProjectModel, editor: Layer2DEditor, qtbot: QtBot
) -> None:
    layer_id = _add_active_layer(project_model)
    project_model.apply(AddLoggersCommand(project_model, layer_id, [Logger("L1", 0.2, 0.2, 0.5)]))
    project_model.select_logger("L1")
    qtbot.keyClick(editor, Qt.Key.Key_Delete)
    assert project_model.space.layers[0].loggers == []


def _make_square(model: ProjectModel) -> None:
    model.apply(
        SetSpacePropertiesCommand(
            model, footprint=PolygonFootprint(((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)))
        )
    )


def test_footprint_vertex_drag_updates_polygon(
    project_model: ProjectModel, editor: Layer2DEditor, qtbot: QtBot
) -> None:
    _make_square(project_model)
    editor.set_mode(EditorMode.EDIT_FOOTPRINT)
    start = editor.world_to_widget(2.0, 2.0).toPoint()
    target = editor.world_to_widget(2.5, 2.5).toPoint()
    qtbot.mousePress(editor, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(editor, target)
    qtbot.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=target)
    vertex = project_model.space.footprint.vertices[2]
    assert vertex[0] == pytest.approx(2.5, abs=0.11)
    assert vertex[1] == pytest.approx(2.5, abs=0.11)
    project_model.undo()
    assert project_model.space.footprint.vertices[2] == (2.0, 2.0)


def test_self_intersecting_vertex_move_rejected(
    project_model: ProjectModel, editor: Layer2DEditor, qtbot: QtBot
) -> None:
    _make_square(project_model)
    editor.set_mode(EditorMode.EDIT_FOOTPRINT)
    start = editor.world_to_widget(2.0, 2.0).toPoint()
    target = editor.world_to_widget(1.0, -1.0).toPoint()
    with qtbot.waitSignal(editor.edit_rejected, timeout=500):
        qtbot.mousePress(editor, Qt.MouseButton.LeftButton, pos=start)
        qtbot.mouseMove(editor, target)
        qtbot.mouseRelease(editor, Qt.MouseButton.LeftButton, pos=target)
    assert project_model.space.footprint.vertices[2] == (2.0, 2.0)


def test_insert_vertex_on_edge_click(
    project_model: ProjectModel, editor: Layer2DEditor, qtbot: QtBot
) -> None:
    _make_square(project_model)
    editor.set_mode(EditorMode.EDIT_FOOTPRINT)
    qtbot.mouseClick(
        editor, Qt.MouseButton.LeftButton, pos=editor.world_to_widget(1.0, 0.0).toPoint()
    )
    vertices = project_model.space.footprint.vertices
    assert len(vertices) == 5
    assert any(abs(v[0] - 1.0) < 0.11 and abs(v[1]) < 0.11 for v in vertices)


def test_delete_key_removes_selected_vertex(
    project_model: ProjectModel, editor: Layer2DEditor, qtbot: QtBot
) -> None:
    _make_square(project_model)
    editor.set_mode(EditorMode.EDIT_FOOTPRINT)
    qtbot.mouseClick(
        editor, Qt.MouseButton.LeftButton, pos=editor.world_to_widget(2.0, 2.0).toPoint()
    )  # selects vertex
    qtbot.keyClick(editor, Qt.Key.Key_Delete)
    assert len(project_model.space.footprint.vertices) == 3
