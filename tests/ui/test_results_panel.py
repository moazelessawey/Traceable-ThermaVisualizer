"""Results panel: criteria editor, presets, evaluation scope (RES-01/02)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from thermavisualizer.core.results import AcceptanceCriteria
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.ui.panels.results_panel import ResultsPanel


@pytest.fixture
def panel(qtbot: QtBot, tmp_path: Path) -> ResultsPanel:
    model = ProjectModel(user_name="tester", profiles_path=tmp_path / "p.json")
    widget = ResultsPanel(model)
    qtbot.addWidget(widget)
    widget.show()
    widget._model_ref = model
    return widget


def test_apply_criteria_updates_model(panel: ResultsPanel) -> None:
    panel.name_edit.setText("Cold chain")
    panel.temp_min_spin.setValue(2.0)
    panel.temp_max_spin.setValue(8.0)
    panel._on_apply()
    criteria = panel._model_ref.criteria()
    assert criteria.name == "Cold chain"
    assert criteria.temperature_max == 8.0


def test_save_and_load_preset(panel: ResultsPanel) -> None:  # RES-01
    panel.name_edit.setText("My preset")
    panel.temp_min_spin.setValue(15.0)
    panel.temp_max_spin.setValue(25.0)
    panel._on_save_preset()
    assert any(p.name == "My preset" for p in panel._model_ref.criteria_presets())
    panel.temp_min_spin.setValue(0.0)
    panel._on_preset_selected(panel.preset_combo.findData("My preset"))
    assert panel.temp_min_spin.value() == 15.0


def test_default_presets_present(panel: ResultsPanel) -> None:  # RES-01 defaults
    names = [panel.preset_combo.itemText(i) for i in range(panel.preset_combo.count())]
    assert any("2-8" in name for name in names)
