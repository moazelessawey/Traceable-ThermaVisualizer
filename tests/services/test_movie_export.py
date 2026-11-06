"""Movie export orchestration with a fake frame source (EXP-02, no GL needed)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from thermavisualizer.core.interpolation import InterpolationSettings
from thermavisualizer.core.models import BoxFootprint, Quantity, Space
from thermavisualizer.services.workers import MovieJob, export_movie_task

import thermavisualizer.rendering.offscreen as offscreen_module


def _job(tmp_path: Path, name: str = "movie.gif") -> MovieJob:
    times = np.datetime64("2024-03-01T08:00", "ns") + np.arange(2) * np.timedelta64(60, "s")
    return MovieJob(
        output_path=str(tmp_path / name),
        space=Space(footprint=BoxFootprint(0, 0, 1, 1), height=1.0),
        obstacles=(),
        positions=np.array([[0.5, 0.5, 0.5]]),
        logger_ids=("L1",),
        times=times,
        values=np.array([[20.0], [21.0]]),
        settings=InterpolationSettings(),
        quantity=Quantity.TEMPERATURE,
        range_start=0,
        range_end=1,
        step_stride=1,
        fps=5,
        width=8,
        height=8,
        colormap="viridis",
        clim=(19.0, 22.0),
        slices=(),
        burn_timestamp=False,
        burn_colorbar=False,
    )


def test_export_movie_task_writes_gif(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frames = [np.full((8, 8, 3), 10, dtype=np.uint8), np.full((8, 8, 3), 200, dtype=np.uint8)]
    monkeypatch.setattr(offscreen_module, "render_movie_frames", lambda job, cc, rp: iter(frames))
    result = export_movie_task(_job(tmp_path), lambda: False, lambda percent: None)
    assert result is not None
    assert result.frames == 2
    assert result.format == "gif"
    assert Path(result.path).exists()


def test_export_movie_task_cancel_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = [np.zeros((8, 8, 3), dtype=np.uint8)]
    monkeypatch.setattr(offscreen_module, "render_movie_frames", lambda job, cc, rp: iter(frames))
    result = export_movie_task(_job(tmp_path), lambda: True, lambda percent: None)
    assert result is None
    assert not (tmp_path / "movie.gif").exists()
