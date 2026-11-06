"""Observable ProjectModel: single source of state (AGENTS architecture rule).

Widgets subscribe to its Qt signals; they never hold copies of project data.
Every mutation goes through a ``ProjectCommand`` on the undo stack (CFG-08),
and every apply/undo/redo is written to the audit trail (AUD-01, AUD-04).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoStack

from thermavisualizer.core.alignment import (
    AlignedDataset,
    AlignmentOptions,
    AlignmentError,
    align_loggers,
)
from thermavisualizer.core.interpolation import (
    InterpolationError,
    InterpolationSettings,
    build_voxel_grid,
)
from thermavisualizer.core.layout import LayoutIssue, validate_layout
from thermavisualizer.core.models import (
    ImportProfile,
    Layer,
    Logger,
    LoggerMapping,
    Obstacle,
    ParsedFile,
    Quantity,
    Space,
    Study,
    TimelineMode,
)
from thermavisualizer.core.results import (
    AcceptanceCriteria,
    ResultsError,
    StudyPeriod,
    StudyResults,
    evaluate_dataset,
)
from thermavisualizer.core.statistics import AggregationMethod, aggregate_series, moving_average
from thermavisualizer.core.validation import (
    ValidationFinding,
    ValidationOptions,
    ValidationReport,
    validate_files,
)
from thermavisualizer.io.presets import (
    DEFAULT_PRESETS,
    PresetError,
    load_criteria_presets,
    save_criteria_presets,
)
from thermavisualizer.io.profile_store import (
    ProfileStoreError,
    default_profiles_path,
    load_profiles,
    save_profiles,
)
from thermavisualizer.io.project_file import ProjectSnapshot
from thermavisualizer.services.audit import AuditAction, AuditEntry, AuditService
from thermavisualizer.services.cache import InterpolationCache, volume_cache_key
from thermavisualizer.services.undo import ProjectCommand
from thermavisualizer.services.workers import (
    FileLoadResult,
    FunctionWorker,
    InterpolationJob,
    InterpolationResult,
    interpolate_volume_job,
    job_time_key,
    job_time_label,
    load_data_files,
)

logger = logging.getLogger(__name__)


class ProjectModel(QObject):
    """Observable holder of all project state (configuration today; data later)."""

    space_changed = Signal()
    layers_changed = Signal()
    loggers_changed = Signal()
    obstacles_changed = Signal()
    config_changed = Signal()
    audit_entry_added = Signal(object)
    files_changed = Signal()
    mapping_changed = Signal()
    validation_changed = Signal()
    aligned_changed = Signal()
    load_progress_changed = Signal(int)
    active_layer_changed = Signal()
    timeline_changed = Signal()
    timeline_mode_changed = Signal()
    playhead_changed = Signal(object)
    criteria_changed = Signal()
    study_periods_changed = Signal()
    results_changed = Signal()
    logger_selected = Signal()
    obstacle_selected = Signal()
    interpolation_settings_changed = Signal()
    interpolation_progress_changed = Signal(int)
    volume_ready = Signal(object)
    interpolation_failed = Signal(str)
    study_changed = Signal()
    modified_changed = Signal()
    project_loaded = Signal()

    def __init__(
        self,
        user_name: str,
        parent: QObject | None = None,
        profiles_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._space = Space()
        self._audit = AuditService(user_name)
        self._undo_stack = QUndoStack(self)
        self._active_layer_id: str | None = None
        self._selected_logger_id: str | None = None
        self._selected_obstacle_id: str | None = None
        self._profiles_path = (
            profiles_path if profiles_path is not None else default_profiles_path()
        )
        self._import_profiles: dict[str, ImportProfile] = {}
        self._files: dict[str, ParsedFile] = {}
        self._mappings: dict[str, LoggerMapping] = {}
        self._structural_findings: tuple[ValidationFinding, ...] = ()
        self._validation_report = ValidationReport(())
        self._aligned: dict[Quantity, AlignedDataset] = {}

        self._interpolation_settings = InterpolationSettings()
        self._interpolation_cache = InterpolationCache()
        self._interpolation_worker: FunctionWorker | None = None
        self._last_interpolation: dict[str, object] | None = None

        self._timeline_mode = TimelineMode.AGGREGATE
        self._timeline_start: np.datetime64 | None = None
        self._timeline_end: np.datetime64 | None = None
        self._playhead: np.datetime64 | None = None
        self._criteria = AcceptanceCriteria()
        self._criteria_presets_path = self._profiles_path.parent / "criteria_presets.json"
        self._criteria_presets: list[AcceptanceCriteria] = []
        self._study_periods: list[StudyPeriod] = []
        self._study_results: StudyResults | None = None
        self._load_criteria_presets()

        self._current_volumes: dict[Quantity, InterpolationResult] = {}
        self.config_changed.connect(self._invalidate_interpolation_all)
        self.mapping_changed.connect(self._invalidate_volumes)
        self.files_changed.connect(self._invalidate_volumes)
        self._load_profiles()

        self._study = Study()
        self._modified = False
        self._loading = False
        self.config_changed.connect(self._mark_modified)
        self.files_changed.connect(self._mark_modified)
        self.mapping_changed.connect(self._mark_modified)
        self.criteria_changed.connect(self._mark_modified)
        self.interpolation_settings_changed.connect(self._mark_modified)
        self.study_changed.connect(self._mark_modified)

    def _load_profiles(self) -> None:
        try:
            self._import_profiles = load_profiles(self._profiles_path)
        except ProfileStoreError as error:
            logger.warning("import profile store not loaded: %s", error)
            self._import_profiles = {}

    def _load_criteria_presets(self) -> None:
        try:
            self._criteria_presets = load_criteria_presets(self._criteria_presets_path)
        except PresetError as error:
            logger.warning("criteria presets not loaded: %s", error)
            self._criteria_presets = list(DEFAULT_PRESETS)

    # ------------------------------------------------------------ accessors

    @property
    def space(self) -> Space:
        """The configured space (single source of configuration state)."""
        return self._space

    @property
    def audit(self) -> AuditService:
        """The audit trail service."""
        return self._audit

    @property
    def undo_stack(self) -> QUndoStack:
        """The undo stack through which every edit must pass (CFG-08)."""
        return self._undo_stack

    # -------------------------------------------------------------- lookups

    def layer_by_id(self, layer_id: str) -> Layer:
        """Return the layer with ``layer_id`` or raise KeyError."""
        for layer in self._space.layers:
            if layer.layer_id == layer_id:
                return layer
        raise KeyError(f"unknown layer id: {layer_id}")

    def layer_index(self, layer_id: str) -> int:
        """Return the index of the layer with ``layer_id`` or raise KeyError."""
        for index, layer in enumerate(self._space.layers):
            if layer.layer_id == layer_id:
                return index
        raise KeyError(f"unknown layer id: {layer_id}")

    def logger_by_id(self, layer_id: str, logger_id: str) -> Logger:
        """Return the logger with ``logger_id`` in the layer or raise KeyError."""
        for item in self.layer_by_id(layer_id).loggers:
            if item.logger_id == logger_id:
                return item
        raise KeyError(f"unknown logger id: {logger_id}")

    def logger_index(self, layer_id: str, logger_id: str) -> int:
        """Return the index of the logger in its layer or raise KeyError."""
        for index, item in enumerate(self.layer_by_id(layer_id).loggers):
            if item.logger_id == logger_id:
                return index
        raise KeyError(f"unknown logger id: {logger_id}")

    def obstacle_by_id(self, obstacle_id: str) -> Obstacle:
        """Return the obstacle with ``obstacle_id`` or raise KeyError."""
        for obstacle in self._space.obstacles:
            if obstacle.obstacle_id == obstacle_id:
                return obstacle
        raise KeyError(f"unknown obstacle id: {obstacle_id}")

    def obstacle_index(self, obstacle_id: str) -> int:
        """Return the index of the obstacle or raise KeyError."""
        for index, obstacle in enumerate(self._space.obstacles):
            if obstacle.obstacle_id == obstacle_id:
                return index
        raise KeyError(f"unknown obstacle id: {obstacle_id}")

    # ---------------------------------------------------------------- edits

    def apply(self, command: ProjectCommand) -> None:
        """Execute ``command`` via the undo stack and audit it (CFG-08, AUD-03)."""
        if not isinstance(command, ProjectCommand):
            raise TypeError("configuration edits must use ProjectCommand subclasses")
        self._undo_stack.push(command)  # calls redo()
        entry = self._audit.record(command.audit_action(), command.audit_target(), command.text())
        self.audit_entry_added.emit(entry)
        logger.info("applied: %s", command.text())

    def undo(self) -> None:
        """Undo the last command and audit the undo itself (AUD-04)."""
        if not self._undo_stack.canUndo():
            return
        text = self._undo_stack.undoText()
        self._undo_stack.undo()
        entry = self._audit.record(AuditAction.UNDO, "project", f"Undo: {text}")
        self.audit_entry_added.emit(entry)
        logger.info("undo: %s", text)

    def redo(self) -> None:
        """Redo the last undone command and audit it (AUD-04)."""
        if not self._undo_stack.canRedo():
            return
        text = self._undo_stack.redoText()
        self._undo_stack.redo()
        entry = self._audit.record(AuditAction.REDO, "project", f"Redo: {text}")
        self.audit_entry_added.emit(entry)
        logger.info("redo: %s", text)

    def layout_issues(self) -> list[LayoutIssue]:
        """Validate the current layout (CFG-11)."""
        return validate_layout(self._space)

    # -------------------------------------------------------- notifications

    def notify_space_changed(self) -> None:
        """Emit signals after a space property edit (called by commands)."""
        self.space_changed.emit()
        self.config_changed.emit()

    def notify_layers_changed(self) -> None:
        """Emit signals after the layer list or layer fields changed."""
        self.layers_changed.emit()
        self.config_changed.emit()

    def notify_loggers_changed(self) -> None:
        """Emit signals after logger geometry changed."""
        self.loggers_changed.emit()
        self.config_changed.emit()

    def notify_obstacles_changed(self) -> None:
        """Emit signals after the obstacle list or obstacle fields changed."""
        self.obstacles_changed.emit()
        self.config_changed.emit()

    # ------------------------------------------------------------ view state

    def active_layer_id(self) -> str | None:
        """Active layer id, or None when unset or the layer no longer exists."""
        if self._active_layer_id is None:
            return None
        if any(layer.layer_id == self._active_layer_id for layer in self._space.layers):
            return self._active_layer_id
        return None

    def set_active_layer(self, layer_id: str | None) -> None:
        """Activate a layer (or none). Raises KeyError for unknown ids."""
        if layer_id == self._active_layer_id:
            return
        if layer_id is not None:
            self.layer_by_id(layer_id)
        self._active_layer_id = layer_id
        self.active_layer_changed.emit()

    def active_layer(self) -> Layer | None:
        """The active layer, or None."""
        layer_id = self.active_layer_id()
        return None if layer_id is None else self.layer_by_id(layer_id)

    def selected_logger_id(self) -> str | None:
        """Selected logger id within the active layer, or None."""
        if self._selected_logger_id is None:
            return None
        layer = self.active_layer()
        if layer is not None and any(
            item.logger_id == self._selected_logger_id for item in layer.loggers
        ):
            return self._selected_logger_id
        return None

    def select_logger(self, logger_id: str | None) -> None:
        """Select a logger of the active layer, or clear the selection."""
        if logger_id == self._selected_logger_id:
            return
        if logger_id is not None:
            layer = self.active_layer()
            if layer is None or not any(item.logger_id == logger_id for item in layer.loggers):
                raise KeyError(f"logger not in active layer: {logger_id}")
        self._selected_logger_id = logger_id
        self.logger_selected.emit()

    def selected_obstacle_id(self) -> str | None:
        """Selected obstacle id, or None when it no longer exists."""
        if self._selected_obstacle_id is None:
            return None
        if any(
            obstacle.obstacle_id == self._selected_obstacle_id for obstacle in self._space.obstacles
        ):
            return self._selected_obstacle_id
        return None

    def select_obstacle(self, obstacle_id: str | None) -> None:
        """Select an obstacle, or clear the selection."""
        if obstacle_id == self._selected_obstacle_id:
            return
        if obstacle_id is not None:
            self.obstacle_by_id(obstacle_id)
        self._selected_obstacle_id = obstacle_id
        self.obstacle_selected.emit()

    def note(self, action: AuditAction, target: str, summary: str, comment: str = "") -> AuditEntry:
        """Record a non-command event (imports/exports) in the audit trail (AUD-03)."""
        entry = self._audit.record(action, target, summary, comment)
        self.audit_entry_added.emit(entry)
        logger.info("audit: %s %s", str(action), summary)
        return entry

    def timeline_mode(self) -> TimelineMode:
        """Aggregate-over-range vs instant-at-playhead display mode (PRD 4.4)."""
        return self._timeline_mode

    def set_timeline_mode(self, mode: TimelineMode) -> None:
        """Switch the timeline display mode."""
        if mode is self._timeline_mode:
            return
        self._timeline_mode = mode
        self.timeline_mode_changed.emit()

    # ------------------------------------------------------------- profiles

    def import_profiles(self) -> dict[str, ImportProfile]:
        """Saved import profiles keyed by name (DAT-01)."""
        return dict(self._import_profiles)

    def save_profile(self, profile: ImportProfile) -> None:
        """Add or replace a profile and persist the store (DAT-01)."""
        self._import_profiles[profile.name] = profile
        save_profiles(self._profiles_path, self._import_profiles)
        logger.info("import profile saved: %s", profile.name)

    def remove_profile(self, name: str) -> None:
        """Remove a profile from the store (DAT-01)."""
        if self._import_profiles.pop(name, None) is not None:
            save_profiles(self._profiles_path, self._import_profiles)

    # ---------------------------------------------------------------- files

    def files(self) -> list[ParsedFile]:
        """Loaded raw data files (immutable arrays)."""
        return list(self._files.values())

    def file_by_path(self, path: str) -> ParsedFile | None:
        """Return the loaded file with this path, or None."""
        return self._files.get(path)

    def load_files_async(self, jobs: Sequence[tuple[Path, ImportProfile]]) -> FunctionWorker:
        """Load data files in a background worker (AGENTS §4). Returns the worker."""
        worker = FunctionWorker(
            lambda cancel_check, report_progress: load_data_files(
                jobs, cancel_check, report_progress
            ),
            self,
        )
        worker.progress_changed.connect(self.load_progress_changed)
        worker.result_ready.connect(self._on_load_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        return worker

    def _on_load_finished(self, results: object) -> None:
        self.ingest_load_results(list(results))  # type: ignore[arg-type]

    def ingest_load_results(self, results: Sequence[FileLoadResult]) -> None:
        """Merge worker load results: files, structural findings, audit (AUD-03)."""
        for result in results:
            self._structural_findings = (
                tuple(f for f in self._structural_findings if f.file != Path(result.path).name)
                + result.report.findings
            )
            if result.parsed is not None:
                self._files[result.parsed.path] = result.parsed
                self.note(
                    AuditAction.FILE_IMPORTED,
                    f"file:{result.parsed.name}",
                    f"Data file loaded: {result.parsed.row_count} row(s), "
                    f"{len(result.parsed.columns)} column(s)",
                )
        if results:
            self._invalidate_aligned()
            self.files_changed.emit()
            self._refresh_validation_from_structural()

    def remove_file(self, path: str) -> None:
        """Remove a loaded file and every mapping that references it."""
        if self._files.pop(path, None) is None:
            return
        file_name = Path(path).name
        self._structural_findings = tuple(
            f for f in self._structural_findings if f.file != file_name
        )
        mapping_changed = False
        for logger_id, mapping in list(self._mappings.items()):
            if mapping.temperature_file == path or mapping.humidity_file == path:
                del self._mappings[logger_id]
                mapping_changed = True
        self._invalidate_aligned()
        self.files_changed.emit()
        self._refresh_validation_from_structural()
        if mapping_changed:
            self.mapping_changed.emit()

    # -------------------------------------------------------------- mapping

    def mappings(self) -> list[LoggerMapping]:
        """All stored logger mappings."""
        return list(self._mappings.values())

    def mapping_for(self, logger_id: str) -> LoggerMapping | None:
        """Mapping of one logger, or None."""
        return self._mappings.get(logger_id)

    def set_mapping(self, mapping: LoggerMapping, summary: str = "") -> None:
        """Set one logger's mapping and audit it (DAT-03, AUD-03)."""
        self._mappings[mapping.logger_id] = mapping
        self._invalidate_aligned()
        self.mapping_changed.emit()
        state = (
            "excluded" if mapping.excluded else "mapped" if mapping.is_satisfied() else "unmapped"
        )
        self.note(
            AuditAction.MAPPING_CHANGED,
            f"logger:{mapping.logger_id}",
            summary or f"Mapping set to {state}",
        )

    def set_mappings(
        self, mappings: Sequence[LoggerMapping], summary: str = "Mapping updated"
    ) -> None:
        """Bulk mapping update as one audited step (mapping UI, auto-suggest)."""
        for mapping in mappings:
            self._mappings[mapping.logger_id] = mapping
        if mappings:
            self._invalidate_aligned()
            self.mapping_changed.emit()
            self.note(
                AuditAction.MAPPING_CHANGED,
                "mapping",
                f"{summary} ({len(mappings)} logger(s))",
            )

    def all_logger_ids(self) -> list[str]:
        """Every configured logger ID in layout order."""
        return [logger.logger_id for layer in self._space.layers for logger in layer.loggers]

    def unmapped_logger_ids(self) -> list[str]:
        """Loggers neither mapped nor excluded — the DAT-03 gate."""
        return [
            logger_id
            for logger_id in self.all_logger_ids()
            if (mapping := self._mappings.get(logger_id)) is None or not mapping.is_satisfied()
        ]

    def mapping_complete(self) -> bool:
        """True when at least one logger exists and all are satisfied (DAT-03)."""
        return bool(self.all_logger_ids()) and not self.unmapped_logger_ids()

    # ----------------------------------------------------------- validation

    @property
    def validation_report(self) -> ValidationReport:
        """Latest combined validation report (structural + mapping-based)."""
        return self._validation_report

    def run_validation(self, options: ValidationOptions | None = None) -> ValidationReport:
        """Re-validate loaded files against current mappings (VAL, AUD-03)."""
        base = validate_files(
            list(self._files.values()),
            list(self._mappings.values()),
            options or ValidationOptions(),
        )
        self._validation_report = ValidationReport(self._structural_findings + base.findings)
        self.validation_changed.emit()
        self.note(
            AuditAction.VALIDATION_RUN,
            "validation",
            f"Validation run: {len(self._validation_report.errors())} error(s), "
            f"{len(self._validation_report.warnings())} warning(s)",
        )
        return self._validation_report

    def _refresh_validation_from_structural(self) -> None:
        self._validation_report = ValidationReport(
            self._structural_findings
            + tuple(
                f for f in self._validation_report.findings if f not in self._structural_findings
            )
        )
        self.validation_changed.emit()

    # ------------------------------------------------------------ alignment

    def aligned_dataset(self, quantity: Quantity) -> AlignedDataset | None:
        """Latest aligned dataset for the quantity, if computed."""
        return self._aligned.get(quantity)

    def align(
        self,
        quantity: Quantity = Quantity.TEMPERATURE,
        options: AlignmentOptions | None = None,
    ) -> AlignedDataset:
        """Align mapped loggers and cache the result (DAT-06/07, AUD-03).

        Convenience: aligning one quantity also aligns the other when it is
        mapped but not yet aligned, so plots can show humidity without an
        extra manual step (or a 3D compute).
        """
        dataset = self._align_quantity(quantity, options)
        self._store_aligned(quantity, dataset)
        other = (
            Quantity.HUMIDITY if quantity is Quantity.TEMPERATURE else Quantity.TEMPERATURE
        )
        if other not in self._aligned and self._has_mappings_for(other):
            try:
                other_dataset = self._align_quantity(other, options)
            except AlignmentError as error:
                logger.warning("auto-alignment skipped for %s: %s", other.value, error)
            else:
                self._store_aligned(other, other_dataset)
        self.aligned_changed.emit()
        return dataset

    def _align_quantity(self, quantity: Quantity, options: AlignmentOptions | None) -> AlignedDataset:
        return align_loggers(
            list(self._files.values()),
            list(self._mappings.values()),
            quantity,
            options or AlignmentOptions(),
        )

    def _store_aligned(self, quantity: Quantity, dataset: AlignedDataset) -> None:
        self._aligned[quantity] = dataset
        self.note(
            AuditAction.PROCESSING_CHANGED, "alignment",
            f"Aligned {len(dataset.logger_ids)} logger(s) for {quantity.value} "
            f"({dataset.method.value})",
        )

    def _has_mappings_for(self, quantity: Quantity) -> bool:
        if quantity is Quantity.TEMPERATURE:
            return any(m.has_temperature() for m in self._mappings.values())
        return any(m.has_humidity() for m in self._mappings.values())

    def _invalidate_aligned(self) -> None:
        if self._aligned:
            self._aligned.clear()
            self.aligned_changed.emit()

    # ------------------------------------------------- interpolation state

    def interpolation_settings(self) -> InterpolationSettings:
        """Current interpolation/voxel settings (INT-01/02)."""
        return self._interpolation_settings

    def set_interpolation_settings(self, settings: InterpolationSettings) -> None:
        """Replace settings, drop all caches, and audit the change (AUD-03)."""
        if settings == self._interpolation_settings:
            return
        self._interpolation_settings = settings
        self._invalidate_interpolation_all()
        self.interpolation_settings_changed.emit()
        self.note(
            AuditAction.PROCESSING_CHANGED,
            "interpolation",
            f"Interpolation settings changed: method={settings.method.value}, "
            f"resolution={settings.resolution} m, "
            f"extrapolation={settings.extrapolation.value}",
        )

    def current_volume(self, quantity: Quantity) -> InterpolationResult | None:
        """Latest interpolation result for the quantity, if any."""
        return self._current_volumes.get(quantity)

    def cancel_interpolation(self) -> None:
        """Cancel the running interpolation worker, if any (INT-07)."""
        if self._interpolation_worker is not None:
            self._interpolation_worker.cancel()

    def current_logger_values(self, quantity: Quantity) -> np.ndarray | None:
        """Per-logger values matching the last interpolation request (VIS-03)."""
        params = self._last_interpolation
        dataset = self._aligned.get(quantity)
        if params is None or dataset is None or params["quantity"] is not quantity:
            return None
        series = dataset.values
        window = int(params["temporal_window"])  # type: ignore[arg-type]
        if window > 1:
            series = moving_average(series, window)
        if params["aggregation"] is AggregationMethod.INSTANT:
            return np.asarray(series[int(params["time_index"])], dtype=float)  # type: ignore[index]
        block = series[int(params["range_start"]) : int(params["range_end"]) + 1]  # type: ignore[index]
        return np.asarray(aggregate_series(block, params["aggregation"]), dtype=float)

    def interpolate_async(
        self,
        quantity: Quantity = Quantity.TEMPERATURE,
        aggregation: AggregationMethod = AggregationMethod.INSTANT,
        time_index: int = 0,
        range_start: int = 0,
        range_end: int | None = None,
        temporal_window: int = 1,
    ) -> FunctionWorker | None:
        """Interpolate the aligned quantity in a background worker (INT-07).

        Returns the worker, or None when the volume was served from the cache
        (``volume_ready`` is emitted either way). Raises InterpolationError /
        AlignmentError for missing prerequisites.
        """
        job = self._build_interpolation_job(
            quantity, aggregation, time_index, range_start, range_end
        )
        grid = build_voxel_grid(job.space, job.settings.resolution)
        key = volume_cache_key(
            job.quantity,
            job.settings,
            job.positions,
            grid,
            job.aggregation,
            job_time_key(job),
        )
        self._last_interpolation = {
            "quantity": quantity,
            "aggregation": aggregation,
            "time_index": job.time_index,
            "range_start": job.range_start,
            "range_end": job.range_end,
            "temporal_window": job.temporal_window,
        }
        hit = self._interpolation_cache.get_volume(key)
        if hit is not None:
            result = InterpolationResult(
                hit,
                quantity,
                job.settings,
                aggregation,
                job_time_label(job),
                key,
                True,
                positions=job.positions,
                logger_ids=job.logger_ids,
            )
            self._current_volumes[quantity] = result
            self.volume_ready.emit(result)
            return None
        self.cancel_interpolation()
        worker = FunctionWorker(
            lambda cancel_check, report_progress: interpolate_volume_job(
                job, cancel_check, report_progress, self._interpolation_cache
            ),
            self,
        )
        worker.progress_changed.connect(self.interpolation_progress_changed)
        worker.result_ready.connect(self._on_interpolation_finished)
        worker.error_occurred.connect(self._on_interpolation_failed)
        worker.finished.connect(worker.deleteLater)
        self._interpolation_worker = worker
        worker.start()
        return worker

    def _build_interpolation_job(
        self,
        quantity: Quantity,
        aggregation: AggregationMethod,
        time_index: int,
        range_start: int,
        range_end: int | None,
        temporal_window: int = 1,
    ) -> InterpolationJob:
        dataset = self._aligned.get(quantity)
        if dataset is None:
            dataset = self.align(quantity)
        count = dataset.times.size
        if count == 0 or dataset.values.shape[1] == 0:
            raise InterpolationError("aligned dataset is empty")
        end = count - 1 if range_end is None else range_end
        if aggregation is AggregationMethod.INSTANT:
            if not 0 <= time_index < count:
                raise InterpolationError(f"time index {time_index} out of range (0..{count - 1})")
        elif not 0 <= range_start <= end < count:
            raise InterpolationError("aggregation range out of bounds")
        return InterpolationJob(
            space=self._space,
            obstacles=tuple(self._space.obstacles),
            positions=self._positions_for(dataset.logger_ids),
            times=dataset.times,
            values=dataset.values,
            settings=self._interpolation_settings,
            quantity=quantity,
            aggregation=aggregation,
            time_index=time_index,
            range_start=range_start,
            range_end=end,
            logger_ids=dataset.logger_ids,
            temporal_window=temporal_window,
        )

    def _positions_for(self, logger_ids: tuple[str, ...]) -> np.ndarray:
        lookup = {
            logger.logger_id: (logger.x, logger.y, logger.z)
            for layer in self._space.layers
            for logger in layer.loggers
        }
        try:
            positions = [lookup[logger_id] for logger_id in logger_ids]
        except KeyError as error:
            raise InterpolationError(f"logger {error} is missing from the layout") from error
        return np.asarray(positions, dtype=float)

    def _on_interpolation_finished(self, result: object) -> None:
        if self.sender() is not self._interpolation_worker:
            return  # stale worker superseded by a newer request
        self._interpolation_worker = None
        if result is None:  # cancelled between phases
            return
        assert isinstance(result, InterpolationResult)
        self._current_volumes[result.quantity] = result
        self.volume_ready.emit(result)

    def _on_interpolation_failed(self, message: str) -> None:
        if self.sender() is not self._interpolation_worker:
            return
        self._interpolation_worker = None
        logger.error("interpolation failed: %s", message)
        self.interpolation_failed.emit(message)

    def _invalidate_volumes(self) -> None:
        self._interpolation_cache.clear_volumes()
        self._current_volumes.clear()

    def _invalidate_interpolation_all(self) -> None:
        self._interpolation_cache.clear()
        self._current_volumes.clear()

    # ------------------------------------------------ timeline & playhead

    def timeline_range(self) -> tuple[np.datetime64 | None, np.datetime64 | None]:
        """Current timeline selection (start, end); (None, None) = full range."""
        return self._timeline_start, self._timeline_end

    def set_timeline_range(self, start: np.datetime64 | None, end: np.datetime64 | None) -> None:
        """Set the timeline selection; invalidates derived results."""
        if start == self._timeline_start and end == self._timeline_end:
            return
        self._timeline_start = start
        self._timeline_end = end
        self.timeline_changed.emit()
        self._invalidate_results()

    def playhead(self) -> np.datetime64 | None:
        """Current animation playhead time (EXP-01 ground)."""
        return self._playhead

    def set_playhead(self, time: np.datetime64 | None) -> None:
        """Move the animation playhead."""
        if time == self._playhead:
            return
        self._playhead = time
        self.playhead_changed.emit(time)

    # ----------------------------------------------- criteria & results

    def criteria(self) -> AcceptanceCriteria:
        """Current acceptance criteria (RES-01)."""
        return self._criteria

    def set_criteria(self, criteria: AcceptanceCriteria) -> None:
        """Set criteria, audit it, and invalidate derived results (AUD-03)."""
        if criteria == self._criteria:
            return
        self._criteria = criteria
        self.criteria_changed.emit()
        self._invalidate_results()
        self.note(
            AuditAction.CRITERIA_CHANGED,
            "criteria",
            f"Criteria set to '{criteria.name}' "
            f"({criteria.temperature_min} to {criteria.temperature_max} °C)",
        )

    def criteria_presets(self) -> list[AcceptanceCriteria]:
        """Saved criteria presets (RES-01 JSON store)."""
        return list(self._criteria_presets)

    def save_criteria_preset(self, criteria: AcceptanceCriteria) -> None:
        """Save or replace a criteria preset; persists to disk."""
        presets = [p for p in self._criteria_presets if p.name != criteria.name]
        presets.append(criteria)
        save_criteria_presets(self._criteria_presets_path, presets)
        self._criteria_presets = presets
        self.criteria_changed.emit()

    def study_periods(self) -> list[StudyPeriod]:
        """Named study periods for targeted evaluation (RES-02)."""
        return list(self._study_periods)

    def add_study_period(self, period: StudyPeriod) -> None:
        """Add a named study period and audit it."""
        self._study_periods.append(period)
        self.study_periods_changed.emit()
        self.note(
            AuditAction.CRITERIA_CHANGED,
            f"period:{period.name}",
            f"Study period '{period.name}' added ({period.start} → {period.end})",
        )

    def remove_study_period(self, name: str) -> None:
        """Remove a named study period."""
        before = len(self._study_periods)
        self._study_periods = [p for p in self._study_periods if p.name != name]
        if len(self._study_periods) != before:
            self.study_periods_changed.emit()

    def study_results(self) -> StudyResults | None:
        """Latest evaluated study results, if any (RES-08)."""
        return self._study_results

    def run_results_evaluation(self, quantity: Quantity = Quantity.TEMPERATURE) -> StudyResults:
        """Evaluate criteria over the current timeline range (RES-02, AUD-03)."""
        dataset = self._aligned.get(quantity)
        if dataset is None:
            raise ResultsError(f"no aligned dataset for {quantity.value}")
        results = evaluate_dataset(
            dataset.times,
            dataset.logger_ids,
            dataset.values,
            self._criteria,
            quantity,
            self._timeline_start,
            self._timeline_end,
        )
        self._study_results = results
        self.results_changed.emit()
        self.note(
            AuditAction.RESULTS_EVALUATED,
            "results",
            f"Results evaluated for {quantity.value}: "
            f"{'PASS' if results.overall.passed else 'FAIL'} "
            f"({len(results.excursions)} excursion(s))",
        )
        return results

    def _invalidate_results(self) -> None:
        """Drop cached results when inputs (timeline, criteria) change."""
        if self._study_results is not None:
            self._study_results = None
            self.results_changed.emit()

    def logger_positions(self, logger_ids: Sequence[str]) -> np.ndarray:
        """Layout positions (x, y, z) in metres for the given logger IDs."""
        return self._positions_for(tuple(logger_ids))

    # ---------------------------------------------------------------- study

    def study(self) -> Study:
        """Study metadata (STY-01)."""
        return self._study

    def set_study(self, study: Study) -> None:
        """Update study metadata and audit it (STY-01, AUD-03)."""
        if study == self._study:
            return
        self._study = study
        self.study_changed.emit()
        self.note(
            AuditAction.STUDY_CHANGED,
            "study",
            f"Study metadata updated: '{study.title or 'untitled'}'",
        )

    # ----------------------------------------------------- modified tracking

    def is_modified(self) -> bool:
        """True when unsaved changes exist."""
        return self._modified

    def mark_saved(self) -> None:
        """Clear the modified flag after a successful save/load."""
        if self._modified:
            self._modified = False
            self.modified_changed.emit()

    def _mark_modified(self) -> None:
        if not self._loading and not self._modified:
            self._modified = True
            self.modified_changed.emit()

    # ---------------------------------------------------- snapshot lifecycle

    def build_snapshot(self, view_state: dict) -> ProjectSnapshot:
        """Collect the full project state for saving (EXP-05)."""
        return ProjectSnapshot(
            space=self._space,
            study=self._study,
            criteria=self._criteria,
            study_periods=tuple(self._study_periods),
            mappings=tuple(self._mappings.values()),
            import_profiles=tuple(self._import_profiles.values()),
            raw_files=tuple(self._files.values()),
            aligned=tuple(self._aligned.items()),
            interpolation_settings=self._interpolation_settings,
            view_state=view_state,
            validation_findings=self._validation_report.findings,
            results=self._study_results,
            audit_jsonl=self._audit.to_jsonl(),
        )

    def load_snapshot(self, snapshot: ProjectSnapshot) -> None:
        """Replace the entire project state (EXP-05). View state is applied by the UI."""
        self._loading = True
        try:
            self._undo_stack.clear()
            self._space = snapshot.space
            self._study = snapshot.study
            self._criteria = snapshot.criteria
            self._study_periods = list(snapshot.study_periods)
            self._mappings = {m.logger_id: m for m in snapshot.mappings}
            self._import_profiles = {p.name: p for p in snapshot.import_profiles}
            self._files = {f.path: f for f in snapshot.raw_files}
            self._aligned = dict(snapshot.aligned)
            self._interpolation_settings = snapshot.interpolation_settings
            self._structural_findings = ()
            self._validation_report = ValidationReport(snapshot.validation_findings)
            self._study_results = snapshot.results
            try:
                self._audit = AuditService.from_jsonl(snapshot.audit_jsonl, self._audit.user_name)
            except (ValueError, KeyError, TypeError) as error:
                logger.warning("audit trail not restored (%s); starting fresh", error)
                self._audit = AuditService(self._audit.user_name)
            self._timeline_start = None
            self._timeline_end = None
            self._playhead = None
            self._timeline_mode = TimelineMode.AGGREGATE
            self._interpolation_cache.clear()
            self._current_volumes.clear()
            self._last_interpolation = None
        finally:
            self._loading = False
        self.config_changed.emit()
        self.files_changed.emit()
        self.mapping_changed.emit()
        self.criteria_changed.emit()
        self.study_changed.emit()
        self.aligned_changed.emit()
        self.validation_changed.emit()
        self.results_changed.emit()
        self.interpolation_settings_changed.emit()
        self.active_layer_changed.emit()
        self._modified = False
        self.modified_changed.emit()
        self.project_loaded.emit()

    def reset_project(self) -> None:
        """Start a fresh empty project and audit it (AUD-03 project create)."""
        user = self._audit.user_name
        self._loading = True
        try:
            self._undo_stack.clear()
            self._space = Space()
            self._study = Study()
            self._criteria = AcceptanceCriteria()
            self._study_periods = []
            self._mappings = {}
            self._files = {}
            self._aligned = {}
            self._interpolation_settings = InterpolationSettings()
            self._structural_findings = ()
            self._validation_report = ValidationReport(())
            self._study_results = None
            self._audit = AuditService(user)
            self._timeline_start = None
            self._timeline_end = None
            self._playhead = None
            self._timeline_mode = TimelineMode.AGGREGATE
            self._active_layer_id = None
            self._selected_logger_id = None
            self._selected_obstacle_id = None
            self._interpolation_cache.clear()
            self._current_volumes.clear()
            self._last_interpolation = None
        finally:
            self._loading = False
        self.config_changed.emit()
        self.files_changed.emit()
        self.mapping_changed.emit()
        self.criteria_changed.emit()
        self.study_changed.emit()
        self.aligned_changed.emit()
        self.validation_changed.emit()
        self.results_changed.emit()
        self.interpolation_settings_changed.emit()
        self.active_layer_changed.emit()
        self._modified = False
        self.modified_changed.emit()
        self.note(AuditAction.PROJECT_CREATE, "project", "New project created")
        self.project_loaded.emit()
