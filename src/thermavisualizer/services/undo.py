"""QUndoCommand implementations for all configuration edits (CFG-08, BLK-06).

Every command mutates the ``ProjectModel`` state in ``redo`` and restores it
exactly in ``undo``. Bulk operations are single commands so they undo as one
step (BLK-06). Construct commands immediately before ``ProjectModel.apply``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QUndoCommand

from thermavisualizer.core.models import Layer, Logger, Obstacle
from thermavisualizer.services.audit import AuditAction

if TYPE_CHECKING:
    from thermavisualizer.services.project_model import ProjectModel

_SPACE_PROPERTY_KEYS = frozenset({"name", "space_type", "height", "length_unit", "footprint"})


class ProjectCommand(QUndoCommand):
    """Base class for model commands carrying audit metadata."""

    def __init__(self, model: ProjectModel, text: str, action: AuditAction, target: str) -> None:
        super().__init__(text)
        self._model = model
        self._action = action
        self._target = target

    def audit_action(self) -> AuditAction:
        """Audit action type for this edit (AUD-03)."""
        return self._action

    def audit_target(self) -> str:
        """Audit target descriptor, e.g. ``layer:low``."""
        return self._target


# ------------------------------------------------------------------- layers


class AddLayerCommand(ProjectCommand):
    """Add a layer at an index (default: end) — CFG-02."""

    def __init__(self, model: ProjectModel, layer: Layer, index: int | None = None) -> None:
        super().__init__(
            model,
            f"Add layer '{layer.name}' at {layer.height:.3f} m",
            AuditAction.LAYER_ADDED,
            f"layer:{layer.name}",
        )
        self._layer = layer
        self._index = index

    def redo(self) -> None:
        layers = self._model.space.layers
        index = len(layers) if self._index is None else self._index
        self._index = index
        layers.insert(index, self._layer)
        self._model.set_active_layer(self._layer.layer_id)
        self._model.notify_layers_changed()

    def undo(self) -> None:
        self._model.space.layers.pop(self._index)
        layers = self._model.space.layers
        self._model.set_active_layer(layers[-1].layer_id if layers else None)
        self._model.notify_layers_changed()


class RemoveLayerCommand(ProjectCommand):
    """Remove a layer by id; undo restores it at the same position — CFG-02."""

    def __init__(self, model: ProjectModel, layer_id: str) -> None:
        layer = model.layer_by_id(layer_id)
        super().__init__(
            model,
            f"Remove layer '{layer.name}'",
            AuditAction.LAYER_REMOVED,
            f"layer:{layer.name}",
        )
        self._layer_id = layer_id
        self._layer: Layer | None = None
        self._index = -1

    def redo(self) -> None:
        layers = self._model.space.layers
        self._index = self._model.layer_index(self._layer_id)
        was_active = self._model.active_layer_id() == self._layer_id
        self._layer = layers.pop(self._index)
        if was_active:
            fallback: str | None = None
            if self._index < len(layers):
                fallback = layers[self._index].layer_id
            elif layers:
                fallback = layers[-1].layer_id
            self._model.set_active_layer(fallback)
        self._model.notify_layers_changed()

    def undo(self) -> None:
        assert self._layer is not None
        self._model.space.layers.insert(self._index, self._layer)
        self._model.set_active_layer(self._layer.layer_id)
        self._model.notify_layers_changed()


class RenameLayerCommand(ProjectCommand):
    """Rename a layer — CFG-02."""

    def __init__(self, model: ProjectModel, layer_id: str, new_name: str) -> None:
        if not new_name.strip():
            raise ValueError("layer name must not be empty")
        super().__init__(
            model,
            f"Rename layer to '{new_name}'",
            AuditAction.LAYER_CHANGED,
            f"layer:{new_name}",
        )
        self._layer_id = layer_id
        self._new_name = new_name
        self._old_name: str | None = None

    def redo(self) -> None:
        layer = self._model.layer_by_id(self._layer_id)
        if self._old_name is None:
            self._old_name = layer.name
        layer.name = self._new_name
        self._model.notify_layers_changed()

    def undo(self) -> None:
        assert self._old_name is not None
        layer = self._model.layer_by_id(self._layer_id)
        layer.name = self._old_name
        self._model.notify_layers_changed()


class MoveLayerCommand(ProjectCommand):
    """Reorder layers — CFG-02."""

    def __init__(self, model: ProjectModel, from_index: int, to_index: int) -> None:
        count = len(model.space.layers)
        if not 0 <= from_index < count or not 0 <= to_index < count:
            raise ValueError(
                f"layer indices out of range: {from_index} -> {to_index} (count {count})"
            )
        layer = model.space.layers[from_index]
        super().__init__(
            model,
            f"Move layer '{layer.name}' from position {from_index + 1} to {to_index + 1}",
            AuditAction.LAYER_CHANGED,
            f"layer:{layer.name}",
        )
        self._from = from_index
        self._to = to_index

    def redo(self) -> None:
        layers = self._model.space.layers
        layers.insert(self._to, layers.pop(self._from))
        self._model.notify_layers_changed()

    def undo(self) -> None:
        layers = self._model.space.layers
        layers.insert(self._from, layers.pop(self._to))
        self._model.notify_layers_changed()


class SetLayerCompletedCommand(ProjectCommand):
    """Mark a layer completed or reopen it — CFG-04."""

    def __init__(self, model: ProjectModel, layer_id: str, completed: bool) -> None:
        layer = model.layer_by_id(layer_id)
        verb = "Complete" if completed else "Reopen"
        super().__init__(
            model,
            f"{verb} layer '{layer.name}'",
            AuditAction.LAYER_CHANGED,
            f"layer:{layer.name}",
        )
        self._layer_id = layer_id
        self._completed = completed
        self._previous: bool | None = None

    def redo(self) -> None:
        layer = self._model.layer_by_id(self._layer_id)
        if self._previous is None:
            self._previous = layer.completed
        layer.completed = self._completed
        self._model.notify_layers_changed()

    def undo(self) -> None:
        assert self._previous is not None
        layer = self._model.layer_by_id(self._layer_id)
        layer.completed = self._previous
        self._model.notify_layers_changed()


class SetLayerHeightCommand(ProjectCommand):
    """Change a layer's height in metres (CFG-02)."""

    def __init__(self, model: ProjectModel, layer_id: str, height: float) -> None:
        layer = model.layer_by_id(layer_id)
        super().__init__(
            model,
            f"Set layer '{layer.name}' height to {height:.3f} m",
            AuditAction.LAYER_CHANGED,
            f"layer:{layer.name}",
        )
        self._layer_id = layer_id
        self._height = height
        self._previous: float | None = None

    def redo(self) -> None:
        layer = self._model.layer_by_id(self._layer_id)
        if self._previous is None:
            self._previous = layer.height
        layer.height = self._height
        self._model.notify_layers_changed()

    def undo(self) -> None:
        assert self._previous is not None
        layer = self._model.layer_by_id(self._layer_id)
        layer.height = self._previous
        self._model.notify_layers_changed()


