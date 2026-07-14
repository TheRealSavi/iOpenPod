from typing import cast

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton

from ..glyphs import glyph_icon
from ..styles import (
    BROWSER_SEARCH_CONTROL_SIZE,
    BROWSER_SEARCH_FIELD_WIDTH,
    FONT_FAMILY,
    Colors,
    Metrics,
    browser_search_field_css,
    btn_css,
    context_menu_css,
)

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

        self.setObjectName("gridHeaderBar")
        self.setFixedHeight(56)
        self.setStyleSheet("""
            QFrame#gridHeaderBar {
                background: transparent;
                border: none;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Metrics.GRID_MARGIN_X, 0, Metrics.GRID_MARGIN_X, 0)
        layout.setSpacing(10)

        self._title = QLabel(self._category)
        self._title.setObjectName("gridHeaderTitle")
        self._title.setFont(
            QFont(FONT_FAMILY, Metrics.FONT_BROWSER_TITLE, QFont.Weight.DemiBold)
        )
        self._title.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;"
        )

        control_size = BROWSER_SEARCH_CONTROL_SIZE
        self._sort_btn = QPushButton()
        self._sort_btn.setObjectName("gridSortButton")
        self._sort_btn.setFixedSize(control_size, control_size)
        self._sort_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_HOVER,
            bg_press=Colors.SURFACE_ACTIVE,
            border=f"1px solid {Colors.BORDER}",
            radius=control_size // 2,
            padding="0px",
        ))
        sort_icon = glyph_icon("sort-descending", 18, Colors.TEXT_SECONDARY)
        if sort_icon is not None:
            self._sort_btn.setIcon(sort_icon)
            self._sort_btn.setIconSize(QSize(18, 18))
        self._update_sort_accessibility()
        self._sort_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sort_btn.clicked.connect(self._show_sort_menu)

        self._search = QLineEdit()
        self._search.setObjectName("gridSearchField")
        self._search.setPlaceholderText(f"Find in {self._category}")
        self._search.setFixedSize(
            BROWSER_SEARCH_FIELD_WIDTH,
            BROWSER_SEARCH_CONTROL_SIZE,
        )
        self._search.setStyleSheet(browser_search_field_css())
        search_icon = glyph_icon("search", 16, Colors.TEXT_TERTIARY)
        if search_icon is not None:
            self._search.addAction(
                search_icon,
                QLineEdit.ActionPosition.LeadingPosition,
            )
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self.search_changed)

        layout.addWidget(self._title)
        layout.addStretch()
        layout.addWidget(self._sort_btn)
        layout.addWidget(self._search)

    # ── Public API ────────────────────────────────────────────────────────────

    def setCategory(self, category: str) -> None:
        """Update the available sort options for the given category."""
        self._category = category
        self._title.setText(category)
        self._search.setPlaceholderText(f"Find in {category}")

    def resetState(self) -> None:
        """Reset search text and sort selection to defaults."""
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._active_label = _DEFAULT_LABEL
        self._update_sort_accessibility()
        # Emit the default sort so grid is reset even if called from other paths
        self.sort_changed.emit("title", False)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _show_sort_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(context_menu_css())

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
        self._update_sort_accessibility()
        self.sort_changed.emit(key, reverse)

    def _update_sort_accessibility(self) -> None:
        label = f"Sort: {self._active_label}"
        self._sort_btn.setAccessibleName(label)
        self._sort_btn.setToolTip(label)
