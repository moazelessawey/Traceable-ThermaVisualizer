"""Import dialog: profile build, preview parse, mapping hand-off (DAT-01..05)."""

from __future__ import annotations

from pathlib import Path

from pytestqt.qtbot import QtBot

from thermavisualizer.core.models import Layer, Logger
from thermavisualizer.services.project_model import ProjectModel
from thermavisualizer.services.undo import AddLayerCommand, AddLoggersCommand
from thermavisualizer.ui.dialogs.import_data import ImportDataDialog


def _add_loggers(model: ProjectModel) -> None:
    layer = Layer(name="low", height=0.5)
    model.apply(AddLayerCommand(model, layer))
    model.apply(
        AddLoggersCommand(model, layer.layer_id, [Logger("L1", 0, 0, 0.5), Logger("L2", 1, 0, 0.5)])
    )


def test_build_profile_reads_form(qtbot: QtBot, project_model: ProjectModel) -> None:
    dialog = ImportDataDialog(project_model)
    qtbot.addWidget(dialog)
    dialog._profile_name_edit.setText("Euro")
    dialog._delimiter_edit.setText(";")
    dialog._decimal_combo.setCurrentText(",")
    dialog._header_row_spin.setValue(2)
    profile = dialog._build_profile()
    assert profile.name == "Euro"
    assert profile.delimiter == ";"
    assert profile.decimal == ","
    assert profile.header_row == 2


def test_preview_parses_selected_file(
    qtbot: QtBot, project_model: ProjectModel, tmp_path: Path
) -> None:
    _add_loggers(project_model)
    csv = tmp_path / "d.csv"
    csv.write_text("Timestamp,L1,L2\n2024-01-01 00:00:00,1,2\n", encoding="utf-8")
    dialog = ImportDataDialog(project_model)
    qtbot.addWidget(dialog)
    dialog.add_paths([csv])
    assert dialog._parse_all_previews() is True
    parsed = dialog._previews[str(csv)]
    assert [c.name for c in parsed.columns] == ["Timestamp", "L1", "L2"]


def test_import_loads_files_and_applies_mapping(
    qtbot: QtBot, project_model: ProjectModel, tmp_path: Path, monkeypatch
) -> None:
    _add_loggers(project_model)
    csv = tmp_path / "d.csv"
    csv.write_text("Timestamp,L1,L2\n2024-01-01 00:00:00,1,2\n", encoding="utf-8")
    dialog = ImportDataDialog(project_model)
    qtbot.addWidget(dialog)
    dialog.add_paths([csv])
    dialog._parse_all_previews()
    dialog._mapping_editor.set_files(list(dialog._previews.values()))

    jobs_seen = []
    monkeypatch.setattr(project_model, "load_files_async", lambda jobs: jobs_seen.extend(jobs))
    dialog._mapping_editor._temp_combos["L1"].setCurrentText("d.csv :: L1")
    dialog._perform_import()

    assert len(jobs_seen) == 1
    assert jobs_seen[0][0] == csv
    mapping = project_model.mapping_for("L1")
    assert mapping is not None and mapping.temperature_column == "L1"
