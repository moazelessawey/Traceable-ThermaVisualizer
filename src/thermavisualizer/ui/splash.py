"""Startup splash screen (M7 polish).

The pixmap is drawn programmatically (no binary assets) so the look is
reproducible and headless-testable. Rendered at 2x for HiDPI sharpness.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSplashScreen

_SPLASH_WIDTH = 680
_SPLASH_HEIGHT = 420
_DEVICE_RATIO = 2.0

# Viridis-like thermal ramp used as the brand motif (VIS-04 family).
_RAMP = (
    (0.00, "#440154"),
    (0.25, "#3b528b"),
    (0.50, "#21918c"),
    (0.75, "#5ec962"),
    (1.00, "#fde725"),
)

# Fixed decorative "logger" positions (pixels) for the background motif.
_DEMO_LOGGERS = (
    (120.0, 70.0),
    (210.0, 100.0),
    (300.0, 60.0),
    (390.0, 95.0),
    (480.0, 65.0),
    (570.0, 100.0),
    (160.0, 255.0),
    (520.0, 255.0),
)


def _ramp_color(fraction: float) -> QColor:
    """Interpolate the thermal ramp at ``fraction`` in [0, 1]."""
    fraction = min(1.0, max(0.0, fraction))
    for (start, start_hex), (end, end_hex) in zip(_RAMP, _RAMP[1:]):
        if fraction <= end:
            local = (fraction - start) / (end - start)
            lower = QColor(start_hex)
            upper = QColor(end_hex)
            return QColor(
                int(lower.red() + (upper.red() - lower.red()) * local),
                int(lower.green() + (upper.green() - lower.green()) * local),
                int(lower.blue() + (upper.blue() - lower.blue()) * local),
            )
    return QColor(_RAMP[-1][1])


def build_splash_pixmap(version: str) -> QPixmap:
    """Draw the splash pixmap. Units: logical pixels at 2x device ratio."""
    pixmap = QPixmap(int(_SPLASH_WIDTH * _DEVICE_RATIO), int(_SPLASH_HEIGHT * _DEVICE_RATIO))
    pixmap.setDevicePixelRatio(_DEVICE_RATIO)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    background = QLinearGradient(0.0, 0.0, 0.0, float(_SPLASH_HEIGHT))
    background.setColorAt(0.0, QColor("#101820"))
    background.setColorAt(1.0, QColor("#1d2d3f"))
    painter.fillRect(0, 0, _SPLASH_WIDTH, _SPLASH_HEIGHT, background)

    # Faint layout-grid motif above the ramp strip.
    painter.setPen(QPen(QColor(255, 255, 255, 16), 1.0))
    for x in range(40, _SPLASH_WIDTH, 40):
        painter.drawLine(x, 0, x, _SPLASH_HEIGHT - 70)
    for y in range(40, _SPLASH_HEIGHT - 70, 40):
        painter.drawLine(0, y, _SPLASH_WIDTH, y)

    # Logger markers colored along the thermal ramp.
    painter.setPen(Qt.PenStyle.NoPen)
    for index, (x, y) in enumerate(_DEMO_LOGGERS):
        color = _ramp_color(index / max(len(_DEMO_LOGGERS) - 1, 1))
        halo = QColor(color)
        halo.setAlpha(70)
        painter.setBrush(halo)
        painter.drawEllipse(QPointF(x, y), 9.0, 9.0)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(x, y), 5.0, 5.0)

    # Title block.
    title_font = QFont()
    title_font.setPointSize(27)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.setPen(QColor("#f5f7fa"))
    painter.drawText(
        QRectF(0, 128, _SPLASH_WIDTH, 50),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        "Traceable.ThermaVisualizer",
    )
    subtitle_font = QFont()
    subtitle_font.setPointSize(12)
    painter.setFont(subtitle_font)
    painter.setPen(QColor("#b8c4d0"))
    painter.drawText(
        QRectF(0, 182, _SPLASH_WIDTH, 22),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        "3D visualization of thermal mapping studies",
    )
    version_font = QFont()
    version_font.setPointSize(10)
    painter.setFont(version_font)
    painter.setPen(QColor("#8fa0b3"))
    painter.drawText(
        QRectF(0, 208, _SPLASH_WIDTH, 18),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        f"version {version}  •  Python / PySide6 / OpenGL",
    )

    # Maintainer credit (AGENTS branding; same text as the status bar).
    credit_font = QFont()
    credit_font.setPointSize(10)
    credit_font.setItalic(True)
    painter.setFont(credit_font)
    painter.setPen(QColor("#d5dde5"))
    painter.drawText(
        QRectF(0, 300, _SPLASH_WIDTH, 20),
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
        "Developed and maintained by Moaz El-Essawey",
    )

    # Thermal ramp strip along the bottom edge.
    ramp = QLinearGradient(0.0, 0.0, float(_SPLASH_WIDTH), 0.0)
    for fraction, hex_value in _RAMP:
        ramp.setColorAt(fraction, QColor(hex_value))
    painter.fillRect(0, _SPLASH_HEIGHT - 14, _SPLASH_WIDTH, 14, ramp)

    painter.end()
    return pixmap


def create_splash(version: str) -> QSplashScreen:
    """Create and show the application splash screen."""
    splash = QSplashScreen(build_splash_pixmap(version))
    splash.show()
    return splash
