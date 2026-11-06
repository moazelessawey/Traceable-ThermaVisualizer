"""Study report assembly task (RPT-01..04): figures + snapshot + PDF.

Matplotlib (Agg) and off-screen PyVista render PNG bytes here; io/report.py
assembles the PDF. Runs inside a FunctionWorker for progress/cancel. Units:
°C / %RH / metres. Raw data is never modified.
"""

from __future__ import annotations

import io as _io
import logging
import platform
import sys
from importlib import metadata
from datetime import UTC, datetime, timezone

import numpy as np

from thermavisualizer import __version__
from thermavisualizer.core.geometry import footprint_bounds
from thermavisualizer.core.models import BoxFootprint, Quantity
from thermavisualizer.io.report import (
    AlignedSummary,
    FileInfo,
    LayerInfo,
    MappingSummary,
    ObstacleInfo,
    ProcessingSummary,
    ReportFigure,
    ReportOptions,
    ReportPayload,
    SpaceSummary,
    ValidationRow,
    build_report_pdf,
)
from thermavisualizer.services.project_model import ProjectModel


logger = logging.getLogger(__name__)


def _timeseries_png(model: ProjectModel, quantity: Quantity) -> bytes | None:
    """Render the quantity's aligned series as a styled PNG (Agg-safe)."""
    dataset = model.aligned_dataset(quantity)
    if dataset is None or dataset.values.shape[1] == 0:
        return None
    from matplotlib.figure import Figure

    from thermavisualizer.services.plot_style import (
        decimate_for_display,
        format_time_axis,
        layout_figure,
        place_legend_outside,
        series_color,
        style_axes,
    )

    figure = Figure(figsize=(7.2, 3.6), dpi=150)
    axes = figure.add_subplot(1, 1, 1)
    for index, logger_id in enumerate(dataset.logger_ids):
        times, values = decimate_for_display(dataset.times, dataset.values[:, index])
        axes.plot(
            times, values, label=logger_id, color=series_color(index), linewidth=0.9
        )
    quantity_name = "Temperature" if quantity is Quantity.TEMPERATURE else "Humidity"
    unit = "°C" if quantity is Quantity.TEMPERATURE else "%RH"
    title = model.study().title or "Thermal mapping study"
    style_axes(axes, f"{quantity_name} ({unit})", f"{title} — {quantity_name}")
    format_time_axis(axes)
    has_legend = place_legend_outside(axes)
    layout_figure(figure, has_side_legend=has_legend, has_bottom_legend=False)
    buffer = _io.BytesIO()
    figure.savefig(buffer, format="png", bbox_inches="tight")  # includes the legend
    return buffer.getvalue()


def _snapshot_png(model: ProjectModel) -> tuple[bytes, str] | None:
    """Render a mid-height interpolated slice off-screen; None without GL/data."""
    result = model.current_volume(Quantity.TEMPERATURE) or model.current_volume(Quantity.HUMIDITY)
    if result is None:
        return None
    try:
        import pyvista as pv

        from thermavisualizer.core.interpolation import build_voxel_grid
        from thermavisualizer.core.slicing import SliceAxis, extract_axis_slice
        from thermavisualizer.rendering.pyvista_backend import PyVistaScene
        from thermavisualizer.rendering.scene import ObstacleStyle

        plotter = pv.Plotter(off_screen=True, window_size=(800, 600))
        scene = PyVistaScene(plotter=plotter)
        scene.set_space(model.space)
        scene.set_obstacles(
            [o for o in model.space.obstacles if o.visible], ObstacleStyle.TRANSPARENT
        )
        grid = build_voxel_grid(model.space, result.settings.resolution)
        finite = result.volume[__import__("numpy").isfinite(result.volume)]
        clim = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
        slice_data = extract_axis_slice(
            result.volume,
            grid,
            model.space,
            list(model.space.obstacles),
            SliceAxis.Z,
            float(model.space.height) / 2.0,
        )
        scene.show_slice("report", slice_data, "viridis", clim, 1.0, "value")
        scene.reset_camera()
        frame = plotter.screenshot(return_img=True)
        scene.shutdown()
        from PIL import Image as _PILImage

        buffer = _io.BytesIO()
        _PILImage.fromarray(frame).save(buffer, format="PNG")
        return buffer.getvalue(), result.settings.method.value
    except Exception as error:  # no GL context or backend issue: skip the figure
        logger.info("3D snapshot skipped: %s", error)
        return None


def _environment_lines() -> tuple[str, ...]:
    """Library versions for the software appendix (traceability, AGENTS §9)."""
    lines = [f"Python {sys.version.split()[0]}", f"Platform {platform.platform()}"]
    for distribution in (
        "PySide6", "numpy", "scipy", "pandas", "matplotlib", "pyvista",
        "pyvistaqt", "reportlab", "scikit-image", "imageio",
    ):
        try:
            lines.append(f"{distribution} {metadata.version(distribution)}")
        except metadata.PackageNotFoundError:
            lines.append(f"{distribution} not installed")
    return tuple(lines)