# ------------------------------------------------------------------ loggers


class AddLoggersCommand(ProjectCommand):
    """Add loggers to a layer as one undoable step (BLK-06)."""

    def __init__(self, model: ProjectModel, layer_id: str, loggers: Sequence[Logger]) -> None:
        if not loggers:
            raise ValueError("cannot add zero loggers")
        layer = model.layer_by_id(layer_id)
        count = len(loggers)
        super().__init__(
            model,
            f"Add {count} logger(s) to layer '{layer.name}'",
            AuditAction.LOGGER_ADDED,
            f"layer:{layer.name}",
        )
        self._layer_id = layer_id
        self._loggers = list(loggers)

    def redo(self) -> None:
        layer = self._model.layer_by_id(self._layer_id)
        layer.loggers.extend(self._loggers)
        self._model.notify_loggers_changed()

    def undo(self) -> None:
        layer = self._model.layer_by_id(self._layer_id)
        ids = {item.logger_id for item in self._loggers}
        layer.loggers = [item for item in layer.loggers if item.logger_id not in ids]
        self._model.notify_loggers_changed()


class RemoveLoggersCommand(ProjectCommand):
    """Remove loggers by id as one undoable step; order is restored (BLK-06)."""

    def __init__(self, model: ProjectModel, layer_id: str, logger_ids: Sequence[str]) -> None:
        if not logger_ids:
            raise ValueError("cannot remove zero loggers")
        layer = model.layer_by_id(layer_id)
        super().__init__(
            model,
            f"Remove {len(logger_ids)} logger(s) from layer '{layer.name}'",
            AuditAction.LOGGER_REMOVED,
            f"layer:{layer.name}",
        )
        self._layer_id = layer_id
        self._ids = frozenset(logger_ids)
        self._removed: list[tuple[int, Logger]] = []

    def redo(self) -> None:
        layer = self._model.layer_by_id(self._layer_id)
        removed: list[tuple[int, Logger]] = []
        for index, item in enumerate(layer.loggers):
            if item.logger_id in self._ids:
                removed.append((index, item))
        for index, _ in reversed(removed):
            layer.loggers.pop(index)
        self._removed = removed
        self._model.notify_loggers_changed()

    def undo(self) -> None:
        layer = self._model.layer_by_id(self._layer_id)
        for index, item in self._removed:
            layer.loggers.insert(index, item)
        self._model.notify_loggers_changed()


