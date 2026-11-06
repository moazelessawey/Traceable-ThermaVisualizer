"""Left-panel controls for the 3D View tab (PRD 4.3): interpolation, slices,
color scale, display options, limits highlight, and the probe (SLC-06/07)."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from thermavisualizer.core.alignment import AlignmentError, nearest_time_index, time_range_indices
from thermavisualizer.core.geometry import point_in_space
from thermavisualizer.core.interpolation import (
    ExtrapolationPolicy,
    InterpolationError,
    InterpolationMethod,
    InterpolationSettings,
    RBFKernel,
    build_voxel_grid,
)
from thermavisualizer.core.models import Quantity, TimelineMode
from thermavisualizer.core.slicing import SliceAxis, sample_volume
from thermavisualizer.core.statistics import AggregationMethod
from thermavisualizer.rendering.colormaps import ColorMapName, ColorScale
from thermavisualizer.rendering.scene import ObstacleStyle
from thermavisualizer.rendering.view3d import SliceSpec
from thermavisualizer.services.project_model import ProjectModel


def _spin(
    minimum: float,
    maximum: float,
    value: float,
    step: float = 0.1,
    decimals: int = 3,
    parent: QWidget | None = None,
) -> QDoubleSpinBox:
    spin = QDoubleSpinBox(parent)
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    spin.setValue(value)
    return spin


class ColorScaleWidget(QWidget):
    """Color map + range editor (VIS-04); emits every change."""

    scale_changed = Signal(object)

    def __init__(self, initial: ColorScale | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        self.colormap_combo = QComboBox(self)
        for name in ColorMapName:
            self.colormap_combo.addItem(name.value, name)
        self.colormap_combo.addItem("custom", "custom")
        self.custom_from_edit = _color_edit("#000080", self)
        self.custom_to_edit = _color_edit("#ff0000", self)
        self.auto_range_check = QCheckBox("Auto range", self)
        self.auto_range_check.setChecked(True)
        self.vmin_spin = _spin(-1000.0, 1000.0, 0.0, parent=self)
        self.vmax_spin = _spin(-1000.0, 1000.0, 1.0, parent=self)
        form.addRow("Color map", self.colormap_combo)
        form.addRow("Custom from", self.custom_from_edit)
        form.addRow("Custom to", self.custom_to_edit)
        form.addRow(self.auto_range_check)
        form.addRow("User min", self.vmin_spin)
        form.addRow("User max", self.vmax_spin)
        self.colormap_combo.currentIndexChanged.connect(self._emit)
        self.custom_from_edit.editingFinished.connect(self._emit)
        self.custom_to_edit.editingFinished.connect(self._emit)
        self.auto_range_check.toggled.connect(self._emit)
        self.vmin_spin.editingFinished.connect(self._emit)
        self.vmax_spin.editingFinished.connect(self._emit)
        if initial is not None:
            self.set_color_scale(initial)

    def scale(self) -> ColorScale:
        """Build the ColorScale from the form."""
        data = self.colormap_combo.currentData()
        custom = None
        colormap = ColorMapName.VIRIDIS
        if data == "custom":
            custom = (
                self.custom_from_edit.text().strip() or "#000000",
                self.custom_to_edit.text().strip() or "#ffffff",
            )
        else:
            colormap = ColorMapName(str(data))
        return ColorScale(
            colormap=colormap,
            auto_range=self.auto_range_check.isChecked(),
            vmin=self.vmin_spin.value(),
            vmax=self.vmax_spin.value(),
            custom_colors=custom,
        )

    def set_color_scale(self, scale: ColorScale) -> None:
        """Populate the form without emitting signals (external sync)."""
        widgets = (
            self.colormap_combo,
            self.custom_from_edit,
            self.custom_to_edit,
            self.auto_range_check,
            self.vmin_spin,
            self.vmax_spin,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            if scale.custom_colors:
                self.colormap_combo.setCurrentIndex(self.colormap_combo.findData("custom"))
                self.custom_from_edit.setText(scale.custom_colors[0])
                self.custom_to_edit.setText(scale.custom_colors[-1])
            else:
                self.colormap_combo.setCurrentIndex(
                    self.colormap_combo.findData(scale.colormap.value)
                )
            self.auto_range_check.setChecked(scale.auto_range)
            self.vmin_spin.setValue(scale.vmin)
            self.vmax_spin.setValue(scale.vmax)
        finally:
            for widget in widgets:
                widget.blockSignals(False)

    def _emit(self) -> None:
        self.scale_changed.emit(self.scale())


def _color_edit(default: str, parent: QWidget) -> QLineEdit:
    from PySide6.QtWidgets import QLineEdit

    edit = QLineEdit(default, parent)
    edit.setMaxLength(9)
    return edit


class View3DPanel(QWidget):
    """Interpolation, slices, color, display, limits, and probe controls."""

    slices_changed = Signal(object)
    color_scale_changed = Signal(object)
    limits_changed = Signal(object)
    axes_toggled = Signal(bool)
    obstacle_style_changed = Signal(object)
    status_message = Signal(str)
    edit_rejected = Signal(str)

    def __init__(self, model: ProjectModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model

        content = QWidget(self)
        root = QVBoxLayout(content)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(6)
        root.addWidget(self._build_data_group(parent=content))
        root.addWidget(self._build_interpolation_group(parent=content))
        root.addWidget(self._build_slices_group(parent=content))
        color_group = QGroupBox("Color scale (VIS-04)", content)
        color_layout = QVBoxLayout(color_group)
        self._color_widget = ColorScaleWidget(ColorScale(), color_group)
        color_layout.addWidget(self._color_widget)
        root.addWidget(color_group)
        root.addWidget(self._build_display_group(parent=content))
        root.addWidget(self._build_limits_group(parent=content))
        root.addWidget(self._build_probe_group(parent=content))
        root.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._color_widget.scale_changed.connect(self.color_scale_changed)
        model.interpolation_progress_changed.connect(self._on_progress)
        model.interpolation_failed.connect(self.edit_rejected)
        model.volume_ready.connect(lambda _result: self.progress_bar.hide())
        model.interpolation_settings_changed.connect(self._update_method_note)
        self._update_method_note()

    # -------------------------------------------------------------- groups

    def _build_data_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Data & aggregation (INT-04/05, VIS-06)", parent)
        layout = QVBoxLayout(group)
        form = QFormLayout()
        self.quantity_combo = QComboBox(group)
        self.quantity_combo.addItem("Temperature (°C)", Quantity.TEMPERATURE)
        self.quantity_combo.addItem("Humidity (%RH)", Quantity.HUMIDITY)
        self.aggregation_combo = QComboBox(group)
        for method in AggregationMethod:
            self.aggregation_combo.addItem(method.value, method)
        self.time_index_spin = QSpinBox(group)
        self.time_index_spin.setRange(0, 10_000_000)
        self.temporal_window_spin = QSpinBox(group)
        self.temporal_window_spin.setRange(1, 1000)
        self.temporal_window_spin.setValue(1)
        self.temporal_window_spin.setToolTip("Moving-average window in samples; 1 = off")
        form.addRow("Quantity", self.quantity_combo)
        form.addRow("Aggregation", self.aggregation_combo)
        form.addRow("Time index (instant)", self.time_index_spin)
        form.addRow("Temporal window", self.temporal_window_spin)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.compute_button = QPushButton("Compute && update view", group)
        self.cancel_button = QPushButton("Cancel", group)
        self.compute_button.clicked.connect(self._on_compute)
        self.cancel_button.clicked.connect(self._model.cancel_interpolation)
        buttons.addWidget(self.compute_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self.progress_bar = QProgressBar(group)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        self.method_note_label = QLabel("", group)
        self.method_note_label.setWordWrap(True)
        layout.addWidget(self.method_note_label)
        return group

    def _build_interpolation_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Interpolation (INT-01/02/03/06)", parent)
        form = QFormLayout(group)
        settings = self._model.interpolation_settings()
        self.method_combo = QComboBox(group)
        for method in InterpolationMethod:
            self.method_combo.addItem(method.value, method)
        self.method_combo.setCurrentIndex(list(InterpolationMethod).index(settings.method))
        self.idw_power_spin = _spin(0.1, 10.0, settings.idw_power, parent=group)
        self.rbf_kernel_combo = QComboBox(group)
        for kernel in RBFKernel:
            self.rbf_kernel_combo.addItem(kernel.value, kernel)
        self.rbf_kernel_combo.setCurrentIndex(list(RBFKernel).index(settings.rbf_kernel))
        self.rbf_smoothing_spin = _spin(0.0, 100.0, settings.rbf_smoothing, parent=group)
        self.extrapolation_combo = QComboBox(group)
        for policy in ExtrapolationPolicy:
            self.extrapolation_combo.addItem(policy.value, policy)
        self.extrapolation_combo.setCurrentIndex(
            list(ExtrapolationPolicy).index(settings.extrapolation)
        )
        self.sigma_spin = _spin(0.0, 10.0, settings.smoothing_sigma, parent=group)
        self.resolution_spin = _spin(0.02, 10.0, settings.resolution, parent=group)
        form.addRow("Method", self.method_combo)
        form.addRow("IDW power", self.idw_power_spin)
        form.addRow("RBF kernel", self.rbf_kernel_combo)
        form.addRow("RBF smoothing", self.rbf_smoothing_spin)
        form.addRow("Extrapolation", self.extrapolation_combo)
        form.addRow("Spatial sigma (m)", self.sigma_spin)
        form.addRow("Resolution (m)", self.resolution_spin)
        self.apply_settings_button = QPushButton("Apply interpolation settings", group)
        self.apply_settings_button.clicked.connect(self._on_apply_settings)
        form.addRow(self.apply_settings_button)
        return group

    def _build_slices_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Slices (SLC-01/02/04)", parent)
        layout = QVBoxLayout(group)
        self._slice_controls: dict[str, dict[str, QWidget]] = {}
        for axis in (SliceAxis.X, SliceAxis.Y, SliceAxis.Z):
            row = QHBoxLayout()
            enabled = QCheckBox(f"{axis.value.upper()} slice", group)
            position = _spin(-1000.0, 1000.0, 0.0, parent=group)
            opacity = _spin(0.05, 1.0, 1.0, parent=group)
            row.addWidget(enabled)
            row.addWidget(_form_label("pos (m)", group))
            row.addWidget(position)
            row.addWidget(_form_label("opacity", group))
            row.addWidget(opacity)
            layout.addLayout(row)
            self._slice_controls[axis.value] = {
                "enabled": enabled,
                "position": position,
                "opacity": opacity,
            }
            enabled.toggled.connect(self._emit_slices)
            position.editingFinished.connect(self._emit_slices)
            opacity.editingFinished.connect(self._emit_slices)
        plane_row_1 = QHBoxLayout()
        plane_row_2 = QHBoxLayout()
        plane_row_3 = QHBoxLayout()
        self.plane_enabled = QCheckBox("Plane", group)
        self.plane_px = _spin(-1000.0, 1000.0, 0.0, parent=group)
        self.plane_py = _spin(-1000.0, 1000.0, 0.0, parent=group)
        self.plane_pz = _spin(-1000.0, 1000.0, 0.0, parent=group)
        self.plane_nx = _spin(-10.0, 10.0, 0.0, parent=group)
        self.plane_ny = _spin(-10.0, 10.0, 0.0, parent=group)
        self.plane_nz = _spin(-10.0, 10.0, 1.0, parent=group)
        self.plane_opacity = _spin(0.05, 1.0, 1.0, parent=group)
        plane_row_1.addWidget(self.plane_enabled)
        plane_row_1.addWidget(_form_label("op", self.plane_opacity))
        plane_row_1.addWidget(self.plane_opacity)

        for label, widget in (("p", self.plane_px), ("", self.plane_py), ("", self.plane_pz)):
            if label:
                plane_row_2.addWidget(_form_label(label, group))
            plane_row_2.addWidget(widget)
        for label, widget in (("n", self.plane_nx), ("", self.plane_ny), ("", self.plane_nz)):
            if label:
                plane_row_3.addWidget(_form_label(label, group))
            plane_row_3.addWidget(widget)

        layout.addLayout(plane_row_1)
        layout.addLayout(plane_row_2)
        layout.addLayout(plane_row_3)
        for widget in (
            self.plane_enabled,
            self.plane_px,
            self.plane_py,
            self.plane_pz,
            self.plane_nx,
            self.plane_ny,
            self.plane_nz,
            self.plane_opacity,
        ):
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._emit_slices)
            else:
                widget.editingFinished.connect(self._emit_slices)
        return group

    def _build_display_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Display (VIS-02/03, OBS-03)", parent)
        layout = QVBoxLayout(group)
        self.axes_check = QCheckBox("Show axes && dimensions", group)
        self.axes_check.setChecked(True)
        self.axes_check.toggled.connect(self.axes_toggled)
        self.obstacle_style_combo = QComboBox(group)
        for style in ObstacleStyle:
            self.obstacle_style_combo.addItem(style.value, style)
        self.obstacle_style_combo.setCurrentIndex(
            list(ObstacleStyle).index(ObstacleStyle.TRANSPARENT)
        )
        self.obstacle_style_combo.currentIndexChanged.connect(self._on_obstacle_style)
        row = QHBoxLayout()
        row.addWidget(_form_label("Obstacles", group))
        row.addWidget(self.obstacle_style_combo)
        layout.addWidget(self.axes_check)
        layout.addLayout(row)
        return group

    def _build_limits_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Limits highlight (SLC-07)", parent)
        layout = QVBoxLayout(group)
        self.limits_check = QCheckBox("Highlight values outside limits", group)
        row = QHBoxLayout()
        self.limit_low_spin = _spin(-1000.0, 1000.0, 2.0, parent=group)
        self.limit_high_spin = _spin(-1000.0, 1000.0, 8.0, parent=group)
        row.addWidget(_form_label("low", group))
        row.addWidget(self.limit_low_spin)
        row.addWidget(_form_label("high", group))
        row.addWidget(self.limit_high_spin)
        layout.addWidget(self.limits_check)
        layout.addLayout(row)
        self.limits_check.toggled.connect(self._emit_limits)
        self.limit_low_spin.editingFinished.connect(self._emit_limits)
        self.limit_high_spin.editingFinished.connect(self._emit_limits)
        return group

    def _build_probe_group(self, parent: QWidget) -> QGroupBox:
        group = QGroupBox("Probe (SLC-06)", parent)
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self.probe_x = _spin(-1000.0, 1000.0, 0.0, parent=group)
        self.probe_y = _spin(-1000.0, 1000.0, 0.0, parent=group)
        self.probe_z = _spin(-1000.0, 1000.0, 0.0, parent=group)
        for label, widget in (("x", self.probe_x), ("y", self.probe_y), ("z", self.probe_z)):
            row.addWidget(_form_label(label, group))
            row.addWidget(widget)
        layout.addLayout(row)
        self.probe_button = QPushButton("Probe", group)
        self.probe_button.clicked.connect(self._on_probe)
        layout.addWidget(self.probe_button)
        self.probe_result_label = QLabel("", group)
        self.probe_result_label.setWordWrap(True)
        layout.addWidget(self.probe_result_label)
        return group

    # --------------------------------------------------------------- slots

    def _settings_from_form(self) -> InterpolationSettings:
        """Build settings; re-wrap enums returned by QVariant as plain strings."""
        return InterpolationSettings(
            method=InterpolationMethod(str(self.method_combo.currentData())),
            idw_power=self.idw_power_spin.value(),
            rbf_kernel=RBFKernel(str(self.rbf_kernel_combo.currentData())),
            rbf_smoothing=self.rbf_smoothing_spin.value(),
            smoothing_sigma=self.sigma_spin.value(),
            extrapolation=ExtrapolationPolicy(str(self.extrapolation_combo.currentData())),
            resolution=self.resolution_spin.value(),
        )

    def _on_apply_settings(self) -> None:
        self._model.set_interpolation_settings(self._settings_from_form())
        self.status_message.emit("Interpolation settings applied (audited)")

    def _update_method_note(self) -> None:
        settings = self._model.interpolation_settings()
        self.method_note_label.setText(
            "Interpolated values are estimates — method: "
            f"{settings.method.value}, grid {settings.resolution} m"
        )

    def _on_progress(self, percent: int) -> None:
        self.progress_bar.show()
        self.progress_bar.setValue(percent)

    def _on_compute(self) -> None:
        if not self._model.mapping_complete():
            self.edit_rejected.emit("Map or exclude every logger before computing (DAT-03)")
            return
        self._on_apply_settings()
        quantity = Quantity(str(self.quantity_combo.currentData()))
        aggregation = AggregationMethod(str(self.aggregation_combo.currentData()))
        try:
            self._model.interpolate_async(
                quantity,
                aggregation,
                time_index=self.time_index_spin.value(),
                temporal_window=self.temporal_window_spin.value(),
            )
        except (AlignmentError, InterpolationError) as error:
            self.edit_rejected.emit(str(error))

    def _on_obstacle_style(self, _index: int) -> None:
        self.obstacle_style_changed.emit(
            ObstacleStyle(str(self.obstacle_style_combo.currentData()))
        )

    def _emit_slices(self, *_args) -> None:
        self.slices_changed.emit(self._slice_specs())

    def _slice_specs(self) -> list[SliceSpec]:
        specs: list[SliceSpec] = []
        for axis in (SliceAxis.X, SliceAxis.Y, SliceAxis.Z):
            controls = self._slice_controls[axis.value]
            if controls["enabled"].isChecked():
                specs.append(
                    SliceSpec(
                        spec_id=axis.value,
                        axis=axis,
                        position=controls["position"].value(),
                        opacity=controls["opacity"].value(),
                    )
                )
        if self.plane_enabled.isChecked():
            specs.append(
                SliceSpec(
                    spec_id="plane",
                    axis=None,
                    point=(self.plane_px.value(), self.plane_py.value(), self.plane_pz.value()),
                    normal=(self.plane_nx.value(), self.plane_ny.value(), self.plane_nz.value()),
                    opacity=self.plane_opacity.value(),
                )
            )
        return specs

    def _emit_limits(self, *_args) -> None:
        if self.limits_check.isChecked():
            self.limits_changed.emit((self.limit_low_spin.value(), self.limit_high_spin.value()))
        else:
            self.limits_changed.emit(None)

    def set_color_scale(self, scale: ColorScale) -> None:
        """Sync the color form from an external source and propagate once."""
        self._color_widget.set_color_scale(scale)
        self.color_scale_changed.emit(scale)

    def open_color_scale_dialog(self) -> None:
        """Open a standalone color-scale dialog (overlay 'Colors' action)."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Color scale")
        layout = QVBoxLayout(dialog)
        widget = ColorScaleWidget(self._color_widget.scale(), dialog)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(widget)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            scale = widget.scale()
            self._color_widget.set_color_scale(scale)

    def _on_probe(self) -> None:
        quantity = self.quantity_combo.currentData()
        result = self._model.current_volume(quantity)
        if result is None:
            self.edit_rejected.emit("Compute a volume before probing")
            return
        point = (self.probe_x.value(), self.probe_y.value(), self.probe_z.value())
        if not point_in_space(self._model.space, *point):
            self.probe_result_label.setText(
                f"({point[0]:.3f}, {point[1]:.3f}, {point[2]:.3f}) m is outside the space"
            )
            return
        grid = build_voxel_grid(self._model.space, result.settings.resolution)
        value = sample_volume(result.volume, grid, point)
        unit = "°C" if quantity is Quantity.TEMPERATURE else "%RH"
        if math.isnan(value):
            text = f"({point[0]:.3f}, {point[1]:.3f}, {point[2]:.3f}) m → no data (masked)"
        else:
            text = (
                f"({point[0]:.3f}, {point[1]:.3f}, {point[2]:.3f}) m → {value:.3f} {unit} "
                f"(estimated, {result.settings.method.value})"
            )
        distances = np.linalg.norm(result.positions - np.asarray(point), axis=1)
        nearest = int(distances.argmin())
        dataset = self._model.aligned_dataset(quantity)
        if dataset is not None and dataset.values.shape[1] > nearest:
            series = dataset.values[:, nearest]
            finite = series[np.isfinite(series)]
            if finite.size:
                text += (
                    f"\nNearest logger '{result.logger_ids[nearest]}': "
                    f"min {finite.min():.2f}, max {finite.max():.2f}, "
                    f"mean {finite.mean():.2f} {unit}"
                )
        self.probe_result_label.setText(text)

    def on_timeline_changed(self) -> None:
        """Recompute the 3D view for a new timeline selection (acceptance item 6)."""
        self._recompute_for_timeline()

    def on_playhead_changed(self, _time: object) -> None:
        """Recompute in instant mode only; aggregate mode ignores the playhead."""
        if self._model.timeline_mode() is TimelineMode.INSTANT:
            self._recompute_for_timeline()

    def _recompute_for_timeline(self) -> None:
        if not self._model.mapping_complete():
            return
        quantity = Quantity(str(self.quantity_combo.currentData()))
        dataset = self._model.aligned_dataset(quantity)
        if dataset is None or self._model.current_volume(quantity) is None:
            return  # never auto-start before the first explicit compute
        settings = self._settings_from_form()
        if settings != self._model.interpolation_settings():
            self._model.set_interpolation_settings(settings)
        window = self.temporal_window_spin.value()
        try:
            if self._model.timeline_mode() is TimelineMode.INSTANT:
                playhead = self._model.playhead()
                time = playhead if playhead is not None else dataset.times[0]
                index = nearest_time_index(dataset.times, time)
                self._model.interpolate_async(
                    quantity,
                    AggregationMethod.INSTANT,
                    time_index=index,
                    temporal_window=window,
                )
            else:
                start, end = self._model.timeline_range()
                indices = (
                    time_range_indices(dataset.times, start, end)
                    if start is not None and end is not None
                    else None
                )
                if indices is None:
                    indices = (0, dataset.times.size - 1)
                method = AggregationMethod(str(self.aggregation_combo.currentData()))
                if method is AggregationMethod.INSTANT:
                    method = AggregationMethod.MEAN  # range mode needs a range aggregation
                self._model.interpolate_async(
                    quantity,
                    method,
                    range_start=indices[0],
                    range_end=indices[1],
                    temporal_window=window,
                )
        except (AlignmentError, InterpolationError) as error:
            self.edit_rejected.emit(str(error))

    def current_slices(self) -> list[SliceSpec]:
        """Slice specs currently configured (visible and hidden)."""
        return self._slice_specs()

    def current_color_scale(self) -> ColorScale:
        """Color scale currently configured."""
        return self._color_widget.scale()

    def current_limits(self) -> tuple[float, float] | None:
        """Active limit highlight range, or None when disabled (SLC-07)."""
        if not self.limits_check.isChecked():
            return None
        return (self.limit_low_spin.value(), self.limit_high_spin.value())

    def apply_slice_specs(self, specs) -> None:
        """Restore slice controls from saved specs (project view state)."""
        by_id = {spec.spec_id: spec for spec in specs}
        for axis in (SliceAxis.X, SliceAxis.Y, SliceAxis.Z):
            controls = self._slice_controls[axis.value]
            spec = by_id.get(axis.value)
            controls["enabled"].setChecked(spec is not None and spec.visible)
            if spec is not None:
                controls["position"].setValue(spec.position)
                controls["opacity"].setValue(spec.opacity)
        plane = by_id.get("plane")
        self.plane_enabled.setChecked(plane is not None and plane.visible)
        if plane is not None:
            self.plane_px.setValue(plane.point[0])
            self.plane_py.setValue(plane.point[1])
            self.plane_pz.setValue(plane.point[2])
            self.plane_nx.setValue(plane.normal[0])
            self.plane_ny.setValue(plane.normal[1])
            self.plane_nz.setValue(plane.normal[2])
            self.plane_opacity.setValue(plane.opacity)

    def apply_limits(self, limits: tuple[float, float] | None) -> None:
        """Restore the limit highlight controls (project view state)."""
        if limits is None:
            self.limits_check.setChecked(False)
            return
        self.limit_low_spin.setValue(float(limits[0]))
        self.limit_high_spin.setValue(float(limits[1]))
        self.limits_check.setChecked(True)


def _form_label(text: str, parent: QWidget) -> QLabel:
    return QLabel(text, parent)
