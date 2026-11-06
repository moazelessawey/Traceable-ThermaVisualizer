"""Themes: palettes, persistence, menu wiring (VIS-08)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from thermavisualizer.resources.themes import (
    Theme,
    apply_theme,
    build_dark_palette,
    build_light_palette,
)
from thermavisualizer.services.settings import AppSettings


def test_palettes_are_distinct() -> None:
    light = build_light_palette()
    dark = build_dark_palette()
    assert light.color(QPalette.ColorRole.Window) != dark.color(QPalette.ColorRole.Window)


def test_apply_theme_runs(qtbot: QtBot) -> None:
    app = QApplication.instance()
    apply_theme(app, Theme.DARK)
    apply_theme(app, Theme.LIGHT)
    apply_theme(app, Theme.SYSTEM)


def test_theme_and_prompt_flags_persist(tmp_path: Path) -> None:
    settings = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    assert settings.theme() == "system"
    settings.set_theme("dark")
    assert settings.user_name_asked() is False
    settings.set_user_name_asked()
    reopened = AppSettings(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    assert reopened.theme() == "dark"
    assert reopened.user_name_asked() is True


def test_view_menu_has_theme_actions(main_window) -> None:
    view_menu = next(
        action.menu()
        for action in main_window.menuBar().actions()
        if action.text() == "&View"
    )
    theme_menu = next(
        action.menu() for action in view_menu.actions() if action.text() == "Theme"
    )
    assert len(theme_menu.actions()) == len(Theme)