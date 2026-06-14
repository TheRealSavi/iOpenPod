from typing import cast

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QMenu, QPushButton, QSizePolicy

from ..styles import Colors, Metrics, btn_css, input_css

# Sort definitions per category: (display_label, sort_key, reverse)
_SORTS = {
    "Albums": [
        ("Name", "title", False),
        ("Artist", "artist", False),
        ("Year", "year", True),
        ("Most Tracks", "track_count", True),
    ],
    "Artists": [
        ("Name", "title", False),
        ("Most Albums", "album_count", True),
        ("Most Tracks", "track_count", True),
        ("Most Plays", "total_plays", True),
    ],
    "Genres": [
        ("Name", "title", False),
        ("Most Artists", "artist_count", True),
        ("Most Tracks", "track_count", True),
    ],
    "Playlists": [
        ("Name", "title", False),
        ("Most Tracks", "track_count", True),
        ("Most Skipped", "skipped_count", True),
    ],
    "Photos": [
        ("Name", "title", False),
        ("Largest", "size", True),
        ("Most Albums", "album_count", True),
    ],
}

_DEFAULT_LABEL = "Name"


class GridHeaderBar(QFrame):
    """Thin header strip above the grid with a Sort menu and search bar."""

    sort_changed = pyqtSignal(str, bool)   # (sort_key, reverse)
    search_changed = pyqtSignal(str)       # filter query

    def __init__(self, parent=None):
        super().__init__(parent)
        self._category = "Albums"
        self._active_label = _DEFAULT_LABEL

        self.setFixedHeight(36)
        self.setStyleSheet(f"""
            GridHeaderBar {{
                background: {Colors.BG_DARK};
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)

        self._sort_btn = QPushButton(f"Sort: {_DEFAULT_LABEL} \u25be")
        self._sort_btn.setStyleSheet(
            btn_css(padding="4px 10px", radius=Metrics.BORDER_RADIUS_SM)
        )
        self._sort_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._sort_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sort_btn.clicked.connect(self._show_sort_menu)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search\u2026")
        self._search.setFixedWidth(200)
        self._search.setStyleSheet(
            input_css(radius=Metrics.BORDER_RADIUS_SM, padding="4px 10px")
        )
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.search_changed)

        layout.addWidget(self._sort_btn)
        layout.addStretch()
        layout.addWidget(self._search)

    # ── Public API ────────────────────────────────────────────────────────────

    def setCategory(self, category: str) -> None:
        """Update the available sort options for the given category."""
        self._category = category

    def resetState(self) -> None:
        """Reset search text and sort selection to defaults."""
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._active_label = _DEFAULT_LABEL
        self._sort_btn.setText(f"Sort: {_DEFAULT_LABEL} \u25be")
        # Emit the default sort so grid is reset even if called from other paths
        self.sort_changed.emit("title", False)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _show_sort_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
                padding: 4px 0;
            }}
            QMenu::item {{
                padding: 6px 16px;
            }}
            QMenu::item:selected {{
                background: {Colors.SURFACE_HOVER};
            }}
            QMenu::item:checked {{
                color: {Colors.ACCENT};
            }}
            QMenu::separator {{
                height: 1px;
                background: {Colors.BORDER_SUBTLE};
                margin: 4px 0;
            }}
        """)

        all_sorts = _SORTS.get(self._category, _SORTS["Albums"])
        for label, key, reverse in all_sorts:
            action = cast(QAction, menu.addAction(label))
            action.setCheckable(True)
            action.setChecked(label == self._active_label)
            action.triggered.connect(
                lambda checked, lbl=label, k=key, r=reverse: self._on_sort_selected(lbl, k, r)
            )

        menu.exec(self._sort_btn.mapToGlobal(
            self._sort_btn.rect().bottomLeft()
        ))

    def _on_sort_selected(self, label: str, key: str, reverse: bool) -> None:
        self._active_label = label
        self._sort_btn.setText(f"Sort: {label} \u25be")
        self.sort_changed.emit(key, reverse)
