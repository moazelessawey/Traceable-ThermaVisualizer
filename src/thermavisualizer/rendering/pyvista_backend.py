"""PyVista/VTK implementation of SceneRenderer (CFG-10; M3-ready).

Only modules inside ``rendering/`` may import this (AGENTS rule). Units:
metres; VTK's coordinate system is right-handed Z-up, matching the Space.
"""

from __future__ import annotations

import logging
import math
import os
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pyvista as pv
from PySide6.QtWidgets import QWidget
from pyvistaqt import QtInteractor

from thermavisualizer.core.models import (
    BoxFootprint,
    Layer,
    Obstacle,
    ObstacleShape,
    Space,
)
from thermavisualizer.core.slicing import SliceData
from thermavisualizer.rendering.scene import ObstacleStyle, PresetView, SceneRenderer

logger = logging.getLogger(__name__)

_LAYER_COLORS = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#17becf",
)
_SELECTED_COLOR = "#ffd60a"
_SPACE_COLOR = "#555555"
_OBSTACLE_OPACITY_TRANSPARENT = 0.35


def pyvista_backend_available() -> tuple[bool, str]:
    """Return ``(available, reason)`` from an import check (no GL created)."""
    try:
        import pyvista  # noqa: F401
        import pyvistaqt  # noqa: F401
    except ImportError as error:
        return False, f"PyVista not importable: {error}"
    return True, ""