class UpdateLoggerCommand(ProjectCommand):
    """Replace a logger's editable fields (id, position, role, notes) — CFG-05.

    Pass ``previous_id`` when the ID itself changes. Raises ValueError when
    the new ID collides with another logger (CFG-11 uniqueness).
    """

    def __init__(
        self,
        model: ProjectModel,
        layer_id: str,
        replacement: Logger,
        previous_id: str | None = None,
    ) -> None:
        lookup = previous_id if previous_id is not None else replacement.logger_id
        current = model.logger_by_id(layer_id, lookup)
        if replacement.logger_id != current.logger_id:
            for item in model.layer_by_id(layer_id).loggers:
                if item.logger_id == replacement.logger_id:
                    raise ValueError(f"logger ID '{replacement.logger_id}' already exists")
        super().__init__(
            model,
            f"Update logger '{replacement.logger_id}'",
            AuditAction.LOGGER_CHANGED,
            f"logger:{replacement.logger_id}",
        )
        self._layer_id = layer_id
        self._new = replace(replacement)
        self._old = replace(current)
        self._lookup_id = lookup

    def redo(self) -> None:
        layer = self._model.layer_by_id(self._layer_id)
        index = self._model.logger_index(self._layer_id, self._lookup_id)
        layer.loggers[index] = replace(self._new)
        self._lookup_id = self._new.logger_id
        self._model.notify_loggers_changed()

    def undo(self) -> None:
        layer = self._model.layer_by_id(self._layer_id)
        index = self._model.logger_index(self._layer_id, self._lookup_id)
        layer.loggers[index] = replace(self._old)
        self._lookup_id = self._old.logger_id
        self._model.notify_loggers_changed()


# -------------------------------------------------------------------- space


class SetSpacePropertiesCommand(ProjectCommand):
    """Update space properties (name, type, height, unit, footprint) — CFG-01, GEO-01."""

    def __init__(self, model: ProjectModel, **changes: Any) -> None:
        if not changes:
            raise ValueError("no space properties given")
        unknown = set(changes) - _SPACE_PROPERTY_KEYS
        if unknown:
            raise ValueError(f"unknown space properties: {sorted(unknown)}")
        text = "Update space properties: " + ", ".join(sorted(changes))
        super().__init__(model, text, AuditAction.SPACE_CHANGED, "space")
        self._changes = dict(changes)
        self._previous: dict[str, Any] | None = None

    def redo(self) -> None:
        space = self._model.space
        if self._previous is None:
            self._previous = {key: getattr(space, key) for key in self._changes}
        for key, value in self._changes.items():
            setattr(space, key, value)
        self._model.notify_space_changed()

    def undo(self) -> None:
        assert self._previous is not None
        space = self._model.space
        for key, value in self._previous.items():
            setattr(space, key, value)
        self._model.notify_space_changed()


# ---------------------------------------------------------------- obstacles


class AddObstacleCommand(ProjectCommand):
    """Add an obstacle (also used for duplicates) — OBS-01, OBS-02."""

    def __init__(self, model: ProjectModel, obstacle: Obstacle) -> None:
        super().__init__(
            model,
            f"Add obstacle '{obstacle.name}'",
            AuditAction.OBSTACLE_ADDED,
            f"obstacle:{obstacle.name}",
        )
        self._obstacle = obstacle
        self._index: int | None = None

    def redo(self) -> None:
        obstacles = self._model.space.obstacles
        index = len(obstacles) if self._index is None else self._index
        self._index = index
        obstacles.insert(index, self._obstacle)
        self._model.notify_obstacles_changed()

    def undo(self) -> None:
        assert self._index is not None
        self._model.space.obstacles.pop(self._index)
        self._model.notify_obstacles_changed()


