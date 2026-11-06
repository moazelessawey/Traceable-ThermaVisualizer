"""Mapping editor behavior (DAT-03/04/05)."""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot

from thermavisualizer.core.models import Layer, Logger
from thermavisualizer.core.validation import validate_path
from thermavisualizer.core.models import ImportProfile
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.services.workers import FileLoadResult
from thermavisualizer.ui.widgets.mapping_editor import MappingEditorWidget

DATA = Path(__file__).resolve().parents[1] / "data"


def _setup(model: ProjectModel) -> str:
    layer = Layer(name="low", height=0.5)
    model.apply(AddLayerCommand(model, layer))
    model.apply(
        AddLoggersCommand(model, layer.layer_id, [Logger("T1", 0, 0, 0.5), Logger("T2", 1, 0, 0.5)])
    )
    parsed, report = validate_path(DATA / "data_simple.csv", ImportProfile())
    assert parsed is not None
    model.ingest_load_results(
        [FileLoadResult(str(DATA / "data_simple.csv"), "Default", parsed, report)]
    )
    return parsed.path


def test_editor_lists_loggers_and_files(qtbot: QtBot, project_model: ProjectModel) -> None:
    path = _setup(project_model)
    editor = MappingEditorWidget(project_model)
    qtbot.addWidget(editor)
    assert editor._table.rowCount() == 2
    assert project_model.file_by_path(path) is not None


def test_assigning_a_column_updates_model(qtbot: QtBot, project_model: ProjectModel) -> None:
    path = _setup(project_model)
    editor = MappingEditorWidget(project_model)
    qtbot.addWidget(editor)
    combo = editor._temp_combos["T1"]
    combo.setCurrentText("data_simple.csv :: T1")
    mapping = project_model.mapping_for("T1")
    assert mapping is not None
    assert mapping.temperature_file == path
    assert mapping.temperature_column == "T1"


def test_duplicate_warning_emitted(qtbot: QtBot, project_model: ProjectModel) -> None:
    _setup(project_model)
    editor = MappingEditorWidget(project_model)
    qtbot.addWidget(editor)
    messages: list[str] = []
    editor.duplicate_warning.connect(messages.append)
    editor._temp_combos["T1"].setCurrentText("data_simple.csv :: T1")
    editor._temp_combos["T2"].setCurrentText("data_simple.csv :: T1")
    assert any("Duplicate column mapping" in message for message in messages)
