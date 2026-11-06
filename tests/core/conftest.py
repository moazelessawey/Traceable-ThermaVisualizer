"""Shared fixtures for core tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def data_path() -> Callable[[str], Path]:
    """Resolve committed sample files under tests/data."""
    root = Path(__file__).resolve().parents[1] / "data"

    def resolve(name: str) -> Path:
        return root / name

    return resolve
