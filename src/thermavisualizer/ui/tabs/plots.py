"""Plots tab: time-series charts for selected loggers (PLT-01..07, OBS-04).

matplotlib is embedded via FigureCanvasQTAgg with QT_API=pyside6 (AGENTS §6).
Display series are decimated for speed; statistics are always computed on the
full-resolution data within the selected window (AGENTS §10). Units: °C, %RH;
timestamps naive-UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.alignment import select_time_window
from thermavisualizer.core.geometry import nearest_context_obstacle
from thermavisualizer.core.models import Quantity
from thermavisualizer.core.statistics import mean_kinetic_temperature
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.plot_style import (
    decimate_for_display as _decimate_for_display,  # alias kept for tests
    format_time_axis,
    layout_figure,
    place_legend_below,
    place_legend_outside,
    series_color,
    style_axes,
)


class PlotLayout(StrEnum):
    """Plot layout mode (PLT-02)."""

    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    DUAL_AXIS = "dual_axis"
    SEPARATE = "separate"


@dataclass(frozen=True)
class PlotOptions:
    """User options for the plots tab (PLT-02/03/04)."""

    layout: PlotLayout = PlotLayout.TEMPERATURE
    show_limits: bool = True
    show_statistics: bool = True


class PlotsTab(QWidget):
    """Time-series plots, statistics table, and hot/cold spot summary."""

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._options = PlotOptions()
        self._selected_series: tuple[str, ...] = ()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._figure = Figure(figsize=(8, 4))
        self.canvas = FigureCanvasQTAgg(self._figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas, 1)

        self.summary_label = QLabel("", self)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.stats_table = QTableWidget(0, 6, self)
        self.stats_table.setHorizontalHeaderLabels(("Logger", "Min", "Max", "Mean", "Std", "MKT"))
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats_table.setMaximumHeight(200)
        layout.addWidget(self.stats_table)

        model.timeline_changed.connect(self.refresh)
        model.aligned_changed.connect(self.refresh)
        model.criteria_changed.connect(self.refresh)
        model.config_changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------- options

    def set_options(self, options: PlotOptions) -> None:
        """Replace plot options and redraw (PLT-02/03/04)."""
        self._options = options
        self.refresh()

    def set_selected_series(self, logger_ids: tuple[str, ...] | list[str]) -> None:
        """Set the plotted logger IDs; empty selection plots everything."""
        self._selected_series = tuple(logger_ids)
        self.refresh()

    # -------------------------------------------------------------- render

    def refresh(self) -> None:
        """Redraw figure, statistics table, and summary (PLT-07 sync)."""
        self._figure.clear()
        options = self._options
        start, end = self._model.timeline_range()
        temp = self._model.aligned_dataset(Quantity.TEMPERATURE)
        humidity = self._model.aligned_dataset(Quantity.HUMIDITY)
        plot_temp = temp is not None and options.layout in (
            PlotLayout.TEMPERATURE,
            PlotLayout.DUAL_AXIS,
            PlotLayout.SEPARATE,
        )
        plot_rh = humidity is not None and options.layout in (
            PlotLayout.HUMIDITY,
            PlotLayout.DUAL_AXIS,
            PlotLayout.SEPARATE,
        )

        # --- axes creation (must come first: everything below uses these) ---
        if options.layout is PlotLayout.SEPARATE and plot_temp and plot_rh:
            ax_temp = self._figure.add_subplot(2, 1, 1)
            ax_rh = self._figure.add_subplot(2, 1, 2, sharex=ax_temp)
        elif options.layout is PlotLayout.DUAL_AXIS and plot_temp and plot_rh:
            ax_temp = self._figure.add_subplot(1, 1, 1)
            ax_rh = ax_temp.twinx()
        elif plot_temp:
            ax_temp = self._figure.add_subplot(1, 1, 1)
            ax_rh = None
        elif plot_rh:
            ax_temp = None
            ax_rh = self._figure.add_subplot(1, 1, 1)
        else:
            ax_temp = self._figure.add_subplot(1, 1, 1)
            ax_rh = None
            ax_temp.text(
                0.5, 0.5, "No aligned data — import and map loggers first",
                ha="center", va="center", transform=ax_temp.transAxes,
            )

        study_title = self._model.study().title or "Thermal mapping study"
        bottom_axis = None
        if options.layout is PlotLayout.SEPARATE and plot_temp and plot_rh:
            bottom_axis = ax_rh  # shared x labels live on the bottom subplot
        elif plot_temp:
            bottom_axis = ax_temp
        elif plot_rh:
            bottom_axis = ax_rh

        if plot_temp:
            self._draw_series(ax_temp, temp, start, end)
            style_axes(
                ax_temp,
                "Temperature (°C)",
                f"{study_title} — Temperature",
                show_xlabel=bottom_axis is ax_temp,
            )
            if bottom_axis is ax_temp:
                format_time_axis(ax_temp)
            if options.show_limits:
                criteria = self._model.criteria()
                self._draw_limits(ax_temp, criteria.temperature_min, criteria.temperature_max)
        if plot_rh and ax_rh is not None:
            self._draw_series(ax_rh, humidity, start, end)
            if options.layout is PlotLayout.DUAL_AXIS:
                style_axes(ax_rh, "Humidity (%RH)", "", show_xlabel=False)
            else:
                style_axes(
                    ax_rh,
                    "Humidity (%RH)",
                    f"{study_title} — Humidity",
                    show_xlabel=bottom_axis is ax_rh,
                )
                if bottom_axis is ax_rh:
                    format_time_axis(ax_rh)
            if options.show_limits:
                criteria = self._model.criteria()
                self._draw_limits(ax_rh, criteria.humidity_min, criteria.humidity_max)

        side_axes: list = []
        bottom_axes: list = []
        if plot_temp and plot_rh and options.layout is PlotLayout.DUAL_AXIS:
            bottom_axes = [ax_temp, ax_rh]  # right spine hosts the RH axis
        else:
            if plot_temp:
                side_axes.append(ax_temp)
            if plot_rh and ax_rh is not None:
                side_axes.append(ax_rh)
        for axes in side_axes:
            place_legend_outside(axes)
        has_bottom_legend = bool(bottom_axes) and place_legend_below(
            self._figure, bottom_axes
        )
        layout_figure(
            self._figure,
            has_side_legend=bool(side_axes),
            has_bottom_legend=bool(has_bottom_legend),
        )
        self._refresh_stats(start, end)
        self._refresh_summary(start, end)
        self.canvas.draw_idle()

    def _draw_series(self, axes, dataset, start, end) -> None:
        """Draw selected series; NaN samples break the line (no implied data)."""
        times, values = select_time_window(dataset.times, dataset.values, start, end)
        selection = set(self._selected_series) or set(dataset.logger_ids)
        color_index = 0
        for index, logger_id in enumerate(dataset.logger_ids):
            if logger_id not in selection:
                continue
            t_plot, v_plot = _decimate_for_display(times, values[:, index])
            axes.plot(
                t_plot,
                v_plot,
                label=logger_id,
                color=series_color(color_index),
                linewidth=1.2,
                alpha=0.95,
            )
            color_index += 1

    def _draw_limits(self, axes, low: float | None, high: float | None) -> None:
        for limit in (low, high):
            if limit is not None:
                axes.axhline(limit, color="red", linestyle="--", linewidth=1.0)

    # ------------------------------------------------------------ analysis

    def _primary_dataset(self):
        """Dataset used for statistics/summary: temperature unless layout says RH."""
        temp = self._model.aligned_dataset(Quantity.TEMPERATURE)
        humidity = self._model.aligned_dataset(Quantity.HUMIDITY)
        if self._options.layout is PlotLayout.HUMIDITY:
            return humidity, Quantity.HUMIDITY
        if temp is not None:
            return temp, Quantity.TEMPERATURE
        return humidity, Quantity.HUMIDITY

    def _refresh_stats(self, start, end) -> None:  # PLT-03
        table = self.stats_table
        table.setRowCount(0)
        if not self._options.show_statistics:
            table.hide()
            return
        dataset, quantity = self._primary_dataset()
        if dataset is None:
            table.hide()
            return
        table.show()
        times, values = select_time_window(dataset.times, dataset.values, start, end)
        selection = set(self._selected_series) or set(dataset.logger_ids)
        rows: list[tuple[str, float, float, float, float, float | None]] = []
        for index, logger_id in enumerate(dataset.logger_ids):
            if logger_id not in selection:
                continue
            finite = values[:, index][np.isfinite(values[:, index])]
            if finite.size == 0:
                continue
            mkt = mean_kinetic_temperature(finite) if quantity is Quantity.TEMPERATURE else None
            rows.append(
                (
                    logger_id,
                    float(finite.min()),
                    float(finite.max()),
                    float(finite.mean()),
                    float(finite.std()),
                    mkt,
                )
            )
        table.setRowCount(len(rows))
        for row, (logger_id, vmin, vmax, mean, std, mkt) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(logger_id))
            table.setItem(row, 1, QTableWidgetItem(f"{vmin:.2f}"))
            table.setItem(row, 2, QTableWidgetItem(f"{vmax:.2f}"))
            table.setItem(row, 3, QTableWidgetItem(f"{mean:.2f}"))
            table.setItem(row, 4, QTableWidgetItem(f"{std:.2f}"))
            table.setItem(row, 5, QTableWidgetItem(f"{mkt:.2f}" if mkt is not None else "—"))

    def _refresh_summary(self, start, end) -> None:  # PLT-05 + OBS-04
        dataset, quantity = self._primary_dataset()
        if dataset is None:
            self.summary_label.setText("")
            return
        times, values = select_time_window(dataset.times, dataset.values, start, end)
        finite = np.isfinite(values)
        if not finite.any():
            self.summary_label.setText("")
            return
        unit = "°C" if quantity is Quantity.TEMPERATURE else "%RH"
        max_row, max_col = divmod(
            int(np.nanargmax(np.where(finite, values, -np.inf))), values.shape[1]
        )
        min_row, min_col = divmod(
            int(np.nanargmin(np.where(finite, values, np.inf))), values.shape[1]
        )
        high_label = "Hot spot" if quantity is Quantity.TEMPERATURE else "Highest"
        low_label = "Cold spot" if quantity is Quantity.TEMPERATURE else "Lowest"
        self.summary_label.setText(
            "\n".join(
                (
                    self._spot_line(
                        high_label,
                        dataset.logger_ids[max_col],
                        values[max_row, max_col],
                        times[max_row],
                        unit,
                    ),
                    self._spot_line(
                        low_label,
                        dataset.logger_ids[min_col],
                        values[min_row, min_col],
                        times[min_row],
                        unit,
                    ),
                )
            )
        )

    def _spot_line(
        self, label: str, logger_id: str, value: float, time: np.datetime64, unit: str
    ) -> str:
        text = f"{label}: '{logger_id}' {value:.2f} {unit} at {time}"
        position = self._logger_position(logger_id)
        if position is not None:
            context = nearest_context_obstacle(self._model.space, position[0], position[1])
            if context is not None:
                obstacle, distance = context
                text += (
                    f" — near {obstacle.obstacle_type.value} '{obstacle.name}' ({distance:.1f} m)"
                )
        return text

    def _logger_position(self, logger_id: str) -> tuple[float, float] | None:
        for layer in self._model.space.layers:
            for logger in layer.loggers:
                if logger.logger_id == logger_id:
                    return logger.x, logger.y
        return None


def render_slice_heatmap_png(
    slice_data,
    path,
    colormap: str = "viridis",
    clim: tuple[float, float] | None = None,
    title: str = "",
) -> None:
    """Render a SliceData grid to a 2D heat-map PNG (EXP-03).

    Axis-aligned slices get world-axis extents in metres; arbitrary planes fall
    back to sample-index axes. NaN samples render as blank. Units: metres.
    """
    values = slice_data.values.reshape(slice_data.u_count, slice_data.v_count)
    points = slice_data.points
    spans = points.max(axis=0) - points.min(axis=0)
    constant_axis = int(spans.argmin())
    axes_idx = [i for i in range(3) if i != constant_axis]
    if float(spans[constant_axis]) <= 1e-9:
        extent = (
            float(points[:, axes_idx[0]].min()),
            float(points[:, axes_idx[0]].max()),
            float(points[:, axes_idx[1]].min()),
            float(points[:, axes_idx[1]].max()),
        )
        xlabel, ylabel = f"{'xyz'[axes_idx[0]]} (m)", f"{'xyz'[axes_idx[1]]} (m)"
    else:
        extent = (0.0, float(slice_data.u_count), 0.0, float(slice_data.v_count))
        xlabel, ylabel = "u samples", "v samples"
    figure = Figure(figsize=(6, 5))
    axes = figure.add_subplot(1, 1, 1)
    image = axes.imshow(
        values.T,
        origin="lower",
        extent=extent,
        cmap=colormap,
        vmin=clim[0] if clim else None,
        vmax=clim[1] if clim else None,
        aspect="auto",
    )
    axes.set_xlabel(xlabel)
    axes.set_ylabel(ylabel)
    if title:
        axes.set_title(title)
    figure.colorbar(image, ax=axes, label=title or "value")
    figure.savefig(path, dpi=150, bbox_inches="tight")
