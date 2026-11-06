"""Layout import dialog: preview, auto-mapping, error report (BLK-01)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from thermavisualizer.ui.panels.layout_import_dialog import LayoutImportDialog

DATA = Path(__file__).resolve().parents[1] / "data"


def test_dialog_autosuggest_preview_and_finish(qtbot: QtBot) -> None:
    dialog = LayoutImportDialog(DATA / "layout_valid.csv", frozenset())
    qtbot.addWidget(dialog)
    assert dialog.preview_table.rowCount() == 6
    assert dialog.mapping_combos["x"].currentText() == "X"
    assert dialog.mapping_combos["layer"].currentText() == "Layer"
    assert dialog.finish() is True
    assert [layer.name for layer in dialog.imported_layers()] == ["low", "high"]


def test_dialog_reports_errors_and_blocks_import(qtbot: QtBot) -> None:
    dialog = LayoutImportDialog(DATA / "layout_errors.csv", frozenset())
    qtbot.addWidget(dialog)
    assert dialog.finish() is False
    assert dialog.imported_layers() == []
    assert dialog.report_list.count() == 4
    assert "duplicate-id" in dialog.report_list.item(0).text()


def test_dialog_delimiter_and_decimal_options(qtbot: QtBot) -> None:
    dialog = LayoutImportDialog(DATA / "layout_semicolon.csv", frozenset())
    qtbot.addWidget(dialog)
    dialog.delimiter_combo.setCurrentText(";")
    dialog.decimal_combo.setCurrentText(",")
    assert dialog.finish() is True
    layers = dialog.imported_layers()
    assert layers[0].loggers[0].x == pytest.approx(0.5)


def test_dialog_flags_conflicts_with_project(qtbot: QtBot) -> None:
    dialog = LayoutImportDialog(DATA / "layout_valid.csv", frozenset({"L1"}))
    qtbot.addWidget(dialog)
    assert dialog.finish() is False
    assert any(
        "duplicate-id" in dialog.report_list.item(i).text()
        for i in range(dialog.report_list.count())
    )
