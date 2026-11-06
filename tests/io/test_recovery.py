"""Recovery file round-trip (NFR reliability)."""

from __future__ import annotations

from pathlib import Path

from thermavisualizer.core.interpolation import InterpolationSettings
from thermavisualizer.core.models import Space, Study
from thermavisualizer.core.results import AcceptanceCriteria
from thermavisualizer.io.project_file import ProjectSnapshot, load_project
from thermavisualizer.io.recovery import (
    default_recovery_path,
    read_recovery_metadata,
    write_recovery,
)


def _snapshot() -> ProjectSnapshot:
    return ProjectSnapshot(
        space=Space(), study=Study(), criteria=AcceptanceCriteria(),
        study_periods=(), mappings=(), import_profiles=(), raw_files=(),
        aligned=(), interpolation_settings=InterpolationSettings(),
        view_state={}, validation_findings=(), results=None, audit_jsonl="",
    )


def test_recovery_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "recovery.tmap.autosave"
    write_recovery(path, _snapshot(), author="tester")
    meta = read_recovery_metadata(path)
    assert meta is not None and meta["path"] == str(path)
    snapshot, warnings = load_project(path)
    assert warnings == []
    assert snapshot.space.name == "Space"


def test_missing_recovery_returns_none(tmp_path: Path) -> None:
    assert read_recovery_metadata(tmp_path / "absent") is None
    assert default_recovery_path().name == "recovery.tmap.autosave"