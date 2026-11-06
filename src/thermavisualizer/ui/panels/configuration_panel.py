"""Left-panel controls for the Configuration tab (PRD 4.3).

Space, footprint, layers, selected logger, grid tools, obstacles, and the
validation summary. All edits go through ProjectModel commands (CFG-08).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.geometry import footprint_bounds, validate_footprint
from thermavisualizer.core.layout import (
    LayoutError,
    duplicate_logger_ids,
    generate_lattice,
)
from thermavisualizer.core.models import (
    BoxFootprint,
    ConfigurationError,
    Layer,
    LengthUnit,
    LoggerRole,
    PolygonFootprint,
    SpaceType,
    new_id,
)
from thermavisualizer.io.layout_io import (
    LayoutIOError,
    export_layout,
    file_sha256,
    read_footprint_vertices,
    write_layout_template,
)
from thermavisualizer.services.audit import AuditAction
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import (
    AddLayerCommand,
    AddLoggersCommand,
    AddObstacleCommand,
    BulkAddLayersCommand,
    MoveLayerCommand,
    RemoveLayerCommand,
    RemoveObstacleCommand,
    RenameLayerCommand,
    SetLayerCompletedCommand,
    SetLayerHeightCommand,
    SetObstacleVisibleCommand,
    SetSpacePropertiesCommand,
    UpdateLoggerCommand,
    UpdateObstacleCommand,
)
from thermavisualizer.ui.panels.configuration_dialogs import LayerDialog, ObstacleDialog
from thermavisualizer.ui.panels.layout_import_dialog import LayoutImportDialog

_UNIT_FACTORS = {
    LengthUnit.METRES: 1.0,
    LengthUnit.CENTIMETRES: 100.0,
    LengthUnit.MILLIMETRES: 1000.0,
}


def _length_spin() -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(-10000.0, 10000.0)
    spin.setDecimals(3)
    spin.setSingleStep(0.1)
    return spin


class ConfigurationPanel(QWidget):
    """Contextual configuration controls hosted in the left panel."""

    edit_rejected = Signal(str)
    status_message = Signal(str)

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._refreshing = False

        content = QWidget(self)
        root = QVBoxLayout(content)
        root.setContentsMargins(2, 2, 2, 2)
        root.addWidget(self._build_space_group(content))
        root.addWidget(self._build_footprint_group(content))
        root.addWidget(self._build_layers_group(content))
        root.addWidget(self._build_logger_group(content))
        root.addWidget(self._build_grid_group(content))
        root.addWidget(self._build_bulk_group(content))
        root.addWidget(self._build_obstacles_group(content))
        root.addWidget(self._build_issues_group(content))
        root.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        model.config_changed.connect(self._refresh)
        model.active_layer_changed.connect(self._refresh)
        model.logger_selected.connect(self._refresh_logger_form)
        self._refresh()

    # -------------------------------------------------------------- builders

    def _build_space_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Space (CFG-01)", parent)
        layout = QVBoxLayout(group)
        self.space_name_edit = QLineEdit(group)
        self.space_name_edit.editingFinished.connect(self._on_space_name)
        self.space_type_combo = QComboBox(group)
        for space_type in SpaceType:
            self.space_type_combo.addItem(space_type.value, space_type)
        self.space_type_combo.currentIndexChanged.connect(self._on_space_type)
        self.space_height_spin = _length_spin()
        self.space_height_spin.setRange(0.01, 1000.0)
        self.space_height_spin.editingFinished.connect(self._on_space_height)
        self.length_unit_combo = QComboBox(group)
        for unit in LengthUnit:
            self.length_unit_combo.addItem(unit.value, unit)
        self.length_unit_combo.currentIndexChanged.connect(self._on_length_unit)
        layout.addWidget(_labeled("Name", self.space_name_edit, group))
        layout.addWidget(_labeled("Type", self.space_type_combo, group))
        layout.addWidget(_labeled("Height", self.space_height_spin, group))
        layout.addWidget(_labeled("Length unit", self.length_unit_combo, group))
        return group

    def _build_bulk_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Bulk layout (BLK-01/02)", parent)
        layout = QVBoxLayout(group)
        self.import_layout_button = QPushButton("Import layout…", group)
        self.export_layout_button = QPushButton("Export layout…", group)
        self.layout_template_button = QPushButton("Download template…", group)
        self.import_layout_button.clicked.connect(self._on_import_layout)
        self.export_layout_button.clicked.connect(self._on_export_layout)
        self.layout_template_button.clicked.connect(self._on_layout_template)
        layout.addWidget(self.import_layout_button)
        layout.addWidget(self.export_layout_button)
        layout.addWidget(self.layout_template_button)
        return group

    def _build_footprint_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Footprint (GEO-01/02)", parent)
        layout = QVBoxLayout(group)
        self.footprint_shape_combo = QComboBox(group)
        self.footprint_shape_combo.addItem("Box")
        self.footprint_shape_combo.addItem("Polygon")
        self.footprint_shape_combo.currentIndexChanged.connect(self._on_footprint_shape)
        layout.addWidget(_labeled("Shape", self.footprint_shape_combo, group))

        self.import_footprint_button = QPushButton("Import vertices… (GEO-05)", group)
        self.import_footprint_button.clicked.connect(self._on_import_footprint)
        layout.addWidget(self.import_footprint_button)

        self.box_xmin_spin = _length_spin()
        self.box_xmax_spin = _length_spin()
        self.box_ymin_spin = _length_spin()
        self.box_ymax_spin = _length_spin()
        for spin in (
            self.box_xmin_spin,
            self.box_xmax_spin,
            self.box_ymin_spin,
            self.box_ymax_spin,
        ):
            spin.editingFinished.connect(self._on_box_edit)
        layout.addWidget(_labeled("X min", self.box_xmin_spin, group))
        layout.addWidget(_labeled("X max", self.box_xmax_spin, group))
        layout.addWidget(_labeled("Y min", self.box_ymin_spin, group))
        layout.addWidget(_labeled("Y max", self.box_ymax_spin, group))
        self.polygon_info_label = QLabel(group)
        self.polygon_info_label.setWordWrap(True)
        layout.addWidget(self.polygon_info_label)
        return group

    def _build_layers_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Layers (CFG-02/04/06)", parent)
        layout = QVBoxLayout(group)
        self.layer_list = QListWidget(group)
        self.layer_list.currentRowChanged.connect(self._on_layer_selected)
        layout.addWidget(self.layer_list)
        self.add_layer_button = QPushButton("Add…", group)
        self.edit_layer_button = QPushButton("Edit…", group)
        self.remove_layer_button = QPushButton("Remove", group)
        self.move_up_button = QPushButton("Up", group)
        self.move_down_button = QPushButton("Down", group)
        self.duplicate_layer_button = QPushButton("Duplicate", group)
        self.complete_button = QPushButton("Completed", group)
        self.complete_button.setCheckable(True)
        self.add_layer_button.clicked.connect(self._on_add_layer)
        self.edit_layer_button.clicked.connect(self._on_edit_layer)
        self.remove_layer_button.clicked.connect(self._on_remove_layer)
        self.move_up_button.clicked.connect(lambda: self._on_move_layer(-1))
        self.move_down_button.clicked.connect(lambda: self._on_move_layer(1))
        self.duplicate_layer_button.clicked.connect(self._on_duplicate_layer)
        self.complete_button.clicked.connect(self._on_toggle_completed)
        row_one = QHBoxLayout()
        row_one.addWidget(self.add_layer_button)
        row_one.addWidget(self.edit_layer_button)
        row_one.addWidget(self.remove_layer_button)
        row_two = QHBoxLayout()
        row_two.addWidget(self.move_up_button)
        row_two.addWidget(self.move_down_button)
        row_two.addWidget(self.duplicate_layer_button)
        row_two.addWidget(self.complete_button)
        layout.addLayout(row_one)
        layout.addLayout(row_two)
        return group

    def _build_logger_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Selected logger (CFG-05)", parent)
        layout = QVBoxLayout(group)
        self.logger_id_edit = QLineEdit(group)
        self.logger_x_spin = _length_spin()
        self.logger_y_spin = _length_spin()
        self.logger_z_spin = _length_spin()
        self.logger_role_combo = QComboBox(group)
        for role in LoggerRole:
            self.logger_role_combo.addItem(role.value, role)
        self.logger_notes_edit = QLineEdit(group)
        for widget in (self.logger_id_edit, self.logger_notes_edit):
            widget.editingFinished.connect(self._on_logger_field)
        for spin in (self.logger_x_spin, self.logger_y_spin, self.logger_z_spin):
            spin.editingFinished.connect(self._on_logger_field)
        self.logger_role_combo.currentIndexChanged.connect(self._on_logger_role)
        layout.addWidget(_labeled("ID", self.logger_id_edit, group))
        layout.addWidget(_labeled("X (m)", self.logger_x_spin, group))
        layout.addWidget(_labeled("Y (m)", self.logger_y_spin, group))
        layout.addWidget(_labeled("Z (m)", self.logger_z_spin, group))
        layout.addWidget(_labeled("Role", self.logger_role_combo, group))
        layout.addWidget(_labeled("Notes", self.logger_notes_edit, group))
        self._logger_form_widgets = (
            self.logger_id_edit,
            self.logger_x_spin,
            self.logger_y_spin,
            self.logger_z_spin,
            self.logger_role_combo,
            self.logger_notes_edit,
        )
        return group

    def _build_grid_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Grid tools (BLK-03)", parent)
        layout = QVBoxLayout(group)
        self.grid_rows_spin = QSpinBox(group)
        self.grid_columns_spin = QSpinBox(group)
        for spin in (self.grid_rows_spin, self.grid_columns_spin):
            spin.setRange(1, 50)
            spin.setValue(2)
        self.grid_spacing_x_spin = _length_spin()
        self.grid_spacing_y_spin = _length_spin()
        self.grid_spacing_x_spin.setValue(0.5)
        self.grid_spacing_y_spin.setValue(0.5)
        self.grid_offset_x_spin = _length_spin()
        self.grid_offset_y_spin = _length_spin()
        layout.addWidget(_labeled("Rows", self.grid_rows_spin, group))
        layout.addWidget(_labeled("Columns", self.grid_columns_spin, group))
        layout.addWidget(_labeled("Space X (m)", self.grid_spacing_x_spin, group))
        layout.addWidget(_labeled("Space Y (m)", self.grid_spacing_y_spin, group))
        layout.addWidget(_labeled("Offset X (m)", self.grid_offset_x_spin, group))
        layout.addWidget(_labeled("Offset Y (m)", self.grid_offset_y_spin, group))
        self.generate_lattice_button = QPushButton("Generate lattice", group)
        self.generate_lattice_button.clicked.connect(self._on_generate_lattice)
        layout.addWidget(self.generate_lattice_button)
        return group

    def _build_obstacles_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Obstacles (OBS-01/02)", parent)
        layout = QVBoxLayout(group)
        self.obstacle_list = QListWidget(group)
        self.obstacle_list.currentRowChanged.connect(self._on_obstacle_selected)
        layout.addWidget(self.obstacle_list)
        self.add_obstacle_button = QPushButton("Add…", group)
        self.edit_obstacle_button = QPushButton("Edit…", group)
        self.duplicate_obstacle_button = QPushButton("Duplicate", group)
        self.remove_obstacle_button = QPushButton("Remove", group)
        self.toggle_obstacle_visible_button = QPushButton("Show/Hide", group)
        self.add_obstacle_button.clicked.connect(self._on_add_obstacle)
        self.edit_obstacle_button.clicked.connect(self._on_edit_obstacle)
        self.duplicate_obstacle_button.clicked.connect(self._on_duplicate_obstacle)
        self.remove_obstacle_button.clicked.connect(self._on_remove_obstacle)
        self.toggle_obstacle_visible_button.clicked.connect(self._on_toggle_obstacle_visible)
        row_one = QHBoxLayout()
        row_one.addWidget(self.add_obstacle_button)
        row_one.addWidget(self.edit_obstacle_button)
        row_one.addWidget(self.remove_obstacle_button)
        row_two = QHBoxLayout()
        row_two.addWidget(self.duplicate_obstacle_button)
        row_two.addWidget(self.toggle_obstacle_visible_button)
        layout.addLayout(row_one)
        layout.addLayout(row_two)
        return group

    def _build_issues_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Validation (CFG-11)", parent)
        layout = QVBoxLayout(group)
        self.issue_count_label = QLabel(group)
        self.issues_list = QListWidget(group)
        self.issues_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self.issue_count_label)
        layout.addWidget(self.issues_list)
        return group

    # --------------------------------------------------------------- refresh

    def _refresh(self) -> None:
        self._refreshing = True
        try:
            self._refresh_space()
            self._refresh_footprint()
            self._refresh_layers()
            self._refresh_logger_form()
            self._refresh_obstacles()
            self._refresh_validation()
        finally:
            self._refreshing = False

    def _unit_factor(self) -> float:
        return _UNIT_FACTORS[self._model.space.length_unit]

    def _refresh_space(self) -> None:
        space = self._model.space
        factor = self._unit_factor()
        self.space_name_edit.setText(space.name)
        self.space_type_combo.setCurrentIndex(list(SpaceType).index(space.space_type))
        self.space_height_spin.setValue(space.height * factor)
        self.length_unit_combo.setCurrentIndex(list(LengthUnit).index(space.length_unit))

    def _refresh_footprint(self) -> None:
        footprint = self._model.space.footprint
        factor = self._unit_factor()
        is_box = isinstance(footprint, BoxFootprint)
        self.footprint_shape_combo.setCurrentIndex(0 if is_box else 1)
        for spin in (
            self.box_xmin_spin,
            self.box_xmax_spin,
            self.box_ymin_spin,
            self.box_ymax_spin,
        ):
            spin.setVisible(is_box)
        if is_box:
            self.box_xmin_spin.setValue(footprint.x_min * factor)
            self.box_xmax_spin.setValue(footprint.x_max * factor)
            self.box_ymin_spin.setValue(footprint.y_min * factor)
            self.box_ymax_spin.setValue(footprint.y_max * factor)
            self.polygon_info_label.setText("")
        else:
            self.polygon_info_label.setText(
                f"Polygon with {len(footprint.vertices)} vertices. Edit in the 2D view: "
                "switch to 'Edit footprint', drag vertices, click an edge to insert, "
                "press Delete to remove."
            )

    def _refresh_layers(self) -> None:
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        active_id = self._model.active_layer_id()
        selected_row = -1
        for index, layer in enumerate(self._model.space.layers):
            marker = "  [completed]" if layer.completed else ""
            item = QListWidgetItem(f"{layer.name} — {layer.height:.2f} m{marker}")
            item.setData(Qt.ItemDataRole.UserRole, layer.layer_id)
            self.layer_list.addItem(item)
            if layer.layer_id == active_id:
                selected_row = index
        if selected_row >= 0:
            self.layer_list.setCurrentRow(selected_row)
        self.layer_list.blockSignals(False)
        active = self._model.active_layer()
        self.complete_button.setChecked(active.completed if active else False)

    def _refresh_logger_form(self) -> None:
        if self._refreshing:
            pass
        selected = self._model.selected_logger_id()
        layer = self._model.active_layer()
        logger = None
        if selected is not None and layer is not None:
            try:
                logger = self._model.logger_by_id(layer.layer_id, selected)
            except KeyError:
                logger = None
        enabled = logger is not None
        for widget in self._logger_form_widgets:
            widget.setEnabled(enabled)
        if logger is None:
            return
        self._refreshing = True
        try:
            self.logger_id_edit.setText(logger.logger_id)
            self.logger_x_spin.setValue(logger.x)
            self.logger_y_spin.setValue(logger.y)
            self.logger_z_spin.setValue(logger.z)
            self.logger_role_combo.setCurrentIndex(list(LoggerRole).index(logger.role))
            self.logger_notes_edit.setText(logger.notes)
        finally:
            self._refreshing = False

    def _refresh_obstacles(self) -> None:
        self.obstacle_list.blockSignals(True)
        self.obstacle_list.clear()
        selected_id = self._model.selected_obstacle_id()
        selected_row = -1
        for index, obstacle in enumerate(self._model.space.obstacles):
            hidden = "" if obstacle.visible else "  [hidden]"
            item = QListWidgetItem(f"{obstacle.name} ({obstacle.obstacle_type.value}){hidden}")
            item.setData(Qt.ItemDataRole.UserRole, obstacle.obstacle_id)
            self.obstacle_list.addItem(item)
            if obstacle.obstacle_id == selected_id:
                selected_row = index
        if selected_row >= 0:
            self.obstacle_list.setCurrentRow(selected_row)
        self.obstacle_list.blockSignals(False)

    def _refresh_validation(self) -> None:
        issues = self._model.layout_issues()
        errors = sum(1 for issue in issues if issue.severity.value == "error")
        warnings = sum(1 for issue in issues if issue.severity.value == "warning")
        self.issue_count_label.setText(f"{errors} error(s), {warnings} warning(s)")
        self.issues_list.clear()
        for issue in issues:
            item = QListWidgetItem(f"{issue.severity.value.upper()}: {issue.message}")
            if issue.severity.value == "error":
                item.setForeground(Qt.GlobalColor.red)
            elif issue.severity.value == "warning":
                item.setForeground(Qt.GlobalColor.darkYellow)
            self.issues_list.addItem(item)

    # ----------------------------------------------------------- space slots

    def _on_space_name(self) -> None:
        if self._refreshing:
            return
        name = self.space_name_edit.text().strip()
        if name and name != self._model.space.name:
            self._model.apply(SetSpacePropertiesCommand(self._model, name=name))

    def _on_space_type(self, index: int) -> None:
        if self._refreshing:
            return
        data = self.space_type_combo.itemData(index)
        if data is None:
            return
        space_type = SpaceType(str(data))
        if space_type is not self._model.space.space_type:
            self._model.apply(SetSpacePropertiesCommand(self._model, space_type=space_type))

    def _on_space_height(self) -> None:
        if self._refreshing:
            return
        height = self.space_height_spin.value() / self._unit_factor()
        if height != self._model.space.height:
            self._model.apply(SetSpacePropertiesCommand(self._model, height=height))

    def _on_length_unit(self, index: int) -> None:
        if self._refreshing:
            return
        data = self.length_unit_combo.itemData(index)
        if data is None:
            return
        unit = LengthUnit(str(data))
        if unit is not self._model.space.length_unit:
            self._model.apply(SetSpacePropertiesCommand(self._model, length_unit=unit))

    # ------------------------------------------------------- footprint slots

    def _on_footprint_shape(self, index: int) -> None:
        if self._refreshing:
            return
        space = self._model.space
        if index == 0:
            if isinstance(space.footprint, BoxFootprint):
                return
            x_min, y_min, x_max, y_max = footprint_bounds(space.footprint)
            self._model.apply(
                SetSpacePropertiesCommand(
                    self._model, footprint=BoxFootprint(x_min, y_min, x_max, y_max)
                )
            )
        else:
            if isinstance(space.footprint, PolygonFootprint):
                return
            x_min, y_min, x_max, y_max = footprint_bounds(space.footprint)
            corners = ((x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max))
            self._model.apply(
                SetSpacePropertiesCommand(self._model, footprint=PolygonFootprint(corners))
            )

    def _on_box_edit(self) -> None:
        if self._refreshing:
            return
        factor = self._unit_factor()
        x_min = self.box_xmin_spin.value() / factor
        x_max = self.box_xmax_spin.value() / factor
        y_min = self.box_ymin_spin.value() / factor
        y_max = self.box_ymax_spin.value() / factor
        if x_max <= x_min or y_max <= y_min:
            self.edit_rejected.emit("Box footprint needs x_max > x_min and y_max > y_min")
            self._refresh_footprint()
            return
        new_footprint = BoxFootprint(x_min, y_min, x_max, y_max)
        if new_footprint != self._model.space.footprint:
            self._model.apply(SetSpacePropertiesCommand(self._model, footprint=new_footprint))

    # ----------------------------------------------------------- layer slots

    def _on_layer_selected(self, row: int) -> None:
        if self._refreshing or row < 0:
            return
        item = self.layer_list.item(row)
        self._model.set_active_layer(item.data(Qt.ItemDataRole.UserRole))

    def _on_add_layer(self) -> None:
        layers = self._model.space.layers
        suggested_height = (layers[-1].height + 0.5) if layers else 0.0
        dialog = LayerDialog(
            self, "Add layer", name=f"Layer {len(layers) + 1}", height=suggested_height
        )
        if dialog.exec() != LayerDialog.DialogCode.Accepted:
            return
        name, height = dialog.values()
        self._model.apply(AddLayerCommand(self._model, Layer(name=name, height=height)))

    def _on_edit_layer(self) -> None:
        layer = self._model.active_layer()
        if layer is None:
            return
        dialog = LayerDialog(self, "Edit layer", name=layer.name, height=layer.height)
        if dialog.exec() != LayerDialog.DialogCode.Accepted:
            return
        name, height = dialog.values()
        if name != layer.name:
            self._model.apply(RenameLayerCommand(self._model, layer.layer_id, name))
        if height != layer.height:
            self._model.apply(SetLayerHeightCommand(self._model, layer.layer_id, height))

    def _on_remove_layer(self) -> None:
        layer = self._model.active_layer()
        if layer is not None:
            self._model.apply(RemoveLayerCommand(self._model, layer.layer_id))

    def _on_move_layer(self, delta: int) -> None:
        layers = self._model.space.layers
        active_id = self._model.active_layer_id()
        if active_id is None:
            return
        index = self._model.layer_index(active_id)
        target = index + delta
        if 0 <= target < len(layers):
            self._model.apply(MoveLayerCommand(self._model, index, target))

    def _on_duplicate_layer(self) -> None:
        source = self._model.active_layer()
        if source is None:
            return
        existing = frozenset(
            item.logger_id for layer in self._model.space.layers for item in layer.loggers
        )
        new_ids = duplicate_logger_ids([lg.logger_id for lg in source.loggers], existing)
        copies = [
            replace(logger, logger_id=new_id) for logger, new_id in zip(source.loggers, new_ids)
        ]
        self._model.apply(
            AddLayerCommand(
                self._model, Layer(name=f"{source.name} copy", height=source.height, loggers=copies)
            )
        )

    def _on_toggle_completed(self) -> None:
        layer = self._model.active_layer()
        if layer is not None:
            self._model.apply(
                SetLayerCompletedCommand(self._model, layer.layer_id, not layer.completed)
            )

    # ---------------------------------------------------------- logger slots

    def _selected_logger_or_none(self):
        layer = self._model.active_layer()
        selected = self._model.selected_logger_id()
        if layer is None or selected is None:
            return None, None
        try:
            return layer, self._model.logger_by_id(layer.layer_id, selected)
        except KeyError:
            return None, None

    def _on_logger_field(self) -> None:
        if self._refreshing:
            return
        layer, logger = self._selected_logger_or_none()
        if layer is None or logger is None:
            return
        new_id = self.logger_id_edit.text().strip()
        if not new_id:
            self._refresh_logger_form()
            return
        replacement = replace(
            logger,
            logger_id=new_id,
            x=self.logger_x_spin.value(),
            y=self.logger_y_spin.value(),
            z=self.logger_z_spin.value(),
            notes=self.logger_notes_edit.text(),
        )
        if replacement == logger:
            return
        try:
            self._model.apply(
                UpdateLoggerCommand(
                    self._model,
                    layer.layer_id,
                    replacement,
                    previous_id=logger.logger_id if new_id != logger.logger_id else None,
                )
            )
        except ValueError as error:
            self.edit_rejected.emit(str(error))
            self._refresh_logger_form()

    def _on_logger_role(self, index: int) -> None:
        if self._refreshing:
            return
        layer, logger = self._selected_logger_or_none()
        if layer is None or logger is None:
            return
        role = list(LoggerRole)[index]
        if role is not logger.role:
            self._model.apply(
                UpdateLoggerCommand(self._model, layer.layer_id, replace(logger, role=role))
            )

    # ------------------------------------------------------------ grid slots

    def _on_generate_lattice(self) -> None:
        layer = self._model.active_layer()
        if layer is None:
            self.edit_rejected.emit("Add and select a layer before generating a lattice")
            return
        existing = frozenset(
            item.logger_id for any_layer in self._model.space.layers for item in any_layer.loggers
        )
        try:
            loggers = generate_lattice(
                rows=self.grid_rows_spin.value(),
                columns=self.grid_columns_spin.value(),
                spacing_x=self.grid_spacing_x_spin.value(),
                spacing_y=self.grid_spacing_y_spin.value(),
                height=layer.height,
                offset_x=self.grid_offset_x_spin.value(),
                offset_y=self.grid_offset_y_spin.value(),
                existing_ids=existing,
            )
        except LayoutError as error:
            self.edit_rejected.emit(str(error))
            return
        self._model.apply(AddLoggersCommand(self._model, layer.layer_id, loggers))

    # -------------------------------------------------------- obstacle slots

    def _on_obstacle_selected(self, row: int) -> None:
        if self._refreshing or row < 0:
            return
        item = self.obstacle_list.item(row)
        self._model.select_obstacle(item.data(Qt.ItemDataRole.UserRole))

    def _on_add_obstacle(self) -> None:
        dialog = ObstacleDialog(self, "Add obstacle")
        if dialog.exec() != ObstacleDialog.DialogCode.Accepted:
            return
        self._model.apply(AddObstacleCommand(self._model, dialog.obstacle()))

    def _on_edit_obstacle(self) -> None:
        obstacle_id = self._model.selected_obstacle_id()
        if obstacle_id is None:
            return
        obstacle = self._model.obstacle_by_id(obstacle_id)
        dialog = ObstacleDialog(self, "Edit obstacle")
        dialog.set_obstacle(obstacle)
        if dialog.exec() != ObstacleDialog.DialogCode.Accepted:
            return
        self._model.apply(UpdateObstacleCommand(self._model, dialog.obstacle(obstacle_id)))

    def _on_duplicate_obstacle(self) -> None:
        obstacle_id = self._model.selected_obstacle_id()
        if obstacle_id is None:
            return
        obstacle = self._model.obstacle_by_id(obstacle_id)
        copy = replace(obstacle, obstacle_id=new_id(), name=f"{obstacle.name} copy")
        self._model.apply(AddObstacleCommand(self._model, copy))

    def _on_remove_obstacle(self) -> None:
        obstacle_id = self._model.selected_obstacle_id()
        if obstacle_id is not None:
            self._model.apply(RemoveObstacleCommand(self._model, obstacle_id))

    def _on_toggle_obstacle_visible(self) -> None:
        obstacle_id = self._model.selected_obstacle_id()
        if obstacle_id is None:
            return
        obstacle = self._model.obstacle_by_id(obstacle_id)
        self._model.apply(SetObstacleVisibleCommand(self._model, obstacle_id, not obstacle.visible))

    # ----------------------------------------------------------- bulk slots

    def _all_logger_ids(self) -> frozenset[str]:
        return frozenset(
            item.logger_id for layer in self._model.space.layers for item in layer.loggers
        )

    def _on_import_layout(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import layout",
            "",
            "Layout files (*.csv *.txt *.xlsx);;All files (*)",
        )
        if not path:
            return
        dialog = LayoutImportDialog(Path(path), self._all_logger_ids(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        layers = dialog.imported_layers()
        if not layers:
            return
        source = Path(path).name
        self._model.apply(BulkAddLayersCommand(self._model, layers, source=source))
        total = sum(len(layer.loggers) for layer in layers)
        self._model.note(
            AuditAction.FILE_IMPORTED,
            f"file:{source}",
            f"Layout imported: {len(layers)} layer(s), {total} logger(s)",
        )
        self.status_message.emit(f"Imported {len(layers)} layer(s), {total} logger(s)")

    def _on_export_layout(self) -> None:
        layers = self._model.space.layers
        if not layers:
            self.edit_rejected.emit("No layers to export")
            return
        default_name = f"{self._model.space.name or 'layout'}_layout.csv"
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export layout", default_name, "CSV (*.csv);;Excel (*.xlsx)"
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() not in (".csv", ".xlsx", ".xls"):
            target = target.with_suffix(".xlsx" if "Excel" in selected_filter else ".csv")
        export_layout(target, layers)
        digest = file_sha256(target)
        total = sum(len(layer.loggers) for layer in layers)
        self._model.note(
            AuditAction.EXPORTED,
            f"file:{target.name}",
            f"Layout exported: {len(layers)} layer(s), {total} logger(s); sha256={digest[:16]}…",
        )
        self.status_message.emit(f"Layout exported to {target.name}")

    def _on_layout_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save layout template",
            "layout_template.csv",
            "CSV (*.csv);;Excel (*.xlsx)",
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() not in (".csv", ".xlsx", ".xls"):
            target = target.with_suffix(".csv")
        write_layout_template(target)
        self._model.note(
            AuditAction.EXPORTED, f"file:{target.name}", "Layout import template exported"
        )
        self.status_message.emit(f"Template saved to {target.name}")

    def _on_import_footprint(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import footprint vertices",
            "",
            "Vertex files (*.csv *.txt *.xlsx);;All files (*)",
        )
        if not path:
            return
        try:
            vertices = read_footprint_vertices(Path(path))
            footprint = PolygonFootprint(tuple(vertices))
            validate_footprint(footprint)
        except (LayoutIOError, ConfigurationError) as error:
            self.edit_rejected.emit(str(error))
            return
        self._model.apply(SetSpacePropertiesCommand(self._model, footprint=footprint))
        self._model.note(
            AuditAction.FILE_IMPORTED,
            f"file:{Path(path).name}",
            f"Footprint vertices imported ({len(vertices)} vertices)",
        )
        self.status_message.emit(f"Footprint imported ({len(vertices)} vertices)")


def _labeled(text: str, widget: QWidget, parent: QWidget) -> QWidget:
    """Wrap a widget with a small label row."""
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    label = QLabel(text, row)
    label.setMinimumWidth(70)
    layout.addWidget(label)
    layout.addWidget(widget, 1)
    return row
