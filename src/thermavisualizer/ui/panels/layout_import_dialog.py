"""Layout import dialog: preview, column mapping, validation report (BLK-01)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.models import Layer, Severity
from thermavisualizer.io.layout_io import (
    LayoutIOError,
    LayoutMapping,
    LayoutTable,
    parse_layout_records,
    read_layout_table,
    records_to_layers,
    suggest_mapping,
)

_PREVIEW_ROW_LIMIT = 50
_NONE = "(none)"
_FIELDS = (
    ("logger_id", "Logger ID"),
    ("x", "X"),
    ("y", "Y"),
    ("z", "Z"),
    ("layer", "Layer"),
    ("notes", "Notes"),
)


class LayoutImportDialog(QDialog):
    """Import a logger layout from CSV/TXT/XLSX.

    Shows a raw preview, lets the user map columns, and produces a row-level
    error report before anything touches the project (BLK-01).
    """

    def __init__(
        self, path: Path, existing_ids: frozenset[str], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Import layout — {path.name}")
        self.resize(760, 640)
        self._path = path
        self._existing_ids = existing_ids
        self._imported_layers: list[Layer] = []
        self._table: LayoutTable | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"File: {path}", self))

        options = QHBoxLayout()
        options.addWidget(QLabel("Delimiter", self))
        self.delimiter_combo = QComboBox(self)
        self.delimiter_combo.addItems(("Auto", ",", ";", "Tab"))
        options.addWidget(self.delimiter_combo)
        options.addWidget(QLabel("Decimal", self))
        self.decimal_combo = QComboBox(self)
        self.decimal_combo.addItems((".", ","))
        options.addWidget(self.decimal_combo)
        options.addStretch(1)
        layout.addLayout(options)

        mapping_row = QHBoxLayout()
        self.mapping_combos: dict[str, QComboBox] = {}
        for key, label in _FIELDS:
            mapping_row.addWidget(QLabel(label, self))
            combo = QComboBox(self)
            combo.addItem(_NONE)
            self.mapping_combos[key] = combo
            mapping_row.addWidget(combo)
        layout.addLayout(mapping_row)

        self.preview_table = QTableWidget(self)
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.preview_table, 1)

        self.report_summary = QLabel("", self)
        self.report_list = QListWidget(self)
        self.report_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self.report_summary)
        layout.addWidget(self.report_list, 1)

        buttons = QHBoxLayout()
        self.import_button = QPushButton("Import into project", self)
        self.import_button.clicked.connect(self._on_import_clicked)
        cancel_button = QPushButton("Cancel", self)
        cancel_button.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(self.import_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        self._load()

    # -------------------------------------------------------------- loading

    def _load(self) -> None:
        try:
            self._table = read_layout_table(self._path)
        except LayoutIOError as error:
            self.report_summary.setText(str(error))
            self.import_button.setEnabled(False)
            return
        self._refresh_columns(self._table)
        self._populate_preview(self._table)

    def _refresh_columns(self, table: LayoutTable) -> None:
        """Sync mapping combos with table columns, re-suggesting as needed."""
        suggested = suggest_mapping(table.columns)
        columns = list(table.columns)
        for key, combo in self.mapping_combos.items():
            previous = combo.currentText()
            combo.blockSignals(True)
            while combo.count() > 1:
                combo.removeItem(combo.count() - 1)
            combo.addItems(columns)
            if previous != _NONE and previous in columns:
                combo.setCurrentText(previous)
            else:
                value = getattr(suggested, key)
                combo.setCurrentText(value if value is not None else _NONE)
            combo.blockSignals(False)

    def _populate_preview(self, table: LayoutTable) -> None:
        preview_rows = table.rows[:_PREVIEW_ROW_LIMIT]
        self.preview_table.setColumnCount(len(table.columns))
        self.preview_table.setHorizontalHeaderLabels(list(table.columns))
        self.preview_table.setRowCount(len(preview_rows))
        for row_index, row in enumerate(preview_rows):
            for column_index, value in enumerate(row):
                self.preview_table.setItem(row_index, column_index, QTableWidgetItem(value))

    # -------------------------------------------------------------- mapping

    def current_mapping(self) -> LayoutMapping:
        """Mapping built from the combos ('(none)' means absent)."""
        values: dict[str, str | None] = {}
        for key, combo in self.mapping_combos.items():
            text = combo.currentText()
            values[key] = None if text == _NONE else text
        return LayoutMapping(**values)

    def finish(self) -> bool:
        """Parse with current options; build layers when the report is clean."""
        if self._table is None:
            return False
        delimiter_text = self.delimiter_combo.currentText()
        delimiter = (
            None
            if delimiter_text == "Auto"
            else ("\t" if delimiter_text == "Tab" else delimiter_text)
        )
        try:
            table = read_layout_table(self._path, delimiter=delimiter)
        except LayoutIOError as error:
            self.report_list.clear()
            self.report_summary.setText(str(error))
            self._imported_layers = []
            return False
        if table.columns != self._table.columns:
            self._table = table
            self._refresh_columns(table)
            self._populate_preview(table)
        try:
            records, issues = parse_layout_records(
                table,
                self.current_mapping(),
                decimal=self.decimal_combo.currentText(),
                existing_ids=self._existing_ids,
            )
        except LayoutIOError as error:
            self.report_list.clear()
            self.report_summary.setText(str(error))
            self._imported_layers = []
            return False
        errors = sum(1 for issue in issues if issue.severity is Severity.ERROR)
        self.report_list.clear()
        for issue in issues:
            item = QListWidgetItem(
                f"Row {issue.row} [{issue.severity.value.upper()}] {issue.code}: {issue.message}"
            )
            if issue.severity is Severity.ERROR:
                item.setForeground(Qt.GlobalColor.red)
            elif issue.severity is Severity.WARNING:
                item.setForeground(Qt.GlobalColor.darkYellow)
            self.report_list.addItem(item)
        self.report_summary.setText(
            f"{len(records)} record(s) ready — {errors} error(s), "
            f"{len(issues) - errors} other finding(s)"
        )
        if errors == 0:
            self._imported_layers = records_to_layers(records)
            return True
        self._imported_layers = []
        return False

    def imported_layers(self) -> list[Layer]:
        """Layers built by the last successful ``finish``."""
        return list(self._imported_layers)

    def _on_import_clicked(self) -> None:
        if self.finish():
            self.accept()
