"""Editable logger-to-column mapping table (DAT-03/04/05)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.mapping import find_duplicate_column_mappings
from thermavisualizer.core.models import LoggerMapping, ParsedFile
from thermavisualizer.services.project_model import ProjectModel

_NO_SOURCE = "— none —"


class MappingEditorWidget(QWidget):
    """Table mapping each logger to a temperature and optional humidity column."""

    duplicate_warning = Signal(str)

    def __init__(
        self,
        model: ProjectModel,
        files: list[ParsedFile] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self._refreshing = False
        self._files = files if files is not None else model.files()
        self._options: list[str] = []
        self._source_by_label: dict[str, tuple[str, str]] = {}
        self._label_by_source: dict[tuple[str, str], str] = {}
        self._row_of: dict[str, int] = {}
        self._temp_combos: dict[str, QComboBox] = {}
        self._hum_combos: dict[str, QComboBox] = {}
        self._excl_checks: dict[str, QCheckBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(self)
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Logger", "Temperature", "Humidity", "Excluded"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        self._build_options()
        self.refresh()
        model.mapping_changed.connect(self._maybe_refresh)
        model.files_changed.connect(self._on_files_changed)

    # ------------------------------------------------------------ options

    def set_files(self, files: list[ParsedFile]) -> None:
        """Use an explicit file list (e.g. previews) for the column options."""
        self._files = files
        self._build_options()
        self.refresh()

    def _build_options(self) -> None:
        self._options = [_NO_SOURCE]
        self._source_by_label = {_NO_SOURCE: ("", "")}
        self._label_by_source = {("", ""): _NO_SOURCE}
        for file in self._files:
            for column in file.numeric_column_names():
                label = f"{file.name} :: {column}"
                self._options.append(label)
                self._source_by_label[label] = (file.path, column)
                self._label_by_source[(file.path, column)] = label

    # ------------------------------------------------------------ refresh

    def _maybe_refresh(self) -> None:
        if not self._refreshing:
            self.refresh()

    def _on_files_changed(self) -> None:
        self._files = self._model.files()
        self._build_options()
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the table from the model."""
        self._refreshing = True
        try:
            self._populate()
        finally:
            self._refreshing = False

    def _populate(self) -> None:
        self._table.clearContents()
        self._row_of.clear()
        self._temp_combos.clear()
        self._hum_combos.clear()
        self._excl_checks.clear()
        logger_ids = self._model.all_logger_ids()
        self._table.setRowCount(len(logger_ids))
        for row, logger_id in enumerate(logger_ids):
            self._row_of[logger_id] = row
            id_item = QTableWidgetItem(logger_id)
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, id_item)

            temp = QComboBox(self)
            hum = QComboBox(self)
            for combo in (temp, hum):
                combo.addItems(self._options)
            excl = QCheckBox(self)
            self._table.setCellWidget(row, 1, temp)
            self._table.setCellWidget(row, 2, hum)
            self._table.setCellWidget(row, 3, excl)
            self._temp_combos[logger_id] = temp
            self._hum_combos[logger_id] = hum
            self._excl_checks[logger_id] = excl

            temp.currentIndexChanged.connect(lambda _i, lid=logger_id: self._apply_row(lid))
            hum.currentIndexChanged.connect(lambda _i, lid=logger_id: self._apply_row(lid))
            excl.toggled.connect(lambda _state, lid=logger_id: self._apply_row(lid))

            mapping = self._model.mapping_for(logger_id)
            if mapping is not None:
                self._set_row(logger_id, mapping)
            self._sync_enabled(logger_id)

    def _set_row(self, logger_id: str, mapping: LoggerMapping) -> None:
        temp_label = self._label_by_source.get(
            (mapping.temperature_file, mapping.temperature_column), _NO_SOURCE
        )
        hum_label = self._label_by_source.get(
            (mapping.humidity_file, mapping.humidity_column), _NO_SOURCE
        )
        self._temp_combos[logger_id].setCurrentText(temp_label)
        self._hum_combos[logger_id].setCurrentText(hum_label)
        self._excl_checks[logger_id].setChecked(mapping.excluded)
        self._sync_enabled(logger_id)

    def _sync_enabled(self, logger_id: str) -> None:
        excluded = self._excl_checks[logger_id].isChecked()
        self._temp_combos[logger_id].setEnabled(not excluded)
        self._hum_combos[logger_id].setEnabled(not excluded)

    # ------------------------------------------------------------- editing

    def _apply_row(self, logger_id: str) -> None:
        self._refreshing = True
        try:
            mapping = self._read_row(logger_id)
            self._sync_enabled(logger_id)
            self._model.set_mapping(mapping)
        finally:
            self._refreshing = False
        self._check_duplicates()

    def _read_row(self, logger_id: str) -> LoggerMapping:
        temp_label = self._temp_combos[logger_id].currentText()
        hum_label = self._hum_combos[logger_id].currentText()
        excluded = self._excl_checks[logger_id].isChecked()
        temp_file, temp_col = self._source_by_label.get(temp_label, ("", ""))
        hum_file, hum_col = self._source_by_label.get(hum_label, ("", ""))
        if excluded:
            temp_file = temp_col = hum_file = hum_col = ""
        return LoggerMapping(
            logger_id=logger_id,
            temperature_file=temp_file,
            temperature_column=temp_col,
            humidity_file=hum_file,
            humidity_column=hum_col,
            excluded=excluded,
        )

    def current_mappings(self) -> list[LoggerMapping]:
        """All rows as mappings (for the import dialog)."""
        return [self._read_row(logger_id) for logger_id in self._row_of]

    def _check_duplicates(self) -> None:
        duplicates = find_duplicate_column_mappings(self._model.mappings())
        if duplicates:
            parts = [
                f"'{column}' in {Path(file).name} → {', '.join(ids)}"
                for file, column, _quantity, ids in duplicates
            ]
            self.duplicate_warning.emit("Duplicate column mapping (DAT-05): " + "; ".join(parts))
        else:
            self.duplicate_warning.emit("")
