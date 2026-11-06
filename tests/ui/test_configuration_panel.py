"""Configuration panel flows (CFG-01/02/04/06, OBS-02, BLK-03, CFG-11)."""

from __future__ import annotations

import pytest

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog
from pytestqt.qtbot import QtBot

from thermavisualizer.core.models import (
    Layer,
    Logger,
    Obstacle,
    ObstacleShape,
    ObstacleType,
    PolygonFootprint,
    SpaceType,
    BoxFootprint,
)
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand, AddObstacleCommand
from thermavisualizer.ui.panels.configuration_dialogs import LayerDialog, ObstacleDialog
from thermavisualizer.ui.panels.configuration_panel import ConfigurationPanel
from thermavisualizer.services.audit import AuditAction
from thermavisualizer.io.layout_io import LayoutIOError  # noqa: F401  (kept for clarity)
from thermavisualizer.ui.panels.layout_import_dialog import LayoutImportDialog


DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def panel(qtbot: QtBot, project_model: ProjectModel) -> ConfigurationPanel:
    widget = ConfigurationPanel(project_model)
    qtbot.addWidget(widget)
    widget.resize(320, 900)
    widget.show()
    return widget


def _accept_layer_dialog(monkeypatch, name: str, height: float) -> None:
    def fake_exec(dialog: LayerDialog) -> int:
        dialog.name_edit.setText(name)
        dialog.height_spin.setValue(height)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LayerDialog, "exec", fake_exec)


def test_space_name_edit(panel: ConfigurationPanel, project_model: ProjectModel) -> None:
    panel.space_name_edit.setText("WH-01")
    panel.space_name_edit.editingFinished.emit()
    assert project_model.space.name == "WH-01"
    project_model.undo()
    assert project_model.space.name == "Space"


def test_space_type_and_height(panel: ConfigurationPanel, project_model: ProjectModel) -> None:
    panel.space_type_combo.setCurrentIndex(list(SpaceType).index(SpaceType.CHAMBER))
    assert project_model.space.space_type is SpaceType.CHAMBER
    panel.space_height_spin.setValue(2.5)
    panel.space_height_spin.editingFinished.emit()
    assert project_model.space.height == pytest.approx(2.5)


def test_add_layer_via_dialog(
    panel: ConfigurationPanel, project_model: ProjectModel, qtbot: QtBot, monkeypatch
) -> None:
    _accept_layer_dialog(monkeypatch, "Middle", 1.25)
    qtbot.mouseClick(panel.add_layer_button, Qt.MouseButton.LeftButton)
    assert [layer.name for layer in project_model.space.layers] == ["Middle"]
    assert project_model.space.layers[0].height == pytest.approx(1.25)


def test_layer_buttons(
    panel: ConfigurationPanel, project_model: ProjectModel, qtbot: QtBot
) -> None:
    first = Layer(name="first", height=0.5)
    second = Layer(name="second", height=1.5)
    project_model.apply(AddLayerCommand(project_model, first))
    project_model.apply(AddLayerCommand(project_model, second))
    assert panel.layer_list.count() == 2
    panel.layer_list.setCurrentRow(1)
    qtbot.mouseClick(panel.move_up_button, Qt.MouseButton.LeftButton)
    assert [layer.name for layer in project_model.space.layers] == ["second", "first"]
    panel.layer_list.setCurrentRow(0)
    qtbot.mouseClick(panel.complete_button, Qt.MouseButton.LeftButton)
    assert project_model.space.layers[0].completed is True
    qtbot.mouseClick(panel.duplicate_layer_button, Qt.MouseButton.LeftButton)
    assert len(project_model.space.layers) == 3
    assert project_model.space.layers[2].name == "second copy"
    qtbot.mouseClick(panel.remove_layer_button, Qt.MouseButton.LeftButton)
    assert len(project_model.space.layers) == 2


