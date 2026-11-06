"""Left-panel controls for the Results tab (PRD 4.3): criteria editor, presets,
study-period selector, and the evaluate action (RES-01/02)."""

from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.models import Quantity, Study, StudyType
from thermavisualizer.core.results import AcceptanceCriteria
from thermavisualizer.services.project_model import ProjectModel


def _limit_spin(value: float, parent: QWidget) -> QDoubleSpinBox:
    spin = QDoubleSpinBox(parent)
    spin.setRange(-1000.0, 1000.0)
    spin.setDecimals(2)
    spin.setSingleStep(0.5)
    spin.setValue(value)
    return spin


class ResultsPanel(QWidget):
    """Criteria editing, preset management, and evaluation trigger."""

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._syncing_study = False

        content = QWidget(self)
        root = QVBoxLayout(content)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(6)
        root.addWidget(self._build_study_group(content))

        preset_group = QGroupBox("Criteria presets (RES-01)", self)
        preset_layout = QVBoxLayout(preset_group)
        self.preset_combo = QComboBox(preset_group)
        self._load_presets()
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        preset_layout.addWidget(self.preset_combo)
        root.addWidget(preset_group)

        editor_group = QGroupBox("Acceptance criteria (RES-01)", self)
        form = QFormLayout(editor_group)
        criteria = model.criteria()
        self.name_edit = QLineEdit(criteria.name, editor_group)
        self.temp_min_spin = _limit_spin(criteria.temperature_min, editor_group)
        self.temp_max_spin = _limit_spin(criteria.temperature_max, editor_group)
        self.rh_min_spin = _limit_spin(criteria.humidity_min or 0.0, editor_group)
        self.rh_max_spin = _limit_spin(criteria.humidity_max or 100.0, editor_group)
        form.addRow("Name", self.name_edit)
        form.addRow("Temperature min (°C)", self.temp_min_spin)
        form.addRow("Temperature max (°C)", self.temp_max_spin)
        form.addRow("Humidity min (%RH)", self.rh_min_spin)
        form.addRow("Humidity max (%RH)", self.rh_max_spin)
        root.addWidget(editor_group)

        period_group = QGroupBox("Evaluation scope (RES-02)", self)
        period_layout = QVBoxLayout(period_group)
        self.period_combo = QComboBox(period_group)
        self.period_combo.addItem("Timeline selection", "timeline")
        self.period_combo.addItem("Full dataset", "full")
        for period in model.study_periods():
            self.period_combo.addItem(f"Period: {period.name}", period.name)
        period_layout.addWidget(self.period_combo)
        root.addWidget(period_group)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("Apply criteria", self)
        self.apply_button.clicked.connect(self._on_apply)
        self.save_preset_button = QPushButton("Save preset", self)
        self.save_preset_button.clicked.connect(self._on_save_preset)
        self.evaluate_button = QPushButton("Evaluate", self)
        self.evaluate_button.clicked.connect(self._on_evaluate)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.save_preset_button)
        buttons.addWidget(self.evaluate_button)
        root.addLayout(buttons)
        root.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        model.criteria_changed.connect(self._load_presets)
        model.study_changed.connect(self._sync_study_form)
        self._sync_study_form()

        model.criteria_changed.connect(self._load_presets)

    # -------------------------------------------------------------- helpers

    def _criteria_from_form(self) -> AcceptanceCriteria:
        """Build criteria from the form (values are plain floats, no enums)."""
        return AcceptanceCriteria(
            name=self.name_edit.text().strip() or "Custom",
            temperature_min=self.temp_min_spin.value(),
            temperature_max=self.temp_max_spin.value(),
            humidity_min=self.rh_min_spin.value(),
            humidity_max=self.rh_max_spin.value(),
        )

    def _load_presets(self) -> None:
        current = self.preset_combo.currentData()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for preset in self._model.criteria_presets():
            self.preset_combo.addItem(preset.name, preset.name)
        if current:
            index = self.preset_combo.findData(current)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
        self.preset_combo.blockSignals(False)

    def _on_preset_selected(self, index: int) -> None:
        name = self.preset_combo.itemData(index)
        if not name:
            return
        for preset in self._model.criteria_presets():
            if preset.name == name:
                self._populate_form(preset)
                break

    def _populate_form(self, criteria: AcceptanceCriteria) -> None:
        self.name_edit.setText(criteria.name)
        self.temp_min_spin.setValue(criteria.temperature_min)
        self.temp_max_spin.setValue(criteria.temperature_max)
        self.rh_min_spin.setValue(criteria.humidity_min or 0.0)
        self.rh_max_spin.setValue(criteria.humidity_max or 100.0)

    # -------------------------------------------------------------- actions

    def _on_apply(self) -> None:
        self._model.set_criteria(self._criteria_from_form())

    def _on_save_preset(self) -> None:
        criteria = self._criteria_from_form()
        self._model.save_criteria_preset(criteria)
        self._load_presets()

    def _on_evaluate(self) -> None:
        self._on_apply()
        scope = self.period_combo.currentData()
        if scope == "full":
            self._model.set_timeline_range(None, None)
        elif scope == "timeline":
            pass  # use the current timeline selection as-is
        else:
            for period in self._model.study_periods():
                if period.name == scope:
                    self._model.set_timeline_range(period.start, period.end)
                    break
        quantity = (
            Quantity.TEMPERATURE
            if self._model.aligned_dataset(Quantity.TEMPERATURE) is not None
            else Quantity.HUMIDITY
        )
        self._model.run_results_evaluation(quantity)

    def _build_study_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Study metadata (STY-01)", parent)
        form = QFormLayout(group)
        self.study_title_edit = QLineEdit(group)
        self.study_protocol_edit = QLineEdit(group)
        self.study_equipment_edit = QLineEdit(group)
        self.study_location_edit = QLineEdit(group)
        self.study_type_combo = QComboBox(group)
        for study_type in StudyType:
            self.study_type_combo.addItem(study_type.value.replace("_", " "), study_type.value)
        self.study_performed_edit = QLineEdit(group)
        self.study_reviewer_edit = QLineEdit(group)
        self.study_start_date = QDateEdit(group)
        self.study_end_date = QDateEdit(group)
        for date_edit in (self.study_start_date, self.study_end_date):
            date_edit.setDisplayFormat("yyyy-MM-dd")
            date_edit.setCalendarPopup(True)
            date_edit.setMinimumDate(QDate(2000, 1, 1))
            date_edit.setDate(QDate(2000, 1, 1))
        self.study_notes_edit = QLineEdit(group)
        form.addRow("Title", self.study_title_edit)
        form.addRow("Protocol ID", self.study_protocol_edit)
        form.addRow("Equipment/space ID", self.study_equipment_edit)
        form.addRow("Location", self.study_location_edit)
        form.addRow("Study type", self.study_type_combo)
        form.addRow("Performed by", self.study_performed_edit)
        form.addRow("Reviewer", self.study_reviewer_edit)
        form.addRow("Start date", self.study_start_date)
        form.addRow("End date", self.study_end_date)
        form.addRow("Notes", self.study_notes_edit)
        for edit in (
            self.study_title_edit,
            self.study_protocol_edit,
            self.study_equipment_edit,
            self.study_location_edit,
            self.study_performed_edit,
            self.study_reviewer_edit,
            self.study_notes_edit,
        ):
            edit.editingFinished.connect(self._apply_study)
        self.study_type_combo.currentIndexChanged.connect(self._apply_study)
        self.study_start_date.dateChanged.connect(self._apply_study)
        self.study_end_date.dateChanged.connect(self._apply_study)
        return group

    def _date_text(self, date_edit: QDateEdit) -> str:
        if date_edit.date().year() <= 2000:
            return ""
        return date_edit.date().toString(Qt.DateFormat.ISODate)

    def _apply_study(self, *_args) -> None:
        if self._syncing_study:
            return
        self._model.set_study(
            Study(
                title=self.study_title_edit.text().strip(),
                protocol_id=self.study_protocol_edit.text().strip(),
                equipment_id=self.study_equipment_edit.text().strip(),
                location=self.study_location_edit.text().strip(),
                study_type=StudyType(str(self.study_type_combo.currentData())),
                performed_by=self.study_performed_edit.text().strip(),
                reviewer=self.study_reviewer_edit.text().strip(),
                start_date=self._date_text(self.study_start_date),
                end_date=self._date_text(self.study_end_date),
                notes=self.study_notes_edit.text().strip(),
            )
        )

    def _sync_study_form(self) -> None:
        study = self._model.study()
        self._syncing_study = True
        try:
            self.study_title_edit.setText(study.title)
            self.study_protocol_edit.setText(study.protocol_id)
            self.study_equipment_edit.setText(study.equipment_id)
            self.study_location_edit.setText(study.location)
            index = self.study_type_combo.findData(study.study_type.value)
            if index >= 0:
                self.study_type_combo.setCurrentIndex(index)
            self.study_performed_edit.setText(study.performed_by)
            self.study_reviewer_edit.setText(study.reviewer)
            for date_edit, text in (
                (self.study_start_date, study.start_date),
                (self.study_end_date, study.end_date),
            ):
                parsed = QDate.fromString(text, Qt.DateFormat.ISODate) if text else QDate()
                date_edit.setDate(parsed if parsed.isValid() else QDate(2000, 1, 1))
            self.study_notes_edit.setText(study.notes)
        finally:
            self._syncing_study = False
