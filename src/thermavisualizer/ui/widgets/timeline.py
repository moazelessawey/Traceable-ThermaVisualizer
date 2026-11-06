"""Timeline panel: range slider bound to aligned data + transport (PRD 4.4).

The two handles select the analysis range; the playhead marks the current
instant. The selection drives the 3D view, plots, statistics, and exports.
Units: timestamps are naive-UTC.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.alignment import nearest_time_index, time_range_indices
from thermavisualizer.core.models import TimelineMode
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.timeline import TimelineController
from thermavisualizer.ui.widgets.range_slider import RangeSlider

_SPEED_ITEMS = (("0.5×", 0.5), ("1×", 1.0), ("2×", 2.0), ("4×", 4.0))


def _format_duration(delta: np.timedelta64) -> str:
    """Human-readable duration like '2d 3h 15m'."""
    total_minutes = int(delta / np.timedelta64(1, "m"))
    days, remainder = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class TimelinePanel(QWidget):
    """Range selection, playhead, and playback controls for the study timeline."""

    def __init__(
        self,
        model: ProjectModel,
        controller: TimelineController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._controller = controller
        self._times: np.ndarray | None = None
        self._updating = False  # guard for model <-> slider sync loops

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        controls = QHBoxLayout()
        style = self.style()
        pixmap = QStyle.StandardPixmap
        self.play_button = QToolButton(self)
        self.play_button.setIcon(style.standardIcon(pixmap.SP_MediaPlay))
        self.play_button.setToolTip("Play/pause the timeline")
        self.play_button.clicked.connect(self._controller.toggle)
        self.step_back_button = QToolButton(self)
        self.step_back_button.setIcon(style.standardIcon(pixmap.SP_MediaSeekBackward))
        self.step_back_button.setToolTip("Step one sample back")
        self.step_back_button.clicked.connect(self._controller.step_backward)
        self.step_forward_button = QToolButton(self)
        self.step_forward_button.setIcon(style.standardIcon(pixmap.SP_MediaSeekForward))
        self.step_forward_button.setToolTip("Step one sample forward")
        self.step_forward_button.clicked.connect(self._controller.step_forward)
        self.loop_button = QToolButton(self)
        self.loop_button.setIcon(style.standardIcon(pixmap.SP_BrowserReload))
        self.loop_button.setToolTip("Loop playback at the range end")
        self.loop_button.setCheckable(True)
        self.loop_button.setChecked(controller.loop())
        self.loop_button.toggled.connect(self._controller.set_loop)
        self.speed_combo = QComboBox(self)
        for label, value in _SPEED_ITEMS:
            self.speed_combo.addItem(label, value)
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.setToolTip("Playback speed")
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("Aggregate range", TimelineMode.AGGREGATE)
        self.mode_combo.addItem("Instant at playhead", TimelineMode.INSTANT)
        self.mode_combo.setToolTip("How the selected range feeds the views (PRD 4.4)")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.full_range_button = QPushButton("Full range", self)
        self.full_range_button.clicked.connect(self._on_full_range)
        self.zoom_button = QPushButton("Zoom to selection", self)
        self.zoom_button.clicked.connect(self._zoom_to_selection)
        for widget in (
            self.play_button,
            self.step_back_button,
            self.step_forward_button,
            self.loop_button,
        ):
            controls.addWidget(widget)
        controls.addWidget(self.speed_combo)
        controls.addWidget(self.mode_combo)
        controls.addWidget(self.full_range_button)
        controls.addWidget(self.zoom_button)
        controls.addStretch(1)
        self.duration_label = QLabel("", self)
        controls.addWidget(self.duration_label)
        outer.addLayout(controls)

        slider_row = QHBoxLayout()
        self.start_label = QLabel("—", self)
        self.end_label = QLabel("—", self)
        self._slider = RangeSlider(self)
        slider_row.addWidget(self.start_label)
        slider_row.addWidget(self._slider, 1)
        slider_row.addWidget(self.end_label)
        outer.addLayout(slider_row)

        self._slider.range_changed.connect(self._on_slider_range)
        self._slider.playhead_changed.connect(self._on_slider_playhead)
        model.aligned_changed.connect(self._rebuild_from_dataset)
        model.timeline_changed.connect(self._sync_from_model)
        model.playhead_changed.connect(self._sync_playhead_from_model)
        model.timeline_mode_changed.connect(self._update_playhead_visibility)
        controller.playback_started.connect(self._on_playback_started)
        controller.playback_paused.connect(self._on_playback_paused)
        self._set_transport_enabled(False)
        self._rebuild_from_dataset()

    # ------------------------------------------------------------ accessors

    @property
    def slider(self) -> RangeSlider:
        """Two-handle range slider (start/end of the selected time range)."""
        return self._slider

    @property
    def controller(self) -> TimelineController:
        """Playback controller driving this timeline."""
        return self._controller

    # ------------------------------------------------------- slider -> model

    def _on_slider_range(self, low: int, high: int) -> None:
        if self._updating or self._times is None:
            return
        self._model.set_timeline_range(self._times[low], self._times[high])

    def _on_slider_playhead(self, value: int) -> None:
        if self._updating or self._times is None:
            return
        self._model.set_playhead(self._times[value])

    def _on_speed_changed(self, index: int) -> None:
        data = self.speed_combo.itemData(index)
        if data is not None:
            self._controller.set_speed(float(data))

    def _on_mode_changed(self, index: int) -> None:
        data = self.mode_combo.itemData(index)
        if data is not None:
            self._model.set_timeline_mode(TimelineMode(str(data)))

    def _on_full_range(self) -> None:
        if self._times is None:
            return
        self._updating = True
        try:
            self._slider.set_bounds(0, self._times.size - 1)
        finally:
            self._updating = False
        self._controller.snap_full_range()

    def _zoom_to_selection(self) -> None:
        if self._times is None:
            return
        low, high = self._slider.selected_range()
        if high <= low:
            return
        self._updating = True
        try:
            self._slider.set_bounds(low, high)
            self._slider.set_range(low, high)
        finally:
            self._updating = False

    # ------------------------------------------------------- model -> slider

    def _sync_from_model(self) -> None:
        if self._times is None:
            return
        indices = time_range_indices(self._times, *self._model.timeline_range())
        if indices is None:
            indices = (0, self._times.size - 1)
        low, high = indices
        if self._slider.selected_range() != (low, high):
            self._updating = True
            try:
                self._slider.set_range(low, high)
            finally:
                self._updating = False
        self._update_labels()
        self._update_playhead_visibility()

    def _sync_playhead_from_model(self, _time: object = None) -> None:
        if self._times is None:
            return
        playhead = self._model.playhead()
        if playhead is None:
            return
        index = nearest_time_index(self._times, playhead)
        if self._slider.playhead != index:
            self._updating = True
            try:
                self._slider.set_playhead(index)
            finally:
                self._updating = False
        self._update_playhead_visibility()

    def _update_playhead_visibility(self) -> None:
        visible = (
            self._controller.is_playing() or self._model.timeline_mode() is TimelineMode.INSTANT
        )
        self._slider.set_playhead_visible(visible)

    def _update_labels(self) -> None:
        if self._times is None:
            self.start_label.setText("—")
            self.end_label.setText("—")
            self.duration_label.setText("")
            return
        start, end = self._model.timeline_range()
        if start is None or end is None:
            start, end = self._times[0], self._times[-1]
        self.start_label.setText(np.datetime_as_string(start, unit="m"))
        self.end_label.setText(np.datetime_as_string(end, unit="m"))
        self.duration_label.setText(_format_duration(end - start))

    # ------------------------------------------------------------ transport

    def _on_playback_started(self) -> None:
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self._update_playhead_visibility()

    def _on_playback_paused(self) -> None:
        self.play_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self._update_playhead_visibility()

    def _set_transport_enabled(self, enabled: bool) -> None:
        for widget in (
            self.play_button,
            self.step_back_button,
            self.step_forward_button,
            self.loop_button,
            self.speed_combo,
            self.mode_combo,
            self.full_range_button,
            self.zoom_button,
            self._slider,
        ):
            widget.setEnabled(enabled)

    def _rebuild_from_dataset(self) -> None:
        """Re-bind the slider to the current aligned time base."""
        times = self._controller.times()
        self._times = times
        if times is None or times.size < 2:
            self._set_transport_enabled(False)
            self.start_label.setText("—")
            self.end_label.setText("—")
            self.duration_label.setText("")
            return
        self._set_transport_enabled(True)
        self._updating = True
        try:
            self._slider.set_bounds(0, times.size - 1)
            self._slider.set_range(0, times.size - 1)
            self._slider.set_playhead(0)
        finally:
            self._updating = False
        if self._model.timeline_range() == (None, None):
            self._model.set_timeline_range(times[0], times[-1])
        if self._model.playhead() is None:
            self._model.set_playhead(times[0])
        self._sync_from_model()
        self._sync_playhead_from_model()
