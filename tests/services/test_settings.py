"""Tests for AppSettings persistence (M0)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

from thermavisualizer.services.settings import AppSettings


def _make_settings(tmp_path: Path, name: str) -> AppSettings:
    return AppSettings(QSettings(str(tmp_path / name), QSettings.Format.IniFormat))


def test_window_geometry_roundtrip(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, "g.ini")
    settings.save_window_geometry(QByteArray(b"geometry-bytes"))
    settings.sync()
    assert _make_settings(tmp_path, "g.ini").window_geometry() == QByteArray(b"geometry-bytes")


def test_splitter_state_roundtrip(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, "s.ini")
    settings.save_splitter_state(QByteArray(b"splitter-bytes"))
    settings.sync()
    assert _make_settings(tmp_path, "s.ini").splitter_state() == QByteArray(b"splitter-bytes")


def test_missing_values_return_none(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, "empty.ini")
    assert settings.window_geometry() is None
    assert settings.splitter_state() is None


def test_user_name_roundtrip(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, "u.ini")
    settings.set_user_name("Moaz El-Essawey")
    settings.sync()
    assert _make_settings(tmp_path, "u.ini").user_name() == "Moaz El-Essawey"


def test_user_name_defaults_to_os_user(tmp_path: Path) -> None:
    settings = _make_settings(tmp_path, "default.ini")
    assert settings.user_name()  # falls back to the OS user name
