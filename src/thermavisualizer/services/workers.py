"""Background workers: long operations off the GUI thread (AGENTS §4, NFR)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from thermavisualizer.core.geometry import build_volume_mask
from thermavisualizer.core.interpolation import (
    InterpolationSettings,
    Interpolator,
    build_voxel_grid,
)
from thermavisualizer.core.models import ImportProfile, Obstacle, ParsedFile, Quantity, Space
from thermavisualizer.core.slicing import SliceSpec
from thermavisualizer.core.statistics import AggregationMethod, aggregate_series, moving_average
from thermavisualizer.core.validation import ValidationReport, validate_path
from thermavisualizer.services.cache import (
    CacheKey,
    InterpolationCache,
    interpolator_key,
    volume_cache_key,
)

logger = logging.getLogger(__name__)

CancelCheck = Callable[[], bool]
ProgressReport = Callable[[int], None]


class FunctionWorker(QThread):
    """Run ``task(cancel_check, report_progress)`` off the GUI thread.

    Signals (queued to the GUI thread): ``progress_changed`` (0..100),
    ``result_ready`` (task return value), ``error_occurred`` (message),
    ``work_cancelled``. Cancellation is cooperative: tasks poll the check.
    """

    progress_changed = Signal(int)
    result_ready = Signal(object)
    error_occurred = Signal(str)
    work_cancelled = Signal()

    def __init__(
        self,
        task: Callable[[CancelCheck, ProgressReport], Any],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation; tasks stop at their next check."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """True once cancellation has been requested."""
        return self._cancelled

    def run(self) -> None:
        """Execute the task; never swallow failures (AGENTS §6)."""
        try:
            result = self._task(self.is_cancelled, self.progress_changed.emit)
        except Exception as error:
            logger.exception("worker task failed")
            self.error_occurred.emit(str(error))
            return
        if self._cancelled:
            self.work_cancelled.emit()
        else:
            self.result_ready.emit(result)


@dataclass(frozen=True)
class FileLoadResult:
    """Outcome of loading one data file (worker → GUI payload)."""

    path: str
    profile_name: str
    parsed: ParsedFile | None
    report: ValidationReport


def load_data_files(
    jobs: Sequence[tuple[Path, ImportProfile]],
    cancel_check: CancelCheck,
    report_progress: ProgressReport,
) -> list[FileLoadResult]:
    """Read and structurally validate each (path, profile) pair (VAL-01/02).

    Progress is reported per file; cancellation is checked between files.
    """
    results: list[FileLoadResult] = []
    total = max(len(jobs), 1)
    for index, (path, profile) in enumerate(jobs):
        if cancel_check():
            break
        parsed, report = validate_path(path, profile)
        results.append(FileLoadResult(str(path), profile.name, parsed, report))
        report_progress(int(100 * (index + 1) / total))
    return results


@dataclass(frozen=True)
class InterpolationJob:
    """Immutable description of one interpolation run (INT-07).

    Units: positions in metres; values in °C or %RH depending on ``quantity``.
    """

    space: Space
    obstacles: tuple[Obstacle, ...]
    positions: np.ndarray  # (N, 3) metres, aligned-dataset order
    times: np.ndarray  # datetime64[ns], UTC
    values: np.ndarray  # (T, N) canonical units
    settings: InterpolationSettings
    quantity: Quantity
    aggregation: AggregationMethod
    time_index: int
    range_start: int
    range_end: int  # inclusive
    logger_ids: tuple[str, ...]
    temporal_window: int = 1


@dataclass(frozen=True)
class InterpolationResult:
    """One computed or cache-served volume with display context."""

    volume: np.ndarray
    quantity: Quantity
    settings: InterpolationSettings
    aggregation: AggregationMethod
    time_label: str
    cache_key: CacheKey
    from_cache: bool
    positions: np.ndarray
    logger_ids: tuple[str, ...]


def job_time_key(job: InterpolationJob) -> CacheKey:
    """Hashable time selector for cache keys (INT-07), incl. temporal window."""
    window = int(job.temporal_window)
    if job.aggregation is AggregationMethod.INSTANT:
        return ("instant", int(job.time_index), window)
    return ("range", int(job.range_start), int(job.range_end), window)


def job_time_label(job: InterpolationJob) -> str:
    """Human-readable label of the job's time selection (UTC)."""
    if job.aggregation is AggregationMethod.INSTANT:
        return str(job.times[job.time_index])
    start = str(job.times[job.range_start])
    end = str(job.times[job.range_end])
    return f"{job.aggregation.value} {start} → {end}"


