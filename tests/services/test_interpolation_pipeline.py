"""End-to-end interpolation pipeline through ProjectModel (INT-07/09, AUD-03)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from thermavisualizer.core.alignment import AlignmentError
from thermavisualizer.core.interpolation import InterpolationSettings
from thermavisualizer.core.models import (
    ImportProfile,
    Layer,
    Logger,
    LoggerMapping,
    Quantity,
)
from thermavisualizer.core.statistics import AggregationMethod
from thermavisualizer.core.validation import validate_path
from thermavisualizer.services.audit import AuditAction
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import (
    AddLayerCommand,
    AddLoggersCommand,
    SetSpacePropertiesCommand,
)
from thermavisualizer.services.workers import FileLoadResult

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def pipeline_model(qtbot: QtBot, tmp_path: Path) -> ProjectModel:
    model = ProjectModel(user_name="tester", profiles_path=tmp_path / "profiles.json")
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


def test_interpolate_async_produces_volume(pipeline_model: ProjectModel, qtbot: QtBot) -> None:
    progress: list[int] = []
    pipeline_model.interpolation_progress_changed.connect(progress.append)
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000) as blocker:
        worker = pipeline_model.interpolate_async(
            Quantity.TEMPERATURE, AggregationMethod.INSTANT, time_index=0
        )
    assert worker is not None
    result = blocker.args[0]
    assert result.from_cache is False
    assert result.volume.shape == (6, 6, 16)  # 1x1x3 m space at 0.2 m resolution
    assert np.isfinite(result.volume).any()
    assert result.volume[1, 1, 2] == pytest.approx(20.1)  # IDW passes through T1
    assert pipeline_model.current_volume(Quantity.TEMPERATURE) is result
    assert progress  # progress was reported from the worker


def test_second_call_is_served_from_cache(
    pipeline_model: ProjectModel, qtbot: QtBot
) -> None:  # INT-07
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000):
        pipeline_model.interpolate_async(
            Quantity.TEMPERATURE, AggregationMethod.INSTANT, time_index=0
        )
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000) as blocker:
        worker = pipeline_model.interpolate_async(
            Quantity.TEMPERATURE, AggregationMethod.INSTANT, time_index=0
        )
    assert worker is None  # cache hit, no background work
    assert blocker.args[0].from_cache is True


def test_instant_and_mean_aggregation_differ(
    pipeline_model: ProjectModel, qtbot: QtBot
) -> None:  # INT-05
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000) as instant:
        pipeline_model.interpolate_async(
            Quantity.TEMPERATURE, AggregationMethod.INSTANT, time_index=0
        )
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000) as mean:
        pipeline_model.interpolate_async(
            Quantity.TEMPERATURE, AggregationMethod.MEAN, range_start=0, range_end=5
        )
    voxel = (1, 1, 2)  # logger T1 position
    assert instant.args[0].volume[voxel] == pytest.approx(20.1)
    assert mean.args[0].volume[voxel] == pytest.approx(20.35)
    assert "mean" in mean.args[0].time_label


def test_settings_change_audits_and_clears_cache(
    pipeline_model: ProjectModel, qtbot: QtBot
) -> None:  # AUD-03
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000):
        pipeline_model.interpolate_async()
    assert pipeline_model.current_volume(Quantity.TEMPERATURE) is not None
    with qtbot.waitSignal(pipeline_model.interpolation_settings_changed, timeout=500):
        pipeline_model.set_interpolation_settings(
            replace(pipeline_model.interpolation_settings(), idw_power=3.0)
        )
    assert pipeline_model.current_volume(Quantity.TEMPERATURE) is None
    assert any(
        entry.action is AuditAction.PROCESSING_CHANGED and "settings changed" in entry.summary
        for entry in pipeline_model.audit.entries
    )
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000) as blocker:
        pipeline_model.interpolate_async()
    assert blocker.args[0].from_cache is False  # cache was dropped


def test_layout_edit_invalidates_cache(pipeline_model: ProjectModel, qtbot: QtBot) -> None:
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000):
        pipeline_model.interpolate_async()
    pipeline_model.apply(SetSpacePropertiesCommand(pipeline_model, height=2.5))
    assert pipeline_model.current_volume(Quantity.TEMPERATURE) is None
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000) as blocker:
        pipeline_model.interpolate_async()
    assert blocker.args[0].from_cache is False
    assert blocker.args[0].volume.shape[2] == 14  # nz for height 2.5 m at 0.2 m


def test_missing_quantity_alignment_raises(pipeline_model: ProjectModel) -> None:
    with pytest.raises(AlignmentError):
        pipeline_model.interpolate_async(Quantity.HUMIDITY)


def test_worker_error_surfaces(
    pipeline_model: ProjectModel, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    import thermavisualizer.services.project_model as project_model_module

    def boom(job, cancel_check, report_progress, cache=None):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(project_model_module, "interpolate_volume_job", boom)
    with qtbot.waitSignal(pipeline_model.interpolation_failed, timeout=8000) as blocker:
        pipeline_model.interpolate_async()
    assert "kaboom" in blocker.args[0]


def test_cancel_when_idle_is_noop(pipeline_model: ProjectModel) -> None:
    pipeline_model.cancel_interpolation()


def test_temporal_window_smooths_before_instant(
    pipeline_model: ProjectModel, qtbot: QtBot
) -> None:  # INT-04
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000) as raw:
        pipeline_model.interpolate_async(
            Quantity.TEMPERATURE, AggregationMethod.INSTANT, time_index=0
        )
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000) as smoothed:
        pipeline_model.interpolate_async(
            Quantity.TEMPERATURE,
            AggregationMethod.INSTANT,
            time_index=0,
            temporal_window=3,
        )
    voxel = (1, 1, 2)  # coincides with logger T1, so IDW returns the series value
    assert raw.args[0].volume[voxel] == pytest.approx(20.1)
    assert smoothed.args[0].volume[voxel] == pytest.approx(20.1)  # mean(20.1, 20.2)
    assert smoothed.args[0].from_cache is True  # window is part of the cache key


def test_current_logger_values_match_request(pipeline_model: ProjectModel, qtbot: QtBot) -> None:
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000):
        pipeline_model.interpolate_async(
            Quantity.TEMPERATURE, AggregationMethod.INSTANT, time_index=1
        )
    values = pipeline_model.current_logger_values(Quantity.TEMPERATURE)
    assert values is not None
    assert values[0] == pytest.approx(20.2)


def test_pipeline_stays_in_celsius(pipeline_model: ProjectModel, qtbot: QtBot) -> None:
    """Guard against unit drift: aligned + interpolated values stay in °C, never K."""
    dataset = pipeline_model.aligned_dataset(Quantity.TEMPERATURE)
    assert dataset is not None
    finite = dataset.values[np.isfinite(dataset.values)]
    assert 15.0 < finite.mean() < 25.0  # data_simple is ~20 °C, not ~293 K
    with qtbot.waitSignal(pipeline_model.volume_ready, timeout=8000) as blocker:
        pipeline_model.interpolate_async()
    volume = blocker.args[0].volume
    finite_volume = volume[np.isfinite(volume)]
    assert finite_volume.size > 0
    assert 15.0 < finite_volume.mean() < 25.0
