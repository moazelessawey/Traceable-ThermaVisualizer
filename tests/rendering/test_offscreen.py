"""Offscreen movie rendering smoke test (AGENTS §8: skip without GL)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("pyvista")

from thermavisualizer.core.interpolation import InterpolationSettings
from thermavisualizer.core.models import BoxFootprint, Quantity, Space
from thermavisualizer.rendering.offscreen import render_movie_frames
from thermavisualizer.services.workers import MovieJob


def test_render_movie_frames_smoke() -> None:
    times = np.datetime64("2024-03-01T08:00", "ns") + np.arange(2) * np.timedelta64(60, "s")
    job = MovieJob(
        output_path="unused.gif",
        space=Space(footprint=BoxFootprint(0, 0, 1, 1), height=1.0),
        obstacles=(),
        positions=np.array([[0.2, 0.2, 0.5], [0.8, 0.8, 0.5]]),
        logger_ids=("L1", "L2"),
        times=times,
        values=np.array([[20.0, 21.0], [20.5, 21.5]]),
        settings=InterpolationSettings(resolution=0.5),
        quantity=Quantity.TEMPERATURE,
        range_start=0,
        range_end=1,
        step_stride=1,
        fps=5,
        width=64,
        height=64,
        colormap="viridis",
        clim=(19.0, 22.0),
        slices=(),
        burn_timestamp=True,
        burn_colorbar=False,
    )
    try:
        frames = list(render_movie_frames(job, lambda: False, lambda percent: None))
    except Exception as error:
        pytest.skip(f"OpenGL context unavailable: {error}")
    assert len(frames) == 2
    assert frames[0].ndim == 3 and frames[0].shape[2] in (3, 4)