def test_duplicate_layer_copies_loggers_with_unique_ids(
    panel: ConfigurationPanel, project_model: ProjectModel, qtbot: QtBot
) -> None:
    layer = Layer(name="src", height=0.5)
    project_model.apply(AddLayerCommand(project_model, layer))
    project_model.apply(
        AddLoggersCommand(project_model, layer.layer_id, [Logger("A", 0.1, 0.1, 0.5)])
    )
    panel.layer_list.setCurrentRow(0)
    qtbot.mouseClick(panel.duplicate_layer_button, Qt.MouseButton.LeftButton)
    copy = project_model.space.layers[1]
    assert copy.loggers[0].logger_id == "A_c"
    codes = {issue.code for issue in project_model.layout_issues()}
    assert "duplicate-id" not in codes


def test_box_footprint_edit_and_reject(
    panel: ConfigurationPanel, project_model: ProjectModel, qtbot: QtBot
) -> None:
    panel.box_xmax_spin.setValue(3.0)
    panel.box_xmax_spin.editingFinished.emit()
    assert project_model.space.footprint.x_max == pytest.approx(3.0)
    with qtbot.waitSignal(panel.edit_rejected, timeout=500):
        panel.box_xmax_spin.setValue(-1.0)
        panel.box_xmax_spin.editingFinished.emit()
    assert project_model.space.footprint.x_max == pytest.approx(3.0)


def test_switch_to_polygon(panel: ConfigurationPanel, project_model: ProjectModel) -> None:
    panel.footprint_shape_combo.setCurrentIndex(1)
    footprint = project_model.space.footprint
    assert isinstance(footprint, PolygonFootprint)
    assert len(footprint.vertices) == 4


def test_lattice_generation_single_undo(
    panel: ConfigurationPanel, project_model: ProjectModel, qtbot: QtBot
) -> None:
    project_model.apply(AddLayerCommand(project_model, Layer(name="low", height=0.5)))
    panel.grid_rows_spin.setValue(2)
    panel.grid_columns_spin.setValue(3)
    panel.grid_spacing_x_spin.setValue(0.5)
    panel.grid_spacing_y_spin.setValue(0.5)
    qtbot.mouseClick(panel.generate_lattice_button, Qt.MouseButton.LeftButton)
    assert len(project_model.space.layers[0].loggers) == 6
    project_model.undo()
    assert project_model.space.layers[0].loggers == []


def test_obstacle_buttons(
    panel: ConfigurationPanel, project_model: ProjectModel, qtbot: QtBot
) -> None:
    obstacle = Obstacle(
        name="rack",
        obstacle_type=ObstacleType.RACK,
        shape=ObstacleShape.BOX,
        x=0.5,
        y=0.5,
        z=0.5,
        size_x=0.8,
        size_y=0.8,
        size_z=1.0,
    )
    project_model.apply(AddObstacleCommand(project_model, obstacle))
    assert panel.obstacle_list.count() == 1
    panel.obstacle_list.setCurrentRow(0)
    qtbot.mouseClick(panel.toggle_obstacle_visible_button, Qt.MouseButton.LeftButton)
    assert project_model.space.obstacles[0].visible is False
    qtbot.mouseClick(panel.duplicate_obstacle_button, Qt.MouseButton.LeftButton)
    assert len(project_model.space.obstacles) == 2
    assert project_model.space.obstacles[1].name == "rack copy"
    panel.obstacle_list.setCurrentRow(1)
    qtbot.mouseClick(panel.remove_obstacle_button, Qt.MouseButton.LeftButton)
    assert len(project_model.space.obstacles) == 1


def test_add_obstacle_via_dialog(
    panel: ConfigurationPanel, project_model: ProjectModel, qtbot: QtBot, monkeypatch
) -> None:
    def fake_exec(dialog: ObstacleDialog) -> int:
        dialog.name_edit.setText("door")
        dialog.type_combo.setCurrentIndex(list(ObstacleType).index(ObstacleType.DOOR))
        dialog.x_spin.setValue(0.9)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ObstacleDialog, "exec", fake_exec)
    qtbot.mouseClick(panel.add_obstacle_button, Qt.MouseButton.LeftButton)
    assert project_model.space.obstacles[0].name == "door"
    assert project_model.space.obstacles[0].x == pytest.approx(0.9)


