"""Left-panel controls for the Data tab: import, gate status, align, export."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.alignment import AlignmentError
from thermavisualizer.core.mapping import suggest_logger_mappings
from thermavisualizer.core.models import Quantity
from thermavisualizer.io.exporters import export_validation_report_csv
from thermavisualizer.services.project_model import ProjectModel


class DataPanel(QWidget):
    """Actions and gate status for the Data tab (DAT-03 gate, EXP-06)."""

    import_requested = Signal()
    status_message = Signal(str)
    edit_rejected = Signal(str)

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        actions = QGroupBox("Data (DAT)", self)
        actions_layout = QVBoxLayout(actions)
        self._import_button = QPushButton("Import data…", actions)
        self._auto_button = QPushButton("Auto-suggest mapping", actions)
        self._validate_button = QPushButton("Run validation", actions)
        self._align_button = QPushButton("Align data", actions)
        self._export_button = QPushButton("Export validation report…", actions)
        self._import_button.clicked.connect(self.import_requested)
        self._auto_button.clicked.connect(self._on_auto_suggest)
        self._validate_button.clicked.connect(self._on_validate)
        self._align_button.clicked.connect(self._on_align)
        self._export_button.clicked.connect(self._on_export_report)
        for button in (
            self._import_button,
            self._auto_button,
            self._validate_button,
            self._align_button,
            self._export_button,
        ):
            actions_layout.addWidget(button)
        layout.addWidget(actions)

        self._gate_label = QLabel("", self)
        self._gate_label.setWordWrap(True)
        layout.addWidget(self._gate_label)
        layout.addStretch(1)

        model.files_changed.connect(self._update_gate)
        model.mapping_changed.connect(self._update_gate)
        model.config_changed.connect(self._update_gate)
        self._update_gate()

    def _update_gate(self) -> None:
        total = len(self._model.all_logger_ids())
        unmapped = len(self._model.unmapped_logger_ids())
        files = len(self._model.files())
        complete = self._model.mapping_complete()
        self._gate_label.setText(
            f"Files: {files}\nLoggers: {total}, unmapped: {unmapped}\n"
            f"Mapping complete: {'yes' if complete else 'no'}"
        )
        self._align_button.setEnabled(complete and files > 0)
        self._auto_button.setEnabled(files > 0 and total > 0)

    def _on_auto_suggest(self) -> None:
        mappings = suggest_logger_mappings(self._model.all_logger_ids(), self._model.files())
        self._model.set_mappings(mappings, summary="Auto-suggested mapping")
        self.status_message.emit("Mapping auto-suggested from column names (DAT-04)")

    def _on_validate(self) -> None:
        report = self._model.run_validation()
        self.status_message.emit(
            f"Validation: {len(report.errors())} error(s), {len(report.warnings())} warning(s)"
        )

    def _on_align(self) -> None:
        if not self._model.mapping_complete():
            self.edit_rejected.emit("Map or exclude every logger before aligning (DAT-03)")
            return
        try:
            dataset = self._model.align(Quantity.TEMPERATURE)
        except AlignmentError as error:
            self.edit_rejected.emit(str(error))
            return
        self.status_message.emit(f"Aligned {len(dataset.logger_ids)} logger(s) (DAT-06/07)")

    def _on_export_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export validation report",
            "validation_report.csv",
            "CSV (*.csv);;Text (*.txt)",
        )
        if not path:
            return
        count = export_validation_report_csv(
            self._model.validation_report, __import__("pathlib").Path(path)
        )
        self.status_message.emit(f"Validation report exported ({count} findings)")
