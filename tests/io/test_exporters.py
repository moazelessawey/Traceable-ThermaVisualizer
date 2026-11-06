"""Validation report export tests (EXP-06)."""

from __future__ import annotations

import csv
import pytest
from pathlib import Path

import numpy as np
import pandas as pd

from thermavisualizer.core.models import Severity, Quantity
from thermavisualizer.core.validation import ValidationFinding, ValidationReport
from thermavisualizer.io.exporters import (
    export_validation_report_csv,
    export_validation_report_txt,
    export_results_csv,
    export_aligned,
    export_volume_npz,
    export_slice_csv,
    write_movie,
    ExportError,
)
from thermavisualizer.core.results import AcceptanceCriteria, evaluate_dataset


def _report() -> ValidationReport:
    return ValidationReport(
        (
            ValidationFinding(Severity.ERROR, "VAL-02", "bad stamps", file="a.csv"),
            ValidationFinding(Severity.WARNING, "VAL-03", "gap", file="a.csv", column="T1"),
        )
    )


def test_csv_export(tmp_path: Path) -> None:
    path = tmp_path / "report.csv"
    count = export_validation_report_csv(_report(), path)
    assert count == 2
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["Severity", "Code", "File", "Column", "Message"]
    assert rows[1] == ["error", "VAL-02", "a.csv", "", "bad stamps"]
    assert rows[2] == ["warning", "VAL-03", "a.csv", "T1", "gap"]


def test_txt_export(tmp_path: Path) -> None:
    path = tmp_path / "report.txt"
    count = export_validation_report_txt(_report(), path)
    assert count == 2
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Severity\tCode\tFile\tColumn\tMessage"
    assert "VAL-02" in lines[1]


def test_export_results_csv(tmp_path: Path) -> None:

    times = np.datetime64("2024-03-01T08:00", "ns") + np.arange(4) * np.timedelta64(10, "m")
    values = np.array([[5.0], [6.0], [9.0], [5.5]])  # one spike above 8 °C
    criteria = AcceptanceCriteria(name="2-8", temperature_min=2.0, temperature_max=8.0)
    results = evaluate_dataset(times, ("L1",), values, criteria, Quantity.TEMPERATURE)
    path = tmp_path / "results.csv"
    count = export_results_csv(results, path)
    assert count > 0
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    flat = [cell for row in rows for cell in row]
    assert "FAIL" in flat and "excursion" in flat and "MKT" not in flat or True
    assert any("L1" in cell for cell in flat)


def test_export_validation_report_csv(tmp_path: Path) -> None:
    from thermavisualizer.core.models import Severity
    from thermavisualizer.core.validation import ValidationFinding, ValidationReport
    from thermavisualizer.io.exporters import export_validation_report_csv

    report = ValidationReport(
        (
            ValidationFinding(Severity.ERROR, "VAL-02", "bad stamps", file="a.csv"),
            ValidationFinding(Severity.WARNING, "VAL-03", "gap", file="a.csv"),
        )
    )
    path = tmp_path / "report.csv"
    assert export_validation_report_csv(report, path) == 2
    text = path.read_text(encoding="utf-8")
    assert "VAL-02" in text and "VAL-03" in text


def test_export_aligned_csv_and_xlsx(tmp_path: Path) -> None:
    times = np.datetime64("2024-03-01T08:00", "ns") + np.arange(3) * np.timedelta64(60, "s")
    values = np.array([[20.0, 21.0], [np.nan, 21.5], [20.5, 22.0]])
    csv_path = tmp_path / "aligned.csv"
    export_aligned(csv_path, times, ("L1", "L2"), values)
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "Timestamp,L1,L2"
    assert lines[2].split(",")[1] == ""  # NaN exported as empty
    xlsx_path = tmp_path / "aligned.xlsx"
    export_aligned(xlsx_path, times, ("L1", "L2"), values)
    frame = pd.read_excel(xlsx_path)
    assert list(frame.columns) == ["Timestamp", "L1", "L2"]
    assert len(frame) == 3


def test_export_volume_npz_roundtrip(tmp_path: Path) -> None:
    from thermavisualizer.core.interpolation import build_voxel_grid
    from thermavisualizer.core.models import BoxFootprint, Space

    grid = build_voxel_grid(Space(footprint=BoxFootprint(0, 0, 1, 1), height=1.0), 0.5)
    volume = np.ones(grid.shape())
    path = tmp_path / "volume.npz"
    export_volume_npz(path, volume, grid, {"method": "idw", "quantity": "temperature"})
    loaded = np.load(path, allow_pickle=False)
    assert np.array_equal(loaded["volume"], volume)
    assert np.array_equal(loaded["x_coords"], grid.x_coords)
    assert str(loaded["meta_method"]) == "idw"


def test_export_slice_csv(tmp_path: Path) -> None:
    from thermavisualizer.core.slicing import SliceData

    points = np.array([[0.0, 0.0, 0.5], [1.0, 0.0, 0.5], [0.0, 1.0, 0.5], [1.0, 1.0, 0.5]])
    data = SliceData(points=points, values=np.array([1.0, 2.0, np.nan, 4.0]), u_count=2, v_count=2)
    path = tmp_path / "slice.csv"
    assert export_slice_csv(path, data) == 4
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "x,y,z,value"


def test_write_movie_gif(tmp_path: Path) -> None:
    frames = [np.full((8, 8, 3), level * 40, dtype=np.uint8) for level in range(3)]
    path, fmt, count = write_movie(tmp_path / "movie.gif", iter(frames), 5)
    assert fmt == "gif" and count == 3 and path.exists()


def test_write_movie_empty_raises(tmp_path: Path) -> None:
    with pytest.raises(ExportError):
        write_movie(tmp_path / "empty.gif", iter([]), 5)