def test_validation_list_shows_issues(
    panel: ConfigurationPanel, project_model: ProjectModel
) -> None:
    layer = Layer(name="low", height=0.5)
    project_model.apply(AddLayerCommand(project_model, layer))
    project_model.apply(
        AddLoggersCommand(
            project_model, layer.layer_id, [Logger("A", 0.2, 0.2, 0.5), Logger("B", 0.8, 0.2, 0.5)]
        )
    )
    texts = [panel.issues_list.item(i).text() for i in range(panel.issues_list.count())]
    assert any("insufficient-loggers" in text or "at least 4" in text for text in texts)
    assert "2 error" in panel.issue_count_label.text() or "error" in panel.issue_count_label.text()


def test_selected_logger_form_edits(panel: ConfigurationPanel, project_model: ProjectModel) -> None:
    layer = Layer(name="low", height=0.5)
    project_model.apply(AddLayerCommand(project_model, layer))
    project_model.apply(
        AddLoggersCommand(project_model, layer.layer_id, [Logger("L1", 0.1, 0.2, 0.5)])
    )
    project_model.select_logger("L1")
    panel.logger_notes_edit.setText("near door")
    panel.logger_notes_edit.editingFinished.emit()
    assert project_model.logger_by_id(layer.layer_id, "L1").notes == "near door"
    panel.logger_x_spin.setValue(0.3)
    panel.logger_x_spin.editingFinished.emit()
    assert project_model.logger_by_id(layer.layer_id, "L1").x == pytest.approx(0.3)


def test_export_layout_writes_file_and_audits(
    panel: ConfigurationPanel,
    project_model: ProjectModel,
    tmp_path: Path,
    qtbot: QtBot,
    monkeypatch,
) -> None:
    layer = Layer(name="low", height=0.5)
    project_model.apply(AddLayerCommand(project_model, layer))
    project_model.apply(
        AddLoggersCommand(project_model, layer.layer_id, [Logger("L1", 0.1, 0.2, 0.5)])
    )
    target = tmp_path / "out.csv"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "CSV (*.csv)")),
    )
    qtbot.mouseClick(panel.export_layout_button, Qt.MouseButton.LeftButton)
    assert target.exists()
    assert target.read_text(encoding="utf-8").splitlines()[0] == "ID,X,Y,Z,Layer,Notes"
    assert AuditAction.EXPORTED in [entry.action for entry in project_model.audit.entries]


def test_import_layout_flow_single_undo(
    panel: ConfigurationPanel,
    project_model: ProjectModel,
    qtbot: QtBot,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(DATA / "layout_valid.csv"), "")),
    )

    def fake_exec(dialog: LayoutImportDialog) -> int:
        assert dialog.finish() is True
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LayoutImportDialog, "exec", fake_exec)
    qtbot.mouseClick(panel.import_layout_button, Qt.MouseButton.LeftButton)
    assert [layer.name for layer in project_model.space.layers] == ["low", "high"]
    assert project_model.undo_stack.count() == 1  # BLK-06
    project_model.undo()
    assert project_model.space.layers == []
    assert AuditAction.FILE_IMPORTED in [entry.action for entry in project_model.audit.entries]


def test_import_footprint_vertices(
    panel: ConfigurationPanel,
    project_model: ProjectModel,
    qtbot: QtBot,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(DATA / "footprint_l_shape.csv"), "")),
    )
    qtbot.mouseClick(panel.import_footprint_button, Qt.MouseButton.LeftButton)
    footprint = project_model.space.footprint
    assert isinstance(footprint, PolygonFootprint)
    assert len(footprint.vertices) == 6


def test_import_footprint_rejects_self_intersection(
    panel: ConfigurationPanel,
    project_model: ProjectModel,
    qtbot: QtBot,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(DATA / "footprint_bowtie.csv"), "")),
    )
    with qtbot.waitSignal(panel.edit_rejected, timeout=500):
        qtbot.mouseClick(panel.import_footprint_button, Qt.MouseButton.LeftButton)
    assert isinstance(project_model.space.footprint, BoxFootprint)
