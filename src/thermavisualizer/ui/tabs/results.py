"""Results tab: overall summary, per-logger table, excursions (RES-07).

Derived results are recomputed by the model and only displayed here (AGENTS
§4). Out-of-limit loggers are highlighted; the SLC-07 link pushes the criteria
limits to the 3D view's overlay. Units: °C / %RH, durations in seconds.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.models import Quantity
from thermavisualizer.core.results import StudyResults
from thermavisualizer.io.exporters import export_results_csv
from thermavisualizer.services.project_model import ProjectModel

_PASS = QColor("#2e7d32")
_FAIL = QColor("#c62828")


class ResultsTab(QWidget):
    """Displays the latest StudyResults and offers export + 3D link."""

    link_limits_to_3d = Signal(float, float)  # (low, high) for the SLC-07 overlay
    report_requested = Signal()
    compare_requested = Signal()

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        overall_group = QGroupBox("Overall result (RES-04)", self)
        overall_layout = QVBoxLayout(overall_group)
        self.overall_label = QLabel("No results yet — run an evaluation.", overall_group)
        self.overall_label.setWordWrap(True)
        overall_layout.addWidget(self.overall_label)
        root.addWidget(overall_group)

        actions = QHBoxLayout()
        self.evaluate_button = QPushButton("Evaluate now", self)
        self.evaluate_button.clicked.connect(self._on_evaluate)
        self.export_button = QPushButton("Export CSV…", self)
        self.export_button.clicked.connect(self._on_export)
        self.link_3d_button = QPushButton("Show limits in 3D (SLC-07)", self)
        self.link_3d_button.clicked.connect(self._on_link_3d)
        self.report_button = QPushButton("Generate PDF report…", self)
        self.report_button.setToolTip("Generate a PDF study report (RPT-01)")
        self.report_button.clicked.connect(self.report_requested)
        self.compare_button = QPushButton("Compare with project…", self)
        self.compare_button.setToolTip("Compare with a second project (CMP-01)")
        self.compare_button.clicked.connect(self.compare_requested)

        actions.addWidget(self.evaluate_button)
        actions.addWidget(self.export_button)
        actions.addWidget(self.link_3d_button)
        actions.addWidget(self.report_button)
        actions.addWidget(self.compare_button)

        actions.addStretch(1)
        root.addLayout(actions)

        root.addWidget(self._build_logger_table())
        root.addWidget(self._build_excursion_table())

        model.results_changed.connect(self.refresh)
        self.refresh()

    def _build_logger_table(self) -> QGroupBox:
        group = QGroupBox("Per-logger results (RES-03)", self)
        layout = QVBoxLayout(group)
        self.logger_table = QTableWidget(0, 11, group)
        self.logger_table.setHorizontalHeaderLabels(
            (
                "Logger",
                "Samples",
                "Min",
                "Max",
                "Mean",
                "Std",
                "MKT",
                "Out-of-limits",
                "Out %",
                "Excursions",
                "Result",
            )
        )
        self.logger_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.logger_table.verticalHeader().setVisible(False)
        self.logger_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.logger_table)
        return group

    def _build_excursion_table(self) -> QGroupBox:
        group = QGroupBox("Excursions (RES-05)", self)
        layout = QVBoxLayout(group)
        self.excursion_table = QTableWidget(0, 6, group)
        self.excursion_table.setHorizontalHeaderLabels(
            (
                "Logger",
                "Kind",
                "Start (UTC)",
                "End (UTC)",
                "Duration (s)",
                "Peak",
            )
        )
        self.excursion_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.excursion_table.verticalHeader().setVisible(False)
        self.excursion_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.excursion_table)
        return group

    # -------------------------------------------------------------- actions

    def _on_evaluate(self) -> None:
        quantity = Quantity.TEMPERATURE
        if self._model.aligned_dataset(Quantity.TEMPERATURE) is None:
            quantity = Quantity.HUMIDITY
        self._model.run_results_evaluation(quantity)

    def _on_export(self) -> None:
        results = self._model.study_results()
        if results is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "results.csv", "CSV (*.csv)")
        if path:
            export_results_csv(results, Path(path), study=self._model.study())

    def _on_link_3d(self) -> None:
        results = self._model.study_results()
        if results is None:
            return
        criteria = results.criteria
        if results.quantity is Quantity.TEMPERATURE:
            low, high = criteria.temperature_min, criteria.temperature_max
        else:
            low, high = criteria.humidity_min, criteria.humidity_max
        if low is not None and high is not None:
            self.link_limits_to_3d.emit(float(low), float(high))

    # -------------------------------------------------------------- refresh

    def refresh(self) -> None:
        """Redraw all result views from the model's latest StudyResults."""
        results = self._model.study_results()
        if results is None:
            self.overall_label.setText("No results yet — run an evaluation.")
            self.logger_table.setRowCount(0)
            self.excursion_table.setRowCount(0)
            return
        self._refresh_overall(results)
        self._refresh_logger_table(results)
        self._refresh_excursion_table(results)

    def _refresh_overall(self, results: StudyResults) -> None:
        o = results.overall
        unit = "°C" if results.quantity is Quantity.TEMPERATURE else "%RH"
        verdict = "PASS" if o.passed else "FAIL"
        self.overall_label.setText(
            f"{verdict} — {o.reason}\n"
            f"Criteria: {results.criteria.name}   Period: {results.period_start} → "
            f"{results.period_end}\n"
            f"Hottest: '{o.hottest_logger}' {o.hottest_value:.2f} {unit} at "
            f"{o.hottest_time}\n"
            f"Coldest: '{o.coldest_logger}' {o.coldest_value:.2f} {unit} at "
            f"{o.coldest_time}\n"
            f"Largest spread: {o.largest_spread:.2f} {unit} at {o.largest_spread_time}"
        )

    def _refresh_logger_table(self, results: StudyResults) -> None:
        table = self.logger_table
        table.setRowCount(len(results.logger_results))
        for row, lr in enumerate(results.logger_results):
            values = [
                lr.logger_id,
                str(lr.samples),
                f"{lr.minimum:.2f}",
                f"{lr.maximum:.2f}",
                f"{lr.mean:.2f}",
                f"{lr.std:.2f}",
                f"{lr.mkt:.2f}" if lr.mkt is not None else "—",
                str(lr.out_of_limits_samples),
                f"{lr.out_of_limits_pct:.1f}%",
                str(lr.excursion_count),
                "PASS" if lr.passed else "FAIL",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 10:  # Result column — highlight pass/fail (RES-07)
                    item.setForeground(_PASS if lr.passed else _FAIL)
                if not lr.passed:
                    item.setBackground(QColor(255, 235, 235))
                table.setItem(row, col, item)

    def _refresh_excursion_table(self, results: StudyResults) -> None:
        table = self.excursion_table
        table.setRowCount(len(results.excursions))
        for row, ex in enumerate(results.excursions):
            values = [
                ex.logger_id,
                ex.kind.value,
                str(ex.start),
                str(ex.end),
                f"{ex.duration_seconds:.1f}",
                f"{ex.peak:.2f}",
            ]
            for col, text in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(text))
