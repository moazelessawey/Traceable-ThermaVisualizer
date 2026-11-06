"""Light and dark application themes (VIS-08).

Palette construction and application only. Units: n/a.
"""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


class Theme(StrEnum):
    """Available UI themes."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


def build_light_palette() -> QPalette:
    """Explicit light palette with accessible contrast."""
    palette = QPalette()
    text = QColor("#1f1f1f")
    highlight = QColor("#2a6fd6")
    palette.setColor(QPalette.ColorRole.Window, QColor("#f2f2f2"))
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#e9eef5"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, QColor("#e4e4e4"))
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#fffbe6"))
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8a8a8a"))
    muted = QColor("#9a9a9a")
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, muted)
    return palette


def build_dark_palette() -> QPalette:
    """Dark palette for low-light review sessions."""
    palette = QPalette()
    text = QColor("#e8e8e8")
    muted = QColor("#9aa0a6")
    highlight = QColor("#3a76d0")
    palette.setColor(QPalette.ColorRole.Window, QColor("#232629"))
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, QColor("#1a1d21"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2b2f34"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, QColor("#2f343a"))
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#3a3f45"))
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.PlaceholderText, muted)
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, muted)
    return palette


def apply_theme(app: QApplication, theme: Theme) -> None:
    """Apply the theme application-wide; SYSTEM restores the style default."""
    if theme is Theme.SYSTEM:
        app.setPalette(app.style().standardPalette())
    elif theme is Theme.DARK:
        app.setPalette(build_dark_palette())
    else:
        app.setPalette(build_light_palette())
