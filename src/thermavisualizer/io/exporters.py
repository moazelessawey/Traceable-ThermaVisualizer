"""Exporters for validation reports and processed data (EXP-xx). No Qt, headless."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from thermavisualizer.core.interpolation import VoxelGrid
from thermavisualizer.core.results import StudyResults
from thermavisualizer.core.slicing import SliceData
from thermavisualizer.core.validation import ValidationReport


class ExportError(ValueError):
    """Raised when an export cannot be written."""


def export_validation_report_csv(report: ValidationReport, path: Path) -> int:
    """Write the validation report as CSV (EXP-06). Returns the finding count."""
    path = Path(path)
    header, rows = report.to_csv_rows()
    try:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
    except OSError as error:
        raise ExportError(f"cannot write report '{path}': {error}") from error
    return len(rows)


def export_validation_report_txt(report: ValidationReport, path: Path) -> int:
    """Write the validation report as tab-separated text (EXP-06)."""
    path = Path(path)
    header, rows = report.to_csv_rows()
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\t".join(header) + "\n")
            for row in rows:
                handle.write("\t".join(row) + "\n")
    except OSError as error:
        raise ExportError(f"cannot write report '{path}': {error}") from error
    return len(rows)


def export_results_csv(results: StudyResults, path: Path, study=None) -> int:
    """Write study results as CSV (RES-07, EXP-04). Returns data-row count.

    Sections: overall summary, per-logger results, excursion table. Units: °C
    or %RH per ``results.quantity``; durations in seconds; timestamps UTC.
    """
    path = Path(path)
    unit = "°C" if results.quantity.value == "temperature" else "%RH"
    rows: list[list[str]] = []
    overall = results.overall
    rows.append(["section", "field", "value"])
    rows.append(["overall", "result", "PASS" if overall.passed else "FAIL"])
    rows.append(["overall", "reason", overall.reason])
    rows.append(["overall", "quantity", results.quantity.value])
    rows.append(["overall", "criteria", results.criteria.name])
    rows.append(["overall", "period_start", str(results.period_start)])
    rows.append(["overall", "period_end", str(results.period_end)])
    rows.append(["overall", "hottest_logger", overall.hottest_logger])
    rows.append(["overall", f"hottest_value_{unit}", f"{overall.hottest_value:.3f}"])
    rows.append(["overall", "hottest_time", str(overall.hottest_time)])
    rows.append(["overall", "coldest_logger", overall.coldest_logger])
    rows.append(["overall", f"coldest_value_{unit}", f"{overall.coldest_value:.3f}"])
    rows.append(["overall", "coldest_time", str(overall.coldest_time)])
    rows.append(["overall", f"largest_spread_{unit}", f"{overall.largest_spread:.3f}"])
    rows.append(["overall", "largest_spread_time", str(overall.largest_spread_time)])
    if study is not None:
        rows.append(["study", "title", study.title])
        rows.append(["study", "protocol_id", study.protocol_id])
        rows.append(["study", "study_type", str(study.study_type.value)])

    header_logger = [
        "section",
        "logger",
        "samples",
        "min",
        "max",
        "mean",
        "std",
        "mkt",
        "out_of_limits_samples",
        "out_of_limits_pct",
        "excursion_count",
        "longest_excursion_s",
        "passed",
    ]
    rows.append(header_logger)
    for lr in results.logger_results:
        rows.append(
            [
                "logger",
                lr.logger_id,
                str(lr.samples),
                f"{lr.minimum:.3f}",
                f"{lr.maximum:.3f}",
                f"{lr.mean:.3f}",
                f"{lr.std:.3f}",
                f"{lr.mkt:.3f}" if lr.mkt is not None else "",
                str(lr.out_of_limits_samples),
                f"{lr.out_of_limits_pct:.2f}",
                str(lr.excursion_count),
                f"{lr.longest_excursion_seconds:.1f}",
                "PASS" if lr.passed else "FAIL",
            ]
        )
    rows.append(["section", "logger", "kind", "start", "end", "duration_s", "peak"])
    for ex in results.excursions:
        rows.append(
            [
                "excursion",
                ex.logger_id,
                ex.kind.value,
                str(ex.start),
                str(ex.end),
                f"{ex.duration_seconds:.1f}",
                f"{ex.peak:.3f}",
            ]
        )
    try:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)
    except OSError as error:
        raise ExportError(f"cannot write results '{path}': {error}") from error
    return len(rows)


def export_validation_report_csv(report: ValidationReport, path: Path) -> int:
    """Write the validation report as CSV (EXP-06). Returns the finding count."""
    path = Path(path)
    header, rows = report.to_csv_rows()
    try:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
    except OSError as error:
        raise ExportError(f"cannot write report '{path}': {error}") from error
    return len(rows)


def export_aligned_csv(
    path: Path, times: np.ndarray, logger_ids: Sequence[str], values: np.ndarray
) -> int:
    """Export aligned logger data as CSV (EXP-04). Timestamps UTC; °C / %RH."""
    path = Path(path)
    try:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Timestamp", *[str(logger_id) for logger_id in logger_ids]])
            for row in range(values.shape[0]):
                writer.writerow(
                    [
                        str(times[row]),
                        *[
                            "" if not np.isfinite(value) else f"{value:.4f}"
                            for value in values[row]
                        ],
                    ]
                )
    except OSError as error:
        raise ExportError(f"cannot write aligned data '{path}': {error}") from error
    return int(values.shape[0])


def export_aligned_xlsx(
    path: Path, times: np.ndarray, logger_ids: Sequence[str], values: np.ndarray
) -> None:
    """Export aligned logger data as XLSX (EXP-04)."""
    frame = pd.DataFrame(values, columns=[str(logger_id) for logger_id in logger_ids])
    frame.insert(0, "Timestamp", [str(time) for time in times])
    try:
        frame.to_excel(path, index=False)
    except (OSError, ValueError) as error:
        raise ExportError(f"cannot write aligned data '{path}': {error}") from error


def export_aligned(
    path: Path, times: np.ndarray, logger_ids: Sequence[str], values: np.ndarray
) -> None:
    """Write aligned data, choosing CSV or XLSX by suffix (EXP-04)."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        export_aligned_xlsx(path, times, logger_ids, values)
    else:
        export_aligned_csv(path, times, logger_ids, values)


