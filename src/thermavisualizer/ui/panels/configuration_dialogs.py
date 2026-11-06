"""Dialogs for layer and obstacle editing used by the Configuration panel."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.models import (
    Obstacle,
    ObstacleShape,
    ObstacleType,
    new_id,
)

_COLOURS = (
    ("Grey", "#8a8a8a"),
    ("Blue", "#3b6fb6"),
    ("Green", "#3a9a5b"),
    ("Orange", "#c87a2b"),
    ("Red", "#b6423b"),
    ("Purple", "#7a5fb0"),
)


def _spin(value: float = 0.0, minimum: float = -1000.0, maximum: float = 1000.0) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(3)
    spin.setSingleStep(0.1)
    spin.setValue(value)
    return spin


class LayerDialog(QDialog):
    """Name + height dialog for adding or editing a layer (CFG-02)."""

    def __init__(
        self, parent: QWidget | None, title: str, name: str = "", height: float = 0.0
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout()
        self.name_edit = QLineEdit(name, self)
        self.height_spin = _spin(height, minimum=0.0, maximum=100.0)
        form.addRow("Name", self.name_edit)
        form.addRow("Height (m)", self.height_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, float]:
        """Return the chosen (name, height in metres)."""
        return self.name_edit.text().strip() or "Layer", self.height_spin.value()


class ObstacleDialog(QDialog):
    """Add/edit dialog for obstacles (OBS-01)."""

    def __init__(self, parent: QWidget | None, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout()
        self.name_edit = QLineEdit("Obstacle", self)
        self.type_combo = QComboBox(self)
        for obstacle_type in ObstacleType:
            self.type_combo.addItem(obstacle_type.value, obstacle_type)
        self.shape_combo = QComboBox(self)
        for shape in ObstacleShape:
            self.shape_combo.addItem(shape.value, shape)
        self.x_spin = _spin(0.0)
        self.y_spin = _spin(0.0)
        self.z_spin = _spin(0.5, minimum=0.0)
        self.size_x_spin = _spin(1.0, minimum=0.001)
        self.size_y_spin = _spin(1.0, minimum=0.0)
        self.size_z_spin = _spin(1.0, minimum=0.001)
        self._label_size_x = QLabel("Size X (m)", self)
        self._label_size_y = QLabel("Size Y (m)", self)
        self._label_size_z = QLabel("Size Z (m)", self)
        self.rotation_spin = _spin(0.0, minimum=-360.0, maximum=360.0)
        self.colour_combo = QComboBox(self)
        for label, hex_value in _COLOURS:
            self.colour_combo.addItem(label, hex_value)
        self.solid_check = QCheckBox("Solid (masks interpolation, OBS-05)", self)
        self.visible_check = QCheckBox("Visible", self)
        self.visible_check.setChecked(True)

        form.addRow("Name", self.name_edit)
        form.addRow("Type", self.type_combo)
        form.addRow("Shape", self.shape_combo)
        form.addRow("X (m)", self.x_spin)
        form.addRow("Y (m)", self.y_spin)
        form.addRow("Z centre (m)", self.z_spin)
        form.addRow(self._label_size_x, self.size_x_spin)
        form.addRow(self._label_size_y, self.size_y_spin)
        form.addRow(self._label_size_z, self.size_z_spin)
        form.addRow("Rotation about Z (°)", self.rotation_spin)
        form.addRow("Colour", self.colour_combo)
        form.addRow(self.solid_check)
        form.addRow(self.visible_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.shape_combo.currentIndexChanged.connect(self._update_size_labels)

    def _update_size_labels(self) -> None:
        """Swap size labels between box and cylinder semantics (OBS-01)."""
        shape = ObstacleShape(self.shape_combo.currentData())
        if shape is ObstacleShape.CYLINDER:
            self._label_size_x.setText("Diameter (m)")
            self._label_size_y.setText("— (unused)")
            self._label_size_z.setText("Height (m)")
            self.size_y_spin.setEnabled(False)
        else:
            self._label_size_x.setText("Size X (m)")
            self._label_size_y.setText("Size Y (m)")
            self._label_size_z.setText("Size Z (m)")
            self.size_y_spin.setEnabled(True)

    def set_obstacle(self, obstacle: Obstacle) -> None:
        """Populate the form from an existing obstacle."""
        self.name_edit.setText(obstacle.name)
        self.type_combo.setCurrentIndex(list(ObstacleType).index(obstacle.obstacle_type))
        self.shape_combo.setCurrentIndex(list(ObstacleShape).index(obstacle.shape))
        self.x_spin.setValue(obstacle.x)
        self.y_spin.setValue(obstacle.y)
        self.z_spin.setValue(obstacle.z)
        self.size_x_spin.setValue(obstacle.size_x)
        self.size_y_spin.setValue(obstacle.size_y)
        self.size_z_spin.setValue(obstacle.size_z)
        self.rotation_spin.setValue(obstacle.rotation_z_deg)
        self.colour_combo.setCurrentIndex(max(self.colour_combo.findData(obstacle.colour), 0))
        self.solid_check.setChecked(obstacle.solid)
        self.visible_check.setChecked(obstacle.visible)

    def obstacle(self, obstacle_id: str | None = None) -> Obstacle:
        """Build the Obstacle from the form (new id when ``obstacle_id`` is None)."""
        return Obstacle(
            name=self.name_edit.text().strip() or "Obstacle",
            obstacle_type=ObstacleType(self.type_combo.currentData()),
            shape=ObstacleShape(self.shape_combo.currentData()),
            x=self.x_spin.value(),
            y=self.y_spin.value(),
            z=self.z_spin.value(),
            size_x=self.size_x_spin.value(),
            size_y=self.size_y_spin.value(),
            size_z=self.size_z_spin.value(),
            obstacle_id=obstacle_id if obstacle_id is not None else new_id(),
            rotation_z_deg=self.rotation_spin.value(),
            colour=str(self.colour_combo.currentData()),
            visible=self.visible_check.isChecked(),
            solid=self.solid_check.isChecked(),
        )
