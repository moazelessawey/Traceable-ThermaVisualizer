"""Main application window implementing the PRD section 4 layout contract."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
    QStatusBar,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QDialog,
)

from thermavisualizer import __version__
from thermavisualizer.core.alignment import time_range_indices
from thermavisualizer.core.interpolation import build_voxel_grid
from thermavisualizer.core.models import Quantity, TimelineMode
from thermavisualizer.core.slicing import (
    extract_axis_slice,
    extract_plane_slice,
    slice_spec_from_dict,
    slice_spec_to_dict,
)
from thermavisualizer.io import recovery
from thermavisualizer.io.exporters import (
    export_aligned,
    export_slice_csv,
    export_validation_report_csv,
    export_volume_npz,
)
from thermavisualizer.io.layout_io import file_sha256
from thermavisualizer.io.project_file import load_project, save_project
from thermavisualizer.io.report import ReportOptions
from thermavisualizer.rendering.colormaps import (
    color_limits,
    color_scale_from_dict,
    color_scale_to_dict,
    colormap_for,
)
from thermavisualizer.rendering.scene import ObstacleStyle
from thermavisualizer.resources.themes import Theme, apply_theme
from thermavisualizer.services.audit import AuditAction
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.reporting import report_task
from thermavisualizer.services.settings import AppSettings
from thermavisualizer.services.timeline import TimelineController
from thermavisualizer.services.workers import (
    FunctionWorker,
    MovieJob,
    MovieResult,
    export_movie_task,
)
from thermavisualizer.ui.dialogs import (
    AuditTrailDialog,
    CompareDialog,
    DataExportDialog,
    DiagnosticsDialog,
    MovieExportDialog,
    PreferencesDialog,
    show_about_dialog,
)
from thermavisualizer.ui.dialogs.import_data import ImportDataDialog
from thermavisualizer.ui.panels.configuration_panel import ConfigurationPanel
from thermavisualizer.ui.panels.control_panel import ControlPanel
from thermavisualizer.ui.panels.data_panel import DataPanel
from thermavisualizer.ui.panels.plots_panel import PlotsPanel
from thermavisualizer.ui.panels.results_panel import ResultsPanel
from thermavisualizer.ui.panels.view3d_panel import View3DPanel
from thermavisualizer.ui.tabs.configuration import ConfigurationTab
from thermavisualizer.ui.tabs.data import DataTab
from thermavisualizer.ui.tabs.placeholders import PlaceholderTab
from thermavisualizer.ui.tabs.plots import PlotsTab, render_slice_heatmap_png
from thermavisualizer.ui.tabs.results import ResultsTab
from thermavisualizer.ui.tabs.view3d import View3DTab
from thermavisualizer.ui.widgets.timeline import TimelinePanel

logger = logging.getLogger(__name__)

MAINTAINER_CREDIT = "Developed and maintained by Moaz El-Essawey"
TAB_NAMES: tuple[str, ...] = ("Configuration", "3D View", "Plots", "Results", "Data")

_TAB_DESCRIPTIONS: dict[str, str] = {
    "Configuration": (
        "Space dimensions, layers, logger grid, and obstacles.\n"
        "Layout design arrives in milestone M1."
    ),
    "3D View": (
        "Interpolated 3D heat map, slices, and probes.\nVisualization arrives in milestone M3."
    ),
    "Plots": ("Temperature and humidity time-series plots.\nPlots arrive in milestone M4."),
    "Results": (
        "Acceptance criteria, excursions, and pass/fail results.\nResults arrive in milestone M4."
    ),
    "Data": (
        "File import, logger-to-column mapping, and validation.\n"
        "Data loading arrives in milestone M2."
    ),
}

_DEFAULT_SIZE = (1280, 800)
_SPLIT_LEFT = 320
_SPLIT_RIGHT = 960


class MainWindow(QMainWindow):
    """Primary application window (menu, toolbar, east tabs, timeline, status bar)."""

    def __init__(
        self,
        settings: AppSettings | None = None,
        recovery_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings if settings is not None else AppSettings()
        self.setWindowTitle(f"Traceable.ThermaVisualizer {__version__}")

        self._model = ProjectModel(user_name=self._settings.user_name(), parent=self)
        self._model.load_progress_changed.connect(self._show_load_progress)
        self._undo_stack = self._model.undo_stack
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._timeline_controller = TimelineController(self._model, self)

        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self._splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self._splitter.setChildrenCollapsible(False)

        self._control_panel = ControlPanel(self)
        self._tabs = QTabWidget(self)
        self._tabs.setTabPosition(QTabWidget.TabPosition.East)
        for name in TAB_NAMES:
            self._control_panel.add_page(name, _TAB_DESCRIPTIONS[name])
            if name == "Configuration":
                self._configuration_tab = ConfigurationTab(self._model, self)
                self._tabs.addTab(self._configuration_tab, name)
            elif name == "Data":
                self._data_tab = DataTab(self._model, self)
                self._tabs.addTab(self._data_tab, name)
            elif name == "3D View":
                self._view3d_tab = View3DTab(self._model, self)
                self._tabs.addTab(self._view3d_tab, name)
            elif name == "Plots":
                self._plots_tab = PlotsTab(self._model, self)
                self._tabs.addTab(self._plots_tab, name)
            elif name == "Results":
                self._results_tab = ResultsTab(self._model, self)
                self._tabs.addTab(self._results_tab, name)
            else:
                self._tabs.addTab(PlaceholderTab(name, _TAB_DESCRIPTIONS[name], self), name)
        self._tabs.currentChanged.connect(self._control_panel.set_active_index)

        self._splitter.addWidget(self._control_panel)
        self._splitter.addWidget(self._tabs)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 3)

        self._configuration_panel = ConfigurationPanel(self._model, self)
        self._control_panel.replace_page(0, self._configuration_panel)
        self._configuration_panel.status_message.connect(self._show_status_message)
        self._configuration_tab.editor.edit_rejected.connect(self._show_status_message)
        self._configuration_tab.table.edit_rejected.connect(self._show_status_message)
        self._configuration_panel.edit_rejected.connect(self._show_status_message)

        data_index = TAB_NAMES.index("Data")
        self._data_panel = DataPanel(self._model, self)
        self._control_panel.replace_page(data_index, self._data_panel)
        self._data_panel.import_requested.connect(self._on_import_data)
        self._data_panel.status_message.connect(self._show_status_message)
        self._data_panel.edit_rejected.connect(self._show_status_message)
        self._action_import_data.setEnabled(True)
        self._action_import_data.triggered.connect(self._on_import_data)

        view3d_index = TAB_NAMES.index("3D View")
        self._view3d_panel = View3DPanel(self._model, self)
        self._control_panel.replace_page(view3d_index, self._view3d_panel)
        self._view3d_panel.slices_changed.connect(self._view3d_tab.view.set_slices)
        self._view3d_panel.color_scale_changed.connect(self._view3d_tab.view.set_color_scale)
        self._view3d_panel.limits_changed.connect(self._view3d_tab.view.set_limits)
        self._view3d_panel.axes_toggled.connect(self._view3d_tab.view.set_axes_visible)
        self._view3d_panel.obstacle_style_changed.connect(self._view3d_tab.view.set_obstacle_style)
        self._view3d_panel.status_message.connect(self._show_status_message)
        self._view3d_panel.edit_rejected.connect(self._show_status_message)
        self._view3d_tab.status_message.connect(self._show_status_message)
        self._view3d_tab.color_scale_clicked.connect(self._view3d_panel.open_color_scale_dialog)
        self._action_reset_camera.triggered.connect(self._view3d_tab.view.reset_camera)

        self._timeline = TimelinePanel(self._model, self._timeline_controller, self)
        self._model.timeline_changed.connect(self._view3d_panel.on_timeline_changed)
        self._model.timeline_mode_changed.connect(self._view3d_panel.on_timeline_changed)
        self._model.playhead_changed.connect(self._view3d_panel.on_playhead_changed)

        plots_index = TAB_NAMES.index("Plots")
        self._plots_panel = PlotsPanel(self._model, self)
        self._control_panel.replace_page(plots_index, self._plots_panel)
        self._plots_panel.options_changed.connect(self._plots_tab.set_options)
        self._plots_panel.series_changed.connect(self._plots_tab.set_selected_series)

        results_index = TAB_NAMES.index("Results")
        self._results_panel = ResultsPanel(self._model, self)
        self._control_panel.replace_page(results_index, self._results_panel)
        self._results_tab.link_limits_to_3d.connect(self._on_link_limits_to_3d)
        self._results_tab.report_requested.connect(self._on_generate_report)
        self._results_tab.compare_requested.connect(self._on_compare)

        self._export_worker: FunctionWorker | None = None
        self._action_export_image.setEnabled(True)
        self._action_export_image.setToolTip("Export the current 3D view as PNG/JPG (EXP-03)")
        self._action_export_image.triggered.connect(self._on_export_image)
        self._action_export_movie.setEnabled(True)
        self._action_export_movie.setToolTip("Export an animation over the selected range (EXP-02)")
        self._action_export_movie.triggered.connect(self._on_export_movie)
        self._action_export_data.setEnabled(True)
        self._action_export_data.setToolTip("Export data, volumes, slices, or reports (EXP-04)")
        self._action_export_data.triggered.connect(self._on_export_data)

        self._project_path: Path | None = None
        self._project_worker: FunctionWorker | None = None
        self._action_new.setEnabled(True)
        self._action_new.setToolTip("Start a new project")
        self._action_new.triggered.connect(self._on_new_project)
        self._action_open.setEnabled(True)
        self._action_open.setToolTip("Open a .tmap project (EXP-05)")
        self._action_open.triggered.connect(self._on_open_project)
        self._action_save.setEnabled(True)
        self._action_save.setToolTip("Save the .tmap project (EXP-05)")
        self._action_save.triggered.connect(self._on_save_project)
        self._action_save_as.setEnabled(True)
        self._action_save_as.setToolTip("Save the project under a new name")
        self._action_save_as.triggered.connect(self._on_save_project_as)
        self._action_audit_viewer.setEnabled(True)
        self._action_audit_viewer.setToolTip("View the audit trail (AUD-06)")
        self._action_audit_viewer.triggered.connect(self._on_audit_viewer)
        self._model.study_changed.connect(self._refresh_window_title)
        self._model.modified_changed.connect(self._refresh_window_title)
        self._model.project_loaded.connect(self._refresh_window_title)
        self._refresh_recent_menu()
        self._refresh_window_title()

        self._splitter_initialized = False

        root.addWidget(self._splitter, 1)
        root.addWidget(self._timeline, 0)
        self.setCentralWidget(central)

        self._build_status_bar()
        self._start_maximized = False
        self._restore_layout()

        self._recovery_path = (
            recovery_path if recovery_path is not None else recovery.default_recovery_path()
        )
        apply_theme(QApplication.instance(), self._theme_from_settings())
        self._model.logger_selected.connect(self._show_selected_logger_info)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(60_000)  # NFR reliability: periodic autosave
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()
        self._ensure_user_name()
        QTimer.singleShot(0, self._offer_recovery)

        logger.info("Main window initialised (M0 shell)")

    # ------------------------------------------------------------ building

    def _make_action(
        self,
        text: str,
        *,
        shortcut: QKeySequence.StandardKey | str | None = None,
        icon: QStyle.StandardPixmap | None = None,
        enabled: bool = True,
        tip: str = "",
        slot: Callable[[], object] | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(self.style().standardIcon(icon))
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.setEnabled(enabled)
        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        if slot is not None:
            action.triggered.connect(slot)
        return action

    def _build_actions(self) -> None:
        pixmap = QStyle.StandardPixmap
        self._action_new = self._make_action(
            "&New Project",
            shortcut=QKeySequence.StandardKey.New,
            icon=pixmap.SP_FileDialogNewFolder,
            enabled=False,
            tip="Create a new project (available from M6)",
        )
        self._action_open = self._make_action(
            "&Open Project…",
            shortcut=QKeySequence.StandardKey.Open,
            icon=pixmap.SP_DirOpenIcon,
            enabled=False,
            tip="Open a .tmap project (available from M6)",
        )
        self._action_save = self._make_action(
            "&Save Project",
            shortcut=QKeySequence.StandardKey.Save,
            icon=pixmap.SP_DialogSaveButton,
            enabled=False,
            tip="Save the .tmap project (available from M6)",
        )
        self._action_save_as = self._make_action(
            "Save Project &As…",
            shortcut=QKeySequence.StandardKey.SaveAs,
            enabled=False,
            tip="Save the project under a new name (available from M6)",
        )
        self._action_import_data = self._make_action(
            "&Import Data…",
            shortcut="Ctrl+I",
            icon=pixmap.SP_DialogOpenButton,
            enabled=False,
            tip="Import logger data files (available from M2)",
        )
        self._action_export_image = self._make_action(
            "Export &Image…", enabled=False, tip="Export the current view as an image (M5)"
        )
        self._action_export_movie = self._make_action(
            "Export &Movie…",
            enabled=False,
            tip="Export an animation over the selected range (M5)",
        )
        self._action_export_data = self._make_action(
            "Export &Data…",
            enabled=False,
            tip="Export processed data and statistics (M5)",
        )
        self._action_export_image.setObjectName("action_export_image")
        self._action_export_movie.setObjectName("action_export_movie")
        self._action_export_data.setObjectName("action_export_data")
        
        self._action_reset_camera = self._make_action(
            "Reset Camera",
            icon=pixmap.SP_BrowserReload,
            enabled=False,
            tip="Reset the 3D camera",
        )
        self._action_reset_camera.setEnabled(True)
        self._action_reset_camera.setToolTip("Reset the 3D camera to fit the scene")
        self._action_exit = self._make_action(
            "E&xit",
            shortcut=QKeySequence.StandardKey.Quit,
            slot=self.close,
            tip="Quit ThermaVisualizer",
        )
        self._action_undo = self._undo_stack.createUndoAction(self, "&Undo")
        self._action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self._action_redo = self._undo_stack.createRedoAction(self, "&Redo")
        self._action_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self._action_reset_layout = self._make_action(
            "&Reset Window Layout",
            slot=self._reset_layout,
            tip="Restore the default window layout",
        )
        self._action_audit_viewer = self._make_action(
            "&Audit Trail Viewer…",
            enabled=False,
            tip="Audit trail viewer (available from M6)",
        )
        self._action_preferences = self._make_action(
            "&Preferences…", enabled=False, tip="Preferences (available from M7)"
        )
        self._action_preferences.setEnabled(True)
        self._action_preferences.setToolTip("Application preferences")
        self._action_preferences.triggered.connect(self._on_preferences)
        self._action_about = self._make_action(
            "&About ThermaVisualizer", slot=self._show_about, tip="About this application"
        )
        self._action_diagnostics = self._make_action(
            "&Diagnostics…", slot=self._show_diagnostics, tip="Version and environment details"
        )

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self._action_new)
        file_menu.addAction(self._action_open)
        file_menu.addAction(self._action_save)
        file_menu.addAction(self._action_save_as)
        self._recent_menu = file_menu.addMenu("Recent Files")
        file_menu.addSeparator()
        file_menu.addAction(self._action_import_data)
        export_menu = file_menu.addMenu("&Export")
        export_menu.addAction(self._action_export_image)
        export_menu.addAction(self._action_export_movie)
        export_menu.addAction(self._action_export_data)
        file_menu.addSeparator()
        file_menu.addAction(self._action_exit)

        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self._action_undo)
        edit_menu.addAction(self._action_redo)

        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self._action_reset_layout)

        theme_menu = view_menu.addMenu("Theme")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        current = self._theme_from_settings()
        for theme in Theme:
            action = QAction(theme.value.capitalize(), self)
            action.setCheckable(True)
            action.setData(theme.value)
            action.setChecked(theme is current)
            self._theme_group.addAction(action)
            theme_menu.addAction(action)
        self._theme_group.triggered.connect(self._on_theme_selected)

        data_menu = menu_bar.addMenu("&Data")
        data_menu.addAction(self._action_import_data)

        tools_menu = menu_bar.addMenu("&Tools")
        tools_menu.addAction(self._action_audit_viewer)
        tools_menu.addSeparator()
        tools_menu.addAction(self._action_preferences)

        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self._action_about)
        help_menu.addAction(self._action_diagnostics)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main Toolbar", self)
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for action in (
            self._action_new,
            self._action_open,
            self._action_save,
            self._action_import_data,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()
        for action in (
            self._action_export_image,
            self._action_export_movie,
            self._action_reset_camera,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self._action_undo)
        toolbar.addAction(self._action_redo)

    def _build_status_bar(self) -> None:
        status = QStatusBar(self)
        self.setStatusBar(status)
        self._credit_label = QLabel("Ready . " + MAINTAINER_CREDIT, self)
        status.addWidget(self._credit_label)

    # ------------------------------------------------------------- layout

    def _restore_layout(self) -> None:
        geometry = self._settings.window_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(*_DEFAULT_SIZE)
        splitter_state = self._settings.splitter_state()
        if splitter_state is not None:
            self._splitter.restoreState(splitter_state)
        else:
            self._start_maximized = True  # first launch: use the full screen

    def _save_layout(self) -> None:
        self._settings.save_window_geometry(self.saveGeometry())
        self._settings.save_splitter_state(self._splitter.saveState())
        self._settings.sync()

    def should_start_maximized(self) -> bool:
        """True on first launch (no persisted window geometry yet)."""
        return self._start_maximized

    def _reset_layout(self) -> None:
        self._splitter.setSizes([_SPLIT_LEFT, _SPLIT_RIGHT])
        self.resize(*_DEFAULT_SIZE)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt virtual
        """Guard unsaved changes, then persist the window layout."""
        if not self._confirm_discard():
            event.ignore()
            return
        self._save_layout()
        self._clear_recovery()
        logger.info("Main window closed; layout persisted")
        super().closeEvent(event)

    def _on_link_limits_to_3d(self, low: float, high: float) -> None:
        """Push result criteria limits to the 3D view overlay (SLC-07)."""
        self._view3d_panel.limits_check.setChecked(True)
        self._view3d_panel.limit_low_spin.setValue(low)
        self._view3d_panel.limit_high_spin.setValue(high)
        self._view3d_panel._emit_limits()
        self._tabs.setCurrentWidget(self._view3d_tab)

    # --------------------------------------------------------------- slots

    def _show_about(self) -> None:
        show_about_dialog(self)

    def _show_diagnostics(self) -> None:
        DiagnosticsDialog(self).exec()

    def _show_load_progress(self, percent: int) -> None:
        """Show background load progress in the status bar (PRD 4.1)."""
        self.statusBar().showMessage(f"Loading data… {percent}%", 0)

    def _on_import_data(self) -> None:
        dialog = ImportDataDialog(self._model, self)
        dialog.exec()

    # ---------------------------------------------------------- accessors

    @property
    def tab_widget(self) -> QTabWidget:
        """Right-hand tab widget (tab bar on the east edge)."""
        return self._tabs

    @property
    def splitter(self) -> QSplitter:
        """Main horizontal splitter (left panel | tabs)."""
        return self._splitter

    @property
    def control_panel(self) -> ControlPanel:
        """Left contextual control panel."""
        return self._control_panel

    @property
    def timeline(self) -> TimelinePanel:
        """Timeline panel below the main area."""
        return self._timeline

    def status_credit(self) -> str:
        """Text of the permanent status bar credit label."""
        return self._credit_label.text()

    @property
    def model(self) -> ProjectModel:
        """The observable project model (single source of state)."""
        return self._model

    def _show_status_message(self, message: str) -> None:
        """Show a transient rejection/info message in the status bar."""
        self.statusBar().showMessage(message, 5000)

    @property
    def configuration_tab(self) -> ConfigurationTab:
        """The Configuration tab widget."""
        return self._configuration_tab

    @property
    def configuration_panel(self) -> ConfigurationPanel:
        """The Configuration left-panel widget."""
        return self._configuration_panel

    @property
    def timeline_controller(self) -> TimelineController:
        """Playback controller for the timeline."""
        return self._timeline_controller

    @property
    def plots_tab(self) -> PlotsTab:
        """The Plots tab widget."""
        return self._plots_tab

    @property
    def plots_panel(self) -> PlotsPanel:
        """The Plots left-panel widget."""
        return self._plots_panel

    @property
    def results_tab(self) -> ResultsTab:
        return self._results_tab

    @property
    def results_panel(self) -> ResultsPanel:
        return self._results_panel

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt virtual
        """Enforce the default 25/75 split on first show when no state is saved."""
        super().showEvent(event)
        if self._splitter_initialized:
            return
        self._splitter_initialized = True
        if self._settings.splitter_state() is None:
            width = self._splitter.size().width()
            if width <= 0:
                width = max(self.width() - 24, 0)
            if width > 0:
                left = width // 4
                self._splitter.setSizes([left, width - left])

    # -------------------------------------------------------------- exports

    def _audit_export(self, path: Path, summary: str) -> None:
        digest = file_sha256(path)
        self._model.note(
            AuditAction.EXPORTED,
            f"file:{path.name}",
            f"{summary}; sha256={digest[:16]}…",
        )

    def _primary_dataset(self):
        return self._model.aligned_dataset(Quantity.TEMPERATURE) or self._model.aligned_dataset(
            Quantity.HUMIDITY
        )

    def _on_export_image(self) -> None:  # EXP-03
        if not self._view3d_tab.view.is_active():
            self._show_status_message("Open the 3D View with an active renderer first")
            return
        scale, accepted = QInputDialog.getInt(
            self, "Export image", "Resolution scale (1-4):", 2, 1, 4
        )
        if not accepted:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export 3D image", "view3d.png", "PNG (*.png);;JPEG (*.jpg)"
        )
        if not path:
            return
        target = Path(path)
        if self._view3d_tab.view.save_screenshot(target, scale=int(scale)):
            self._audit_export(target, f"3D image exported (scale {scale})")
            self._show_status_message(f"Image exported to {target.name}")

    def _on_export_movie(self) -> None:  # EXP-02
        if self._export_worker is not None:
            self._export_worker.cancel()
            self._show_status_message("Cancelling movie export…")
            return
        dataset = self._primary_dataset()
        if dataset is None:
            self._show_status_message("Align data before exporting a movie")
            return
        dialog = MovieExportDialog(self, frame_count_hint=dataset.times.size)
        if dialog.exec() != MovieExportDialog.DialogCode.Accepted:
            return
        options = dialog.values()
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export movie", "movie.mp4", "MP4 (*.mp4);;GIF (*.gif)"
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() not in (".mp4", ".gif"):
            target = target.with_suffix(".gif" if "GIF" in selected_filter else ".mp4")
        scale = self._view3d_panel.current_color_scale()
        start_index, end_index = 0, dataset.times.size - 1
        range_start, range_end = self._model.timeline_range()
        if range_start is not None and range_end is not None:
            indices = time_range_indices(dataset.times, range_start, range_end)
            if indices is not None:
                start_index, end_index = indices
        job = MovieJob(
            output_path=str(target),
            space=self._model.space,
            obstacles=tuple(self._model.space.obstacles),
            positions=self._model.logger_positions(dataset.logger_ids),
            logger_ids=tuple(dataset.logger_ids),
            times=dataset.times,
            values=dataset.values,
            settings=self._model.interpolation_settings(),
            quantity=dataset.quantity,
            range_start=start_index,
            range_end=end_index,
            step_stride=int(options["stride"]),
            fps=int(options["fps"]),
            width=int(options["width"]),
            height=int(options["height"]),
            colormap=colormap_for(scale),
            clim=None if scale.auto_range else (scale.vmin, scale.vmax),
            slices=tuple(s for s in self._view3d_panel.current_slices() if s.visible),
            burn_timestamp=bool(options["burn_timestamp"]),
            burn_colorbar=bool(options["burn_colorbar"]),
        )
        worker = FunctionWorker(
            lambda cancel_check, report_progress: export_movie_task(
                job, cancel_check, report_progress
            ),
            self,
        )
        self._run_export_worker(worker, f"Exporting movie to {target.name}…")

    def _on_export_data(self) -> None:  # EXP-03/04/06
        dataset = self._primary_dataset()
        volume_result = self._model.current_volume(
            Quantity.TEMPERATURE
        ) or self._model.current_volume(Quantity.HUMIDITY)
        visible_slice = next((s for s in self._view3d_panel.current_slices() if s.visible), None)
        has_slice = bool(visible_slice is not None and volume_result is not None)
        enabled = {
            "aligned": dataset is not None,
            "volume": volume_result is not None,
            "slice": has_slice,
            "slice_image": has_slice,
            "validation": len(self._model.validation_report.findings) > 0,
        }
        dialog = DataExportDialog(self, enabled)
        if dialog.exec() != DataExportDialog.DialogCode.Accepted:
            return
        choice = dialog.selected()
        if choice == "aligned" and dataset is not None:
            self._export_aligned(dataset)
        elif choice == "volume" and volume_result is not None:
            self._export_volume(volume_result)
        elif choice in ("slice", "slice_image") and volume_result is not None:
            self._export_slice(volume_result, visible_slice, choice)
        elif choice == "validation":
            self._export_validation()

    def _export_aligned(self, dataset) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export aligned data", "aligned_data.csv", "CSV (*.csv);;Excel (*.xlsx)"
        )
        if not path:
            return
        target = Path(path)
        export_aligned(target, dataset.times, dataset.logger_ids, dataset.values)
        self._audit_export(
            target,
            f"Aligned {dataset.quantity.value} data exported ({dataset.values.shape[0]} rows)",
        )
        self._show_status_message(f"Aligned data exported to {target.name}")

    def _export_volume(self, result) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export interpolated volume", "volume.npz", "NumPy archive (*.npz)"
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".npz":
            target = target.with_suffix(".npz")
        grid = build_voxel_grid(self._model.space, result.settings.resolution)
        export_volume_npz(
            target,
            result.volume,
            grid,
            {
                "quantity": result.quantity.value,
                "method": result.settings.method.value,
                "time_label": result.time_label,
                "app_version": __version__,
                "study_title": self._model.study().title,
                "study_protocol": self._model.study().protocol_id,
            },
        )
        self._audit_export(target, f"Interpolated volume exported ({result.quantity.value})")
        self._show_status_message(f"Volume exported to {target.name}")

    def _export_slice(self, result, spec, choice: str) -> None:
        grid = build_voxel_grid(self._model.space, result.settings.resolution)
        obstacles = list(self._model.space.obstacles)
        if spec.axis is not None:
            data = extract_axis_slice(
                result.volume, grid, self._model.space, obstacles, spec.axis, spec.position
            )
        else:
            data = extract_plane_slice(
                result.volume, grid, self._model.space, obstacles, spec.point, spec.normal
            )
        if choice == "slice":
            path, _ = QFileDialog.getSaveFileName(
                self, "Export slice samples", "slice.csv", "CSV (*.csv)"
            )
            if not path:
                return
            target = Path(path)
            export_slice_csv(target, data)
            self._audit_export(target, f"Slice '{spec.spec_id}' samples exported")
            self._show_status_message(f"Slice exported to {target.name}")
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export slice heat map", "slice_heatmap.png", "PNG (*.png)"
            )
            if not path:
                return
            target = Path(path)
            scale = self._view3d_panel.current_color_scale()
            title = (
                "Temperature (°C)" if result.quantity is Quantity.TEMPERATURE else "Humidity (%RH)"
            )
            render_slice_heatmap_png(
                data, target, colormap_for(scale), color_limits(scale, result.volume), title
            )
            self._audit_export(target, f"Slice '{spec.spec_id}' heat map exported")
            self._show_status_message(f"Slice heat map exported to {target.name}")

    def _export_validation(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export validation report", "validation_report.csv", "CSV (*.csv)"
        )
        if not path:
            return
        target = Path(path)
        export_validation_report_csv(self._model.validation_report, target)
        self._audit_export(target, "Validation report exported")
        self._show_status_message(f"Validation report exported to {target.name}")

    def _run_export_worker(self, worker: FunctionWorker, label: str) -> None:
        """Run an export worker with status-bar progress and a cancel button."""
        bar = QProgressBar(self)
        bar.setRange(0, 100)
        bar.setMaximumWidth(220)
        cancel_button = QToolButton(self)
        cancel_button.setText("Cancel")
        cancel_button.clicked.connect(worker.cancel)
        self.statusBar().addPermanentWidget(bar)
        self.statusBar().addPermanentWidget(cancel_button)

        def finish() -> None:
            bar.deleteLater()
            cancel_button.deleteLater()
            self._export_worker = None

        def on_result(result: object) -> None:
            finish()
            if result is None:
                self._show_status_message("Export cancelled")
            elif isinstance(result, MovieResult):
                self._audit_export(
                    Path(result.path),
                    f"Movie exported ({result.frames} frames, {result.format})",
                )
                self._show_status_message(f"Movie exported to {Path(result.path).name}")
            elif isinstance(result, str) and result.endswith(".pdf"):
                self._audit_export(Path(result), "PDF report generated")
                self._show_status_message(f"Report saved to {Path(result).name}")
            else:
                self._show_status_message("Export finished")

        def on_error(message: str) -> None:
            finish()
            self._show_status_message(f"Export failed: {message}")

        def on_cancelled() -> None:
            finish()
            self._show_status_message("Export cancelled")

        worker.progress_changed.connect(bar.setValue)
        worker.result_ready.connect(on_result)
        worker.error_occurred.connect(on_error)
        worker.work_cancelled.connect(on_cancelled)
        worker.finished.connect(worker.deleteLater)
        self._export_worker = worker
        self.statusBar().showMessage(label, 0)
        worker.start()

    # ---------------------------------------------------- project lifecycle

    def _confirm_discard(self) -> bool:
        if not self._model.is_modified():
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "The project has unsaved changes. Discard them?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _refresh_window_title(self) -> None:
        """Window title shows study/project identity and modified state (STY-02)."""
        identity = self._model.study().title or (
            self._project_path.name if self._project_path else "Untitled"
        )
        marker = "*" if self._model.is_modified() else ""
        self.setWindowTitle(f"{marker}Traceable.ThermaVisualizer {__version__} — {identity}")

    def _on_new_project(self) -> None:
        if not self._confirm_discard():
            return
        self._model.reset_project()
        self._project_path = None
        self._refresh_window_title()
        self._show_status_message("New project created")

    def _on_open_project(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "ThermaVisualizer project (*.tmap)"
        )
        if path:
            self._open_project(Path(path))

    def _open_project(self, path: Path) -> None:
        if self._project_worker is not None:
            self._show_status_message("Another project operation is in progress")
            return

        worker = FunctionWorker(lambda cancel_check, report_progress: load_project(path), self)

        def on_result(result: object) -> None:
            self._project_worker = None
            snapshot, warnings = result  # type: ignore[misc]
            self._model.load_snapshot(snapshot)
            self._apply_view_state(snapshot.view_state)
            self._project_path = path
            self._model.mark_saved()
            self._model.note(AuditAction.PROJECT_OPEN, f"file:{path.name}", "Project opened")
            self._settings.add_recent_file(str(path))
            self._refresh_recent_menu()
            self._refresh_window_title()
            self._show_status_message(f"Project opened: {path.name}")
            if warnings:
                QMessageBox.warning(self, "Project integrity warnings", "\n".join(warnings))

        def on_error(message: str) -> None:
            self._project_worker = None
            QMessageBox.critical(self, "Open failed", message)

        worker.result_ready.connect(on_result)
        worker.error_occurred.connect(on_error)
        worker.finished.connect(worker.deleteLater)
        self._project_worker = worker
        self.statusBar().showMessage(f"Opening {path.name}…", 0)
        worker.start()

    def _on_save_project(self) -> None:
        if self._project_path is None:
            self._on_save_project_as()
            return
        self._save_to(self._project_path)

    def _on_save_project_as(self) -> None:
        default = (self._model.study().title or "study").replace(" ", "_") + ".tmap"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", default, "ThermaVisualizer project (*.tmap)"
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".tmap":
            target = target.with_suffix(".tmap")
        self._save_to(target)

    def _save_to(self, target: Path) -> None:
        if self._project_worker is not None:
            self._show_status_message("Another project operation is in progress")
            return
        snapshot = self._model.build_snapshot(self._collect_view_state())
        author = self._model.audit.user_name
        worker = FunctionWorker(
            lambda cancel_check, report_progress: save_project(target, snapshot, author),
            self,
        )

        def on_result(_result: object) -> None:
            self._project_worker = None
            self._project_path = target
            self._model.mark_saved()
            self._clear_recovery()
            self._model.note(
                AuditAction.PROJECT_SAVE,
                f"file:{target.name}",
                f"Project saved; sha256={file_sha256(target)[:16]}…",
            )
            self._settings.add_recent_file(str(target))
            self._refresh_recent_menu()
            self._refresh_window_title()
            self._show_status_message(f"Project saved to {target.name}")

        def on_error(message: str) -> None:
            self._project_worker = None
            QMessageBox.critical(self, "Save failed", message)

        worker.result_ready.connect(on_result)
        worker.error_occurred.connect(on_error)
        worker.finished.connect(worker.deleteLater)
        self._project_worker = worker
        self.statusBar().showMessage(f"Saving {target.name}…", 0)
        worker.start()

    def _on_audit_viewer(self) -> None:
        AuditTrailDialog(self._model.audit, self).exec()

    def _refresh_recent_menu(self) -> None:
        self._recent_menu.clear()
        for recent in self._settings.recent_files():
            action = self._recent_menu.addAction(recent)
            action.triggered.connect(
                lambda _checked=False, recent_path=recent: self._open_recent(recent_path)
            )

    def _open_recent(self, recent_path: str) -> None:
        if not self._confirm_discard():
            return
        path = Path(recent_path)
        if path.exists():
            self._open_project(path)
        else:
            self._show_status_message(f"Recent project not found: {recent_path}")

    # ----------------------------------------------------------- view state

    def _collect_view_state(self) -> dict:
        """Serialize the visual state so reopening restores it (EXP-05)."""
        view = self._view3d_tab.view
        panel = self._view3d_panel
        start, end = self._model.timeline_range()
        playhead = self._model.playhead()
        return {
            "slices": [slice_spec_to_dict(s) for s in panel.current_slices()],
            "color_scale": color_scale_to_dict(panel.current_color_scale()),
            "limits": panel.current_limits(),
            "axes_visible": panel.axes_check.isChecked(),
            "markers_visible": view.markers_visible(),
            "slices_visible": view.slices_visible(),
            "labels_visible": view.labels_visible(),
            "obstacle_style": view.obstacle_style().value,
            "camera": view.camera_state(),
            "timeline": {
                "start": None if start is None else str(start),
                "end": None if end is None else str(end),
                "playhead": None if playhead is None else str(playhead),
                "mode": self._model.timeline_mode().value,
            },
        }

    def _apply_view_state(self, state: dict) -> None:
        """Restore visual state best-effort; unknown keys are skipped."""
        if not isinstance(state, dict):
            return
        try:
            view = self._view3d_tab.view
            panel = self._view3d_panel
            panel.apply_slice_specs(
                [slice_spec_from_dict(item) for item in state.get("slices", [])]
            )
            if "color_scale" in state:
                panel.set_color_scale(color_scale_from_dict(state["color_scale"]))
            panel.apply_limits(state.get("limits"))
            panel.axes_check.setChecked(bool(state.get("axes_visible", True)))
            view.set_markers_visible(bool(state.get("markers_visible", True)))
            view.set_slices_visible(bool(state.get("slices_visible", True)))
            view.set_labels_visible(bool(state.get("labels_visible", False)))
            style = state.get("obstacle_style")
            if style:
                view.set_obstacle_style(ObstacleStyle(str(style)))
            view.set_camera_state(state.get("camera"))
            timeline = state.get("timeline", {})
            mode = timeline.get("mode")
            if mode:
                self._model.set_timeline_mode(TimelineMode(str(mode)))
            start = timeline.get("start")
            end = timeline.get("end")
            self._model.set_timeline_range(
                np.datetime64(start) if start else None,
                np.datetime64(end) if end else None,
            )
            playhead = timeline.get("playhead")
            self._model.set_playhead(np.datetime64(playhead) if playhead else None)
        except (KeyError, TypeError, ValueError) as error:
            logger.warning("view state not fully restored: %s", error)

    # --------------------------------------------------------------- themes

    def _theme_from_settings(self) -> Theme:
        try:
            return Theme(self._settings.theme())
        except ValueError:
            return Theme.SYSTEM

    def _on_theme_selected(self, action: QAction) -> None:
        theme = Theme(str(action.data()))
        self._settings.set_theme(theme.value)
        apply_theme(QApplication.instance(), theme)

    # ------------------------------------------------------ first launch

    def _ensure_user_name(self) -> None:
        """Ask for the audit user name on first launch (AUD-02)."""
        if self._settings.user_name_asked():
            return
        name, accepted = QInputDialog.getText(
            self,
            "Welcome to Traceable.ThermaVisualizer",
            "Enter your name for the audit trail:",
            text=self._settings.user_name(),
        )
        self._settings.set_user_name_asked()
        if accepted and name.strip():
            self._settings.set_user_name(name.strip())
            self._model.audit.set_user_name(name.strip())

    # ----------------------------------------------------- recovery/autosave

    def _offer_recovery(self) -> None:
        """Offer restoring the autosaved recovery file (NFR reliability)."""
        meta = recovery.read_recovery_metadata(self._recovery_path)
        if meta is None:
            return
        answer = QMessageBox.question(
            self,
            "Recovery file found",
            f"An autosaved project from {meta['modified']} was found.\nRestore it?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._open_project(self._recovery_path)
        else:
            self._clear_recovery()

    def _autosave(self) -> None:
        """Autosave modified projects to the recovery file in the background."""
        if not self._model.is_modified():
            return
        if self._project_worker is not None or self._export_worker is not None:
            return
        snapshot = self._model.build_snapshot(self._collect_view_state())
        author = self._model.audit.user_name
        path = self._recovery_path
        worker = FunctionWorker(
            lambda cancel_check, report_progress: recovery.write_recovery(path, snapshot, author),
            self,
        )
        worker.error_occurred.connect(
            lambda message: logger.warning("autosave failed: %s", message)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _clear_recovery(self) -> None:
        try:
            self._recovery_path.unlink(missing_ok=True)
        except OSError as error:
            logger.warning("could not remove recovery file: %s", error)

    # ------------------------------------------------------- status bar info

    def _show_selected_logger_info(self) -> None:
        """Show the selected logger's coordinates (PRD 4.1 status bar)."""
        logger_id = self._model.selected_logger_id()
        layer = self._model.active_layer()
        if logger_id is None or layer is None:
            return
        try:
            selected = self._model.logger_by_id(layer.layer_id, logger_id)
        except KeyError:
            return
        self.statusBar().showMessage(
            f"Logger '{logger_id}' — x {selected.x:.3f} m, y {selected.y:.3f} m, "
            f"z {selected.z:.3f} m",
            5000,
        )

    def _on_generate_report(self) -> None:  # RPT-01
        if self._model.study_results() is None:
            try:
                self._model.run_results_evaluation()
            except Exception as error:  # ResultsError and friends
                self._show_status_message(f"Evaluate results first: {error}")
                return
        default = (self._model.study().title or "study").replace(" ", "_") + "_report.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Generate PDF report", default, "PDF (*.pdf)")
        if not path:
            return
        options = ReportOptions(
            title=self._model.study().title or "Thermal Mapping Study Report",
            author=self._model.audit.user_name,
        )
        worker = FunctionWorker(
            lambda cancel_check, report_progress: report_task(
                self._model, Path(path), options, cancel_check, report_progress
            ),
            self,
        )
        self._run_export_worker(worker, f"Generating {Path(path).name}…")

    def _on_compare(self) -> None:  # CMP-01/02

        CompareDialog(self._model, self).exec()

    def _on_preferences(self) -> None:
        """Preferences: audit user name and theme (AUD-02, VIS-08)."""
        dialog = PreferencesDialog(self._settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, theme_value = dialog.values()
        if name.strip() and name.strip() != self._settings.user_name():
            self._settings.set_user_name(name.strip())
            self._model.audit.set_user_name(name.strip())
        if theme_value != self._settings.theme():
            self._settings.set_theme(theme_value)
            apply_theme(QApplication.instance(), Theme(theme_value))