"""Floating canvas overlay actions for the 3D view (PRD 4.2)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton, QVBoxLayout

from thermavisualizer.rendering.scene import PresetView


class CanvasOverlay(QFrame):
    """Top-right action strip over the 3D canvas (AGENTS UI contract)."""

    reset_camera_clicked = Signal()
    preset_selected = Signal(object)
    markers_toggled = Signal(bool)
    labels_toggled = Signal(bool)
    bounding_box_toggled = Signal(bool)
    slices_toggled = Signal(bool)
    screenshot_clicked = Signal()
    color_scale_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(2)

        camera_row = QHBoxLayout()
        camera_row.setSpacing(2)
        self.reset_button = self._button("Reset", "Reset camera to fit the scene")
        self.reset_button.clicked.connect(self.reset_camera_clicked)
        self.top_button = self._button("Top", "Top view")
        self.front_button = self._button("Front", "Front view")
        self.side_button = self._button("Side", "Side view")
        self.iso_button = self._button("Iso", "Isometric view")
        self.top_button.clicked.connect(lambda: self.preset_selected.emit(PresetView.TOP))
        self.front_button.clicked.connect(lambda: self.preset_selected.emit(PresetView.FRONT))
        self.side_button.clicked.connect(lambda: self.preset_selected.emit(PresetView.SIDE))
        self.iso_button.clicked.connect(lambda: self.preset_selected.emit(PresetView.ISOMETRIC))
        self.screenshot_button = self._button("Shot", "Save a screenshot (EXP-03)")
        self.screenshot_button.clicked.connect(self.screenshot_clicked)
        self.colors_button = self._button("Colors", "Color scale settings (VIS-04)")
        self.colors_button.clicked.connect(self.color_scale_clicked)
        for button in (
            self.reset_button,
            self.top_button,
            self.front_button,
            self.side_button,
            self.iso_button,
            self.screenshot_button,
            self.colors_button,
        ):
            camera_row.addWidget(button)
        outer.addLayout(camera_row)

        toggles_row = QHBoxLayout()
        toggles_row.setSpacing(2)
        self.markers_button = self._toggle("Markers", "Toggle logger markers", True)
        self.labels_button = self._toggle("Labels", "Toggle logger labels", False)
        self.box_button = self._toggle("Box", "Toggle the space outline", True)
        self.slices_button = self._toggle("Slices", "Toggle slice surfaces", True)
        self.markers_button.toggled.connect(self.markers_toggled)
        self.labels_button.toggled.connect(self.labels_toggled)
        self.box_button.toggled.connect(self.bounding_box_toggled)
        self.slices_button.toggled.connect(self.slices_toggled)
        for button in (
            self.markers_button,
            self.labels_button,
            self.box_button,
            self.slices_button,
        ):
            toggles_row.addWidget(button)
        toggles_row.addStretch(1)
        outer.addLayout(toggles_row)

    def _button(self, text: str, tooltip: str) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setToolTip(tooltip)
        return button

    def _toggle(self, text: str, tooltip: str, checked: bool) -> QToolButton:
        button = self._button(text, tooltip)
        button.setCheckable(True)
        button.setChecked(checked)
        return button
