"""AuditService: append-only, hash-chained, UTC timestamps (AUD-01, AUD-04, AUD-05)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from thermavisualizer.services.audit import GENESIS_HASH, AuditAction, AuditService


def test_record_appends_metadata() -> None:
    service = AuditService("Moaz")
    entry = service.record(AuditAction.LAYER_ADDED, "layer:low", "Add layer 'low'")
    assert entry.sequence == 1
    assert entry.user == "Moaz"
    assert entry.action is AuditAction.LAYER_ADDED
    assert entry.target == "layer:low"
    assert entry.previous_hash == GENESIS_HASH
    assert entry.entry_hash


def test_sequence_and_chain_links() -> None:
    service = AuditService("Moaz")
    first = service.record(AuditAction.PROJECT_CREATE, "project", "create")
    second = service.record(AuditAction.SPACE_CHANGED, "space", "update")
    assert second.sequence == 2
    assert second.previous_hash == first.entry_hash
    assert service.verify_chain()


def test_entries_are_append_only() -> None:
    service = AuditService("Moaz")
    service.record(AuditAction.UNDO, "project", "undo")
    for forbidden in ("delete", "remove", "clear", "edit", "update_entry"):
        assert not hasattr(service, forbidden)


def test_tamper_detection() -> None:
    service = AuditService("Moaz")
    service.record(AuditAction.LAYER_ADDED, "layer:low", "original")
    object.__setattr__(service.entries[0], "summary", "hacked")
    assert not service.verify_chain()


def test_jsonl_roundtrip_preserves_chain() -> None:
    service = AuditService("Moaz")
    service.record(AuditAction.PROJECT_CREATE, "project", "create")
    service.record(AuditAction.LAYER_ADDED, "layer:low", "add", comment="first layer")
    loaded = AuditService.from_jsonl(service.to_jsonl(), "reviewer")
    assert loaded.entries == service.entries
    assert loaded.verify_chain()
    assert loaded.user_name == "reviewer"


def test_timestamps_are_utc() -> None:
    service = AuditService("Moaz")
    entry = service.record(AuditAction.EXPORTED, "file", "export")
    parsed = datetime.fromisoformat(entry.timestamp_utc)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_user_name_required() -> None:
    with pytest.raises(ValueError):
        AuditService("   ")
