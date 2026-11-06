"""Shared pytest fixtures for the ThermaVisualizer test suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.settings import AppSettings
from thermavisualizer.ui.main_window import MainWindow

from rendering.conftest import fake_renderer


def pytest_configure(config: pytest.Config) -> None:
    """Run Qt headless unless the caller chose a platform explicitly."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app_settings(tmp_path: Path) -> AppSettings:
    """Application settings backed by a throwaway INI file."""
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    return AppSettings(settings)

@pytest.fixture
def main_window(qtbot, app_settings, tmp_path, monkeypatch) -> MainWindow:
    """Visible main window with isolated settings and an auto-answered close guard."""

    app_settings.set_user_name_asked()  # skip the first-launch prompt in tests
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes),
    )
    window = MainWindow(
        settings=app_settings, recovery_path=tmp_path / "recovery.autosave"
    )
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    return window


@pytest.fixture
def project_model(qtbot) -> ProjectModel:
    """Fresh ProjectModel for service and UI tests."""
    return ProjectModel(user_name="tester")
