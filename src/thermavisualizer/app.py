"""Application entry point: Qt setup, logging, and the main window."""

from __future__ import annotations

import logging
import sys
import time
from types import TracebackType

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSplashScreen

from thermavisualizer import __version__
from thermavisualizer.services.logging_setup import configure_logging, default_log_file
from thermavisualizer.ui.main_window import MainWindow
from thermavisualizer.ui.splash import create_splash

logger = logging.getLogger(__name__)


def _unhandled_exception(
    exc_type: type[BaseException],
    value: BaseException,
    traceback: TracebackType | None,
) -> None:
    """Log unhandled exceptions and notify the user (local only, no telemetry)."""
    logger.critical("Unhandled exception", exc_info=(exc_type, value, traceback))
    QMessageBox.critical(
        None,
        "Unexpected error",
        "An unexpected error occurred. Details were written to the log file.\n"
        f"{exc_type.__name__}: {value}",
    )


MIN_SPLASH_MS = 3000


def _reveal_main_window(window: MainWindow, splash: QSplashScreen) -> None:
    """Show the main window and close the splash (startup only)."""
    if window.should_start_maximized():
        window.showMaximized()
    else:
        window.show()
    window.raise_()
    window.activateWindow()
    splash.finish(window)
    splash.deleteLater()


def main() -> int:
    """Launch Traceable.ThermaVisualizer. Returns the process exit code."""
    log_file = configure_logging(default_log_file().parent)
    logger.info("Starting Traceable.ThermaVisualizer %s (log: %s)", __version__, log_file)

    QApplication.setApplicationName("ThermaVisualizer")
    QApplication.setOrganizationName("Traceable")
    QApplication.setApplicationVersion(__version__)

    app = QApplication(sys.argv)
    sys.excepthook = _unhandled_exception

    started = time.monotonic()
    splash = create_splash(__version__)
    window = MainWindow()
    elapsed_ms = int((time.monotonic() - started) * 1000)
    delay_ms = max(0, MIN_SPLASH_MS - elapsed_ms)
    QTimer.singleShot(delay_ms, lambda: _reveal_main_window(window, splash))
    logger.info("startup: window ready in %s ms; splash shown for %s ms", elapsed_ms, delay_ms)

    exit_code = app.exec()
    logger.info("Application exited with code %s", exit_code)
    return exit_code
