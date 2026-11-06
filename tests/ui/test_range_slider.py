"""Behaviour tests for the custom two-handle RangeSlider (PRD 4.4)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from pytestqt.qtbot import QtBot

from thermavisualizer.ui.widgets.range_slider import RangeSlider


@pytest.fixture
def slider(qtbot: QtBot) -> RangeSlider:
    widget = RangeSlider()
    qtbot.addWidget(widget)
    widget.resize(215, 28)  # usable width 200 -> 2 px per unit for bounds 0..100
    widget.set_bounds(0, 100)
    widget.set_range(20, 80)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def test_initial_state(slider: RangeSlider) -> None:
    assert slider.selected_range() == (20, 80)
    assert (slider.minimum, slider.maximum) == (0, 100)


def test_set_range_emits(slider: RangeSlider, qtbot: QtBot) -> None:
    with qtbot.waitSignal(slider.range_changed, timeout=500) as blocker:
        slider.set_range(30, 70)
    assert blocker.args == [30, 70]


def test_set_range_rejects_crossing(slider: RangeSlider) -> None:
    with pytest.raises(ValueError, match="must be <= high"):
        slider.set_range(90, 10)


def test_set_bounds_rejects_inverted(slider: RangeSlider) -> None:
    with pytest.raises(ValueError, match="must be >= minimum"):
        slider.set_bounds(50, 10)


def test_set_bounds_clamps_values(slider: RangeSlider) -> None:
    slider.set_bounds(30, 90)
    assert slider.selected_range() == (30, 80)


def test_low_handle_drag_cannot_cross(slider: RangeSlider, qtbot: QtBot) -> None:
    start = QPoint(slider.value_to_x(20), 14)
    target = QPoint(slider.value_to_x(100), 14)
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(slider, target)
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=target)
    assert slider.low_value == slider.high_value == 80


def test_high_handle_drag(slider: RangeSlider, qtbot: QtBot) -> None:
    start = QPoint(slider.value_to_x(80), 14)
    target = QPoint(slider.value_to_x(30), 14)
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(slider, target)
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=target)
    assert slider.selected_range() == (20, 30)


def test_playhead_signal_and_clamp(slider: RangeSlider, qtbot: QtBot) -> None:
    slider.set_playhead_visible(True)
    with qtbot.waitSignal(slider.playhead_changed, timeout=500) as blocker:
        slider.set_playhead(55)
    assert blocker.args == [55]
    slider.set_playhead(500)
    assert slider.playhead == 100


def test_keyboard_moves_active_handle(slider: RangeSlider, qtbot: QtBot) -> None:
    qtbot.keyClick(slider, Qt.Key.Key_Right)
    assert slider.low_value == 21
    qtbot.keyClick(slider, Qt.Key.Key_Left)
    assert slider.low_value == 20

def test_overlapping_handles_drag_right_moves_high(qtbot) -> None:  # TypeError regression
    slider = RangeSlider()
    qtbot.addWidget(slider)
    slider.resize(215, 28)
    slider.set_bounds(0, 100)
    slider.set_range(50, 50)
    x = int(slider.value_to_x(50))
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(x, 14))
    qtbot.mouseMove(slider, QPoint(x + 40, 14))
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(x + 40, 14))
    assert slider.low_value == 50
    assert slider.high_value > 50


def test_overlapping_handles_drag_left_moves_low(qtbot) -> None:
    slider = RangeSlider()
    qtbot.addWidget(slider)
    slider.resize(215, 28)
    slider.set_bounds(0, 100)
    slider.set_range(50, 50)
    x = int(slider.value_to_x(50))
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(x, 14))
    qtbot.mouseMove(slider, QPoint(x - 40, 14))
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(x - 40, 14))
    assert slider.high_value == 50
    assert slider.low_value < 50


def test_overlapping_handles_at_maximum_grab_low(qtbot) -> None:
    slider = RangeSlider()
    qtbot.addWidget(slider)
    slider.resize(215, 28)
    slider.set_bounds(0, 100)
    slider.set_range(100, 100)
    x = int(slider.value_to_x(100))
    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(x, 14))
    qtbot.mouseMove(slider, QPoint(x - 40, 14))
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(x - 40, 14))
    assert slider.high_value == 100
    assert slider.low_value < 100