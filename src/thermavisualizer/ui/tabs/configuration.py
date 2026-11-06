"""Configuration tab: 2D layer editor, vertical stack view, logger table (CFG-09)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.rendering.configuration_preview import ConfigurationPreview
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.ui.widgets.layer_editor import EditorMode, Layer2DEditor
from thermavisualizer.ui.widgets.logger_table import LoggerTableWidget
from thermavisualizer.ui.widgets.mini_stack import MiniStackView


class ConfigurationTab(QWidget):
    """Layout design view: top-down editor with side stack view and table."""

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        self.select_button = QToolButton(self)
        self.select_button.setText("Select")
        self.select_button.setCheckable(True)
        self.select_button.setChecked(True)
        self.add_logger_button = QToolButton(self)
        self.add_logger_button.setText("Add logger")
        self.add_logger_button.setCheckable(True)
        self.edit_footprint_button = QToolButton(self)
        self.edit_footprint_button.setText("Edit footprint")
        self.edit_footprint_button.setCheckable(True)
        self.select_button.clicked.connect(lambda: self.editor.set_mode(EditorMode.SELECT))
        self.add_logger_button.clicked.connect(lambda: self.editor.set_mode(EditorMode.ADD_LOGGER))
        self.edit_footprint_button.clicked.connect(
            lambda: self.editor.set_mode(EditorMode.EDIT_FOOTPRINT)
        )

        toolbar.addWidget(self.select_button)
        toolbar.addWidget(self.add_logger_button)
        toolbar.addWidget(self.edit_footprint_button)
        toolbar.addWidget(QLabel("Snap (m)", self))
        self.snap_spin = QDoubleSpinBox(self)
        self.snap_spin.setRange(0.0, 10.0)
        self.snap_spin.setDecimals(3)
        self.snap_spin.setSingleStep(0.05)
        self.snap_spin.setValue(0.1)
        self.snap_spin.setToolTip("Grid snap step in metres; 0 disables snapping")
        toolbar.addWidget(self.snap_spin)
        self.preview_toggle = QCheckBox("3D preview", self)
        self.preview_toggle.setChecked(True)
        self.preview_toggle.toggled.connect(self._on_preview_toggled)
        toolbar.addWidget(self.preview_toggle)

        toolbar.addStretch(1)
        toolbar.addWidget(
            QLabel(
                "Add mode: click to place • Edit footprint: drag vertices, "
                "click an edge to insert, Delete removes",
                self,
            )
        )
        layout.addLayout(toolbar)

        self.editor = Layer2DEditor(model, self)
        self.mini_view = MiniStackView(model, self)
        self.preview = ConfigurationPreview(model, self)
        splitter = QSplitter(self)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.mini_view)
        splitter.addWidget(self.preview)
        splitter.setSizes([520, 170, 380])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, True)
        layout.addWidget(splitter, 1)

        self.table = LoggerTableWidget(model, self)
        self.table.setMaximumHeight(220)
        layout.addWidget(self.table, 0)

        self.snap_spin.valueChanged.connect(self.editor.set_snap_step)
        self.editor.mode_changed.connect(self._sync_mode_buttons)

    def _sync_mode_buttons(self, mode: EditorMode) -> None:
        self.select_button.setChecked(mode is EditorMode.SELECT)
        self.add_logger_button.setChecked(mode is EditorMode.ADD_LOGGER)
        self.edit_footprint_button.setChecked(mode is EditorMode.EDIT_FOOTPRINT)

    def _on_preview_toggled(self, visible: bool) -> None:
        self.preview.setVisible(visible)
