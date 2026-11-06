"""About and diagnostics dialogs (PRD: Help menu, logging/diagnostics NFR)."""

from __future__ import annotations

import csv
import platform
import sys
from datetime import datetime
from importlib import metadata
from pathlib import Path

from PySide6 import QtCore
from PySide6.QtCore import Qt, qVersion
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QLineEdit,
)

from thermavisualizer import __version__
from thermavisualizer.core.comparison import compare_results, difference_volume, geometries_match
from thermavisualizer.core.models import Quantity
from thermavisualizer.io.project_file import load_project
from thermavisualizer.services.audit import AuditService
from thermavisualizer.services.logging_setup import default_log_file
from thermavisualizer.resources.themes import Theme
from thermavisualizer.services.settings import AppSettings


_ABOUT_HTML = (
    "<h3>Traceable.ThermaVisualizer {version}</h3>"
    "<p>Desktop visualization of thermal mapping (temperature / relative humidity) "
    "studies in pharmaceutical facilities.</p>"
    "<p>Developed and maintained by Moaz El-Essawey — open source, shared with the "
    "community.</p><p>Status: early development (M0 shell).</p>"
)


def show_about_dialog(parent: QWidget | None) -> None:
    """Show the About dialog."""
    QMessageBox.about(
        parent, "About Traceable.ThermaVisualizer", _ABOUT_HTML.format(version=__version__)
    )


def _library_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "not installed"