def _build_payload(model: ProjectModel, figures: list[ReportFigure]) -> ReportPayload:
    space = model.space
    footprint = space.footprint
    x_min, y_min, x_max, y_max = footprint_bounds(footprint)
    if isinstance(footprint, BoxFootprint):
        footprint_kind = "box"
        bounds_text = f"{x_max - x_min:.2f} × {y_max - y_min:.2f} m"
    else:
        footprint_kind = f"polygon ({len(footprint.vertices)} vertices)"
        bounds_text = f"{x_max - x_min:.2f} × {y_max - y_min:.2f} m bounding box"
    space_summary = SpaceSummary(
        name=space.name,
        space_type=space.space_type.value,
        footprint_kind=footprint_kind,
        footprint_bounds=bounds_text,
        height=space.height,
    )
    layers = tuple(
        LayerInfo(layer.name, layer.height, len(layer.loggers), layer.completed)
        for layer in space.layers
    )
    obstacles = tuple(
        ObstacleInfo(
            name=obstacle.name,
            obstacle_type=obstacle.obstacle_type.value,
            shape=obstacle.shape.value,
            position=f"({obstacle.x:.2f}, {obstacle.y:.2f}, {obstacle.z:.2f}) m",
            size=(
                f"Ø {obstacle.size_x:.2f} × {obstacle.size_z:.2f} m"
                if obstacle.shape.value == "cylinder"
                else f"{obstacle.size_x:.2f} × {obstacle.size_y:.2f} × "
                     f"{obstacle.size_z:.2f} m"
            ),
            solid=obstacle.solid,
            visible=obstacle.visible,
        )
        for obstacle in space.obstacles
    )
    files = tuple(
        FileInfo(parsed.name, parsed.profile_name, parsed.row_count, len(parsed.columns))
        for parsed in model.files()
    )
    mappings = model.mappings()
    mapping = MappingSummary(
        loggers_total=len(model.all_logger_ids()),
        temperature_mapped=sum(1 for m in mappings if m.has_temperature()),
        humidity_mapped=sum(1 for m in mappings if m.has_humidity()),
        excluded=sum(1 for m in mappings if m.excluded),
        unmapped=len(model.unmapped_logger_ids()),
    )
    results = model.study_results()
    quantity = results.quantity if results is not None else Quantity.TEMPERATURE
    dataset = (
        model.aligned_dataset(quantity)
        or model.aligned_dataset(Quantity.TEMPERATURE)
        or model.aligned_dataset(Quantity.HUMIDITY)
    )
    aligned = None
    if dataset is not None and dataset.times.size:
        aligned = AlignedSummary(
            quantity=dataset.quantity.value,
            start_utc=str(dataset.times[0]),
            end_utc=str(dataset.times[-1]),
            samples=int(dataset.times.size),
            interval_seconds=float(dataset.interval / np.timedelta64(1, "s")),
        )
    report = model.validation_report
    validation_rows = tuple(
        ValidationRow(f.severity.value, f.code, f.file, f.column, f.message)
        for f in report.findings
    )
    validation_summary = (
        f"{len(report.errors())} error(s), {len(report.warnings())} warning(s), "
        f"{len(report.infos())} info finding(s)."
    )
    settings = model.interpolation_settings()
    volume = model.current_volume(quantity)
    processing = ProcessingSummary(
        method=settings.method.value,
        idw_power=settings.idw_power,
        rbf_kernel=settings.rbf_kernel.value,
        extrapolation=settings.extrapolation.value,
        resolution=settings.resolution,
        smoothing_sigma=settings.smoothing_sigma,
        aggregation=volume.aggregation.value if volume is not None else "",
    )
    audit_lines = tuple(
        f"{e.sequence}\t{e.timestamp_utc}\t{e.user}\t{e.action.value}\t{e.target}\t{e.summary}"
        for e in model.audit.entries
    )
    return ReportPayload(
        study=model.study(),
        criteria=model.criteria(),
        results=results,
        quantity=quantity,
        space=space_summary,
        layers=layers,
        obstacles=obstacles,
        data_files=files,
        mapping=mapping,
        aligned=aligned,
        validation_rows=validation_rows,
        validation_summary=validation_summary,
        processing=processing,
        figures=tuple(figures),
        audit_lines=audit_lines,
        environment=_environment_lines(),
        app_version=__version__,
        generated_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )

def report_task(
    model: ProjectModel,
    path,
    options: ReportOptions,
    cancel_check,
    report_progress,
) -> str | None:
    """Assemble and write the PDF; returns the path or None when cancelled."""
    if cancel_check():
        return None
    report_progress(10)
    figures: list[ReportFigure] = []
    temperature_png = _timeseries_png(model, Quantity.TEMPERATURE)
    if temperature_png:
        figures.append(ReportFigure("Temperature time series (mapped loggers)", temperature_png))
    humidity_png = _timeseries_png(model, Quantity.HUMIDITY)
    if humidity_png:
        figures.append(ReportFigure("Humidity time series (mapped loggers)", humidity_png))
    report_progress(40)
    if cancel_check():
        return None
    snapshot = _snapshot_png(model)
    if snapshot is not None:
        png, method = snapshot
        figures.append(
            ReportFigure("Interpolated slice at mid height", png, estimated=True, method=method)
        )
    report_progress(70)
    payload = _build_payload(model, figures)
    if cancel_check():
        return None
    build_report_pdf(path, options, payload)
    report_progress(100)
    logger.info("report written to %s", path)
    return str(path)
