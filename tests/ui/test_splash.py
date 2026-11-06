"""Splash screen: pixmap rendering and offscreen display (M7 polish)."""

from __future__ import annotations

from PySide6.QtGui import QImage
from pytestqt.qtbot import QtBot

from thermavisualizer.ui.splash import build_splash_pixmap, create_splash


def test_splash_pixmap_dimensions() -> None:
    pixmap = build_splash_pixmap("1.0.0-rc1")
    assert not pixmap.isNull()
    assert pixmap.width() / pixmap.devicePixelRatio() == 680
    assert pixmap.height() / pixmap.devicePixelRatio() == 420


def test_splash_pixmap_is_not_blank() -> None:  # AGENTS §8: non-blank check
    image = build_splash_pixmap("0.0.0").toImage().convertToFormat(
        QImage.Format.Format_RGB32
    )
    colors = set()
    for x in range(0, image.width(), 16):
        for y in range(0, image.height(), 16):
            colors.add(image.pixel(x, y))
    assert len(colors) > 20  # gradient + motif, not a flat fill


def test_create_splash_shows_and_closes(qtbot: QtBot) -> None:
    splash = create_splash("1.0.0-rc1")
    qtbot.addWidget(splash)
    assert splash.isVisible()
    splash.close()