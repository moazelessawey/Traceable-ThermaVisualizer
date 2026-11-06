"""TimelinePanel: slider/transport bound to model state (PRD 4.4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from thermavisualizer.core.models import (
    ImportProfile,
    Layer,
    Logger,
    LoggerMapping,
    Quantity,
    TimelineMode,
)
from thermavisualizer.core.validation import validate_path
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.timeline import TimelineController
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.services.workers import FileLoadResult
from thermavisualizer.ui.widgets.timeline import TimelinePanel

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def timeline_model(qtbot: QtBot, tmp_path: Path) -> ProjectModel:
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
    return model


@pytest.fixture
def panel(qtbot: QtBot, timeline_model: ProjectModel) -> TimelinePanel:
    controller = TimelineController(timeline_model)
    widget = TimelinePanel(timeline_model, controller)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_slider_bounds_and_labels(panel: TimelinePanel, timeline_model: ProjectModel) -> None:
    assert panel.slider.maximum == 5
    assert panel.start_label.text() == "2024-03-01T08:00"
    assert panel.end_label.text() == "2024-03-01T08:05"
    assert panel.duration_label.text() == "5m"


def test_slider_range_drives_model(panel: TimelinePanel, timeline_model: ProjectModel) -> None:
    dataset = timeline_model.aligned_dataset(Quantity.TEMPERATURE)
    assert dataset is not None
    panel.slider.set_range(1, 3)
    assert timeline_model.timeline_range() == (dataset.times[1], dataset.times[3])


def test_model_range_drives_slider(panel: TimelinePanel, timeline_model: ProjectModel) -> None:
    dataset = timeline_model.aligned_dataset(Quantity.TEMPERATURE)
    assert dataset is not None
    timeline_model.set_timeline_range(dataset.times[2], dataset.times[4])
    assert panel.slider.selected_range() == (2, 4)


def test_playhead_sync_and_visibility(panel: TimelinePanel, timeline_model: ProjectModel) -> None:
    dataset = timeline_model.aligned_dataset(Quantity.TEMPERATURE)
    assert dataset is not None
    timeline_model.set_playhead(dataset.times[3])
    assert panel.slider.playhead == 3
    assert not panel.slider.playhead_is_visible()  # aggregate mode, not playing
    timeline_model.set_timeline_mode(TimelineMode.INSTANT)
    assert panel.slider.playhead_is_visible()


def test_play_button_toggles_controller(
    panel: TimelinePanel, timeline_model: ProjectModel, qtbot: QtBot
) -> None:
    qtbot.mouseClick(panel.play_button, Qt.MouseButton.LeftButton)
    assert panel.controller.is_playing()
    qtbot.mouseClick(panel.play_button, Qt.MouseButton.LeftButton)
    assert not panel.controller.is_playing()


def test_full_range_and_zoom(
    panel: TimelinePanel, timeline_model: ProjectModel, qtbot: QtBot
) -> None:
    panel.slider.set_range(1, 3)
    qtbot.mouseClick(panel.zoom_button, Qt.MouseButton.LeftButton)
    assert (panel.slider.minimum, panel.slider.maximum) == (1, 3)
    qtbot.mouseClick(panel.full_range_button, Qt.MouseButton.LeftButton)
    assert (panel.slider.minimum, panel.slider.maximum) == (0, 5)
    assert panel.slider.selected_range() == (0, 5)


def test_mode_combo_updates_model(panel: TimelinePanel, timeline_model: ProjectModel) -> None:
    panel.mode_combo.setCurrentIndex(1)
    assert timeline_model.timeline_mode() is TimelineMode.INSTANT


def test_disabled_without_data(qtbot: QtBot, tmp_path: Path) -> None:
    model = ProjectModel(user_name="t", profiles_path=tmp_path / "x.json")
    controller = TimelineController(model)
    widget = TimelinePanel(model, controller)
    qtbot.addWidget(widget)
    assert not widget.play_button.isEnabled()
    assert not widget.slider.isEnabled()
