"""Shared matplotlib styling for the Plots tab and PDF report figures.

Keeps the interactive canvas and exported/report figures visually consistent.
Headless-safe (bare ``Figure`` API, no Qt backend assumptions). Timestamps
are naive-UTC; value units are carried in the axis labels (°C / %RH).
"""

from __future__ import annotations

import math

import matplotlib.dates as mdates
import numpy as np
from matplotlib.figure import Figure

_BRAND = "#1f4e79"
_GRID = "#d9dee5"
_SPINE = "#8a94a0"
_SERIES_COLORS = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
)
_MAX_DISPLAY_POINTS = 2000


def series_color(index: int) -> str:
    """Deterministic color for series ``index`` (cycles, colorblind-friendlier)."""
    return _SERIES_COLORS[index % len(_SERIES_COLORS)]


def decimate_for_display(
    times: np.ndarray, values: np.ndarray, max_points: int = _MAX_DISPLAY_POINTS
) -> tuple[np.ndarray, np.ndarray]:
    """Downsample a series for display only (never used for statistics)."""
    if times.size <= max_points:
        return times, values
    step = math.ceil(times.size / max_points)
    return times[::step], values[::step]


def format_time_axis(axes) -> None:
    """Adaptive UTC date ticks with compact labels (no manual rotation)."""
    locator = mdates.AutoDateLocator()
    axes.xaxis.set_major_locator(locator)
    axes.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))


def style_axes(axes, ylabel: str, title: str = "", show_xlabel: bool = True) -> None:
    """Shared look: left-aligned title, labelled axes, soft horizontal grid."""
    if title:
        axes.set_title(title, fontsize=10, loc="left", color=_BRAND, fontweight="bold")
    axes.set_ylabel(ylabel, fontsize=9)
    if show_xlabel:
        axes.set_xlabel("Time (UTC)", fontsize=9)
    axes.tick_params(labelsize=8)
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.spines["left"].set_color(_SPINE)
    axes.spines["bottom"].set_color(_SPINE)
    axes.grid(True, axis="y", color=_GRID, linewidth=0.7)
    axes.set_axisbelow(True)
    axes.margins(x=0.01)


def place_legend_outside(axes) -> bool:
    """Put the axes legend to the right, outside the plot area. Returns success."""
    handles, labels = axes.get_legend_handles_labels()
    if not handles:
        return False
    axes.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0.0,
        fontsize=7.5,
        frameon=True,
        framealpha=0.95,
        edgecolor=_GRID,
        labelspacing=0.35,
        handlelength=1.5,
    )
    return True


def place_legend_below(figure: Figure, axes_list: list) -> bool:
    """Combine legends of several axes below the first one (dual-axis layout).

    Returns True when a legend was created.
    """
    handles: list = []
    labels: list = []
    for axes in axes_list:
        for handle, label in zip(*axes.get_legend_handles_labels()):
            if label not in labels:
                handles.append(handle)
                labels.append(label)
    if not handles:
        return False
    axes_list[0].legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=min(6, len(handles)),
        fontsize=7.5,
        frameon=True,
        framealpha=0.95,
        edgecolor=_GRID,
        handlelength=1.5,
    )
    return True


def layout_figure(
    figure: Figure, has_side_legend: bool, has_bottom_legend: bool
) -> None:
    """Tighten the layout, then reserve room for outside legends."""
    figure.tight_layout()
    if has_side_legend:
        figure.subplots_adjust(right=0.76)
    if has_bottom_legend:
        figure.subplots_adjust(bottom=0.24)