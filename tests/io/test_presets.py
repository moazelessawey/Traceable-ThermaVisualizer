"""Criteria preset store tests (RES-01)."""

from __future__ import annotations

from pathlib import Path

import pytest

from thermavisualizer.core.results import AcceptanceCriteria
from thermavisualizer.io.presets import (
    DEFAULT_PRESETS,
    PresetError,
    load_criteria_presets,
    save_criteria_presets,
)


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    presets = load_criteria_presets(tmp_path / "absent.json")
    assert [preset.name for preset in presets] == [p.name for p in DEFAULT_PRESETS]


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "presets.json"
    custom = [
        AcceptanceCriteria(name="Cold", temperature_min=2.0, temperature_max=8.0),
        AcceptanceCriteria(
            name="Ambient+RH",
            temperature_min=15.0,
            temperature_max=25.0,
            humidity_min=35.0,
            humidity_max=65.0,
        ),
    ]
    save_criteria_presets(path, custom)
    loaded = load_criteria_presets(path)
    assert loaded == custom


def test_corrupt_store_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(PresetError):
        load_criteria_presets(path)
