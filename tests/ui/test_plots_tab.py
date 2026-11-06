"""Plots tab tests (PLT-01..07, OBS-04)."""

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
    Obstacle,
    ObstacleShape,
    ObstacleType,
    Quantity,
)
from thermavisualizer.core.results import AcceptanceCriteria
from thermavisualizer.core.validation import validate_path
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import (
    AddLayerCommand,
    AddLoggersCommand,
    AddObstacleCommand,
)
from thermavisualizer.services.workers import FileLoadResult
from thermavisualizer.ui.tabs.plots import PlotLayout, PlotOptions, PlotsTab, _decimate_for_display

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def plots_model(qtbot: QtBot, tmp_path: Path) -> ProjectModel:
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
    model.apply(
        AddObstacleCommand(
            model,
            Obstacle(
                name="Main door",
                obstacle_type=ObstacleType.DOOR,
                shape=ObstacleShape.BOX,
                x=0.9,
                y=0.2,
                z=1.0,
                size_x=0.1,
                size_y=0.8,
                size_z=2.0,
            ),
        )
    )
    parsed, report = validate_path(DATA / "data_simple.csv", ImportProfile())
    assert parsed is not None
    model.ingest_load_results(
        [FileLoadResult(str(DATA / "data_simple.csv"), "Default", parsed, report)]
    )
    model.set_mappings(
        [
            LoggerMapping(
                logger_id="T1",
                temperature_file=parsed.path,
                temperature_column="T1",
                humidity_file=parsed.path,
                humidity_column="RH1",
            ),
            LoggerMapping(logger_id="T2", temperature_file=parsed.path, temperature_column="T2"),
            LoggerMapping(logger_id="T3", temperature_file=parsed.path, temperature_column="T3"),
            LoggerMapping(logger_id="X1", excluded=True),
        ]
    )
    model.align(Quantity.TEMPERATURE)
    model.align(Quantity.HUMIDITY)
    return model


@pytest.fixture
def tab(qtbot: QtBot, plots_model: ProjectModel) -> PlotsTab:
    widget = PlotsTab(plots_model)
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    return widget


def _series_lines(axes) -> list:
    """Lines representing data series (matplotlib auto-labels start with '_')."""
    return [line for line in axes.lines if not line.get_label().startswith("_")]


def test_plots_all_mapped_series_by_default(tab: PlotsTab, plots_model: ProjectModel) -> None:
    assert len(_series_lines(tab._figure.axes[0])) == 3  # T1, T2, T3


def test_series_selection_filters_lines(tab: PlotsTab, plots_model: ProjectModel) -> None:
    tab.set_selected_series(("T1",))
    assert len(_series_lines(tab._figure.axes[0])) == 1


def test_limit_lines_drawn(tab: PlotsTab, plots_model: ProjectModel) -> None:  # PLT-04
    tab.set_options(PlotOptions(show_limits=False))
    assert [l for l in tab._figure.axes[0].lines if l.get_linestyle() == "--"] == []
    plots_model.set_criteria(
        AcceptanceCriteria(name="Tight", temperature_min=19.0, temperature_max=21.0)
    )
    tab.set_options(PlotOptions(show_limits=True))
    dashed = [l for l in tab._figure.axes[0].lines if l.get_linestyle() == "--"]
    assert len(dashed) == 2
    assert {float(line.get_ydata()[0]) for line in dashed} == {19.0, 21.0}


def test_dual_axis_layout(tab: PlotsTab, plots_model: ProjectModel) -> None:  # PLT-02
    tab.set_options(PlotOptions(layout=PlotLayout.DUAL_AXIS))
    assert len(tab._figure.axes) >= 2  # primary + twinx


def test_separate_subplots_layout(tab: PlotsTab, plots_model: ProjectModel) -> None:  # PLT-02
    tab.set_options(PlotOptions(layout=PlotLayout.SEPARATE))
    assert len(tab._figure.axes) == 2


def test_humidity_layout_plots_rh_series(tab: PlotsTab, plots_model: ProjectModel) -> None:
    tab.set_options(PlotOptions(layout=PlotLayout.HUMIDITY))
    assert len(_series_lines(tab._figure.axes[0])) == 1  # only T1 has an RH mapping


def test_hot_cold_summary_with_obstacle_context(
    tab: PlotsTab, plots_model: ProjectModel
) -> None:  # PLT-05 + OBS-04
    text = tab.summary_label.text()
    assert "Hot spot" in text and "Cold spot" in text
    assert "'T2'" in text  # hottest logger (20.9 °C)
    assert "Main door" in text  # nearest door/vent/evaporator context


def test_statistics_hidden_by_option(tab: PlotsTab) -> None:
    tab.set_options(PlotOptions(show_statistics=False))
    assert tab.stats_table.isHidden()


def test_toolbar_present(tab: PlotsTab) -> None:  # PLT-06
    assert tab.toolbar is not None


def test_decimation_bounds() -> None:  # AGENTS §10
    times = np.arange(5000)
    values = np.arange(5000, dtype=float)
    t, v = _decimate_for_display(times, values, max_points=1000)
    assert t.size == v.size == 1000
    small_t, small_v = _decimate_for_display(times[:10], values[:10])
    assert small_t.size == 10


def test_humidity_only_layout_draws_on_primary_axis(
    tab: PlotsTab, plots_model: ProjectModel
) -> None:
    tab.set_options(PlotOptions(layout=PlotLayout.HUMIDITY))
    axes = tab._figure.axes
    assert len(axes) >= 1
    series = [l for l in axes[0].lines if not l.get_label().startswith("_")]
    assert len(series) == 1  # only T1 has an RH mapping
    assert axes[0].get_ylabel() == "Humidity (%RH)"

def test_axis_labels_title_and_side_legend(tab: PlotsTab, plots_model: ProjectModel) -> None:
    tab.set_selected_series(("T1", "T2"))
    axes = tab._figure.axes[0]
    assert axes.get_xlabel() == "Time (UTC)"
    assert axes.get_ylabel() == "Temperature (°C)"
    assert axes.get_title(loc="left") != ""  # shared style uses a left-aligned title
    legend = axes.get_legend()
    assert legend is not None
    anchor = legend.get_bbox_to_anchor().transformed(axes.transAxes.inverted())
    assert anchor.x0 > 1.0  # anchored right of the axes, in axes coordinates: outside


def test_dual_axis_legend_combined_below(tab: PlotsTab, plots_model: ProjectModel) -> None:
    tab.set_options(PlotOptions(layout=PlotLayout.DUAL_AXIS))
    axes = tab._figure.axes[0]
    legend = axes.get_legend()
    assert legend is not None
    assert len(legend.get_texts()) == 3  # T1..T3; T1 shared by temp + RH series
    anchor = legend.get_bbox_to_anchor().transformed(axes.transAxes.inverted())
    assert anchor.y1 < 0.0  # anchored below the axes, in axes coordinates

def test_concise_date_formatter_applied(tab: PlotsTab, plots_model: ProjectModel) -> None:
    import matplotlib.dates as mdates

    axes = tab._figure.axes[0]
    assert isinstance(axes.xaxis.get_major_formatter(), mdates.ConciseDateFormatter)