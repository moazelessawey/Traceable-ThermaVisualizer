"""ProjectModel + undo commands + audit integration (CFG-08, BLK-06, AUD-01/03/04)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from pytestqt.qtbot import QtBot

from thermavisualizer.core.layout import generate_lattice
from thermavisualizer.core.models import (
    Layer,
    Logger,
    Obstacle,
    ObstacleShape,
    ObstacleType,
    SpaceType,
)
from thermavisualizer.services.audit import AuditAction
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import (
    AddLayerCommand,
    AddLoggersCommand,
    AddObstacleCommand,
    MoveLayerCommand,
    RemoveLayerCommand,
    RemoveLoggersCommand,
    RenameLayerCommand,
    SetLayerCompletedCommand,
    SetLayerHeightCommand,
    SetObstacleVisibleCommand,
    SetSpacePropertiesCommand,
    UpdateLoggerCommand,
    UpdateObstacleCommand,
    BulkAddLayersCommand,
)


@pytest.fixture
def model(qtbot: QtBot) -> ProjectModel:
    return ProjectModel(user_name="tester")


def _add_layer(model: ProjectModel, name: str = "low", height: float = 0.5) -> str:
    layer = Layer(name=name, height=height)
    model.apply(AddLayerCommand(model, layer))
    return layer.layer_id


def test_add_layer_undo_redo(model: ProjectModel) -> None:
    layer_id = _add_layer(model)
    assert [layer.name for layer in model.space.layers] == ["low"]
    model.undo()
    assert model.space.layers == []
    model.redo()
    assert model.space.layers[0].layer_id == layer_id


def test_change_signals(model: ProjectModel, qtbot: QtBot) -> None:
    with (
        qtbot.waitSignal(model.layers_changed, timeout=500),
        qtbot.waitSignal(model.config_changed, timeout=500),
    ):
        model.apply(AddLayerCommand(model, Layer(name="sig", height=1.0)))


def test_bulk_add_is_single_undo_step(model: ProjectModel) -> None:  # BLK-06
    layer_id = _add_layer(model)
    loggers = generate_lattice(rows=2, columns=3, spacing_x=0.5, spacing_y=0.5, height=0.5)
    model.apply(AddLoggersCommand(model, layer_id, loggers))
    assert len(model.space.layers[0].loggers) == 6
    model.undo()
    assert model.space.layers[0].loggers == []
    model.redo()
    assert len(model.space.layers[0].loggers) == 6


def test_audit_records_edits_undo_redo(model: ProjectModel) -> None:  # AUD-01/04
    _add_layer(model, "a")
    model.undo()
    model.redo()
    entries = model.audit.entries
    assert [entry.action for entry in entries] == [
        AuditAction.LAYER_ADDED,
        AuditAction.UNDO,
        AuditAction.REDO,
    ]
    first = entries[0]
    assert first.user == "tester"
    assert first.target.startswith("layer:")
    assert first.summary
    assert model.audit.verify_chain()


def test_audit_entry_signal(model: ProjectModel, qtbot: QtBot) -> None:
    with qtbot.waitSignal(model.audit_entry_added, timeout=500) as blocker:
        _add_layer(model)
    assert blocker.args[0].action is AuditAction.LAYER_ADDED


def test_no_op_undo_is_not_audited(model: ProjectModel) -> None:
    model.undo()
    model.redo()
    assert len(model.audit) == 0


def test_rename_layer(model: ProjectModel) -> None:
    layer_id = _add_layer(model, "before")
    model.apply(RenameLayerCommand(model, layer_id, "after"))
    assert model.space.layers[0].name == "after"
    model.undo()
    assert model.space.layers[0].name == "before"


def test_move_layer(model: ProjectModel) -> None:
    _add_layer(model, "first")
    _add_layer(model, "second")
    model.apply(MoveLayerCommand(model, 1, 0))
    assert [layer.name for layer in model.space.layers] == ["second", "first"]
    model.undo()
    assert [layer.name for layer in model.space.layers] == ["first", "second"]


def test_layer_completed_toggle(model: ProjectModel) -> None:  # CFG-04
    layer_id = _add_layer(model)
    model.apply(SetLayerCompletedCommand(model, layer_id, True))
    assert model.space.layers[0].completed is True
    model.undo()
    assert model.space.layers[0].completed is False


def test_remove_layer(model: ProjectModel) -> None:
    layer_id = _add_layer(model)
    model.apply(RemoveLayerCommand(model, layer_id))
    assert model.space.layers == []
    model.undo()
    assert model.space.layers[0].layer_id == layer_id


def test_update_logger(model: ProjectModel) -> None:  # CFG-05
    layer_id = _add_layer(model)
    original = Logger("L1", 0.1, 0.2, 0.5)
    model.apply(AddLoggersCommand(model, layer_id, [original]))
    model.apply(UpdateLoggerCommand(model, layer_id, replace(original, x=1.25)))
    assert model.logger_by_id(layer_id, "L1").x == 1.25
    model.undo()
    assert model.logger_by_id(layer_id, "L1").x == pytest.approx(0.1)


def test_remove_loggers_restores_order(model: ProjectModel) -> None:
    layer_id = _add_layer(model)
    originals = [
        Logger("A", 0.0, 0.0, 0.5),
        Logger("B", 1.0, 0.0, 0.5),
        Logger("C", 2.0, 0.0, 0.5),
    ]
    model.apply(AddLoggersCommand(model, layer_id, originals))
    model.apply(RemoveLoggersCommand(model, layer_id, ["A", "C"]))
    assert [item.logger_id for item in model.space.layers[0].loggers] == ["B"]
    model.undo()
    assert [item.logger_id for item in model.space.layers[0].loggers] == ["A", "B", "C"]


def test_space_properties(model: ProjectModel) -> None:  # CFG-01
    model.apply(
        SetSpacePropertiesCommand(
            model, name="Warehouse 1", height=2.5, space_type=SpaceType.CHAMBER
        )
    )
    space = model.space
    assert (space.name, space.height, space.space_type) == ("Warehouse 1", 2.5, SpaceType.CHAMBER)
    model.undo()
    assert (space.name, space.height, space.space_type) == ("Space", 3.0, SpaceType.WAREHOUSE)


def test_set_space_properties_rejects_unknown_keys(model: ProjectModel) -> None:
    with pytest.raises(ValueError):
        SetSpacePropertiesCommand(model, bogus=1)


def test_obstacle_lifecycle(model: ProjectModel) -> None:  # OBS-01/02
    obstacle = Obstacle(
        name="rack",
        obstacle_type=ObstacleType.RACK,
        shape=ObstacleShape.BOX,
        x=1.0,
        y=1.0,
        z=1.0,
        size_x=1.0,
        size_y=0.5,
        size_z=2.0,
    )
    model.apply(AddObstacleCommand(model, obstacle))
    obstacle_id = model.space.obstacles[0].obstacle_id
    model.apply(SetObstacleVisibleCommand(model, obstacle_id, False))
    assert model.space.obstacles[0].visible is False
    model.apply(UpdateObstacleCommand(model, replace(obstacle, x=2.0)))
    assert model.space.obstacles[0].x == 2.0
    model.undo()
    assert model.space.obstacles[0].x == 1.0
    model.undo()
    assert model.space.obstacles[0].visible is True
    model.undo()
    assert model.space.obstacles == []
    model.redo()
    assert len(model.space.obstacles) == 1


def test_empty_bulk_commands_rejected(model: ProjectModel) -> None:
    layer_id = _add_layer(model)
    with pytest.raises(ValueError):
        AddLoggersCommand(model, layer_id, [])
    with pytest.raises(ValueError):
        RemoveLoggersCommand(model, layer_id, [])


def test_layout_issues_through_model(model: ProjectModel) -> None:  # CFG-11
    layer_id = _add_layer(model)
    model.apply(
        AddLoggersCommand(
            model,
            layer_id,
            [
                Logger("A", 0.5, 0.5, 0.5),
                Logger("B", 0.9, 0.5, 0.5),
                Logger("C", 0.5, 0.9, 0.5),
            ],
        )
    )
    codes = {issue.code for issue in model.layout_issues()}
    assert "insufficient-loggers" in codes


def test_lookup_helpers_raise(model: ProjectModel) -> None:
    with pytest.raises(KeyError):
        model.layer_by_id("missing")
    with pytest.raises(KeyError):
        model.obstacle_by_id("missing")


def test_view_state_active_layer(model: ProjectModel, qtbot: QtBot) -> None:
    assert model.active_layer_id() is None
    layer = Layer(name="a", height=0.5)
    with qtbot.waitSignal(model.active_layer_changed, timeout=500):
        model.apply(AddLayerCommand(model, layer))
    assert model.active_layer_id() == layer.layer_id  # auto-activated
    with pytest.raises(KeyError):
        model.set_active_layer("missing")


def test_view_state_selection_follows_active_layer(model: ProjectModel) -> None:
    layer = Layer(name="a", height=0.5)
    model.apply(AddLayerCommand(model, layer))
    model.apply(AddLoggersCommand(model, layer.layer_id, [Logger("L1", 0.1, 0.1, 0.5)]))
    model.select_logger("L1")
    assert model.selected_logger_id() == "L1"
    second = Layer(name="b", height=1.5)
    model.apply(AddLayerCommand(model, second))  # activates "b"
    assert model.selected_logger_id() is None  # selection scoped to active layer
    model.set_active_layer(layer.layer_id)
    assert model.selected_logger_id() == "L1"


def test_remove_layer_moves_activation(model: ProjectModel) -> None:
    first = Layer(name="first", height=0.5)
    second = Layer(name="second", height=1.5)
    model.apply(AddLayerCommand(model, first))
    model.apply(AddLayerCommand(model, second))
    assert model.active_layer_id() == second.layer_id
    model.apply(RemoveLayerCommand(model, second.layer_id))
    assert model.active_layer_id() == first.layer_id
    model.undo()
    assert model.active_layer_id() == second.layer_id


def test_update_logger_id_change(model: ProjectModel) -> None:
    layer = Layer(name="a", height=0.5)
    model.apply(AddLayerCommand(model, layer))
    model.apply(AddLoggersCommand(model, layer.layer_id, [Logger("L1", 0.1, 0.1, 0.5)]))
    updated = replace(model.logger_by_id(layer.layer_id, "L1"), logger_id="L9")
    model.apply(UpdateLoggerCommand(model, layer.layer_id, updated, previous_id="L1"))
    assert model.logger_by_id(layer.layer_id, "L9").x == pytest.approx(0.1)
    model.undo()
    assert model.logger_by_id(layer.layer_id, "L1").logger_id == "L1"
    model.redo()
    assert model.logger_by_id(layer.layer_id, "L9").logger_id == "L9"


def test_update_logger_rejects_duplicate_id(model: ProjectModel) -> None:
    layer = Layer(name="a", height=0.5)
    model.apply(AddLayerCommand(model, layer))
    model.apply(
        AddLoggersCommand(
            model,
            layer.layer_id,
            [Logger("L1", 0.1, 0.1, 0.5), Logger("L2", 0.2, 0.1, 0.5)],
        )
    )
    current = model.logger_by_id(layer.layer_id, "L1")
    with pytest.raises(ValueError):
        UpdateLoggerCommand(
            model, layer.layer_id, replace(current, logger_id="L2"), previous_id="L1"
        )


def test_set_layer_height(model: ProjectModel) -> None:
    layer = Layer(name="a", height=0.5)
    model.apply(AddLayerCommand(model, layer))
    model.apply(SetLayerHeightCommand(model, layer.layer_id, 1.25))
    assert model.space.layers[0].height == 1.25
    model.undo()
    assert model.space.layers[0].height == 0.5


def test_bulk_add_layers_single_undo_step(model: ProjectModel) -> None:  # BLK-01/06
    layers = [
        Layer(name="a", height=0.5, loggers=[Logger("A1", 0.0, 0.0, 0.5)]),
        Layer(name="b", height=1.5, loggers=[Logger("B1", 0.0, 0.0, 1.5)]),
    ]
    model.apply(BulkAddLayersCommand(model, layers, source="file.csv"))
    assert [layer.name for layer in model.space.layers] == ["a", "b"]
    assert model.undo_stack.count() == 1
    model.undo()
    assert model.space.layers == []
    model.redo()
    assert len(model.space.layers) == 2


def test_note_records_non_command_event(model: ProjectModel, qtbot: QtBot) -> None:
    with qtbot.waitSignal(model.audit_entry_added, timeout=500):
        model.note(AuditAction.FILE_IMPORTED, "file:x.csv", "import")
    assert model.audit.entries[-1].action is AuditAction.FILE_IMPORTED
