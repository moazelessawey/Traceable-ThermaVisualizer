"""Seeded demo-data generator (AGENTS §8): 16 loggers, 2 days, 10-minute samples.

Reads the committed layout ``demo_layout_16.csv`` and writes
``<output>/demo_data_16.csv`` (default ``tests/data/demo/``). Deterministic:
seeded RNG, identical output on every run.

Built-in validation demo cases: L04 carries three +4 °C spikes (VAL-06) and
L13 flat-lines for the last 20 % of the study (VAL-07). Units: °C, %RH.

Usage:
    python tests/data/generate_demo_files.py [output_dir]
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

SEED = 42
START = np.datetime64("2024-03-01T00:00:00")
STEP_MINUTES = 10
N_STEPS = 288  # 2 days

SPACE_X, SPACE_Y, SPACE_Z = 6.0, 4.0, 3.0
# RH_LOGGERS = ("L01", "L05", "L09", "L13")
RH_LOGGERS = (f"L{i:02d}" for i in range(1, 17))


def read_layout(layout_path: Path) -> list[tuple[str, float, float, float, str]]:
    """Return (id, x, y, z, notes) rows from the layout CSV. Units: metres."""
    with open(layout_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [
        (r["ID"], float(r["X"]), float(r["Y"]), float(r["Z"]), r.get("Notes", "")) for r in rows
    ]


def generate_demo_files(output_dir: Path, layout_path: Path | None = None) -> Path:
    """Generate the demo data CSV and return its path. Units: °C and %RH."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if layout_path is None:
        layout_path = Path(__file__).parent / "demo_layout_16.csv"
    loggers = read_layout(layout_path)
    rng = np.random.default_rng(SEED)
    times = START + np.arange(N_STEPS) * np.timedelta64(STEP_MINUTES, "m")
    hours = np.arange(N_STEPS) * STEP_MINUTES / 60.0
    diurnal = 0.6 * np.sin(2.0 * np.pi * hours / 24.0)

    temperature: dict[str, np.ndarray] = {}
    for logger_id, x, y, z, notes in loggers:
        base = (
            5.0
            + 1.2 * x / SPACE_X
            + 0.8 * z / SPACE_Z
            + 0.4 * math.sin(2.0 * math.pi * y / SPACE_Y)
        )
        if "evaporator" in notes:
            base -= 0.8
        values = base + diurnal + rng.normal(0.0, 0.08, N_STEPS)
        if logger_id == "L04":  # VAL-06 demo: three spikes
            for index in (60, 150, 240):
                values[index] += 4.0
        if logger_id == "L13":  # VAL-07 demo: stuck sensor, last 20 %
            start = int(0.8 * N_STEPS)
            values[start:] = values[start]
        temperature[logger_id] = np.round(values, 3)

    humidity: dict[str, np.ndarray] = {}
    for logger_id, x, y, z, _ in loggers:
        if logger_id not in RH_LOGGERS:
            continue
        rh = 45.0 + 6.0 * np.sin(2.0 * np.pi * hours / 24.0 + 1.0)
        rh = rh + rng.normal(0.0, 0.5, N_STEPS)
        humidity[f"RH_{logger_id[1:]}"] = np.round(rh, 1)

    out_path = output_dir / "demo_data_16.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Timestamp"] + [l[0] for l in loggers] + list(humidity))
        for index in range(N_STEPS):
            row = [str(times[index])]
            row += [f"{temperature[l[0]][index]:.3f}" for l in loggers]
            row += [f"{humidity[name][index]:.1f}" for name in humidity]
            writer.writerow(row)
    return out_path


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "demo"
    written = generate_demo_files(target)
    print(f"wrote {written}")
    print("Walkthrough: set the space to 6 x 4 x 3 m; Bulk layout > Import layout…")
    print(f"with {Path(__file__).parent / 'demo_layout_16.csv'}; then File > Import Data…")
    print(f"with {written}, auto-suggest the mapping, and Compute in the 3D View tab.")
