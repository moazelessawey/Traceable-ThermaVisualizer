"""PyVista backend smoke test (AGENTS §8: dimensions/non-blank, not pixel-exact)."""

from __future__ import annotations

import pytest
from pytestqt.qtbot import QtBot

pytest.importorskip("pyvista")
pytest.importorskip("pyvistaqt")

import os
import sys

import numpy as np

from thermavisualizer.core.models import (
    Layer,
    Logger,
    Obstacle,
    ObstacleShape,
    ObstacleType,
    PolygonFootprint,
    Space,
)
from thermavisualizer.rendering.pyvista_backend import PyVistaScene
from thermavisualizer.rendering.scene import ObstacleStyle
from thermavisualizer.core.interpolation import build_voxel_grid
from thermavisualizer.core.slicing import SliceAxis, extract_axis_slice

# Acceptance item 10 preview: an L-shaped footprint, not a box.
L_SHAPE = PolygonFootprint(((0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (2.0, 2.0), (2.0, 4.0), (0.0, 4.0)))


pytestmark = pytest.mark.skipif(
    sys.platform == "win32" and os.environ.get("CI", "").lower() in ("true", "1"),
    reason="OpenGL rendering is unavailable on Windows CI runners (no GPU); "
           "these smoke tests run locally and on Ubuntu CI",
)

def test_pyvista_scene_smoke(qtbot: QtBot) -> None:
    try:
        scene = PyVistaScene()
    except Exception as error:  # no usable GL context in this environment
        pytest.skip(f"OpenGL context unavailable: {error}")
    qtbot.addWidget(scene.widget())
    scene.widget().resize(320, 240)
    assert scene.widget().width() == 320

    space = Space(footprint=L_SHAPE, height=3.0)
    layer = Layer(
        name="mixed",
        height=0.5,
        loggers=[
            Logger("L1", 1.0, 1.0, 0.5),
            Logger("L2", 3.0, 1.0, 0.5),
            Logger("L3", 1.0, 3.0, 1.5),
        ],
    )
    obstacle = Obstacle(
        name="rack",
        obstacle_type=ObstacleType.RACK,
        shape=ObstacleShape.BOX,
        x=1.0,
        y=1.0,
        z=1.0,
        size_x=0.8,
        size_y=0.8,
        size_z=1.5,
        rotation_z_deg=45.0,
    )
    scene.set_space(space)
    scene.set_loggers([layer], "L1")
    scene.set_obstacles([obstacle], ObstacleStyle.TRANSPARENT)
    actors = scene._plotter.renderer.actors  # smoke-test internals on purpose
    assert len(actors) >= 4  # outline + layer cloud + selection marker + obstacle
    scene.set_obstacles([], ObstacleStyle.SOLID)  # clearing must not raise
    scene.reset_camera()
    scene.shutdown()


def test_pyvista_heatmap_smoke(qtbot: QtBot) -> None:
    try:
        scene = PyVistaScene()
    except Exception as error:
        pytest.skip(f"OpenGL context unavailable: {error}")
    qtbot.addWidget(scene.widget())
    scene.widget().resize(320, 240)

    from thermavisualizer.core.interpolation import build_voxel_grid
    from thermavisualizer.core.slicing import SliceAxis, extract_axis_slice
    from thermavisualizer.rendering.scene import PresetView

    space = Space(footprint=L_SHAPE, height=3.0)
    grid = build_voxel_grid(space, 1.0)
    _, _, zs = grid.meshgrid()
    volume = zs  # linear in height; masked L-shape handled by slicing
    slice_data = extract_axis_slice(volume, grid, space, [], SliceAxis.Z, 1.5)

    scene.set_space(space)
    scene.show_slice("z1", slice_data, "viridis", (0.0, 3.0), 0.8, "Temperature (°C)")
    scene.set_logger_scalars(
        np.array([[1.0, 1.0, 0.5], [1.0, 3.0, 1.5]]),
        ["L1", "L2"],
        np.array([20.0, 22.0]),
        "viridis",
        (18.0, 24.0),
        "Temperature (°C)",
    )
    scene.set_axes_visible(True)
    scene.set_labels_visible(True)
    scene.preset_view(PresetView.ISOMETRIC)
    assert len(scene._plotter.renderer.actors) >= 3  # smoke-test internals on purpose
    scene.remove_slice("z1")
    scene.clear_slices()
    scene.shutdown()


def test_pyvista_repeated_updates_do_not_stack_actors(qtbot: QtBot) -> None:
    """Regression: re-rendering replaces actors; nothing overlaps (user report)."""
    try:
        scene = PyVistaScene()
    except Exception as error:
        pytest.skip(f"OpenGL context unavailable: {error}")
    qtbot.addWidget(scene.widget())
    scene.widget().resize(320, 240)

    from thermavisualizer.core.interpolation import build_voxel_grid
    from thermavisualizer.core.slicing import SliceAxis, extract_axis_slice

    space = Space(footprint=L_SHAPE, height=3.0)
    grid = build_voxel_grid(space, 1.0)
    _, _, zs = grid.meshgrid()
    slice_data = extract_axis_slice(zs, grid, space, [], SliceAxis.Z, 1.5)

    def content_counts() -> dict[str, int]:
        counts: dict[str, int] = {}
        for name in scene._plotter.renderer.actors:
            for prefix in ("space_outline", "slice:", "logger_markers"):
                if name.startswith(prefix):
                    counts[prefix] = counts.get(prefix, 0) + 1
        return counts

    scene.set_space(space)
    scene.show_slice("z1", slice_data, "viridis", (0.0, 3.0), 0.8, "T (°C)")
    scene.set_logger_scalars(
        np.array([[1.0, 1.0, 0.5]]),
        ["L1"],
        np.array([20.0]),
        "viridis",
        (18.0, 24.0),
        "T (°C)",
    )
    expected = {"space_outline": 1, "slice:": 1, "logger_markers": 1}
    assert content_counts() == expected

    for _ in range(3):  # simulate repeated recompute cycles
        scene.show_slice("z1", slice_data, "viridis", (0.0, 3.0), 0.8, "T (°C)")
        scene.set_logger_scalars(
            np.array([[1.0, 1.0, 0.5]]),
            ["L1"],
            np.array([21.0]),
            "jet",
            (18.0, 24.0),
            "T (°C)",
        )
        scene.set_space(space)
    assert content_counts() == expected
    scene.shutdown()