class RemoveObstacleCommand(ProjectCommand):
    """Remove an obstacle by id; undo restores it — OBS-02."""

    def __init__(self, model: ProjectModel, obstacle_id: str) -> None:
        obstacle = model.obstacle_by_id(obstacle_id)
        super().__init__(
            model,
            f"Remove obstacle '{obstacle.name}'",
            AuditAction.OBSTACLE_REMOVED,
            f"obstacle:{obstacle.name}",
        )
        self._obstacle_id = obstacle_id
        self._obstacle: Obstacle | None = None
        self._index = -1

    def redo(self) -> None:
        self._index = self._model.obstacle_index(self._obstacle_id)
        self._obstacle = self._model.space.obstacles.pop(self._index)
        self._model.notify_obstacles_changed()

    def undo(self) -> None:
        assert self._obstacle is not None
        self._model.space.obstacles.insert(self._index, self._obstacle)
        self._model.notify_obstacles_changed()


class UpdateObstacleCommand(ProjectCommand):
    """Replace an obstacle's editable fields — OBS-02."""

    def __init__(self, model: ProjectModel, replacement: Obstacle) -> None:
        current = model.obstacle_by_id(replacement.obstacle_id)
        super().__init__(
            model,
            f"Update obstacle '{replacement.name}'",
            AuditAction.OBSTACLE_CHANGED,
            f"obstacle:{replacement.name}",
        )
        self._new = replace(replacement)
        self._old = replace(current)

    def redo(self) -> None:
        index = self._model.obstacle_index(self._new.obstacle_id)
        self._model.space.obstacles[index] = replace(self._new)
        self._model.notify_obstacles_changed()

    def undo(self) -> None:
        index = self._model.obstacle_index(self._old.obstacle_id)
        self._model.space.obstacles[index] = replace(self._old)
        self._model.notify_obstacles_changed()


class SetObstacleVisibleCommand(ProjectCommand):
    """Show/hide an obstacle — OBS-02."""

    def __init__(self, model: ProjectModel, obstacle_id: str, visible: bool) -> None:
        obstacle = model.obstacle_by_id(obstacle_id)
        verb = "Show" if visible else "Hide"
        super().__init__(
            model,
            f"{verb} obstacle '{obstacle.name}'",
            AuditAction.OBSTACLE_CHANGED,
            f"obstacle:{obstacle.name}",
        )
        self._obstacle_id = obstacle_id
        self._visible = visible
        self._previous: bool | None = None

    def redo(self) -> None:
        obstacle = self._model.obstacle_by_id(self._obstacle_id)
        if self._previous is None:
            self._previous = obstacle.visible
        obstacle.visible = self._visible
        self._model.notify_obstacles_changed()

    def undo(self) -> None:
        assert self._previous is not None
        obstacle = self._model.obstacle_by_id(self._obstacle_id)
        obstacle.visible = self._previous
        self._model.notify_obstacles_changed()


class BulkAddLayersCommand(ProjectCommand):
    """Add several layers as one undoable step (BLK-01, BLK-06)."""

    def __init__(self, model: ProjectModel, layers: Sequence[Layer], source: str = "") -> None:
        if not layers:
            raise ValueError("cannot import zero layers")
        total = sum(len(layer.loggers) for layer in layers)
        text = f"Import layout: {len(layers)} layer(s), {total} logger(s)"
        if source:
            text += f" from '{source}'"
        super().__init__(model, text, AuditAction.LAYER_ADDED, "layout")
        self._layers = list(layers)
        self._source = source
        self._indices: list[int] | None = None

    def redo(self) -> None:
        space_layers = self._model.space.layers
        if self._indices is None:
            start = len(space_layers)
            self._indices = [start + offset for offset in range(len(self._layers))]
        for layer, index in zip(self._layers, self._indices):
            space_layers.insert(index, layer)
        self._model.set_active_layer(self._layers[-1].layer_id)
        self._model.notify_layers_changed()

    def undo(self) -> None:
        space_layers = self._model.space.layers
        for layer in reversed(self._layers):
            space_layers.remove(layer)
        self._model.set_active_layer(space_layers[-1].layer_id if space_layers else None)
        self._model.notify_layers_changed()
