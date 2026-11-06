"""ProjectModel timeline, criteria, and results state (M4-B)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from thermavisualizer.core.models import (
    ImportProfile,
    Layer,
    Logger,
    LoggerMapping,
    Quantity,
)
from thermavisualizer.core.results import AcceptanceCriteria, StudyPeriod
from thermavisualizer.core.validation import validate_path
from thermavisualizer.services.audit import AuditAction
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.services.workers import FileLoadResult

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def timeline_model(qtbot: QtBot, tmp_path: Path) -> ProjectModel:
    model = ProjectModel(user_name="tester", profiles_path=tmp_path / "profiles.json")
    layer = Layer(name="low", height=0.4)
    model.apply(AddLayerCommand(model, layer))
    model.apply(
        AddLoggersCommand(
            model,
            layer.layer_id,
            [Logger("T1", 0.2, 0.2, 0.4), Logger("T2", 0.8, 0.8, 0.4)],
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


def test_timeline_range_and_invalidation(timeline_model: ProjectModel, qtbot: QtBot) -> None:
    dataset = timeline_model.aligned_dataset(Quantity.TEMPERATURE)
    assert dataset is not None
    start, end = dataset.times[1], dataset.times[4]
    with qtbot.waitSignal(timeline_model.timeline_changed, timeout=500):
        timeline_model.set_timeline_range(start, end)
    assert timeline_model.timeline_range() == (start, end)


def test_playhead_emits_signal(timeline_model: ProjectModel, qtbot: QtBot) -> None:
    dataset = timeline_model.aligned_dataset(Quantity.TEMPERATURE)
    assert dataset is not None
    with qtbot.waitSignal(timeline_model.playhead_changed, timeout=500) as blocker:
        timeline_model.set_playhead(dataset.times[2])
    assert blocker.args == [dataset.times[2]]


def test_criteria_change_audits_and_invalidates_results(
    timeline_model: ProjectModel, qtbot: QtBot
) -> None:  # RES-01 + AUD-03
    timeline_model.run_results_evaluation()
    assert timeline_model.study_results() is not None
    new_criteria = AcceptanceCriteria(name="Strict", temperature_min=20.0, temperature_max=21.0)
    with qtbot.waitSignal(timeline_model.criteria_changed, timeout=500):
        timeline_model.set_criteria(new_criteria)
    assert timeline_model.study_results() is None  # invalidated (RES-08)
    assert any(
        entry.action is AuditAction.CRITERIA_CHANGED and "Strict" in entry.summary
        for entry in timeline_model.audit.entries
    )


def test_run_results_evaluation_derives_from_aligned_data(
    timeline_model: ProjectModel, qtbot: QtBot
) -> None:  # RES-08
    criteria = AcceptanceCriteria(name="Wide", temperature_min=15.0, temperature_max=25.0)
    timeline_model.set_criteria(criteria)
    with qtbot.waitSignal(timeline_model.results_changed, timeout=500):
        results = timeline_model.run_results_evaluation()
    assert results.overall.passed is True
    assert results.criteria is criteria
    assert timeline_model.study_results() is results
    assert any(
        entry.action is AuditAction.RESULTS_EVALUATED and "PASS" in entry.summary
        for entry in timeline_model.audit.entries
    )


def test_results_evaluation_uses_timeline_range(timeline_model: ProjectModel) -> None:  # RES-02
    dataset = timeline_model.aligned_dataset(Quantity.TEMPERATURE)
    assert dataset is not None
    timeline_model.set_timeline_range(dataset.times[2], dataset.times[4])
    results = timeline_model.run_results_evaluation()
    assert results.period_start == dataset.times[2]
    assert results.period_end == dataset.times[4]


def test_study_periods_management(timeline_model: ProjectModel, qtbot: QtBot) -> None:
    dataset = timeline_model.aligned_dataset(Quantity.TEMPERATURE)
    assert dataset is not None
    period = StudyPeriod("Door Open", dataset.times[1], dataset.times[3])
    with qtbot.waitSignal(timeline_model.study_periods_changed, timeout=500):
        timeline_model.add_study_period(period)
    assert timeline_model.study_periods() == [period]
    timeline_model.remove_study_period("Door Open")
    assert timeline_model.study_periods() == []


def test_criteria_presets_persist(tmp_path: Path, qtbot: QtBot) -> None:  # RES-01
    store = tmp_path / "profiles.json"
    model_a = ProjectModel(user_name="t", profiles_path=store)
    custom = AcceptanceCriteria(name="Freezer", temperature_min=-20.0, temperature_max=-10.0)
    model_a.save_criteria_preset(custom)
    model_b = ProjectModel(user_name="t", profiles_path=store)
    assert any(p.name == "Freezer" for p in model_b.criteria_presets())