def export_volume_npz(
    path: Path,
    volume: np.ndarray,
    grid: VoxelGrid,
    metadata: dict[str, str] | None = None,
) -> None:
    """Export an interpolated volume as compressed NPZ (EXP-04).

    Members: ``volume``, ``x_coords``, ``y_coords``, ``z_coords`` plus one
    ``meta_<key>`` string array per metadata entry (units: metres, °C/%RH).
    """
    arrays: dict[str, np.ndarray] = {
        "volume": volume,
        "x_coords": grid.x_coords,
        "y_coords": grid.y_coords,
        "z_coords": grid.z_coords,
    }
    for key, value in (metadata or {}).items():
        arrays[f"meta_{key}"] = np.array(str(value))
    try:
        np.savez_compressed(path, **arrays)
    except OSError as error:
        raise ExportError(f"cannot write volume '{path}': {error}") from error


def export_slice_csv(path: Path, slice_data: SliceData) -> int:
    """Export slice samples as x,y,z,value rows (EXP-04). Units: metres."""
    path = Path(path)
    try:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["x", "y", "z", "value"])
            for point, value in zip(slice_data.points, slice_data.values):
                writer.writerow(
                    [
                        f"{point[0]:.4f}",
                        f"{point[1]:.4f}",
                        f"{point[2]:.4f}",
                        "" if not np.isfinite(value) else f"{value:.4f}",
                    ]
                )
    except OSError as error:
        raise ExportError(f"cannot write slice '{path}': {error}") from error
    return int(slice_data.points.shape[0])


def write_movie(path: Path, frames: Iterable[np.ndarray], fps: int) -> tuple[Path, str, int]:
    """Write RGB frames to MP4, falling back to GIF when MP4 is unavailable (EXP-02).

    Returns ``(actual path, format, frame count)``. Raises ExportError when no
    frames were written. Units: fps is frames per second.
    """
    import imageio

    path = Path(path)
    fmt = "gif" if path.suffix.lower() == ".gif" else "mp4"
    try:
        if fmt == "gif":
            writer = imageio.get_writer(str(path), mode="I", fps=fps, loop=0)
        else:
            writer = imageio.get_writer(str(path), fps=fps)
    except Exception as error:
        if fmt == "gif":
            raise ExportError(f"cannot create movie writer: {error}") from error
        path = path.with_suffix(".gif")  # MP4 unavailable -> GIF fallback
        fmt = "gif"
        try:
            writer = imageio.get_writer(str(path), mode="I", fps=fps, loop=0)
        except Exception as gif_error:
            raise ExportError(f"cannot create movie writer: {gif_error}") from gif_error
    count = 0
    try:
        for frame in frames:
            writer.append_data(np.asarray(frame, dtype=np.uint8))
            count += 1
    finally:
        writer.close()
    if count == 0:
        path.unlink(missing_ok=True)
        raise ExportError("no frames were written")
    return path, fmt, count
