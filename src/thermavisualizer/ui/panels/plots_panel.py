"""Left-panel controls for the Plots tab (PRD 4.3): series selection, metric,
statistics options, and layout settings (PLT-01/02/03/04)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.models import Quantity
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.ui.tabs.plots import PlotLayout, PlotOptions


class PlotsPanel(QWidget):
    """Series selection and plot options; emits state for the Plots tab."""

    options_changed = Signal(object)
    series_changed = Signal(tuple)

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)

        options_group = QGroupBox("Plot options (PLT-02/03/04)", self)
        options_layout = QVBoxLayout(options_group)
        self.layout_combo = QComboBox(options_group)
        self.layout_combo.addItem("Temperature", PlotLayout.TEMPERATURE)
        self.layout_combo.addItem("Humidity", PlotLayout.HUMIDITY)
        self.layout_combo.addItem("Dual axis (T left, RH right)", PlotLayout.DUAL_AXIS)
        self.layout_combo.addItem("Separate subplots", PlotLayout.SEPARATE)
        self.layout_combo.currentIndexChanged.connect(self._emit_options)
        self.limits_check = QCheckBox("Show limit lines", options_group)
        self.limits_check.setChecked(True)
        self.limits_check.toggled.connect(self._emit_options)
        self.statistics_check = QCheckBox("Show statistics table", options_group)
        self.statistics_check.setChecked(True)
        self.statistics_check.toggled.connect(self._emit_options)
        options_layout.addWidget(self.layout_combo)
        options_layout.addWidget(self.limits_check)
        options_layout.addWidget(self.statistics_check)
        root.addWidget(options_group)

        series_group = QGroupBox("Series (PLT-01)", self)
        series_layout = QVBoxLayout(series_group)
        self.series_list = QListWidget(series_group)
        self.series_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.series_list.itemSelectionChanged.connect(self._emit_series)
        buttons = QHBoxLayout()
        self.select_all_button = QPushButton("All", series_group)
        self.clear_button = QPushButton("None", series_group)
        self.select_all_button.clicked.connect(self.series_list.selectAll)
        self.clear_button.clicked.connect(self.series_list.clearSelection)
        buttons.addWidget(self.select_all_button)
        buttons.addWidget(self.clear_button)
        series_layout.addWidget(self.series_list)
        series_layout.addLayout(buttons)
        root.addWidget(series_group)
        root.addStretch(1)

        model.aligned_changed.connect(self._rebuild_series_list)
        model.mapping_changed.connect(self._rebuild_series_list)
        self._rebuild_series_list()

    # -------------------------------------------------------------- helpers

    def options(self) -> PlotOptions:
        """Options built from the form (StrEnums re-wrapped after QVariant)."""
        return PlotOptions(
            layout=PlotLayout(str(self.layout_combo.currentData())),
            show_limits=self.limits_check.isChecked(),
            show_statistics=self.statistics_check.isChecked(),
        )

    def selected_series(self) -> tuple[str, ...]:
        """Logger IDs currently selected in the series list."""
        return tuple(item.text() for item in self.series_list.selectedItems())

    def _emit_options(self, *_args) -> None:
        if not self._updating:
            self.options_changed.emit(self.options())

    def _emit_series(self) -> None:
        if not self._updating:
            self.series_changed.emit(self.selected_series())

    def _rebuild_series_list(self) -> None:
        """Populate the series list from the aligned datasets, keeping selection."""
        previous = set(self.selected_series())
        self._updating = True
        try:
            self.series_list.clear()
            ids: list[str] = []
            for quantity in (Quantity.TEMPERATURE, Quantity.HUMIDITY):
                dataset = self._model.aligned_dataset(quantity)
                if dataset is not None:
                    for logger_id in dataset.logger_ids:
                        if logger_id not in ids:
                            ids.append(logger_id)
            for logger_id in ids:
                item = QListWidgetItem(logger_id)
                item.setSelected(logger_id in previous)
                self.series_list.addItem(item)
        finally:
            self._updating = False
