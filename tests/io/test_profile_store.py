"""Import profile store round-trips (DAT-01)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thermavisualizer.core.models import ImportProfile, TemperatureUnit
from thermavisualizer.io.profile_store import (
    ProfileStoreError,
    load_profiles,
    profile_from_dict,
    profile_to_dict,
    save_profiles,
)


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    profile = ImportProfile(
        name="Euro",
        delimiter=";",
        decimal=",",
        header_row=1,
        timestamp_column="Zeit",
        timestamp_format="%d.%m.%Y %H:%M",
        timezone="Europe/Berlin",
        temperature_unit=TemperatureUnit.FAHRENHEIT,
    )
    save_profiles(path, {"Euro": profile})
    loaded = load_profiles(path)
    assert loaded["Euro"] == profile


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_profiles(tmp_path / "absent.json") == {}


def test_corrupt_store_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProfileStoreError):
        load_profiles(path)


def test_unknown_keys_ignored() -> None:
    data = profile_to_dict(ImportProfile(name="X"))
    data["future_option"] = True
    assert profile_from_dict(data).name == "X"


def test_invalid_unit_raises() -> None:
    data = profile_to_dict(ImportProfile())
    data["temperature_unit"] = "Q"
    with pytest.raises(ProfileStoreError):
        profile_from_dict(data)


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "profiles.json"
    save_profiles(path, {"D": ImportProfile(name="D")})
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored[0]["name"] == "D"
