"""Timeline playback controller (PRD 4.4; EXP-01 foundation).

Drives the playhead across the aligned time base with play/pause, stepping,
speed, and loop. A QTimer runs on the GUI thread; no heavy work happens here
(AGENTS §4). Units: aligned sample steps; timestamps naive-UTC.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from thermavisualizer.core.alignment import nearest_time_index, time_range_indices
from thermavisualizer.core.models import Quantity, TimelineMode
from thermavisualizer.services.project_model import ProjectModel


class TimelineController(QObject):
    """Playback driver for the study timeline."""

    playback_started = Signal()
    playback_paused = Signal()

    _TICK_MS = 100
    BASE_SAMPLES_PER_SECOND = 10.0  # samples advanced per second at speed 1.0

    def __init__(self, model: ProjectModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._playing = False
        self._speed = 1.0
        self._loop = True
        self._accumulator = 0.0

    # ---------------------------------------------------------------- state

    def times(self) -> np.ndarray | None:
        """Aligned time base (temperature preferred), or None."""
        for quantity in (Quantity.TEMPERATURE, Quantity.HUMIDITY):
            dataset = self._model.aligned_dataset(quantity)
            if dataset is not None:
                return dataset.times
        return None

    def range_indices(self) -> tuple[int, int] | None:
        """(low, high) sample indices of the current timeline selection."""
        times = self.times()
        if times is None or times.size == 0:
            return None
        start, end = self._model.timeline_range()
        if start is None or end is None:
            return 0, times.size - 1
        return time_range_indices(times, start, end)

    def playhead_index(self) -> int | None:
        """Sample index of the playhead (range start when unset)."""
        times = self.times()
        bounds = self.range_indices()
        if times is None or bounds is None:
            return None
        low, high = bounds
        playhead = self._model.playhead()
        if playhead is None:
            return low
        return max(low, min(high, nearest_time_index(times, playhead)))

    def is_playing(self) -> bool:
        """True while playback is running."""
        return self._playing

    def speed(self) -> float:
        """Playback speed multiplier (1.0 = 10 samples/second)."""
        return self._speed

    def loop(self) -> bool:
        """True when playback wraps at the range end."""
        return self._loop

    # -------------------------------------------------------------- control

    def play(self) -> None:
        """Start playback; no-op without an aligned time base (EXP-01)."""
        bounds = self.range_indices()
        times = self.times()
        if self._playing or bounds is None or times is None:
            return
        if self._model.timeline_mode() is TimelineMode.AGGREGATE:
            self._model.set_timeline_mode(TimelineMode.INSTANT)
        low, high = bounds
        index = self.playhead_index()
        if index is None or (index >= high and not self._loop):
            self._model.set_playhead(times[low])  # restart from the range start
        self._accumulator = 0.0
        self._playing = True
        self._timer.start()
        self.playback_started.emit()

    def pause(self) -> None:
        """Pause playback."""
        if not self._playing:
            return
        self._playing = False
        self._timer.stop()
        self.playback_paused.emit()

    def toggle(self) -> None:
        """Toggle play/pause."""
        if self._playing:
            self.pause()
        else:
            self.play()

    def step_forward(self) -> None:
        """Move the playhead one sample forward within the range."""
        self._step(1)

    def step_backward(self) -> None:
        """Move the playhead one sample backward within the range."""
        self._step(-1)

    def set_speed(self, speed: float) -> None:
        """Set the playback speed multiplier (must be positive)."""
        if speed <= 0:
            raise ValueError("playback speed must be positive")
        self._speed = float(speed)

    def set_loop(self, loop: bool) -> None:
        """Enable/disable wrap-around at the range end."""
        self._loop = bool(loop)

    def snap_full_range(self) -> None:
        """Select the full time range and move the playhead to the start."""
        times = self.times()
        if times is None or times.size == 0:
            return
        self._model.set_timeline_range(times[0], times[-1])
        self._model.set_playhead(times[0])

    # ------------------------------------------------------------- internal

    def _step(self, delta: int) -> None:
        times = self.times()
        bounds = self.range_indices()
        if times is None or bounds is None:
            return
        low, high = bounds
        index = self.playhead_index()
        index = low if index is None else index
        self._model.set_playhead(times[max(low, min(high, index + delta))])

    def _tick(self) -> None:
        times = self.times()
        bounds = self.range_indices()
        if times is None or bounds is None:
            self.pause()
            return
        low, high = bounds
        self._accumulator += self._speed * self.BASE_SAMPLES_PER_SECOND * self._TICK_MS / 1000.0
        steps = int(self._accumulator)
        if steps < 1:
            return
        self._accumulator -= steps
        index = self.playhead_index()
        index = low if index is None else index
        new_index = index + steps
        if new_index > high:
            if self._loop:
                span = high - low + 1
                new_index = low + (new_index - high - 1) % span
            else:
                self._model.set_playhead(times[high])
                self.pause()
                return
        self._model.set_playhead(times[new_index])
