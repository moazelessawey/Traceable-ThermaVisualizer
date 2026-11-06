"""Editable table of the active layer's loggers (CFG-03, CFG-05)."""

from __future__ import annotations

import functools
from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from thermavisualizer.core.models import LoggerRole
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import UpdateLoggerCommand


class LoggerTableWidget(QTableWidget):
    """Table with inline editing routed through undoable commands."""

    edit_rejected = Signal(str)

    _COLUMNS = ("ID", "X (m)", "Y (m)", "Z (m)", "Role", "Notes")
    _ID, _X, _Y, _Z, _ROLE, _NOTES = range(6)

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._populating = False
        self.setColumnCount(len(self._COLUMNS))
        self.setHorizontalHeaderLabels(list(self._COLUMNS))
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        model.loggers_changed.connect(self._rebuild)
        model.active_layer_changed.connect(self._rebuild)
        model.logger_selected.connect(self._sync_selection)
        self.itemChanged.connect(self._on_item_changed)
        self.itemSelectionChanged.connect(self._on_selection_changed)

    # -------------------------------------------------------------- building

    def _rebuild(self) -> None:
        self._populating = True
        try:
            self.blockSignals(True)
            self.clearContents()
            layer = self._model.active_layer()
            loggers = layer.loggers if layer is not None else []
            self.setRowCount(len(loggers))
            for row, logger in enumerate(loggers):
                id_item = QTableWidgetItem(logger.logger_id)
                id_item.setData(Qt.ItemDataRole.UserRole, logger.logger_id)
                self.setItem(row, self._ID, id_item)
                self.setItem(row, self._X, QTableWidgetItem(f"{logger.x:.3f}"))
                self.setItem(row, self._Y, QTableWidgetItem(f"{logger.y:.3f}"))
                self.setItem(row, self._Z, QTableWidgetItem(f"{logger.z:.3f}"))
                combo = QComboBox(self)
                combo.addItems([role.value for role in LoggerRole])
                combo.setCurrentText(logger.role.value)
                combo.blockSignals(True)
                self.setCellWidget(row, self._ROLE, combo)
                combo.currentIndexChanged.connect(
                    functools.partial(self._on_role_changed, logger.logger_id)
                )
                combo.blockSignals(False)
                self.setItem(row, self._NOTES, QTableWidgetItem(logger.notes))
        finally:
            self.blockSignals(False)
            self._populating = False
        self._sync_selection()

    def _sync_selection(self) -> None:
        selected = self._model.selected_logger_id()
        self.blockSignals(True)
        try:
            self.clearSelection()
            if selected is not None:
                for row in range(self.rowCount()):
                    row_item = self.item(row, self._ID)
                    if row_item is not None and row_item.data(Qt.ItemDataRole.UserRole) == selected:
                        self.selectRow(row)
                        break
        finally:
            self.blockSignals(False)

    def _logger_id_at(self, row: int) -> str | None:
        """Logger ID stored on the row, or None for invalid rows."""
        if row < 0:
            return None
        item = self.item(row, self._ID)
        if item is None:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole))

    # ----------------------------------------------------------------- slots

    def _on_selection_changed(self) -> None:
        if self._populating:
            return
        rows = self.selectionModel().selectedRows()
        if not rows:
            return
        logger_id = self._logger_id_at(rows[0].row())
        if logger_id is None:
            return
        try:
            self._model.select_logger(logger_id)
        except KeyError:
            pass

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._populating or item is None:
            return
        layer = self._model.active_layer()
        if layer is None:
            return
        row, column = item.row(), item.column()
        logger_id = self._logger_id_at(row)
        if logger_id is None:
            return
        try:
            current = self._model.logger_by_id(layer.layer_id, logger_id)
        except KeyError:
            return
        try:
            if column == self._ID:
                new_id = item.text().strip()
                if not new_id or new_id == current.logger_id:
                    self._rebuild()
                    return
                self._model.apply(
                    UpdateLoggerCommand(
                        self._model,
                        layer.layer_id,
                        replace(current, logger_id=new_id),
                        previous_id=current.logger_id,
                    )
                )
            elif column in (self._X, self._Y, self._Z):
                value = float(item.text())
                field = {self._X: "x", self._Y: "y", self._Z: "z"}[column]
                if value == getattr(current, field):
                    self._rebuild()
                    return
                self._model.apply(
                    UpdateLoggerCommand(
                        self._model, layer.layer_id, replace(current, **{field: value})
                    )
                )
            elif column == self._NOTES:
                if item.text() != current.notes:
                    self._model.apply(
                        UpdateLoggerCommand(
                            self._model, layer.layer_id, replace(current, notes=item.text())
                        )
                    )
        except ValueError as error:
            self.edit_rejected.emit(str(error))
            self._rebuild()

    def _on_role_changed(self, logger_id: str, index: int) -> None:
        if self._populating:
            return
        layer = self._model.active_layer()
        if layer is None:
            return
        try:
            current = self._model.logger_by_id(layer.layer_id, logger_id)
            role = list(LoggerRole)[index]
            if role is not current.role:
                self._model.apply(
                    UpdateLoggerCommand(self._model, layer.layer_id, replace(current, role=role))
                )
        except (KeyError, ValueError) as error:
            self.edit_rejected.emit(str(error))
            self._rebuild()
