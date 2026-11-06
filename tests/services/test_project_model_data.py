"""ProjectModel data state: files, profiles, mapping gate, validation, alignment (M2-D)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from thermavisualizer.core.alignment import AlignmentError
from thermavisualizer.core.models import (
    ImportProfile,
    Layer,
    Logger,
    LoggerMapping,
    Quantity,
)
from thermavisualizer.core.validation import validate_path
from thermavisualizer.services.audit import AuditAction
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.services.workers import FileLoadResult

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def data_model(qtbot: QtBot, tmp_path: Path) -> ProjectModel:
    return ProjectModel(user_name="tester", profiles_path=tmp_path / "profiles.json")


def _ingest_fixture(model: ProjectModel, name: str = "data_simple.csv") -> str:
    path = DATA / name
    parsed, report = validate_path(path, ImportProfile())
    assert parsed is not None
    model.ingest_load_results([FileLoadResult(str(path), "Default", parsed, report)])
    return parsed.path


def test_ingest_adds_files_and_audits(data_model: ProjectModel, qtbot: QtBot) -> None:
    with qtbot.waitSignal(data_model.files_changed, timeout=500):
        path = _ingest_fixture(data_model)
    assert [file.path for file in data_model.files()] == [path]
    assert data_model.validation_report.findings == ()  # clean file, no findings
    assert AuditAction.FILE_IMPORTED in [e.action for e in data_model.audit.entries]


def test_ingest_records_structural_findings(data_model: ProjectModel, tmp_path: Path) -> None:
    bad = tmp_path / "empty.csv"
    bad.write_text("Timestamp,T1\n", encoding="utf-8")
    parsed, report = validate_path(bad, ImportProfile())
    assert parsed is None
    data_model.ingest_load_results([FileLoadResult(str(bad), "Default", None, report)])
    assert "VAL-01" in data_model.validation_report.codes()


def test_load_files_async_end_to_end(data_model: ProjectModel, qtbot: QtBot) -> None:
    worker = data_model.load_files_async([(DATA / "data_simple.csv", ImportProfile())])
    with qtbot.waitSignal(worker.result_ready, timeout=5000):
        pass
    qtbot.waitUntil(lambda: len(data_model.files()) == 1, timeout=3000)
    assert data_model.files()[0].row_count == 6


def test_remove_file_clears_dependent_mappings(data_model: ProjectModel) -> None:
    path = _ingest_fixture(data_model)
    data_model.set_mapping(
        LoggerMapping(logger_id="L1", temperature_file=path, temperature_column="T1")
    )
    data_model.remove_file(path)
    assert data_model.files() == []
    assert data_model.mapping_for("L1") is None


def test_profiles_roundtrip(tmp_path: Path, qtbot: QtBot) -> None:
    store = tmp_path / "profiles.json"
    model_a = ProjectModel(user_name="t", profiles_path=store)
    model_a.save_profile(ImportProfile(name="Euro", delimiter=";", decimal=","))
    model_b = ProjectModel(user_name="t", profiles_path=store)
    assert model_b.import_profiles()["Euro"].delimiter == ";"
    model_b.remove_profile("Euro")
    model_c = ProjectModel(user_name="t", profiles_path=store)
    assert model_c.import_profiles() == {}


def test_mapping_gate(data_model: ProjectModel) -> None:  # DAT-03
    layer = Layer(name="low", height=0.5)
    data_model.apply(AddLayerCommand(data_model, layer))
    data_model.apply(
        AddLoggersCommand(
            data_model,
            layer.layer_id,
            [Logger("A", 0.1, 0.1, 0.5), Logger("B", 0.9, 0.1, 0.5)],
        )
    )
    assert sorted(data_model.unmapped_logger_ids()) == ["A", "B"]
    assert data_model.mapping_complete() is False
    path = _ingest_fixture(data_model)
    data_model.set_mapping(
        LoggerMapping(logger_id="A", temperature_file=path, temperature_column="T1")
    )
    assert data_model.mapping_complete() is False
    data_model.set_mapping(LoggerMapping(logger_id="B", excluded=True))
    assert data_model.mapping_complete() is True
    actions = [entry.action for entry in data_model.audit.entries]
    assert actions.count(AuditAction.MAPPING_CHANGED) == 2


def test_run_validation_reports_and_audits(data_model: ProjectModel, qtbot: QtBot) -> None:
    path = _ingest_fixture(data_model)
    data_model.set_mapping(
        LoggerMapping(logger_id="L1", temperature_file=path, temperature_column="T1")
    )
    with qtbot.waitSignal(data_model.validation_changed, timeout=500):
        report = data_model.run_validation()
    assert "VAL-11" in report.codes()
    assert AuditAction.VALIDATION_RUN in [e.action for e in data_model.audit.entries]


def test_align_temperature_and_humidity(data_model: ProjectModel) -> None:
    path = _ingest_fixture(data_model)
    data_model.set_mappings(
        [
            LoggerMapping(
                logger_id="L1",
                temperature_file=path,
                temperature_column="T1",
                humidity_file=path,
                humidity_column="RH1",
            ),
            LoggerMapping(logger_id="L2", temperature_file=path, temperature_column="T2"),
        ]
    )
    dataset = data_model.align(Quantity.TEMPERATURE)
    assert dataset.logger_ids == ("L1", "L2")
    assert dataset.values.shape[0] == 6
    assert data_model.aligned_dataset(Quantity.TEMPERATURE) is dataset
    humidity = data_model.align(Quantity.HUMIDITY)
    assert humidity.logger_ids == ("L1",)
    assert AuditAction.PROCESSING_CHANGED in [e.action for e in data_model.audit.entries]


def test_align_without_mappings_raises(data_model: ProjectModel) -> None:
    with pytest.raises(AlignmentError):
        data_model.align(Quantity.TEMPERATURE)


def test_aligned_cache_invalidated_by_mapping_change(data_model: ProjectModel) -> None:
    path = _ingest_fixture(data_model)
    data_model.set_mapping(
        LoggerMapping(logger_id="L1", temperature_file=path, temperature_column="T1")
    )
    data_model.align(Quantity.TEMPERATURE)
    data_model.set_mapping(
        LoggerMapping(logger_id="L2", temperature_file=path, temperature_column="T2")
    )
    assert data_model.aligned_dataset(Quantity.TEMPERATURE) is None

def test_align_co_aligns_mapped_humidity(qtbot: QtBot, tmp_path: Path) -> None:
    model = ProjectModel(user_name="tester", profiles_path=tmp_path / "p.json")
    layer = Layer(name="low", height=0.4)
    model.apply(AddLayerCommand(model, layer))
    model.apply(
        AddLoggersCommand(model, layer.layer_id, [Logger("T1", 0.2, 0.2, 0.4)])
    )
    parsed, report = validate_path(DATA / "data_simple.csv", ImportProfile())
    assert parsed is not None
    model.ingest_load_results(
        [FileLoadResult(str(DATA / "data_simple.csv"), "Default", parsed, report)]
    )
    model.set_mappings([
        LoggerMapping(
            logger_id="T1",
            temperature_file=parsed.path, temperature_column="T1",
            humidity_file=parsed.path, humidity_column="RH1",
        ),
    ])
    model.align(Quantity.TEMPERATURE)
    assert model.aligned_dataset(Quantity.TEMPERATURE) is not None
    assert model.aligned_dataset(Quantity.HUMIDITY) is not None  # co-aligned
    