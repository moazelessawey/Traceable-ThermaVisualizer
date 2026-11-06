"""Shared plot styling helpers (Plots tab + report figures)."""

from __future__ import annotations

import io

import numpy as np
from matplotlib.figure import Figure

from thermavisualizer.services.plot_style import (
    decimate_for_display,
    format_time_axis,
    layout_figure,
    place_legend_outside,
    series_color,
    style_axes,
)


def test_series_color_cycles() -> None:
    assert series_color(0) == series_color(10)
    assert series_color(0) != series_color(1)


def test_decimation_bounds() -> None:
    times = np.arange(5000)
    values = np.arange(5000, dtype=float)
    t, v = decimate_for_display(times, values, max_points=1000)
    assert t.size == v.size == 1000
    t2, v2 = decimate_for_display(times[:10], values[:10])
    assert t2.size == 10


def test_styled_figure_renders_headless() -> None:
    times = np.datetime64("2024-03-01T08:00", "ns") + np.arange(6) * np.timedelta64(60, "s")
    figure = Figure(figsize=(6, 3))
    axes = figure.add_subplot(1, 1, 1)
    axes.plot(
        times, np.array([1.0, 2.0, 3.0, 2.5, 2.0, 1.5]),
        label="L1", color=series_color(0),
    )
    style_axes(axes, "Temperature (°C)", "Study — Temperature")
    format_time_axis(axes)
    assert place_legend_outside(axes) is True
    layout_figure(figure, has_side_legend=True, has_bottom_legend=False)
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", bbox_inches="tight")
    assert buffer.getvalue().startswith(b"\x89PNG")