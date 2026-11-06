"""Import wizard: files + profile, preview + column types, mapping (DAT-01..05)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.models import ImportProfile, TemperatureUnit
from thermavisualizer.core.validation import validate_path
from thermavisualizer.io.readers import read_data_file
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.ui.widgets.mapping_editor import MappingEditorWidget

_PREVIEW_ROWS = 20


class ImportDataDialog(QDialog):
    """Three-page wizard: files+profile → preview+types → mapping."""

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("Import Data")
        self.resize(860, 620)
        self._selected_paths: list[Path] = []
        self._previews: dict[str, object] = {}

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._build_files_page())
        self._stack.addWidget(self._build_preview_page())
        self._stack.addWidget(self._build_mapping_page())

        nav = QHBoxLayout()
        self._back_button = QPushButton("Back", self)
        self._next_button = QPushButton("Next", self)
        self._import_button = QPushButton("Import", self)
        self._cancel_button = QPushButton("Cancel", self)
        self._back_button.clicked.connect(self._go_back)
        self._next_button.clicked.connect(self._go_next)
        self._import_button.clicked.connect(self._perform_import)
        self._cancel_button.clicked.connect(self.reject)
        nav.addStretch(1)
        for button in (
            self._back_button,
            self._next_button,
            self._import_button,
            self._cancel_button,
        ):
            nav.addWidget(button)

        root = QVBoxLayout(self)
        root.addWidget(self._stack, 1)
        root.addLayout(nav)
        self._sync_nav()

    # ---------------------------------------------------------- page 0: files

    def _build_files_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        files_row = QHBoxLayout()
        self._file_list = QListWidget(page)
        add_button = QPushButton("Add files…", page)
        remove_button = QPushButton("Remove", page)
        add_button.clicked.connect(self._on_add_files)
        remove_button.clicked.connect(self._on_remove_file)
        files_row.addWidget(self._file_list, 1)
        side = QVBoxLayout()
        side.addWidget(add_button)
        side.addWidget(remove_button)
        side.addStretch(1)
        files_row.addLayout(side)
        layout.addWidget(QLabel("Data files (CSV / TXT / XLSX):", page))
        layout.addLayout(files_row, 1)
        layout.addWidget(self._build_profile_form(page))
        return page

    def _build_profile_form(self, parent: QWidget) -> QWidget:
        group = QWidget(parent)
        form = QFormLayout(group)
        self._profile_combo = QComboBox(group)
        self._profile_name_edit = QLineEdit("Default", group)
        self._delimiter_edit = QLineEdit(",", group)
        self._decimal_combo = QComboBox(group)
        self._decimal_combo.addItems([".", ","])
        self._header_row_spin = QSpinBox(group)
        self._header_row_spin.setRange(0, 100)
        self._timestamp_column_edit = QLineEdit("Timestamp", group)
        self._timestamp_format_edit = QLineEdit("iso", group)
        self._timezone_edit = QLineEdit("UTC", group)
        self._unit_combo = QComboBox(group)
        for unit in TemperatureUnit:
            self._unit_combo.addItem(unit.value, unit)
        self._save_profile_check = QCheckBox("Save this profile", group)

        form.addRow("Saved profiles", self._profile_combo)
        form.addRow("Profile name", self._profile_name_edit)
        form.addRow("Delimiter", self._delimiter_edit)
        form.addRow("Decimal separator", self._decimal_combo)
        form.addRow("Header row (0-based)", self._header_row_spin)
        form.addRow("Timestamp column", self._timestamp_column_edit)
        form.addRow("Timestamp format", self._timestamp_format_edit)
        form.addRow("Time zone", self._timezone_edit)
        form.addRow("Temperature unit", self._unit_combo)
        form.addRow(self._save_profile_check)

        self._profile_combo.currentTextChanged.connect(self._on_profile_selected)
        self._refresh_profile_combo()
        return group

    def _refresh_profile_combo(self) -> None:
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        self._profile_combo.addItems(sorted(self._model.import_profiles()))
        self._profile_combo.blockSignals(False)

    def _on_profile_selected(self, name: str) -> None:
        profile = self._model.import_profiles().get(name)
        if profile is None:
            return
        self._load_profile_into_form(profile)

    def _load_profile_into_form(self, profile: ImportProfile) -> None:
        self._profile_name_edit.setText(profile.name)
        self._delimiter_edit.setText(profile.delimiter)
        self._decimal_combo.setCurrentText(profile.decimal)
        self._header_row_spin.setValue(profile.header_row)
        self._timestamp_column_edit.setText(profile.timestamp_column)
        self._timestamp_format_edit.setText(profile.timestamp_format)
        self._timezone_edit.setText(profile.timezone)
        self._unit_combo.setCurrentText(profile.temperature_unit.value)

    def _build_profile(self) -> ImportProfile:
        """Assemble the current form values into an ImportProfile (DAT-01)."""
        delimiter = self._delimiter_edit.text()
        if delimiter == "\\t":
            delimiter = "\t"
        return ImportProfile(
            name=self._profile_name_edit.text().strip() or "Default",
            delimiter=delimiter or ",",
            decimal=self._decimal_combo.currentText(),
            header_row=self._header_row_spin.value(),
            timestamp_column=self._timestamp_column_edit.text().strip() or "Timestamp",
            timestamp_format=self._timestamp_format_edit.text().strip() or "iso",
            timezone=self._timezone_edit.text().strip() or "UTC",
            temperature_unit=self._unit_combo.currentData(),
        )

    def _on_add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select data files",
            "",
            "Data files (*.csv *.txt *.xlsx *.xls);;All files (*)",
        )
        self.add_paths([Path(p) for p in paths])

    def add_paths(self, paths: list[Path]) -> None:
        """Add files to the selection (used by the UI and by tests)."""
        for path in paths:
            if path not in self._selected_paths:
                self._selected_paths.append(path)
                self._file_list.addItem(str(path))

    def _on_remove_file(self) -> None:
        row = self._file_list.currentRow()
        if row >= 0:
            del self._selected_paths[row]
            self._file_list.takeItem(row)

    # -------------------------------------------------------- page 1: preview

    def _build_preview_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        top = QHBoxLayout()
        top.addWidget(QLabel("Preview file:", page))
        self._preview_combo = QComboBox(page)
        self._preview_combo.currentIndexChanged.connect(self._show_preview)
        top.addWidget(self._preview_combo, 1)
        layout.addLayout(top)
        self._preview_table = QTableWidget(page)
        self._preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._preview_table, 1)
        self._types_label = QLabel(page)
        self._types_label.setWordWrap(True)
        layout.addWidget(self._types_label)
        return page

    def _parse_all_previews(self) -> bool:
        profile = self._build_profile()
        self._previews = {}
        self._preview_combo.blockSignals(True)
        self._preview_combo.clear()
        for path in self._selected_paths:
            parsed, _report = validate_path(path, profile)
            if parsed is None:
                parsed = read_data_file(path, profile, max_rows=_PREVIEW_ROWS)
            self._previews[str(path)] = parsed
            self._preview_combo.addItem(path.name)
        self._preview_combo.blockSignals(False)
        if self._preview_combo.count():
            self._preview_combo.setCurrentIndex(0)
            self._show_preview(0)
        return bool(self._previews)

    def _show_preview(self, index: int) -> None:
        if index < 0 or index >= len(self._selected_paths):
            return
        parsed = self._previews.get(str(self._selected_paths[index]))
        if parsed is None:
            return
        self._preview_table.setColumnCount(len(parsed.columns))
        self._preview_table.setHorizontalHeaderLabels([c.name for c in parsed.columns])
        self._preview_table.setRowCount(min(parsed.row_count, _PREVIEW_ROWS))
        for row in range(min(parsed.row_count, _PREVIEW_ROWS)):
            for col, column in enumerate(parsed.columns):
                value = column.values[row]
                self._preview_table.setItem(row, col, QTableWidgetItem(str(value)))
        types = ", ".join(f"{c.name}: {c.column_type.value}" for c in parsed.columns)
        self._types_label.setText(f"Column types — {types}")

    # -------------------------------------------------------- page 2: mapping

    def _build_mapping_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("Map each logger to a data column (or exclude it):", page))
        self._mapping_editor = MappingEditorWidget(self._model, files=[], parent=page)
        layout.addWidget(self._mapping_editor, 1)
        return page

    # ----------------------------------------------------------- navigation

    def _sync_nav(self) -> None:
        index = self._stack.currentIndex()
        self._back_button.setEnabled(index > 0)
        self._next_button.setEnabled(index < 2)
        self._import_button.setEnabled(index == 2)

    def _go_back(self) -> None:
        self._stack.setCurrentIndex(max(self._stack.currentIndex() - 1, 0))
        self._sync_nav()

    def _go_next(self) -> None:
        index = self._stack.currentIndex()
        if index == 0:
            if not self._selected_paths:
                return
            if not self._parse_all_previews():
                return
            self._stack.setCurrentIndex(1)
        elif index == 1:
            self._mapping_editor.set_files(list(self._previews.values()))
            self._stack.setCurrentIndex(2)
        self._sync_nav()

    # --------------------------------------------------------------- import

    def _perform_import(self) -> None:
        """Save profile (if asked), load files, and apply the mapping (DAT-01/03)."""
        profile = self._build_profile()
        if self._save_profile_check.isChecked():
            self._model.save_profile(profile)
            self._refresh_profile_combo()
        jobs = [(path, profile) for path in self._selected_paths]
        self._model.load_files_async(jobs)
        mappings = self._mapping_editor.current_mappings()
        if mappings:
            self._model.set_mappings(mappings, summary="Import mapping")
        self.accept()
