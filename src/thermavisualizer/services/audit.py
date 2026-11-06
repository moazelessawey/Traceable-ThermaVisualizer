"""AuditService: append-only, hash-chained record of user actions (AUD-01..05).

This is a lightweight audit trail: who did what and when. It is NOT a Part 11
compliance feature and makes no such claim (AGENTS domain rules).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

GENESIS_HASH = "0" * 64


class AuditAction(StrEnum):
    """Audit event types required by AUD-03 (wired as milestones land)."""

    PROJECT_CREATE = "project_create"
    PROJECT_OPEN = "project_open"
    PROJECT_SAVE = "project_save"
    SPACE_CHANGED = "space_changed"
    LAYER_ADDED = "layer_added"
    LAYER_REMOVED = "layer_removed"
    LAYER_CHANGED = "layer_changed"
    LOGGER_ADDED = "logger_added"
    LOGGER_REMOVED = "logger_removed"
    LOGGER_CHANGED = "logger_changed"
    OBSTACLE_ADDED = "obstacle_added"
    OBSTACLE_REMOVED = "obstacle_removed"
    OBSTACLE_CHANGED = "obstacle_changed"
    FILE_IMPORTED = "file_imported"
    MAPPING_CHANGED = "mapping_changed"
    VALIDATION_RUN = "validation_run"
    PROCESSING_CHANGED = "processing_changed"
    EXCLUSION_CHANGED = "exclusion_changed"
    CRITERIA_CHANGED = "criteria_changed"
    EXPORTED = "exported"
    REPORT_GENERATED = "report_generated"
    UNDO = "undo"
    REDO = "redo"
    RESULTS_EVALUATED = "results_evaluated"
    STUDY_CHANGED = "study_changed"


@dataclass(frozen=True)
class AuditEntry:
    """One immutable audit record (AUD-01). Timestamps are stored in UTC."""

    sequence: int
    timestamp_utc: str
    user: str
    action: AuditAction
    target: str
    summary: str
    comment: str
    previous_hash: str
    entry_hash: str


def compute_entry_hash(
    sequence: int,
    timestamp_utc: str,
    user: str,
    action: AuditAction,
    target: str,
    summary: str,
    comment: str,
    previous_hash: str,
) -> str:
    """Return the SHA-256 chain hash for an entry's content (AUD-05)."""
    payload = json.dumps(
        {
            "sequence": sequence,
            "timestamp_utc": timestamp_utc,
            "user": user,
            "action": str(action),
            "target": target,
            "summary": summary,
            "comment": comment,
            "previous_hash": previous_hash,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditService:
    """Append-only, hash-chained audit trail (AUD-01, AUD-04, AUD-05).

    The API offers no way to edit or delete entries. Use ``verify_chain`` to
    detect tampering. Entries serialize to JSONL for the project file
    (``audit_trail.jsonl``, M6).
    """

    def __init__(self, user_name: str) -> None:
        if not user_name.strip():
            raise ValueError("audit user name must not be empty")
        self._user_name = user_name
        self._entries: list[AuditEntry] = []

    @property
    def user_name(self) -> str:
        """User name stamped on new entries (AUD-02)."""
        return self._user_name

    def set_user_name(self, name: str) -> None:
        """Change the user name for future entries (preferences, AUD-02)."""
        if not name.strip():
            raise ValueError("audit user name must not be empty")
        self._user_name = name

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        """All entries in insertion order (read-only copy)."""
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def record(
        self,
        action: AuditAction,
        target: str,
        summary: str,
        comment: str = "",
    ) -> AuditEntry:
        """Append a new entry and return it (AUD-01). Timestamp is UTC."""
        previous = self._entries[-1].entry_hash if self._entries else GENESIS_HASH
        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        sequence = len(self._entries) + 1
        entry_hash = compute_entry_hash(
            sequence, timestamp, self._user_name, action, target, summary, comment, previous
        )
        entry = AuditEntry(
            sequence,
            timestamp,
            self._user_name,
            action,
            target,
            summary,
            comment,
            previous,
            entry_hash,
        )
        self._entries.append(entry)
        return entry

    def verify_chain(self) -> bool:
        """Return True if every entry hash and link is intact (tamper check)."""
        previous = GENESIS_HASH
        for index, entry in enumerate(self._entries):
            if entry.sequence != index + 1 or entry.previous_hash != previous:
                return False
            expected = compute_entry_hash(
                entry.sequence,
                entry.timestamp_utc,
                entry.user,
                entry.action,
                entry.target,
                entry.summary,
                entry.comment,
                previous,
            )
            if entry.entry_hash != expected:
                return False
            previous = entry.entry_hash
        return True

    def to_jsonl(self) -> str:
        """Serialize entries to JSON Lines (project file, M6)."""
        lines = []
        for entry in self._entries:
            data = {
                "sequence": entry.sequence,
                "timestamp_utc": entry.timestamp_utc,
                "user": entry.user,
                "action": entry.action.value,
                "target": entry.target,
                "summary": entry.summary,
                "comment": entry.comment,
                "previous_hash": entry.previous_hash,
                "entry_hash": entry.entry_hash,
            }
            lines.append(json.dumps(data, ensure_ascii=False))
        return "\n".join(lines) + ("\n" if lines else "")

    @classmethod
    def from_jsonl(cls, text: str, user_name: str) -> AuditService:
        """Load entries from JSON Lines. Call ``verify_chain`` after loading."""
        service = cls(user_name)
        for line in text.splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            service._entries.append(
                AuditEntry(
                    sequence=data["sequence"],
                    timestamp_utc=data["timestamp_utc"],
                    user=data["user"],
                    action=AuditAction(data["action"]),
                    target=data["target"],
                    summary=data["summary"],
                    comment=data["comment"],
                    previous_hash=data["previous_hash"],
                    entry_hash=data["entry_hash"],
                )
            )
        return service
