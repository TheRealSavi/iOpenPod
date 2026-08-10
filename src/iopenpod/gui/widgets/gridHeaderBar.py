from typing import cast

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton

from ..glyphs import glyph_icon
from ..styles import (
    BROWSER_SEARCH_CONTROL_SIZE,
    BROWSER_SEARCH_FIELD_WIDTH,
    FONT_FAMILY,
    Metrics,
    browser_search_field_css,
    btn_css,
    context_menu_css,
    paint_css,
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
    selection_grouping_changed = pyqtSignal(bool)
    artist_view_mode_changed = pyqtSignal(str)  # "grid" or "list"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._category = "Albums"
        self._active_label = _DEFAULT_LABEL
        self._artist_view_mode = "grid"

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
            f"color: {paint_css('text.primary')}; background: transparent; border: none;"
        )

        control_size = BROWSER_SEARCH_CONTROL_SIZE
        self._sort_btn = QPushButton()
        self._sort_btn.setObjectName("gridSortButton")
        self._sort_btn.setFixedSize(control_size, control_size)
        self._sort_btn.setStyleSheet(btn_css(
            bg=paint_css("control.secondary.fill"),
            bg_hover=paint_css("control.secondary.hover_fill"),
            bg_press=paint_css("control.secondary.pressed_fill"),
            border=f"1px solid {paint_css('border.default')}",
            radius=control_size // 2,
            padding="0px",
        ))
        sort_icon = glyph_icon("sort-descending", 18, paint_css("text.secondary"))
        if sort_icon is not None:
            self._sort_btn.setIcon(sort_icon)
            self._sort_btn.setIconSize(QSize(18, 18))
        self._update_sort_accessibility()
        self._sort_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sort_btn.clicked.connect(self._show_sort_menu)

        self._selection_group_btn = QPushButton()
        self._selection_group_btn.setObjectName("gridGroupBySelectedButton")
        self._selection_group_btn.setCheckable(True)
        self._selection_group_btn.setFixedSize(control_size, control_size)
        self._selection_group_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selection_group_btn.toggled.connect(self._on_selection_grouping_toggled)
        self._selection_group_btn.hide()
        self._update_selection_grouping_button()

        self._artist_view_switch = QFrame()
        self._artist_view_switch.setObjectName("artistViewModeSwitch")
        self._artist_view_switch.setFixedSize(72, control_size)
        self._artist_view_switch.setStyleSheet(f"""
            QFrame#artistViewModeSwitch {{
                background: {paint_css('control.secondary.fill')};
                border: 1px solid {paint_css('border.default')};
                border-radius: {control_size // 2}px;
            }}
        """)
        artist_view_layout = QHBoxLayout(self._artist_view_switch)
        artist_view_layout.setContentsMargins(3, 3, 3, 3)
        artist_view_layout.setSpacing(0)

        self._artist_grid_btn = self._make_artist_view_button(
            "grid",
            "Artist grid view",
        )
        self._artist_list_btn = self._make_artist_view_button(
            "list",
            "Artist list view",
        )
        self._artist_view_divider = QFrame()
        self._artist_view_divider.setObjectName("artistViewModeDivider")
        self._artist_view_divider.setFixedWidth(1)
        self._artist_view_divider.setStyleSheet(
            f"background: {paint_css('border.default')}; border: none;"
        )
        artist_view_layout.addWidget(self._artist_grid_btn)
        artist_view_layout.addWidget(self._artist_view_divider)
        artist_view_layout.addWidget(self._artist_list_btn)
        self._artist_view_switch.hide()
        self._update_artist_view_buttons()

        self._search = QLineEdit()
        self._search.setObjectName("gridSearchField")
        self._search.setPlaceholderText(f"Find in {self._category}")
        self._search.setFixedSize(
            BROWSER_SEARCH_FIELD_WIDTH,
            BROWSER_SEARCH_CONTROL_SIZE,
        )
        self._search.setStyleSheet(browser_search_field_css())
        search_icon = glyph_icon("search", 16, paint_css("text.tertiary"))
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
        layout.addWidget(self._artist_view_switch)
        layout.addWidget(self._selection_group_btn)
        layout.addWidget(self._search)

    # ── Public API ────────────────────────────────────────────────────────────

    def setCategory(self, category: str) -> None:
        """Update the available sort options for the given category."""
        self._category = category
        self._title.setText(category)
        self._search.setPlaceholderText(f"Find in {category}")
        is_artist_category = category == "Artists"
        self._artist_view_switch.setVisible(is_artist_category)

    def artistViewMode(self) -> str:
        """Return the selected Artists presentation mode."""

        return self._artist_view_mode

    def setArtistViewMode(self, mode: str) -> None:
        """Select the Artists grid or sidebar-browser presentation mode."""

        if mode not in {"grid", "list"}:
            raise ValueError(f"Unknown artist view mode: {mode}")
        if self._artist_view_mode == mode:
            return
        self._artist_view_mode = mode
        self._update_artist_view_buttons()
        self.artist_view_mode_changed.emit(mode)

    def resetState(self) -> None:
        """Reset search text and sort selection to defaults."""
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._active_label = _DEFAULT_LABEL
        self._update_sort_accessibility()
        # Emit the default sort so grid is reset even if called from other paths
        self.sort_changed.emit("title", False)

    def setSelectionGroupingAvailable(self, available: bool) -> None:
        """Show the selected-item grouping control for supporting grids."""

        self._selection_group_btn.setVisible(available)
        if not available:
            self.setGroupBySelected(False)

    def setGroupBySelected(self, enabled: bool) -> None:
        """Set whether a supporting grid separates selected items."""

        enabled = bool(enabled)
        if self._selection_group_btn.isChecked() == enabled:
            return
        self._selection_group_btn.setChecked(enabled)

    def isGroupedBySelected(self) -> bool:
        """Return whether the selected-item grouping control is enabled."""

        return self._selection_group_btn.isChecked()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _make_artist_view_button(self, mode: str, label: str) -> QPushButton:
        button = QPushButton(self._artist_view_switch)
        button.setObjectName(f"artist{mode.title()}ViewButton")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAccessibleName(label)
        button.setToolTip(label)
        icon = glyph_icon(mode, 18, paint_css("text.secondary"))
        if icon is not None:
            button.setIcon(icon)
            button.setIconSize(QSize(18, 18))
        button.clicked.connect(lambda _checked=False, selected_mode=mode: self.setArtistViewMode(selected_mode))
        return button

    def _update_artist_view_buttons(self) -> None:
        for mode, button in (
            ("grid", self._artist_grid_btn),
            ("list", self._artist_list_btn),
        ):
            selected = mode == self._artist_view_mode
            button.blockSignals(True)
            button.setChecked(selected)
            button.blockSignals(False)
            button.setStyleSheet(btn_css(
                bg=(
                    paint_css("surface.active")
                    if selected
                    else "transparent"
                ),
                bg_hover=(
                    paint_css("surface.hover")
                    if not selected
                    else paint_css("surface.active")
                ),
                bg_press=paint_css("surface.raised"),
                border="none",
                radius=14,
                padding="0px",
            ))

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

    def _on_selection_grouping_toggled(self, enabled: bool) -> None:
        self._update_selection_grouping_button()
        self.selection_grouping_changed.emit(enabled)

    def _update_selection_grouping_button(self) -> None:
        enabled = self._selection_group_btn.isChecked()
        control_size = BROWSER_SEARCH_CONTROL_SIZE
        self._selection_group_btn.setStyleSheet(btn_css(
            bg=(
                paint_css("control.toggle.selected_fill")
                if enabled
                else paint_css("control.secondary.fill")
            ),
            bg_hover=(
                paint_css("control.toggle.selected_hover_fill")
                if enabled
                else paint_css("control.secondary.hover_fill")
            ),
            bg_press=(
                paint_css("control.toggle.selected_pressed_fill")
                if enabled
                else paint_css("control.secondary.pressed_fill")
            ),
            border=(
                f"1px solid {paint_css('control.toggle.selected_border')}"
                if enabled
                else f"1px solid {paint_css('border.default')}"
            ),
            radius=control_size // 2,
            padding="0px",
        ))
        icon = glyph_icon(
            "check-circle",
            18,
            (
                paint_css("control.primary.fill")
                if enabled
                else paint_css("text.secondary")
            ),
        )
        if icon is not None:
            self._selection_group_btn.setIcon(icon)
            self._selection_group_btn.setIconSize(QSize(18, 18))
        label = "Group by selected"
        self._selection_group_btn.setAccessibleName(label)
        self._selection_group_btn.setToolTip(
            f"{label}: {'on' if enabled else 'off'}"
        )

    def _update_sort_accessibility(self) -> None:
        label = f"Sort: {self._active_label}"
        self._sort_btn.setAccessibleName(label)
        self._sort_btn.setToolTip(label)
