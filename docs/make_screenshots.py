"""Generate README screenshots by grabbing each real tab off-screen.

Run:  QT_QPA_PLATFORM=offscreen python docs/make_screenshots.py
Writes docs/screenshots/<tab>.png. The 3D View renders its no-GL fallback
off-screen; capture it on a real GPU machine for a populated canvas. Units: px.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from thermavisualizer.ui.main_window import MainWindow  # noqa: E402

OUT = Path(__file__).resolve().parent / "screenshots"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(1400, 900)
    window.show()
    window.grab().save(str(OUT / "overview.png"))
    tabs = window.tab_widget
    for index in range(tabs.count()):
        tabs.setCurrentIndex(index)
        app.processEvents()
        name = tabs.tabText(index).replace(" ", "_").replace("/", "-").lower()
        window.grab().save(str(OUT / f"{name}.png"))
    print(f"wrote screenshots to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())