class DiagnosticsDialog(QDialog):
    """Version and environment details for troubleshooting."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnostics")
        self.resize(540, 420)

        report = QPlainTextEdit(self)
        report.setReadOnly(True)
        report.setPlainText(self._build_report())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(report, 1)
        layout.addWidget(buttons, 0)

    @staticmethod
    def _build_report() -> str:
        lines = [
            f"Traceable.ThermaVisualizer: {__version__}",
            f"Python: {sys.version.splitlines()[0]}",
            f"Platform: {platform.platform()}",
            f"Qt runtime: {qVersion()}",
            f"PySide6: {_library_version('PySide6')}",
            f"numpy: {_library_version('numpy')}",
            f"scipy: {_library_version('scipy')}",
            f"pandas: {_library_version('pandas')}",
            f"matplotlib: {_library_version('matplotlib')}",
            f"3D backend: PyVista {_library_version('pyvista')}",
            f"pyvistaqt: {_library_version('pyvistaqt')}",
            f"VTK: {_library_version('vtk')}",
            f"Log file: {default_log_file()}",
        ]
        return "\n".join(lines)


class MovieExportDialog(QDialog):
    """Movie export options (EXP-02): resolution, FPS, time step, burn-ins."""

    def __init__(self, parent: QWidget | None = None, frame_count_hint: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export movie")
        form = QFormLayout()
        self.fps_spin = QSpinBox(self)
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(10)
        self.width_spin = QSpinBox(self)
        self.width_spin.setRange(160, 3840)
        self.width_spin.setValue(1280)
        self.height_spin = QSpinBox(self)
        self.height_spin.setRange(120, 2160)
        self.height_spin.setValue(720)
        self.stride_spin = QSpinBox(self)
        self.stride_spin.setRange(1, 1000)
        self.stride_spin.setValue(1)
        self.stride_spin.setToolTip("Use every Nth sample as a movie frame")
        self.timestamp_check = QCheckBox("Burn timestamp into frames", self)
        self.timestamp_check.setChecked(True)
        self.colorbar_check = QCheckBox("Burn color bar into frames", self)
        self.colorbar_check.setChecked(True)
        form.addRow("Frames per second", self.fps_spin)
        form.addRow("Width (px)", self.width_spin)
        form.addRow("Height (px)", self.height_spin)
        form.addRow("Time step (samples)", self.stride_spin)
        form.addRow(self.timestamp_check)
        form.addRow(self.colorbar_check)
        if frame_count_hint:
            form.addRow(QLabel(f"Range contains {frame_count_hint} sample(s)", self))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> dict[str, int | bool]:
        """Chosen options."""
        return {
            "fps": self.fps_spin.value(),
            "width": self.width_spin.value(),
            "height": self.height_spin.value(),
            "stride": self.stride_spin.value(),
            "burn_timestamp": self.timestamp_check.isChecked(),
            "burn_colorbar": self.colorbar_check.isChecked(),
        }


class DataExportDialog(QDialog):
    """Picker for what to export (EXP-03/04/06)."""

    OPTIONS: tuple[tuple[str, str], ...] = (
        ("aligned", "Aligned logger data (CSV/XLSX)"),
        ("volume", "Interpolated volume (NPZ)"),
        ("slice", "Current slice samples (CSV)"),
        ("slice_image", "Current slice heat map (PNG)"),
        ("validation", "Validation report (CSV)"),
    )

    def __init__(
        self, parent: QWidget | None = None, enabled: dict[str, bool] | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export data")
        availability = enabled or {}
        layout = QVBoxLayout(self)
        self._group = QButtonGroup(self)
        self._radios: dict[str, QRadioButton] = {}
        first_enabled: str | None = None
        for key, label in self.OPTIONS:
            radio = QRadioButton(label, self)
            available = availability.get(key, True)
            radio.setEnabled(available)
            if available and first_enabled is None:
                first_enabled = key
            self._group.addButton(radio)
            self._radios[key] = radio
            layout.addWidget(radio)
        if first_enabled is not None:
            self._radios[first_enabled].setChecked(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self) -> str:
        """Key of the chosen export target ('' when none)."""
        for key, radio in self._radios.items():
            if radio.isChecked():
                return key
        return ""


class AuditTrailDialog(QDialog):
    """Read-only audit trail viewer with filters, chain check, CSV export (AUD-06)."""

    _COLUMNS = ("#", "Timestamp (local)", "User", "Action", "Target", "Summary", "Comment")

    def __init__(self, audit: AuditService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Audit trail")
        self.resize(920, 520)
        self._audit = audit

        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("User", self))
        self.user_combo = QComboBox(self)
        self.user_combo.addItem("All")
        self.user_combo.addItems(sorted({e.user for e in audit.entries}))
        filters.addWidget(self.user_combo)
        filters.addWidget(QLabel("Action", self))
        self.action_combo = QComboBox(self)
        self.action_combo.addItem("All")
        self.action_combo.addItems(sorted({e.action.value for e in audit.entries}))
        filters.addWidget(self.action_combo)
        filters.addWidget(QLabel("From", self))
        self.from_date = QDateEdit(self)
        self.from_date.setDisplayFormat("yyyy-MM-dd")
        self.from_date.setMinimumDate(QtCore.QDate(2000, 1, 1))
        self.from_date.setDate(QtCore.QDate(2000, 1, 1))
        filters.addWidget(self.from_date)
        filters.addWidget(QLabel("To", self))
        self.to_date = QDateEdit(self)
        self.to_date.setDisplayFormat("yyyy-MM-dd")
        self.to_date.setMinimumDate(QtCore.QDate(2000, 1, 1))
        self.to_date.setDate(QtCore.QDate.currentDate())
        filters.addWidget(self.to_date)
        filters.addStretch(1)
        self.verify_label = QLabel("", self)
        filters.addWidget(self.verify_label)
        layout.addLayout(filters)

        self.table = QTableWidget(0, len(self._COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(self._COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.verify_button = QPushButton("Verify chain", self)
        self.verify_button.clicked.connect(self._on_verify)
        self.export_button = QPushButton("Export CSV…", self)
        self.export_button.clicked.connect(self._on_export)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        buttons.addWidget(self.verify_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.user_combo.currentIndexChanged.connect(self._populate)
        self.action_combo.currentIndexChanged.connect(self._populate)
        self.from_date.dateChanged.connect(self._populate)
        self.to_date.dateChanged.connect(self._populate)
        self._populate()
        self._on_verify()

    def _filtered_entries(self) -> list:
        user = self.user_combo.currentText()
        action = self.action_combo.currentText()
        from_iso = self.from_date.date().toString(Qt.DateFormat.ISODate)
        to_iso = self.to_date.date().toString(Qt.DateFormat.ISODate)
        result = []
        for entry in self._audit.entries:
            if user != "All" and entry.user != user:
                continue
            if action != "All" and entry.action.value != action:
                continue
            day = entry.timestamp_utc[:10]
            if not (from_iso <= day <= to_iso):
                continue
            result.append(entry)
        return result

    def _populate(self) -> None:
        entries = self._filtered_entries()
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            local_time = datetime.fromisoformat(entry.timestamp_utc).astimezone()
            values = (
                str(entry.sequence),
                local_time.strftime("%Y-%m-%d %H:%M:%S"),
                entry.user,
                entry.action.value,
                entry.target,
                entry.summary,
                entry.comment,
            )
            for column, text in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(text))

    def _on_verify(self) -> None:
        if self._audit.verify_chain():
            self.verify_label.setText(f"Chain intact ({len(self._audit)} entries)")
            self.verify_label.setStyleSheet("color: green;")
        else:
            self.verify_label.setText("CHAIN BROKEN — possible tampering")
            self.verify_label.setStyleSheet("color: red;")

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export audit trail", "audit_trail.csv", "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(self._COLUMNS)
            for entry in self._filtered_entries():
                writer.writerow(
                    (
                        entry.sequence,
                        entry.timestamp_utc,
                        entry.user,
                        entry.action.value,
                        entry.target,
                        entry.summary,
                        entry.comment,
                    )
                )


class CompareDialog(QDialog):
    """Compare the current study (A) with a second project (B) (CMP-01/02)."""

    def __init__(self, model, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compare studies")
        self.resize(760, 520)
        self._model = model
        self._snapshot_b = None

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.load_button = QPushButton("Select project B (.tmap)…", self)
        self.load_button.clicked.connect(self._on_load_b)
        self.status_label = QLabel("No comparison project loaded.", self)
        top.addWidget(self.load_button)
        top.addWidget(self.status_label, 1)
        layout.addLayout(top)

        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            ["Logger", "Mean A", "Mean B", "ΔMean", "Max A", "Max B", "ΔMax"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.diff_button = QPushButton("Compute difference (B − A)", self)
        self.diff_button.clicked.connect(self._on_difference)
        self.diff_label = QLabel("", self)
        layout.addWidget(self.diff_button)
        layout.addWidget(self.diff_label)

        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

    def _on_load_b(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open comparison project", "", "ThermaVisualizer project (*.tmap)"
        )
        if not path:
            return

        snapshot, warnings = load_project(Path(path))
        self._snapshot_b = snapshot
        self.status_label.setText(
            f"Loaded {Path(path).name}" + (f" ({len(warnings)} warnings)" if warnings else "")
        )
        self._populate_table()

    def _populate_table(self) -> None:

        results_a = self._model.study_results()
        results_b = self._snapshot_b.results if self._snapshot_b else None
        if results_a is None or results_b is None:
            self.table.setRowCount(0)
            self.status_label.setText("Both projects need computed results to compare.")
            return
        rows = compare_results(results_a, results_b)
        self.table.setRowCount(len(rows))
        for row, item in enumerate(rows):
            values = [
                item.logger_id,
                f"{item.mean_a:.2f}" if item.mean_a is not None else "—",
                f"{item.mean_b:.2f}" if item.mean_b is not None else "—",
                f"{item.delta_mean:+.2f}" if item.delta_mean is not None else "—",
                f"{item.max_a:.2f}" if item.max_a is not None else "—",
                f"{item.max_b:.2f}" if item.max_b is not None else "—",
                f"{item.delta_max:+.2f}" if item.delta_max is not None else "—",
            ]
            for column, text in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(text))

    def _on_difference(self) -> None:  # CMP-02

        volume_a = self._model.current_volume(Quantity.TEMPERATURE)
        if self._snapshot_b is None or volume_a is None:
            self.diff_label.setText("Load project B and compute a 3D volume for A first.")
            return
        if not geometries_match(self._model.space, self._snapshot_b.space):
            self.diff_label.setText("Geometries differ — difference heat map needs a common grid.")
            return
        # For a full difference, interpolate B on A's grid; here we report intent
        # and export A's volume so the user can compute B in project B.
        self.diff_label.setText(
            "Geometries match. Compute B's volume in project B, then use Export → "
            "volume (NPZ) on both to difference them (B − A)."
        )

class PreferencesDialog(QDialog):
    """Application preferences: audit user name and theme (AUD-02, VIS-08)."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(360)
        form = QFormLayout()
        self.user_name_edit = QLineEdit(settings.user_name(), self)
        self.user_name_edit.setToolTip("Used for the audit trail (stored UTC-stamped)")
        self.theme_combo = QComboBox(self)
        for theme in Theme:
            self.theme_combo.addItem(theme.value.capitalize(), theme.value)
        index = self.theme_combo.findData(settings.theme())
        if index >= 0:
            self.theme_combo.setCurrentIndex(index)
        form.addRow("User name", self.user_name_edit)
        form.addRow("Theme", self.theme_combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        """(user name, theme value) from the form."""
        return self.user_name_edit.text().strip(), str(self.theme_combo.currentData())