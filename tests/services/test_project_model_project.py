"""ProjectModel lifecycle: snapshot, reset, modified flag, study (EXP-05, STY-01)."""

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
    Study,
)
from thermavisualizer.core.validation import validate_path
from thermavisualizer.services.audit import AuditAction
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.services.workers import FileLoadResult

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def loaded_model(qtbot: QtBot, tmp_path: Path) -> ProjectModel:
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
    model.mark_saved()
    return model


def test_snapshot_roundtrip_between_models(
    loaded_model: ProjectModel, qtbot: QtBot, tmp_path: Path
) -> None:
    snapshot = loaded_model.build_snapshot({"marker": 1})
    other = ProjectModel(user_name="reviewer", profiles_path=tmp_path / "o.json")
    with qtbot.waitSignal(other.project_loaded, timeout=500):
        other.load_snapshot(snapshot)
    assert other.space.layers[0].name == "low"
    assert len(other.files()) == 1
    assert other.mapping_complete() is True
    assert other.aligned_dataset(Quantity.TEMPERATURE) is not None
    assert other.validation_report is not None
    assert other.is_modified() is False
    assert len(other.audit) == len(loaded_model.audit)
    assert other.audit.verify_chain()
    assert other.audit.user_name == "reviewer"  # current user continues the trail


def test_reset_project_clears_state(loaded_model: ProjectModel, qtbot: QtBot) -> None:
    loaded_model.reset_project()
    assert loaded_model.space.layers == []
    assert loaded_model.files() == []
    assert loaded_model.mappings() == []
    assert loaded_model.aligned_dataset(Quantity.TEMPERATURE) is None
    assert loaded_model.is_modified() is False
    assert AuditAction.PROJECT_CREATE in [e.action for e in loaded_model.audit.entries]


def test_modified_flag_lifecycle(loaded_model: ProjectModel, qtbot: QtBot) -> None:
    assert loaded_model.is_modified() is False
    layer = Layer(name="extra", height=1.0)
    with qtbot.waitSignal(loaded_model.modified_changed, timeout=500):
        loaded_model.apply(AddLayerCommand(loaded_model, layer))
    assert loaded_model.is_modified() is True
    loaded_model.mark_saved()
    assert loaded_model.is_modified() is False


def test_study_metadata_audited(loaded_model: ProjectModel, qtbot: QtBot) -> None:
    with qtbot.waitSignal(loaded_model.study_changed, timeout=500):
        loaded_model.set_study(Study(title="Door open study", protocol_id="PR-9"))
    assert loaded_model.study().title == "Door open study"
    assert AuditAction.STUDY_CHANGED in [e.action for e in loaded_model.audit.entries]
