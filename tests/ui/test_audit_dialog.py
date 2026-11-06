"""Audit trail viewer: listing, filters, chain check, CSV export (AUD-06)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog
from pytestqt.qtbot import QtBot

from thermavisualizer.services.audit import AuditAction, AuditService
from thermavisualizer.ui.dialogs import AuditTrailDialog


def _service() -> AuditService:
    service = AuditService("tester")
    service.record(AuditAction.PROJECT_CREATE, "project", "create")
    service.record(AuditAction.SPACE_CHANGED, "space", "edit space")
    service.record(AuditAction.VALIDATION_RUN, "validation", "run")
    return service


def test_dialog_lists_entries(qtbot: QtBot) -> None:
    dialog = AuditTrailDialog(_service())
    qtbot.addWidget(dialog)
    assert dialog.table.rowCount() == 3


def test_filter_by_action(qtbot: QtBot) -> None:
    dialog = AuditTrailDialog(_service())
    qtbot.addWidget(dialog)
    dialog.action_combo.setCurrentText("validation_run")
    assert dialog.table.rowCount() == 1


def test_verify_chain_detects_tamper(qtbot: QtBot) -> None:
    service = _service()
    dialog = AuditTrailDialog(service)
    qtbot.addWidget(dialog)
    assert "intact" in dialog.verify_label.text()
    object.__setattr__(service.entries[0], "summary", "hacked")
    dialog._on_verify()
    assert "BROKEN" in dialog.verify_label.text()


def test_export_csv(qtbot: QtBot, tmp_path: Path, monkeypatch) -> None:
    dialog = AuditTrailDialog(_service())
    qtbot.addWidget(dialog)
    target = tmp_path / "audit.csv"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "CSV (*.csv)")),
    )
    dialog._on_export()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("#") or "Timestamp" in lines[0]
    assert len(lines) == 4  # header + 3 entries
