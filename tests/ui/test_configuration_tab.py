"""Configuration tab: mode toolbar, mini stack view, logger table."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from thermavisualizer.core.models import Layer, Logger
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.ui.tabs.configuration import ConfigurationTab
from thermavisualizer.ui.widgets.layer_editor import EditorMode


@pytest.fixture
def tab(qtbot: QtBot, project_model: ProjectModel) -> ConfigurationTab:
    widget = ConfigurationTab(project_model)
    qtbot.addWidget(widget)
    widget.resize(900, 620)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def _setup_layer(model: ProjectModel) -> str:
    layer = Layer(name="low", height=0.5)
    model.apply(AddLayerCommand(model, layer))
    model.apply(
        AddLoggersCommand(
            model,
            layer.layer_id,
            [Logger("L1", 0.1, 0.2, 0.5), Logger("L2", 0.9, 0.8, 0.5)],
        )
    )
    return layer.layer_id


def test_mode_buttons_drive_editor(tab: ConfigurationTab, qtbot: QtBot) -> None:
    qtbot.mouseClick(tab.add_logger_button, Qt.MouseButton.LeftButton)
    assert tab.editor.mode() is EditorMode.ADD_LOGGER
    qtbot.mouseClick(tab.select_button, Qt.MouseButton.LeftButton)
    assert tab.editor.mode() is EditorMode.SELECT


def test_snap_spin_drives_editor(tab: ConfigurationTab) -> None:
    tab.snap_spin.setValue(0.25)
    assert tab.editor.snap_step() == pytest.approx(0.25)


def test_table_shows_active_layer_loggers(
    tab: ConfigurationTab, project_model: ProjectModel
) -> None:
    _setup_layer(project_model)
    assert tab.table.rowCount() == 2
    assert tab.table.item(0, 0).text() == "L1"


def test_table_edit_updates_model_and_undoes(
    tab: ConfigurationTab, project_model: ProjectModel, qtbot: QtBot
) -> None:
    layer_id = _setup_layer(project_model)
    tab.table.item(0, 1).setText("0.75")  # setText emits itemChanged
    assert project_model.logger_by_id(layer_id, "L1").x == pytest.approx(0.75)
    project_model.undo()
    assert project_model.logger_by_id(layer_id, "L1").x == pytest.approx(0.1)


def test_table_invalid_number_rejected(
    tab: ConfigurationTab, project_model: ProjectModel, qtbot: QtBot
) -> None:
    layer_id = _setup_layer(project_model)
    with qtbot.waitSignal(tab.table.edit_rejected, timeout=500):
        tab.table.item(0, 1).setText("abc")
    assert project_model.logger_by_id(layer_id, "L1").x == pytest.approx(0.1)


def test_table_role_combo_updates_model(tab: ConfigurationTab, project_model: ProjectModel) -> None:
    layer_id = _setup_layer(project_model)
    combo = tab.table.cellWidget(0, 4)
    combo.setCurrentText("corner")
    from thermavisualizer.core.models import LoggerRole

    assert project_model.logger_by_id(layer_id, "L1").role is LoggerRole.CORNER


def test_mini_stack_click_activates_layer(
    tab: ConfigurationTab, project_model: ProjectModel, qtbot: QtBot
) -> None:
    first = Layer(name="low", height=0.5)
    second = Layer(name="high", height=1.5)
    project_model.apply(AddLayerCommand(project_model, first))
    project_model.apply(AddLayerCommand(project_model, second))
    rect = tab.mini_view.layer_rect(0)
    qtbot.mouseClick(tab.mini_view, Qt.MouseButton.LeftButton, pos=rect.center().toPoint())
    assert project_model.active_layer_id() == first.layer_id


def test_preview_exists_and_toggle_controls_visibility(tab: ConfigurationTab, qtbot: QtBot) -> None:
    assert tab.preview.isVisible()
    qtbot.mouseClick(tab.preview_toggle, Qt.MouseButton.LeftButton)
    assert not tab.preview.isVisible()
    qtbot.mouseClick(tab.preview_toggle, Qt.MouseButton.LeftButton)
    assert tab.preview.isVisible()
