"""Left-hand contextual control panel (PRD 4.3)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QStackedWidget, QVBoxLayout, QWidget

MIN_PANEL_WIDTH = 240


class ControlPanel(QWidget):
    """Contextual controls for the active tab; content follows the tab selection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(MIN_PANEL_WIDTH)

        self._title = QLabel(self)
        font = self._title.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self._title.setFont(font)

        self._stack = QStackedWidget(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._title)
        layout.addWidget(self._stack, 1)

    def add_page(self, title: str, description: str) -> None:
        """Add a placeholder page; one page per tab, kept in tab order."""
        page = QLabel(description, self)
        page.setWordWrap(True)
        page.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        page.setProperty("page_title", title)
        self._stack.addWidget(page)
        if self._stack.count() == 1:
            self.set_active_index(0)

    def set_active_index(self, index: int) -> None:
        """Show the page matching the given tab index."""
        if 0 <= index < self._stack.count():
            self._stack.setCurrentIndex(index)
            title = self._stack.widget(index).property("page_title")
            self._title.setText(str(title) if title else "")

    def page_widget(self, index: int) -> QWidget:
        """Return the page widget at ``index``."""
        return self._stack.widget(index)

    def current_title(self) -> str:
        """Title shown above the stack for the active page."""
        return self._title.text()

    def replace_page(self, index: int, widget: QWidget) -> None:
        """Replace a placeholder page with a real panel, keeping tab order."""
        current = self._stack.currentIndex()
        old = self._stack.widget(index)
        widget.setProperty("page_title", old.property("page_title"))
        self._stack.removeWidget(old)
        old.deleteLater()
        self._stack.insertWidget(index, widget)
        self._stack.setCurrentIndex(current if current >= 0 else 0)
