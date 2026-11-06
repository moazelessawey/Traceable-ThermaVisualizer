"""Demo layout + generated data round-trip (AGENTS §8: seeded synthetic data)."""

from __future__ import annotations

import sys
from pathlib import Path

from thermavisualizer.core.mapping import suggest_logger_mappings
from thermavisualizer.core.models import ImportProfile
from thermavisualizer.io.layout_io import (
    parse_layout_records,
    read_layout_table,
    records_to_layers,
    suggest_mapping,
)
from thermavisualizer.io.readers import read_data_file

DATA = Path(__file__).resolve().parents[1] / "data"
sys.path.insert(0, str(DATA))
import generate_demo_files as demo  # noqa: E402  (script lives with the samples)

LOGGER_IDS = [f"L{i:02d}" for i in range(1, 17)]


def test_committed_demo_layout_parses_into_two_layers() -> None:  # BLK-01
    table = read_layout_table(DATA / "demo_layout_16.csv")
    records, issues = parse_layout_records(table, suggest_mapping(table.columns))
    assert issues == []
    layers = records_to_layers(records)
    assert [layer.name for layer in layers] == ["lower", "upper"]
    assert len(layers[0].loggers) == 8
    assert len(layers[1].loggers) == 8


def test_generated_demo_data_loads_and_autosuggests(tmp_path: Path) -> None:  # DAT-04
    out = demo.generate_demo_files(tmp_path)
    parsed = read_data_file(out, ImportProfile())
    assert parsed.row_count == 288
    names = set(parsed.numeric_column_names())
    assert set(LOGGER_IDS) <= names
    assert "RH_01" in names
    assert len(names) == 32  # 16 temperature + 4 humidity columns
    mappings = suggest_logger_mappings(LOGGER_IDS, [parsed])
    assert all(mapping.has_temperature() for mapping in mappings)


def test_generator_is_deterministic(tmp_path: Path) -> None:  # seeded RNG
    first = demo.generate_demo_files(tmp_path / "a")
    second = demo.generate_demo_files(tmp_path / "b")
    assert first.read_bytes() == second.read_bytes()
