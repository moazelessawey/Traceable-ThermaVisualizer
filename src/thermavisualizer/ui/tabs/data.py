"""Data tab: loaded files, mapping editor, and validation report (PRD 4.2)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.models import Severity
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.ui.widgets.mapping_editor import MappingEditorWidget


class DataTab(QWidget):
    """Table view of loaded files, mapping, and validation results."""

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        layout = QVBoxLayout(self)

        files_group = QGroupBox("Loaded files", self)
        files_layout = QVBoxLayout(files_group)
        self._files_table = QTableWidget(files_group)
        self._files_table.setColumnCount(4)
        self._files_table.setHorizontalHeaderLabels(["File", "Profile", "Rows", "Columns"])
        self._files_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._files_table.setMaximumHeight(140)
        files_layout.addWidget(self._files_table)
        layout.addWidget(files_group)

        mapping_group = QGroupBox("Logger-to-column mapping (DAT-03)", self)
        mapping_layout = QVBoxLayout(mapping_group)
        self._duplicate_label = QLabel("", mapping_group)
        self._duplicate_label.setWordWrap(True)
        self._mapping_editor = MappingEditorWidget(model, parent=mapping_group)
        self._mapping_editor.duplicate_warning.connect(self._duplicate_label.setText)
        mapping_layout.addWidget(self._mapping_editor)
        mapping_layout.addWidget(self._duplicate_label)
        layout.addWidget(mapping_group, 1)

        report_group = QGroupBox("Validation report (VAL)", self)
        report_layout = QVBoxLayout(report_group)
        self._report_table = QTableWidget(report_group)
        self._report_table.setColumnCount(5)
        self._report_table.setHorizontalHeaderLabels(
            ["Severity", "Code", "File", "Column", "Message"]
        )
        self._report_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        report_layout.addWidget(self._report_table)
        layout.addWidget(report_group, 1)

        model.files_changed.connect(self._refresh_files)
        model.validation_changed.connect(self._refresh_report)
        self._refresh_files()
        self._refresh_report()

    @property
    def mapping_editor(self) -> MappingEditorWidget:
        """The embedded mapping editor."""
        return self._mapping_editor

    def _refresh_files(self) -> None:
        files = self._model.files()
        self._files_table.setRowCount(len(files))
        for row, parsed in enumerate(files):
            self._files_table.setItem(row, 0, QTableWidgetItem(parsed.name))
            self._files_table.setItem(row, 1, QTableWidgetItem(parsed.profile_name))
            self._files_table.setItem(row, 2, QTableWidgetItem(str(parsed.row_count)))
            self._files_table.setItem(row, 3, QTableWidgetItem(str(len(parsed.columns))))

    def _refresh_report(self) -> None:
        report = self._model.validation_report
        self._report_table.setRowCount(len(report.findings))
        for row, finding in enumerate(report.findings):
            self._report_table.setItem(row, 0, QTableWidgetItem(finding.severity.value))
            self._report_table.setItem(row, 1, QTableWidgetItem(finding.code))
            self._report_table.setItem(row, 2, QTableWidgetItem(finding.file))
            self._report_table.setItem(row, 3, QTableWidgetItem(finding.column))
            self._report_table.setItem(row, 4, QTableWidgetItem(finding.message))
            if finding.severity is Severity.ERROR:
                for col in range(5):
                    self._report_table.item(row, col).setForeground(Qt.GlobalColor.red)
