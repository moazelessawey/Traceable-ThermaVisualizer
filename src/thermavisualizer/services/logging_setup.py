"""Logging configuration: rotating file plus console handlers (PRD NFR)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3


def default_log_file() -> Path:
    """Default log file path under the user's home directory."""
    return Path.home() / ".thermavisualizer" / "logs" / "thermavisualizer.log"


def configure_logging(log_dir: Path, file_level: int = logging.INFO) -> Path:
    """Configure the ``thermavisualizer`` logger tree.

    A rotating file handler records INFO and above; the console shows WARNING
    and above. Returns the active log file path.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "thermavisualizer.log"

    root = logging.getLogger("thermavisualizer")
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    file_handler = RotatingFileHandler(
        log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(file_level)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(console_handler)

    return log_file
