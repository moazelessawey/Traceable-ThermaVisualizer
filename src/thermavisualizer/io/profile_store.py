"""Persistence for import profiles (DAT-01): JSON store, atomic writes, no Qt."""

from __future__ import annotations

import json
from pathlib import Path

from thermavisualizer.core.models import ImportProfile, TemperatureUnit


class ProfileStoreError(ValueError):
    """Raised when the profile store cannot be read or written."""


def default_profiles_path() -> Path:
    """Default user-level store location."""
    return Path.home() / ".thermavisualizer" / "import_profiles.json"


def profile_to_dict(profile: ImportProfile) -> dict[str, str | int]:
    """JSON-safe representation of a profile."""
    return {
        "name": profile.name,
        "delimiter": profile.delimiter,
        "decimal": profile.decimal,
        "header_row": profile.header_row,
        "timestamp_column": profile.timestamp_column,
        "timestamp_format": profile.timestamp_format,
        "timezone": profile.timezone,
        "temperature_unit": profile.temperature_unit.value,
    }


def profile_from_dict(data: dict[str, object]) -> ImportProfile:
    """Build a profile from stored data; unknown keys ignored (forward-compatible)."""
    try:
        return ImportProfile(
            name=str(data.get("name", "Default")),
            delimiter=str(data.get("delimiter", ",")),
            decimal=str(data.get("decimal", ".")),
            header_row=int(data.get("header_row", 0)),  # type: ignore[arg-type]
            timestamp_column=str(data.get("timestamp_column", "Timestamp")),
            timestamp_format=str(data.get("timestamp_format", "iso")),
            timezone=str(data.get("timezone", "UTC")),
            temperature_unit=TemperatureUnit(str(data.get("temperature_unit", "C"))),
        )
    except (ValueError, TypeError) as error:
        raise ProfileStoreError(f"invalid stored profile: {error}") from error


def load_profiles(path: Path) -> dict[str, ImportProfile]:
    """Load profiles keyed by name; a missing file means an empty store."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProfileStoreError(f"cannot read profile store '{path}': {error}") from error
    if not isinstance(data, list):
        raise ProfileStoreError(f"profile store '{path}' has an unexpected format")
    profiles: dict[str, ImportProfile] = {}
    for item in data:
        profile = profile_from_dict(item)
        profiles[profile.name] = profile
    return profiles


def save_profiles(path: Path, profiles: dict[str, ImportProfile]) -> None:
    """Write profiles atomically (temp file then replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        [profile_to_dict(profile) for profile in profiles.values()],
        indent=2,
        ensure_ascii=False,
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)
