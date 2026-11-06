"""Plots panel: series list and options emission (PRD 4.3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from thermavisualizer.core.models import (
    ImportProfile,
    Layer,
    Logger,
    LoggerMapping,
    Quantity,
)
from thermavisualizer.core.validation import validate_path
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.services.workers import FileLoadResult
from thermavisualizer.ui.panels.plots_panel import PlotsPanel
from thermavisualizer.ui.tabs.plots import PlotLayout

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def panel(qtbot: QtBot, tmp_path: Path) -> PlotsPanel:
    model = ProjectModel(user_name="tester", profiles_path=tmp_path / "p.json")
    layer = Layer(name="low", height=0.4)
    model.apply(AddLayerCommand(model, layer))
    model.apply(
        AddLoggersCommand(
            model,
            layer.layer_id,
            [Logger("T1", 0.2, 0.2, 0.4), Logger("T2", 0.8, 0.2, 0.4)],
        )
    )
    parsed, report = validate_path(DATA / "data_simple.csv", ImportProfile())
    assert parsed is not None
    model.ingest_load_results(
        [FileLoadResult(str(DATA / "data_simple.csv"), "Default", parsed, report)]
    )
    model.set_mappings(
        [
            LoggerMapping(logger_id="T1", temperature_file=parsed.path, temperature_column="T1"),
            LoggerMapping(logger_id="T2", temperature_file=parsed.path, temperature_column="T2"),
        ]
    )
    model.align(Quantity.TEMPERATURE)
    widget = PlotsPanel(model)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_series_list_shows_aligned_loggers(panel: PlotsPanel) -> None:
    assert panel.series_list.count() == 2
    assert {panel.series_list.item(i).text() for i in range(2)} == {"T1", "T2"}


def test_options_signal_rewraps_enum(panel: PlotsPanel, qtbot: QtBot) -> None:
    with qtbot.waitSignal(panel.options_changed, timeout=500) as blocker:
        panel.layout_combo.setCurrentIndex(panel.layout_combo.findData(PlotLayout.SEPARATE))
    assert blocker.args[0].layout is PlotLayout.SEPARATE


def test_series_signal_emits_selection(panel: PlotsPanel, qtbot: QtBot) -> None:
    with qtbot.waitSignal(panel.series_changed, timeout=500) as blocker:
        panel.series_list.item(0).setSelected(True)
    assert blocker.args[0] == ("T1",)
