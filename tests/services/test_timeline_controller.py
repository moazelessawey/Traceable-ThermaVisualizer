"""TimelineController playback tests (PRD 4.4, EXP-01 foundation)."""

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
from thermavisualizer.services.timeline import TimelineController
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.services.workers import FileLoadResult

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
            [
                Logger("T1", 0.2, 0.2, 0.4),
                Logger("T2", 0.8, 0.2, 0.4),
                Logger("T3", 0.2, 0.8, 0.4),
                Logger("X1", 0.6, 0.6, 1.0),
            ],
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
            LoggerMapping(logger_id="T3", temperature_file=parsed.path, temperature_column="T3"),
            LoggerMapping(logger_id="X1", excluded=True),
        ]
    )
    model.align(Quantity.TEMPERATURE)
    return model


def test_times_and_default_range(timeline_model: ProjectModel) -> None:
    controller = TimelineController(timeline_model)
    times = controller.times()
    assert times is not None and times.size == 6
    assert controller.range_indices() == (0, 5)
    assert controller.playhead_index() == 0


def test_play_and_pause_smoke(timeline_model: ProjectModel, qtbot: QtBot) -> None:
    controller = TimelineController(timeline_model)
    with qtbot.waitSignal(controller.playback_started, timeout=500):
        controller.play()
    assert controller.is_playing()
    times = controller.times()
    assert times is not None
    qtbot.waitUntil(
        lambda: timeline_model.playhead() is not None and timeline_model.playhead() > times[0],
        timeout=3000,
    )
    with qtbot.waitSignal(controller.playback_paused, timeout=500):
        controller.pause()
    assert not controller.is_playing()


def test_tick_wraps_with_loop(timeline_model: ProjectModel) -> None:
    controller = TimelineController(timeline_model)
    times = controller.times()
    assert times is not None
    timeline_model.set_playhead(times[5])
    controller.set_loop(True)
    controller._tick()
    assert timeline_model.playhead() == times[0]


def test_tick_stops_at_end_without_loop(timeline_model: ProjectModel) -> None:
    controller = TimelineController(timeline_model)
    times = controller.times()
    assert times is not None
    timeline_model.set_playhead(times[4])
    controller.set_loop(False)
    controller._tick()
    assert timeline_model.playhead() == times[5]
    controller._tick()
    assert not controller.is_playing()
    assert timeline_model.playhead() == times[5]


def test_play_at_end_restarts_without_loop(timeline_model: ProjectModel) -> None:
    controller = TimelineController(timeline_model)
    times = controller.times()
    assert times is not None
    timeline_model.set_playhead(times[5])
    controller.set_loop(False)
    controller.play()
    assert timeline_model.playhead() == times[0]
    controller.pause()


def test_step_forward_backward_and_clamp(timeline_model: ProjectModel) -> None:
    controller = TimelineController(timeline_model)
    times = controller.times()
    assert times is not None
    timeline_model.set_playhead(times[0])
    controller.step_forward()
    assert timeline_model.playhead() == times[1]
    controller.step_backward()
    assert timeline_model.playhead() == times[0]
    controller.step_backward()  # clamps at the range start
    assert timeline_model.playhead() == times[0]


def test_steps_respect_selected_range(timeline_model: ProjectModel) -> None:
    controller = TimelineController(timeline_model)
    times = controller.times()
    assert times is not None
    timeline_model.set_timeline_range(times[2], times[4])
    timeline_model.set_playhead(times[4])
    controller.step_forward()
    assert timeline_model.playhead() == times[4]


def test_snap_full_range(timeline_model: ProjectModel) -> None:
    controller = TimelineController(timeline_model)
    times = controller.times()
    assert times is not None
    timeline_model.set_timeline_range(times[1], times[3])
    controller.snap_full_range()
    assert timeline_model.timeline_range() == (times[0], times[-1])
    assert timeline_model.playhead() == times[0]


def test_speed_validation(timeline_model: ProjectModel) -> None:
    controller = TimelineController(timeline_model)
    with pytest.raises(ValueError):
        controller.set_speed(0.0)
    controller.set_speed(2.0)
    assert controller.speed() == 2.0


def test_play_without_data_is_noop(qtbot: QtBot, tmp_path: Path) -> None:
    model = ProjectModel(user_name="t", profiles_path=tmp_path / "x.json")
    controller = TimelineController(model)
    controller.play()
    assert not controller.is_playing()


def test_play_switches_aggregate_mode_to_instant(timeline_model: ProjectModel) -> None:
    from thermavisualizer.core.models import TimelineMode

    controller = TimelineController(timeline_model)
    timeline_model.set_timeline_mode(TimelineMode.AGGREGATE)
    controller.play()
    assert timeline_model.timeline_mode() is TimelineMode.INSTANT  # EXP-01 semantics
    controller.pause()
