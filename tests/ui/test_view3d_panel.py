"""3D View panel: compute gating, settings, slices, colors, limits, probe."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot
from PySide6.QtWidgets import QScrollArea
from thermavisualizer.core.interpolation import InterpolationMethod
from thermavisualizer.core.models import (
    ImportProfile,
    Layer,
    Logger,
    LoggerMapping,
    Quantity,
    TimelineMode,
)
from thermavisualizer.core.slicing import SliceAxis
from thermavisualizer.core.statistics import AggregationMethod
from thermavisualizer.core.validation import validate_path
from thermavisualizer.rendering.colormaps import ColorMapName
from thermavisualizer.services.audit import AuditAction
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.services.workers import FileLoadResult
from thermavisualizer.ui.panels.view3d_panel import View3DPanel

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def ready_model(qtbot: QtBot, tmp_path: Path) -> ProjectModel:
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


def test_compute_refuses_incomplete_mapping(qtbot: QtBot, tmp_path: Path) -> None:  # DAT-03
    model = ProjectModel(user_name="tester", profiles_path=tmp_path / "p.json")
    model.apply(AddLayerCommand(model, Layer(name="low", height=0.5)))
    model.apply(
        AddLoggersCommand(model, model.space.layers[0].layer_id, [Logger("A", 0.1, 0.1, 0.5)])
    )
    panel = View3DPanel(model)
    qtbot.addWidget(panel)
    messages: list[str] = []
    panel.edit_rejected.connect(messages.append)
    panel._on_compute()
    assert any("DAT-03" in message for message in messages)


def test_compute_produces_volume(qtbot: QtBot, ready_model: ProjectModel) -> None:
    panel = View3DPanel(ready_model)
    qtbot.addWidget(panel)
    panel.resolution_spin.setValue(0.5)
    panel.aggregation_combo.setCurrentIndex(
        list(AggregationMethod).index(AggregationMethod.INSTANT)
    )
    with qtbot.waitSignal(ready_model.volume_ready, timeout=8000):
        panel._on_compute()
    assert ready_model.current_volume(Quantity.TEMPERATURE) is not None


def test_apply_settings_audits(qtbot: QtBot, ready_model: ProjectModel) -> None:
    panel = View3DPanel(ready_model)
    qtbot.addWidget(panel)
    panel.method_combo.setCurrentIndex(list(InterpolationMethod).index(InterpolationMethod.RBF))
    panel._on_apply_settings()
    assert ready_model.interpolation_settings().method is InterpolationMethod.RBF
    assert any(
        entry.action is AuditAction.PROCESSING_CHANGED for entry in ready_model.audit.entries
    )
    assert "estimates" in panel.method_note_label.text()


def test_slice_specs_emitted(qtbot: QtBot, ready_model: ProjectModel) -> None:
    panel = View3DPanel(ready_model)
    qtbot.addWidget(panel)
    received: list[list] = []
    panel.slices_changed.connect(received.append)
    panel._slice_controls["z"]["enabled"].setChecked(True)
    panel._slice_controls["z"]["position"].setValue(0.5)
    panel._emit_slices()
    specs = received[-1]
    assert len(specs) == 1
    assert specs[0].spec_id == "z"
    assert specs[0].axis is SliceAxis.Z
    assert specs[0].position == pytest.approx(0.5)


def test_color_scale_and_limits_emitted(qtbot: QtBot, ready_model: ProjectModel) -> None:
    panel = View3DPanel(ready_model)
    qtbot.addWidget(panel)
    colors: list = []
    limits: list = []
    panel.color_scale_changed.connect(colors.append)
    panel.limits_changed.connect(limits.append)
    panel._color_widget.colormap_combo.setCurrentIndex(
        panel._color_widget.colormap_combo.findData(ColorMapName.THERMAL)
    )
    assert colors[-1].colormap is ColorMapName.THERMAL
    panel.limits_check.setChecked(True)
    assert limits[-1] == (2.0, 8.0)


def test_probe_reports_value_and_nearest_logger(
    qtbot: QtBot, ready_model: ProjectModel
) -> None:  # SLC-06
    panel = View3DPanel(ready_model)
    qtbot.addWidget(panel)
    panel.resolution_spin.setValue(0.5)
    with qtbot.waitSignal(ready_model.volume_ready, timeout=8000):
        panel._on_compute()
    panel.probe_x.setValue(0.2)
    panel.probe_y.setValue(0.2)
    panel.probe_z.setValue(0.4)
    panel._on_probe()
    text = panel.probe_result_label.text()
    assert "estimated" in text
    assert "Nearest logger 'T1'" in text
    panel.probe_x.setValue(5.0)
    panel._on_probe()
    assert "outside the space" in panel.probe_result_label.text()


def test_panel_is_scrollable(qtbot: QtBot, ready_model: ProjectModel) -> None:
    panel = View3DPanel(ready_model)
    qtbot.addWidget(panel)
    assert panel.findChild(QScrollArea) is not None


def test_timeline_range_triggers_recompute(
    ready_model: ProjectModel, qtbot: QtBot
) -> None:  # acceptance item 6 (3D side)
    panel = View3DPanel(ready_model)
    qtbot.addWidget(panel)
    panel.resolution_spin.setValue(0.5)
    with qtbot.waitSignal(ready_model.volume_ready, timeout=8000):
        panel._on_compute()
    dataset = ready_model.aligned_dataset(Quantity.TEMPERATURE)
    assert dataset is not None
    with qtbot.waitSignal(ready_model.volume_ready, timeout=8000) as blocker:
        ready_model.set_timeline_range(dataset.times[1], dataset.times[4])
        panel.on_timeline_changed()
    result = blocker.args[0]
    assert result.aggregation is AggregationMethod.MEAN  # combo 'instant' -> mean in range mode
    assert "mean" in result.time_label


def test_instant_mode_recomputes_at_playhead(ready_model: ProjectModel, qtbot: QtBot) -> None:
    panel = View3DPanel(ready_model)
    qtbot.addWidget(panel)
    panel.resolution_spin.setValue(0.5)
    with qtbot.waitSignal(ready_model.volume_ready, timeout=8000):
        panel._on_compute()
    dataset = ready_model.aligned_dataset(Quantity.TEMPERATURE)
    assert dataset is not None
    ready_model.set_timeline_mode(TimelineMode.INSTANT)
    ready_model.set_playhead(dataset.times[2])
    with qtbot.waitSignal(ready_model.volume_ready, timeout=8000) as blocker:
        panel.on_playhead_changed(dataset.times[2])
    assert blocker.args[0].aggregation is AggregationMethod.INSTANT
    assert "08:02" in blocker.args[0].time_label
