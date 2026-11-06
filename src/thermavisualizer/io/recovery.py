"""Autosave recovery file handling (NFR reliability: no data loss on crash).

The recovery file is a normal .tmap written periodically while the project has
unsaved changes. Headless: no Qt. Units: n/a.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from thermavisualizer.io.project_file import ProjectSnapshot, save_project


def default_recovery_path() -> Path:
    """Location of the crash-recovery file."""
    return Path.home() / ".thermavisualizer" / "recovery.tmap.autosave"


def write_recovery(path: Path, snapshot: ProjectSnapshot, author: str) -> Path:
    """Write the recovery file atomically via the .tmap writer (EXP-05 reuse)."""
    save_project(path, snapshot, author)
    return Path(path)


def read_recovery_metadata(path: Path) -> dict[str, str] | None:
    """Basic info about an existing recovery file, or None when absent."""
    path = Path(path)
    if not path.exists():
        return None
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return {"path": str(path), "modified": modified.isoformat()}
