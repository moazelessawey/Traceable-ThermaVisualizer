"""Traceable.ThermaVisualizer — thermal mapping study visualization.

Sets ``QT_API=pyside6`` before any binding auto-detecting library
(matplotlib, pyqtgraph) is imported, per AGENTS.md.
"""

import os

os.environ.setdefault("QT_API", "pyside6")

__version__ = "1.0.0"