def interpolate_volume_job(
    job: InterpolationJob,
    cancel_check: CancelCheck,
    report_progress: ProgressReport,
    cache: InterpolationCache | None = None,
) -> InterpolationResult | None:
    """Compute one masked volume off the GUI thread (INT-07).

    Uses the volume cache, reuses precomputed interpolator weights (INT-09),
    and checks ``cancel_check`` between phases. Returns None when cancelled.
    """
    report_progress(5)
    grid = build_voxel_grid(job.space, job.settings.resolution)
    mask = build_volume_mask(
        job.space, list(job.obstacles), grid.x_coords, grid.y_coords, grid.z_coords
    )
    time_key = job_time_key(job)
    key = volume_cache_key(
        job.quantity, job.settings, job.positions, grid, job.aggregation, time_key
    )
    if cache is not None:
        hit = cache.get_volume(key)
        if hit is not None:
            report_progress(100)
            return InterpolationResult(
                hit,
                job.quantity,
                job.settings,
                job.aggregation,
                job_time_label(job),
                key,
                True,
                positions=job.positions,
                logger_ids=job.logger_ids,
            )
    if cancel_check():
        return None
    interpolator = (
        cache.get_interpolator(interpolator_key(job.settings, job.positions, grid, mask))
        if cache is not None
        else None
    )
    if interpolator is None:
        interpolator = Interpolator(grid, job.positions, job.settings, mask)
        if cache is not None:
            cache.put_interpolator(
                interpolator_key(job.settings, job.positions, grid, mask), interpolator
            )
    report_progress(60)
    if cancel_check():
        return None
    series = job.values
    if job.temporal_window > 1:
        series = moving_average(series, job.temporal_window)
    if job.aggregation is AggregationMethod.INSTANT:
        selected = series[job.time_index]
    else:
        block = series[job.range_start : job.range_end + 1]
        selected = np.asarray(aggregate_series(block, job.aggregation), dtype=float)
    volume = interpolator.interpolate(selected)
    if cancel_check():
        return None
    if cache is not None:
        cache.put_volume(key, volume)
    report_progress(100)
    return InterpolationResult(
        volume,
        job.quantity,
        job.settings,
        job.aggregation,
        job_time_label(job),
        key,
        False,
        positions=job.positions,
        logger_ids=job.logger_ids,
    )


@dataclass(frozen=True)
class MovieJob:
    """Everything needed to render an export movie (EXP-02). Units: metres, °C/%RH."""

    output_path: str
    space: Space
    obstacles: tuple[Obstacle, ...]
    positions: np.ndarray
    logger_ids: tuple[str, ...]
    times: np.ndarray
    values: np.ndarray  # (T, N)
    settings: InterpolationSettings
    quantity: Quantity
    range_start: int
    range_end: int  # inclusive sample indices
    step_stride: int
    fps: int
    width: int
    height: int
    colormap: str | list[str]
    clim: tuple[float, float] | None
    slices: tuple[SliceSpec, ...]
    burn_timestamp: bool
    burn_colorbar: bool


@dataclass(frozen=True)
class MovieResult:
    """Outcome of a movie export."""

    path: str
    frames: int
    format: str  # "mp4" or "gif"


def export_movie_task(
    job: MovieJob, cancel_check: CancelCheck, report_progress: ProgressReport
) -> MovieResult | None:
    """Render and write the movie off the GUI thread (EXP-02).

    Returns None when cancelled. Rendering and movie IO are imported lazily so
    this module stays importable headless.
    """
    from thermavisualizer.io.exporters import ExportError, write_movie
    from thermavisualizer.rendering.offscreen import render_movie_frames

    frames = render_movie_frames(job, cancel_check, report_progress)
    try:
        path, fmt, count = write_movie(Path(job.output_path), frames, job.fps)
    except ExportError:
        if cancel_check():
            return None
        raise
    if cancel_check():  # cancelled after the last frame: drop the partial file
        Path(path).unlink(missing_ok=True)
        return None
    return MovieResult(str(path), count, fmt)
