"""Offscreen frame rendering for movie export (EXP-01/02).

Frames are produced by the same PyVistaScene drawing path as the live view
(one-render-path rule); only the render target differs (offscreen framebuffer
instead of the on-screen widget). Units: metres, °C/%RH.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import numpy as np

from thermavisualizer.core.geometry import build_volume_mask
from thermavisualizer.core.interpolation import Interpolator, build_voxel_grid
from thermavisualizer.core.models import Quantity
from thermavisualizer.core.slicing import extract_axis_slice, extract_plane_slice
from thermavisualizer.rendering.pyvista_backend import PyVistaScene
from thermavisualizer.rendering.scene import ObstacleStyle

if TYPE_CHECKING:
    from thermavisualizer.services.workers import MovieJob

logger = logging.getLogger(__name__)

CancelCheck = Callable[[], bool]
ProgressReport = Callable[[int], None]


def render_movie_frames(
    job: MovieJob, cancel_check: CancelCheck, report_progress: ProgressReport
) -> Iterator[np.ndarray]:
    """Yield one RGB frame per time step in the job range.

    The scene and interpolation weights are built once (INT-09); each frame is
    a matrix product plus slice re-extraction. Cancel is checked per frame.
    """
    import pyvista as pv

    plotter = pv.Plotter(off_screen=True, window_size=(job.width, job.height))
    scene = PyVistaScene(plotter=plotter)
    try:
        scene.set_space(job.space)
        scene.set_obstacles([o for o in job.obstacles if o.visible], ObstacleStyle.TRANSPARENT)
        scene.set_axes_visible(True)
        scene.set_colorbar_visible(job.burn_colorbar)
        grid = build_voxel_grid(job.space, job.settings.resolution)
        mask = build_volume_mask(
            job.space, list(job.obstacles), grid.x_coords, grid.y_coords, grid.z_coords
        )
        interpolator = Interpolator(grid, job.positions, job.settings, mask)
        clim = job.clim
        if clim is None:
            finite = job.values[np.isfinite(job.values)]
            clim = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
        title = "Temperature (°C)" if job.quantity is Quantity.TEMPERATURE else "Humidity (%RH)"
        indices = list(range(job.range_start, job.range_end + 1, max(1, job.step_stride)))
        total = max(len(indices), 1)
        text_actor = None
        scene.reset_camera()  # fixed framing for the whole movie
        for step, index in enumerate(indices):
            if cancel_check():
                return
            values = job.values[index]
            volume = interpolator.interpolate(values)
            for spec in job.slices:
                if not spec.visible:
                    scene.remove_slice(spec.spec_id)
                    continue
                if spec.axis is not None:
                    data = extract_axis_slice(
                        volume, grid, job.space, list(job.obstacles), spec.axis, spec.position
                    )
                else:
                    data = extract_plane_slice(
                        volume, grid, job.space, list(job.obstacles), spec.point, spec.normal
                    )
                scene.show_slice(spec.spec_id, data, job.colormap, clim, spec.opacity, title)
            scene.set_logger_scalars(
                job.positions, job.logger_ids, values, job.colormap, clim, title
            )
            if job.burn_timestamp:
                if text_actor is not None:
                    try:
                        plotter.remove_actor(text_actor)
                    except Exception:  # actor may already be gone
                        pass
                text_actor = plotter.add_text(
                    str(job.times[index]), position="upper_left", font_size=12, color="white"
                )
            frame = plotter.screenshot(return_img=True)
            yield np.asarray(frame)
            report_progress(int(100 * (step + 1) / total))
    finally:
        scene.shutdown()