class PyVistaScene(SceneRenderer):
    """PyVista-backed scene: space outline, logger markers, obstacles."""

    def __init__(self, parent: QWidget | None = None, plotter: object | None = None) -> None:
        self._plotter = plotter if plotter is not None else QtInteractor(parent)
        self._space_actors: list[pv.Actor] = []
        self._logger_actors: list[pv.Actor] = []
        self._obstacle_actors: list[pv.Actor] = []
        self._slice_actors: dict[str, object] = {}
        self._label_actor: object | None = None
        self._axes_actor: object | None = None
        self._scalar_bar: object | None = None
        self._labels_visible = False
        self._marker_state: tuple[np.ndarray, tuple[str, ...]] | None = None
        self._colorbar_enabled = True
        self._space_actors: list[str] = []
        self._logger_actors: list[str] = []
        self._obstacle_actors: list[str] = []
        self._slice_actors: dict[str, str] = {}  # slice key -> actor name

    def widget(self) -> QWidget:
        """The embeddable VTK/Qt widget."""
        return self._plotter

    # -------------------------------------------------------------- scene

    def set_space(self, space: Space) -> None:
        """Draw the footprint outline extruded from z=0 to the space height."""
        self._remove(self._space_actors)
        vertices = _footprint_vertices(space)
        count = len(vertices)
        bottom = [(x, y, 0.0) for x, y in vertices]
        top = [(x, y, space.height) for x, y in vertices]
        points = np.array(bottom + top, dtype=float)
        lines: list[int] = []
        for index in range(count):
            next_index = (index + 1) % count
            lines += [2, index, next_index]
            lines += [2, count + index, count + next_index]
            lines += [2, index, count + index]
        mesh = pv.PolyData(points, lines=np.array(lines))
        self._plotter.add_mesh(mesh, color=_SPACE_COLOR, line_width=2.0, name="space_outline")
        self._space_actors.append("space_outline")

    def set_loggers(self, layers: Sequence[Layer], selected_logger_id: str | None) -> None:
        """Draw each layer's loggers as spheres, colored per layer."""
        self._remove(self._logger_actors)
        for index, layer in enumerate(layers):
            if not layer.loggers:
                continue
            positions = np.array(
                [[logger.x, logger.y, logger.z] for logger in layer.loggers], dtype=float
            )
            color = _LAYER_COLORS[index % len(_LAYER_COLORS)]
            name = f"loggers:{index}"
            self._plotter.add_mesh(
                pv.PolyData(positions),
                color=color,
                render_points_as_spheres=True,
                point_size=9,
                name=name,
            )
            self._logger_actors.append(name)
        if selected_logger_id is not None:
            for layer in layers:
                for logger in layer.loggers:
                    if logger.logger_id == selected_logger_id:
                        position = np.array([[logger.x, logger.y, logger.z]], dtype=float)
                        self._plotter.add_mesh(
                            pv.PolyData(position),
                            color=_SELECTED_COLOR,
                            render_points_as_spheres=True,
                            point_size=15,
                            name="logger_selected",
                        )
                        self._logger_actors.append("logger_selected")
                        return

    def set_obstacles(self, obstacles: Sequence[Obstacle], style: ObstacleStyle) -> None:
        """Draw obstacles (callers pass only visible ones)."""
        self._remove(self._obstacle_actors)
        for obstacle in obstacles:
            mesh = self._obstacle_mesh(obstacle)
            name = f"obstacle:{obstacle.obstacle_id}"
            if style is ObstacleStyle.WIREFRAME:
                self._plotter.add_mesh(
                    mesh, color=obstacle.colour, style="wireframe", line_width=1.5, name=name
                )
            elif style is ObstacleStyle.TRANSPARENT:
                self._plotter.add_mesh(
                    mesh,
                    color=obstacle.colour,
                    opacity=_OBSTACLE_OPACITY_TRANSPARENT,
                    name=name,
                )
            else:
                self._plotter.add_mesh(mesh, color=obstacle.colour, name=name)
            self._obstacle_actors.append(name)

    def shutdown(self) -> None:
        """Close the VTK render window (idempotent)."""
        try:
            self._plotter.close()
        except Exception:  # pragma: no cover - teardown must never raise
            pass

    # ---------------------------------------------------- heat-map rendering

    def set_logger_scalars(
        self,
        positions: np.ndarray,
        logger_ids: Sequence[str],
        values: np.ndarray | None,
        colormap: str | Sequence[str],
        clim: tuple[float, float] | None,
        scalar_title: str = "",
    ) -> None:
        """Render logger markers colored by current values (VIS-03)."""
        positions = np.asarray(positions, dtype=float)
        if values is not None and len(values) != positions.shape[0]:
            raise ValueError("values must contain one entry per position")
        self._remove(self._logger_actors)
        self._marker_state = (positions, tuple(logger_ids))
        if positions.size == 0:
            return
        cloud = pv.PolyData(positions)
        if not isinstance(colormap, str):
            colormap = list(colormap)  # PyVista requires str/list/Colormap
        if values is None:
            self._plotter.add_mesh(
                cloud,
                color=_SPACE_COLOR,
                render_points_as_spheres=True,
                point_size=9,
                name="logger_markers",
            )
        else:
            cloud["values"] = np.asarray(values, dtype=float)
            actor = self._plotter.add_mesh(
                cloud,
                scalars="values",
                cmap=colormap,
                clim=clim,
                render_points_as_spheres=True,
                point_size=9,
                nan_opacity=0.0,
                show_scalar_bar=False,
                name="logger_markers",
            )
            self._update_scalar_bar(actor, scalar_title)
        self._logger_actors.append("logger_markers")
        if self._labels_visible:
            self._refresh_labels()

    def set_labels_visible(self, visible: bool) -> None:
        """Show/hide logger ID labels (VIS-03)."""
        self._labels_visible = visible
        if visible:
            self._refresh_labels()
        else:
            self._remove_labels()

    def show_slice(
        self,
        key: str,
        slice_data: SliceData,
        colormap: str | Sequence[str],
        clim: tuple[float, float] | None,
        opacity: float,
        scalar_title: str = "",
    ) -> None:
        """Show a color-mapped slice surface (SLC-01/02); NaN regions stay hidden."""
        self.remove_slice(key)
        points = slice_data.points.reshape(slice_data.u_count, slice_data.v_count, 3)
        mesh = pv.StructuredGrid(points[..., 0], points[..., 1], points[..., 2])
        mesh["values"] = slice_data.values.reshape(slice_data.u_count, slice_data.v_count).ravel()
        name = f"slice:{key}"
        if not isinstance(colormap, str):
            colormap = list(colormap)  # PyVista requires str/list/Colormap
        actor = self._plotter.add_mesh(
            mesh,
            scalars="values",
            cmap=colormap,
            clim=clim,
            opacity=opacity,
            nan_opacity=0.0,
            show_scalar_bar=False,
            name=name,
        )
        self._slice_actors[key] = name
        self._update_scalar_bar(actor, scalar_title)

    def remove_slice(self, key: str) -> None:
        """Remove the slice stored under ``key``."""
        name = self._slice_actors.pop(key, None)
        if name is not None:
            try:
                self._plotter.remove_actor(name)
            except Exception:
                logger.debug("slice actor '%s' already removed", name)

    def clear_slices(self) -> None:
        """Remove all slice surfaces."""
        for key in list(self._slice_actors):
            self.remove_slice(key)

    def set_axes_visible(self, visible: bool) -> None:
        """Show/hide the dimension-labelled axes grid (VIS-02)."""
        if visible and self._axes_actor is None:
            self._axes_actor = self._plotter.show_grid()
        elif not visible and self._axes_actor is not None:
            try:
                self._plotter.remove_actor(self._axes_actor)
            except Exception:  # see remove_slice
                pass
            self._axes_actor = None

    def preset_view(self, view: PresetView) -> None:
        """Apply a preset camera orientation, then fit the scene (VIS-01)."""
        bounds = self._plotter.bounds
        center = (
            (bounds[0] + bounds[1]) / 2.0,
            (bounds[2] + bounds[3]) / 2.0,
            (bounds[4] + bounds[5]) / 2.0,
        )
        extent = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4], 0.1)
        distance = extent * 2.0
        if view is PresetView.TOP:
            direction, up = (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)
        elif view is PresetView.FRONT:
            direction, up = (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)
        elif view is PresetView.SIDE:
            direction, up = (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
        else:
            diagonal = 1.0 / math.sqrt(3.0)
            direction, up = (diagonal, diagonal, diagonal), (0.0, 0.0, 1.0)
        camera = self._plotter.camera
        camera.focal_point = center
        camera.position = (
            center[0] + direction[0] * distance,
            center[1] + direction[1] * distance,
            center[2] + direction[2] * distance,
        )
        camera.up = up
        self._plotter.reset_camera()

    def reset_camera(self) -> None:
        """Fit the camera to the scene."""
        self._plotter.reset_camera()

    # ------------------------------------------------------------- internal

    def _refresh_labels(self) -> None:
        self._remove_labels()
        if self._marker_state is None:
            return
        positions, logger_ids = self._marker_state
        if positions.size == 0:
            return
        self._label_actor = self._plotter.add_point_labels(
            positions,
            list(logger_ids),
            font_size=14,
            show_points=False,
        )

    def _remove_labels(self) -> None:
        if self._label_actor is not None:
            try:
                self._plotter.remove_actor(self._label_actor)
            except Exception:  # see remove_slice
                pass
            self._label_actor = None

    def _update_scalar_bar(self, actor: object, title: str) -> None:
        """Create the color bar once, then keep its lookup table in sync (VIS-04)."""
        if not self._colorbar_enabled:
            return

        mapper = getattr(actor, "mapper", None)
        if mapper is None:
            return
        if self._scalar_bar is None:
            try:
                self._scalar_bar = self._plotter.add_scalar_bar(
                    title=title, mapper=mapper, n_labels=5
                )
            except Exception as error:  # pragma: no cover - backend differences
                logger.warning("scalar bar unavailable: %s", error)
                self._scalar_bar = None
            return
        try:
            lookup_table = mapper.GetLookupTable()
            if lookup_table is not None:
                self._scalar_bar.SetLookupTable(lookup_table)
            self._scalar_bar.SetTitle(title)
        except Exception:  # pragma: no cover - backend differences
            pass

    def _obstacle_mesh(self, obstacle: Obstacle) -> pv.PolyData:
        if obstacle.shape is ObstacleShape.CYLINDER:
            mesh = pv.Cylinder(
                center=(0.0, 0.0, 0.0),
                direction=(0.0, 0.0, 1.0),
                radius=obstacle.size_x / 2.0,
                height=obstacle.size_z,
            )
        else:
            mesh = pv.Box(
                bounds=(
                    -obstacle.size_x / 2.0,
                    obstacle.size_x / 2.0,
                    -obstacle.size_y / 2.0,
                    obstacle.size_y / 2.0,
                    -obstacle.size_z / 2.0,
                    obstacle.size_z / 2.0,
                )
            )
        if obstacle.rotation_z_deg:
            mesh = mesh.rotate_z(obstacle.rotation_z_deg)
        return mesh.translate((obstacle.x, obstacle.y, obstacle.z))

    def _remove(self, names: list[str]) -> None:
        """Remove actors by name (stable across PyVista versions)."""
        for name in names:
            try:
                self._plotter.remove_actor(name)
            except Exception:  # actor may already be gone during teardown
                logger.debug("actor '%s' not removed: already absent", name)
        names.clear()

    def set_space_visible(self, visible: bool) -> None:
        """Show/hide the space outline (VIS-02)."""
        for name in self._space_actors:
            actor = self._plotter.renderer.actors.get(name)
            if actor is None:
                continue
            try:
                actor.visibility = visible
            except AttributeError:  # pragma: no cover - older actor API
                actor.SetVisibility(visible)

    def save_screenshot(self, path: Path, scale: int = 1) -> None:
        """Save the current view as an image (EXP-03), optionally upscaled."""
        try:
            self._plotter.screenshot(str(path), scale=scale)
        except TypeError:  # backend build without scale support
            self._plotter.screenshot(str(path))

    def set_colorbar_visible(self, visible: bool) -> None:
        """Show/hide the scalar color bar (VIS-04)."""
        self._colorbar_enabled = visible
        if not visible and self._scalar_bar is not None:
            try:
                self._plotter.remove_actor(self._scalar_bar)
            except Exception:  # actor may already be gone
                pass
            self._scalar_bar = None

    def camera_state(self) -> dict | None:
        """Serializable camera pose (VIS-01, view state)."""
        try:
            camera = self._plotter.camera
            return {
                "position": [float(v) for v in camera.position],
                "focal_point": [float(v) for v in camera.focal_point],
                "up": [float(v) for v in camera.up],
            }
        except Exception:  # pragma: no cover - backend differences
            return None

    def set_camera_state(self, state: dict | None) -> None:
        """Restore a camera pose; ignores invalid state."""
        if not state:
            return
        try:
            camera = self._plotter.camera
            camera.position = tuple(state["position"])
            camera.focal_point = tuple(state["focal_point"])
            camera.up = tuple(state["up"])
        except Exception:  # pragma: no cover - backend differences
            pass

    def render(self) -> None:
        """Force a VTK render of the current scene."""
        self._plotter.render()
        

def _footprint_vertices(space: Space) -> list[tuple[float, float]]:
    """Outline vertices (metres) for either footprint type — no box assumption."""
    footprint = space.footprint
    if isinstance(footprint, BoxFootprint):
        return [
            (footprint.x_min, footprint.y_min),
            (footprint.x_max, footprint.y_min),
            (footprint.x_max, footprint.y_max),
            (footprint.x_min, footprint.y_max),
        ]
    return list(footprint.vertices)


def try_create_scene(parent: QWidget | None = None) -> tuple[SceneRenderer | None, str]:
    """Create a PyVista scene when the environment allows it.

    Returns ``(None, reason)`` on the offscreen platform, when PyVista is
    missing, or when no OpenGL context can be created (software fallback,
    PRD risk table). Units: n/a.
    """
    if os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen":
        return None, "3D view disabled on the offscreen platform"
    available, reason = pyvista_backend_available()
    if not available:
        return None, reason
    try:
        return PyVistaScene(parent), ""
    except Exception as error:  # GL context failure must never crash the app
        logger.warning("PyVista scene creation failed: %s", error)
        return None, str(error)
