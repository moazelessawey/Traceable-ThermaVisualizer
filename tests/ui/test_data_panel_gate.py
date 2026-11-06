"""Mapping gate enforcement in the UI (DAT-03, acceptance item 3)."""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot

from thermavisualizer.core.models import ImportProfile, Layer, Logger, LoggerMapping
from thermavisualizer.core.validation import validate_path
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.services.workers import FileLoadResult
from thermavisualizer.ui.panels.data_panel import DataPanel

DATA = Path(__file__).resolve().parents[1] / "data"


def _load_simple(model: ProjectModel) -> str:
    parsed, report = validate_path(DATA / "data_simple.csv", ImportProfile())
    assert parsed is not None
    model.ingest_load_results(
        [FileLoadResult(str(DATA / "data_simple.csv"), "Default", parsed, report)]
    )
    return parsed.path


def test_align_disabled_until_mapping_complete(qtbot: QtBot, project_model: ProjectModel) -> None:
    layer = Layer(name="low", height=0.5)
    project_model.apply(AddLayerCommand(project_model, layer))
    project_model.apply(
        AddLoggersCommand(
            project_model, layer.layer_id, [Logger("L1", 0, 0, 0.5), Logger("L2", 1, 0, 0.5)]
        )
    )
    path = _load_simple(project_model)
    panel = DataPanel(project_model)
    qtbot.addWidget(panel)
    assert panel._align_button.isEnabled() is False

    project_model.set_mapping(
        LoggerMapping(logger_id="L1", temperature_file=path, temperature_column="T1")
    )
    assert panel._align_button.isEnabled() is False  # L2 still unmapped
    project_model.set_mapping(LoggerMapping(logger_id="L2", excluded=True))
    assert panel._align_button.isEnabled() is True


def test_align_refuses_when_incomplete(qtbot: QtBot, project_model: ProjectModel) -> None:
    layer = Layer(name="low", height=0.5)
    project_model.apply(AddLayerCommand(project_model, layer))
    project_model.apply(AddLoggersCommand(project_model, layer.layer_id, [Logger("L1", 0, 0, 0.5)]))
    panel = DataPanel(project_model)
    qtbot.addWidget(panel)
    messages: list[str] = []
    panel.edit_rejected.connect(messages.append)
    panel._on_align()
    assert any("DAT-03" in message for message in messages)
