"""Typed wrapper around QSettings: window layout persistence and preferences."""

from __future__ import annotations

import getpass

from PySide6.QtCore import QByteArray, QSettings

_WINDOW_GEOMETRY_KEY = "ui/window_geometry"
_SPLITTER_STATE_KEY = "ui/main_splitter_state"
_USER_NAME_KEY = "user/name"
_RECENT_FILES_KEY = "files/recent"
_THEME_KEY = "ui/theme"
_USER_ASKED_KEY = "user/asked_once"


class AppSettings:
    """Application settings: window layout persistence and user preferences."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings()

    def save_window_geometry(self, geometry: QByteArray) -> None:
        """Persist the main window geometry."""
        self._settings.setValue(_WINDOW_GEOMETRY_KEY, geometry)

    def window_geometry(self) -> QByteArray | None:
        """Return the persisted window geometry, if any."""
        return self._byte_array(_WINDOW_GEOMETRY_KEY)

    def save_splitter_state(self, state: QByteArray) -> None:
        """Persist the main splitter state (left panel vs. tabs)."""
        self._settings.setValue(_SPLITTER_STATE_KEY, state)

    def splitter_state(self) -> QByteArray | None:
        """Return the persisted splitter state, if any."""
        return self._byte_array(_SPLITTER_STATE_KEY)

    def user_name(self) -> str:
        """Return the configured user name, defaulting to the OS user (AUD-02)."""
        value = self._settings.value(_USER_NAME_KEY)
        if isinstance(value, str) and value:
            return value
        return getpass.getuser()

    def set_user_name(self, name: str) -> None:
        """Set the user name used by the audit trail and exports."""
        self._settings.setValue(_USER_NAME_KEY, name)

    def sync(self) -> None:
        """Flush settings to persistent storage."""
        self._settings.sync()

    def _byte_array(self, key: str) -> QByteArray | None:
        value = self._settings.value(key)
        if isinstance(value, QByteArray):
            return value
        if isinstance(value, bytes | bytearray):
            return QByteArray(bytes(value))
        return None

    def recent_files(self) -> list[str]:
        """Most recent project paths (newest first), capped at 8."""
        value = self._settings.value(_RECENT_FILES_KEY)
        if isinstance(value, list):
            return [str(item) for item in value][:8]
        if isinstance(value, str) and value:
            return [value]
        return []

    def add_recent_file(self, path: str) -> None:
        """Remember a project path (deduplicated, newest first)."""
        recent = [item for item in self.recent_files() if item != path]
        recent.insert(0, path)
        self._settings.setValue(_RECENT_FILES_KEY, recent[:8])

    def theme(self) -> str:
        """Persisted theme name (VIS-08); defaults to system."""
        value = self._settings.value(_THEME_KEY)
        return value if isinstance(value, str) and value else "system"

    def set_theme(self, name: str) -> None:
        """Persist the chosen theme."""
        self._settings.setValue(_THEME_KEY, name)

    def user_name_asked(self) -> bool:
        """True once the first-launch user-name prompt was shown (AUD-02)."""
        value = self._settings.value(_USER_ASKED_KEY)
        return str(value).strip().lower() in ("true", "1", "yes")

    def set_user_name_asked(self) -> None:
        """Mark the first-launch prompt as done."""
        self._settings.setValue(_USER_ASKED_KEY, True)
