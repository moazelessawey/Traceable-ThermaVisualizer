"""Export dialogs and enabled File > Export actions (EXP-02/03/04)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QAction
from pytestqt.qtbot import QtBot

from thermavisualizer.core.slicing import SliceData
from thermavisualizer.ui.dialogs import DataExportDialog, MovieExportDialog
from thermavisualizer.ui.tabs.plots import render_slice_heatmap_png


def test_movie_dialog_values(qtbot: QtBot) -> None:
    dialog = MovieExportDialog(None, frame_count_hint=100)
    qtbot.addWidget(dialog)
    dialog.fps_spin.setValue(12)
    dialog.stride_spin.setValue(3)
    dialog.burn_timestamp = dialog.timestamp_check  # attribute alias guard
    values = dialog.values()
    assert values["fps"] == 12
    assert values["stride"] == 3
    assert values["width"] == 1280
    assert values["burn_timestamp"] is True


def test_data_dialog_respects_availability(qtbot: QtBot) -> None:
    dialog = DataExportDialog(
        None,
        {
            "aligned": True,
            "volume": False,
            "slice": False,
            "slice_image": False,
            "validation": True,
        },
    )
    qtbot.addWidget(dialog)
    assert dialog.selected() == "aligned"
    assert not dialog._radios["volume"].isEnabled()


def test_export_actions_enabled(main_window) -> None:  # M0 placeholders now live
    for name in ("action_export_image", "action_export_movie", "action_export_data"):
        action = main_window.findChild(QAction, name)
        assert action is not None
        assert action.isEnabled()


def test_render_slice_heatmap_png(tmp_path: Path) -> None:
    points = np.array(
        [
            [0.0, 0.0, 0.5],
            [1.0, 0.0, 0.5],
            [2.0, 0.0, 0.5],
            [0.0, 1.0, 0.5],
            [1.0, 1.0, 0.5],
            [2.0, 1.0, 0.5],
        ]
    )
    data = SliceData(points=points, values=np.arange(6.0), u_count=3, v_count=2)
    out = tmp_path / "heatmap.png"
    render_slice_heatmap_png(data, out, "viridis", (0.0, 5.0), "Temperature (°C)")
    assert out.exists() and out.stat().st_size > 0
