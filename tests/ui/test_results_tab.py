"""Results tab: summary, tables, highlight, export, SLC-07 link (RES-07)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from thermavisualizer.core.models import Quantity
from thermavisualizer.core.results import AcceptanceCriteria, evaluate_dataset
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.ui.tabs.results import ResultsTab


def _seed_results(model: ProjectModel) -> None:
    times = np.datetime64("2024-03-01T08:00", "ns") + np.arange(4) * np.timedelta64(10, "m")
    values = np.array([[5.0, 6.0], [6.0, 7.0], [9.0, 7.5], [5.5, 6.5]])
    criteria = AcceptanceCriteria(name="2-8", temperature_min=2.0, temperature_max=8.0)
    results = evaluate_dataset(times, ("L1", "L2"), values, criteria, Quantity.TEMPERATURE)
    model._study_results = results  # seed directly; model.run_results_evaluation needs alignment
    model.results_changed.emit()


@pytest.fixture
def tab(qtbot: QtBot, tmp_path: Path) -> ResultsTab:
    model = ProjectModel(user_name="tester", profiles_path=tmp_path / "p.json")
    widget = ResultsTab(model)
    qtbot.addWidget(widget)
    widget.show()
    widget._model_ref = model  # keep a handle for the tests
    return widget


def test_empty_state(qtbot: QtBot, tmp_path: Path) -> None:
    model = ProjectModel(user_name="t", profiles_path=tmp_path / "p.json")
    widget = ResultsTab(model)
    qtbot.addWidget(widget)
    assert "No results" in widget.overall_label.text()
    assert widget.logger_table.rowCount() == 0


def test_results_populate_and_highlight(tab: ResultsTab) -> None:
    _seed_results(tab._model_ref)
    assert "FAIL" in tab.overall_label.text()
    assert tab.logger_table.rowCount() == 2
    assert tab.logger_table.item(0, 10).text() == "FAIL"  # L1 has the 9 °C spike
    assert tab.logger_table.item(1, 10).text() == "PASS"  # L2 stays within limits
    assert tab.excursion_table.rowCount() == 1
    assert tab.excursion_table.item(0, 0).text() == "L1"


def test_link_limits_to_3d_emits(tab: ResultsTab, qtbot: QtBot) -> None:  # SLC-07
    _seed_results(tab._model_ref)
    with qtbot.waitSignal(tab.link_limits_to_3d, timeout=500) as blocker:
        tab._on_link_3d()
    assert blocker.args == [2.0, 8.0]
