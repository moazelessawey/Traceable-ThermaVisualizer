"""Acceptance-criteria presets store (RES-01): JSON, atomic writes, no Qt."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from thermavisualizer.core.results import AcceptanceCriteria


class PresetError(ValueError):
    """Raised when the preset store cannot be read or written."""


DEFAULT_PRESETS: tuple[AcceptanceCriteria, ...] = (
    AcceptanceCriteria(name="2-8 °C", temperature_min=2.0, temperature_max=8.0),
    AcceptanceCriteria(name="15-25 °C", temperature_min=15.0, temperature_max=25.0),
)


def default_presets_path() -> Path:
    """Default user-level store location."""
    return Path.home() / ".thermavisualizer" / "criteria_presets.json"


def criteria_to_dict(criteria: AcceptanceCriteria) -> dict[str, object]:
    """JSON-safe representation of one criteria preset."""
    return {
        "name": criteria.name,
        "temperature_min": criteria.temperature_min,
        "temperature_max": criteria.temperature_max,
        "humidity_min": criteria.humidity_min,
        "humidity_max": criteria.humidity_max,
    }


def criteria_from_dict(data: dict[str, object]) -> AcceptanceCriteria:
    """Build a preset from stored data; unknown keys ignored."""
    try:
        return AcceptanceCriteria(
            name=str(data.get("name", "Default")),
            temperature_min=float(data.get("temperature_min", 2.0)),  # type: ignore[arg-type]
            temperature_max=float(data.get("temperature_max", 8.0)),  # type: ignore[arg-type]
            humidity_min=_optional_float(data.get("humidity_min")),
            humidity_max=_optional_float(data.get("humidity_max")),
        )
    except (TypeError, ValueError) as error:
        raise PresetError(f"invalid stored criteria: {error}") from error


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def load_criteria_presets(path: Path) -> list[AcceptanceCriteria]:
    """Load presets; a missing file returns the built-in defaults."""
    path = Path(path)
    if not path.exists():
        return list(DEFAULT_PRESETS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PresetError(f"cannot read preset store '{path}': {error}") from error
    if not isinstance(data, list):
        raise PresetError(f"preset store '{path}' has an unexpected format")
    return [criteria_from_dict(item) for item in data]


def save_criteria_presets(path: Path, criteria: Sequence[AcceptanceCriteria]) -> None:
    """Write presets atomically (temp file then replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        [criteria_to_dict(item) for item in criteria], indent=2, ensure_ascii=False
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
