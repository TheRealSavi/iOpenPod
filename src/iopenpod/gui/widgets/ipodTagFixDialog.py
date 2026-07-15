"""Library-wide iPod tag normalization preview dialog."""

from __future__ import annotations

from collections import Counter
from typing import Any

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iopenpod.search import matches_search

from ..glyphs import glyph_pixmap
from ..styles import (
    FONT_FAMILY,
    MONO_FONT_FAMILY,
    Colors,
    Metrics,
    accent_btn_css,
    btn_css,
    chip_btn_css,
    input_css,
    table_css,
)
from .ipodTagNormalizer import IpodLibraryTagSuggestion

_PREVIEW_ROW_LIMIT = 1000


def _panel_css() -> str:
    return (
        f"background: {Colors.SURFACE};"
        f"border: 1px solid {Colors.BORDER_SUBTLE};"
        f"border-radius: {Metrics.BORDER_RADIUS_SM}px;"
    )


def _label_css(color: str) -> str:
    return f"color: {color}; background: transparent; border: none;"


def _line_edit_css() -> str:
    return input_css(radius=Metrics.BORDER_RADIUS_SM, padding="7px 9px")


def _field_chip_css() -> str:
    return chip_btn_css("sm")


def _value_text(value: Any) -> str:
    if value in (None, ""):
        return "Empty"
    text = str(value)
    return text if len(text) <= 160 else f"{text[:157]}..."


def _track_label(track: dict) -> str:
    title = str(track.get("Title") or "").strip() or "Untitled"
    artist = str(track.get("Artist") or "").strip()
    album = str(track.get("Album") or "").strip()
    parts = [title]
    if artist:
        parts.append(artist)
    if album:
        parts.append(album)
    return " - ".join(parts)


class IpodLibraryTagFixDialog(QDialog):
    """Preview and confirm a library-wide iPod tag normalization plan."""

    def __init__(
        self,
        tracks: list[dict],
        suggestion: IpodLibraryTagSuggestion,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._tracks = tracks
        self._suggestion = suggestion
        self._selected_field: str | None = None
        self._search_text = ""
        self._field_buttons: list[QPushButton] = []
        self._change_table: QTableWidget | None = None
        self._preview_status: QLabel | None = None
        self._explanation_expanded = False
        self._explanation_click_targets: set[QObject] = set()
        self._explanation_toggle_icon: QLabel | None = None
        self._explanation_detail_widgets: list[QWidget] = []
        self.setWindowTitle("Normalize iPod Tags")
        self.setModal(True)
        self.setMinimumSize(860, 620)
        self.resize(980, 720)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(Colors.DIALOG_BG))
        self.setPalette(palette)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_preview(), 1)
        outer.addWidget(self._build_explanation())

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()

        cancel = QPushButton("Cancel", self)
        cancel.setStyleSheet(btn_css())
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        apply = QPushButton("Apply", self)
        apply.setStyleSheet(accent_btn_css())
        apply.clicked.connect(self.accept)
        apply.setDefault(True)
        buttons.addWidget(apply)

        outer.addLayout(buttons)

    def _build_explanation(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("tagFixerExplanation")
        panel.setCursor(Qt.CursorShape.PointingHandCursor)
        panel.setStyleSheet(
            f"QFrame#tagFixerExplanation {{"
            f"background:{Colors.SURFACE};"
            f"border:1px solid {Colors.ACCENT_BORDER};"
            f"border-radius:{Metrics.BORDER_RADIUS_MD}px;"
            f"}}"
            f"QFrame#tagFixerExplanation:hover {{"
            f"background:{Colors.SURFACE_ALT};"
            f"}}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(9)

        help_mark = QLabel("?", panel)
        help_mark.setFixedSize(28, 28)
        help_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        help_mark.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        help_mark.setStyleSheet(
            f"color:{Colors.ACCENT_LIGHT};"
            f"background:{Colors.ACCENT_MUTED};"
            f"border:1px solid {Colors.ACCENT_BORDER};"
            f"border-radius:{Metrics.BORDER_RADIUS_SM}px;"
        )
        header.addWidget(help_mark)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(1)
        title = QLabel("What's this for?", panel)
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.DemiBold))
        title.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        title_stack.addWidget(title)

        profile = QLabel(f"Based on {self._suggestion.profile.label}", panel)
        profile.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_XS))
        profile.setStyleSheet(_label_css(Colors.TEXT_TERTIARY))
        title_stack.addWidget(profile)
        header.addLayout(title_stack, 1)

        toggle_icon = QLabel(panel)
        toggle_icon.setFixedSize(14, 28)
        toggle_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toggle_icon.setStyleSheet(_label_css(Colors.TEXT_TERTIARY))
        self._explanation_toggle_icon = toggle_icon
        header.addWidget(toggle_icon, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        compact = QLabel(
            "Cleans metadata for better iPod browse-menu compatibility and fewer split or "
            "duplicated library entries.",
            panel,
        )
        compact.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        compact.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        compact.setWordWrap(True)
        compact.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(compact)

        body = QLabel(
            "iPods understand a limited set of metadata fields and have various quirks in how they group and display tracks based on that metadata. "
            "When fields are missing or formatted in certain ways, albums can be split into multiple albums, artists can be duplicated, and sorting can be inconsistent. "
            "These are the most common issues that cause that, and how this tool fixes them.",
            panel,
        )
        body.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        body.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(body)
        self._explanation_detail_widgets.append(body)

        fixes = self._build_fix_list(panel)
        layout.addWidget(fixes)
        self._explanation_detail_widgets.append(fixes)

        self._register_explanation_click_targets(panel)
        self._sync_explanation_state()
        return panel

    def _build_fix_list(self, parent: QWidget) -> QWidget:
        wrapper = QWidget(parent)
        wrapper.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(6)

        label = QLabel("What this changes", wrapper)
        label.setFont(QFont(MONO_FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.DemiBold))
        label.setStyleSheet(_label_css(Colors.TEXT_TERTIARY))
        layout.addWidget(label)

        for title, detail in (
            (
                "Hidden characters",
                "Removes hidden/control whitespace from metadata fields.",
            ),
            (
                "Sort fields",
                "Keeps Sort values consistent with their display-field counterparts.",
            ),
            (
                "Featured artists",
                "Moves featured artists out of Artist and appends them to Title for cleaner grouping.",
            ),
            (
                "Album Artist fallback",
                "Uses Album Artist as Artist when that gives older iPod menus a more stable album grouping key.",
            ),
            (
                "Album collisions",
                "Makes album names unique when same-title albums would otherwise be merged or split incorrectly.",
            ),
        ):
            layout.addWidget(self._build_fix_row(wrapper, title, detail))

        return wrapper

    def _build_fix_row(self, parent: QWidget, title: str, detail: str) -> QWidget:
        row = QWidget(parent)
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        bullet_slot = QWidget(row)
        bullet_slot.setFixedWidth(5)
        bullet_slot.setStyleSheet("background: transparent;")
        bullet_layout = QVBoxLayout(bullet_slot)
        bullet_layout.setContentsMargins(0, 5, 0, 0)
        bullet_layout.setSpacing(0)

        bullet = QFrame(bullet_slot)
        bullet.setFixedSize(5, 5)
        bullet.setStyleSheet(
            f"background:{Colors.ACCENT_LIGHT};"
            f"border:0px;"
            f"border-radius:2px;"
        )
        bullet_layout.addWidget(bullet, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(bullet_slot, 0, Qt.AlignmentFlag.AlignTop)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(1)

        title_label = QLabel(title, row)
        title_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        title_label.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        text_stack.addWidget(title_label)

        detail_label = QLabel(detail, row)
        detail_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        detail_label.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        detail_label.setWordWrap(True)
        detail_label.setTextFormat(Qt.TextFormat.PlainText)
        text_stack.addWidget(detail_label)

        layout.addLayout(text_stack, 1)
        return row

    def _register_explanation_click_targets(self, widget: QWidget) -> None:
        self._explanation_click_targets.add(widget)
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            self._explanation_click_targets.add(child)
            child.setCursor(Qt.CursorShape.PointingHandCursor)
            child.installEventFilter(self)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        watched = a0
        event = a1
        if (
            watched is not None
            and event is not None
            and watched in self._explanation_click_targets
            and event.type() == QEvent.Type.MouseButtonRelease
        ):
            button = getattr(event, "button", lambda: None)()
            if button == Qt.MouseButton.LeftButton:
                self._toggle_explanation()
                return True
        return super().eventFilter(watched, event)

    def _toggle_explanation(self) -> None:
        self._explanation_expanded = not self._explanation_expanded
        self._sync_explanation_state()

    def _sync_explanation_state(self) -> None:
        for widget in self._explanation_detail_widgets:
            widget.setVisible(self._explanation_expanded)
        icon = self._explanation_toggle_icon
        if icon is None:
            return
        glyph = "chevron-down" if self._explanation_expanded else "chevron-right"
        px = glyph_pixmap(glyph, 14, Colors.TEXT_TERTIARY)
        if px is not None:
            icon.setPixmap(px)
            icon.setText("")
        else:
            icon.setText("v" if self._explanation_expanded else ">")

    def _build_header(self) -> QFrame:
        header = QFrame(self)
        header.setStyleSheet(_panel_css())
        layout = QVBoxLayout(header)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        title = QLabel("Review iPod Tag Fixes", header)
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_XL, QFont.Weight.Bold))
        title.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        layout.addWidget(title)

        changed_track_count = len(self._suggestion.changes_by_track)
        change_count = sum(len(changes) for changes in self._suggestion.changes_by_track.values())
        field_count = len(self._field_counts())
        summary = QLabel(
            f"{changed_track_count:,} tracks, {change_count:,} field edits, {field_count:,} fields touched.",
            header,
        )
        summary.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        summary.setStyleSheet(_label_css(Colors.TEXT_PRIMARY))
        layout.addWidget(summary)

        return header

    def _build_preview(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        layout.addWidget(self._build_field_chips())

        change_panel = QWidget(panel)
        change_layout = QVBoxLayout(change_panel)
        change_layout.setContentsMargins(0, 0, 0, 0)
        change_layout.setSpacing(6)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        search = QLineEdit(change_panel)
        search.setPlaceholderText("Search track, field, current, or suggested value")
        search.setStyleSheet(_line_edit_css())
        search.textChanged.connect(self._on_search_changed)
        controls.addWidget(search, 1)

        clear = QPushButton("Clear", change_panel)
        clear.setStyleSheet(btn_css())
        clear.clicked.connect(self._clear_filters)
        controls.addWidget(clear)
        change_layout.addLayout(controls)

        self._preview_status = QLabel(change_panel)
        self._preview_status.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        self._preview_status.setStyleSheet(_label_css(Colors.TEXT_TERTIARY))
        change_layout.addWidget(self._preview_status)

        self._change_table = self._build_change_table()
        change_layout.addWidget(self._change_table, 1)
        layout.addWidget(change_panel, 1)
        self._refresh_change_table()
        return panel

    def _build_field_chips(self) -> QWidget:
        wrapper = QWidget(self)
        wrapper.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        label = QLabel("Fields", wrapper)
        label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.DemiBold))
        label.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        layout.addWidget(label)

        for field, count in self._field_counts():
            button = QPushButton(f"{field} {count:,}", wrapper)
            button.setStyleSheet(_field_chip_css())
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked, field=field, button=button: self._on_field_chip_clicked(field, button))
            layout.addWidget(button)
            self._field_buttons.append(button)

        layout.addStretch(1)
        return wrapper

    def _build_change_table(self) -> QTableWidget:
        table = QTableWidget(0, 4, self)
        table.setStyleSheet(table_css())
        table.setHorizontalHeaderLabels(["Track", "Field", "Current", "Suggested"])
        vertical_header = table.verticalHeader()
        if vertical_header is not None:
            vertical_header.hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        horizontal_header = table.horizontalHeader()
        if horizontal_header is not None:
            horizontal_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            horizontal_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            horizontal_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            horizontal_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        return table

    def _refresh_change_table(self) -> None:
        table = self._change_table
        if table is None:
            return

        rows, matching_count = self._filtered_preview_rows()
        extra_count = max(0, matching_count - len(rows))
        table.setRowCount(len(rows) + (1 if extra_count else 0))
        for row, (track, key, old_value, new_value) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(_track_label(track)))
            table.setItem(row, 1, QTableWidgetItem(key))
            table.setItem(row, 2, QTableWidgetItem(_value_text(old_value)))
            table.setItem(row, 3, QTableWidgetItem(_value_text(new_value)))

        if extra_count:
            row = len(rows)
            item = QTableWidgetItem(f"{extra_count:,} additional field edits will be applied.")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            table.setItem(row, 0, item)
            table.setSpan(row, 0, 1, 4)

        status = self._preview_status
        if status is not None:
            total = self._total_change_count()
            status.setText(
                f"Showing {len(rows):,} of {matching_count:,} matching edits"
                f" ({total:,} total)."
            )

    def _on_field_chip_clicked(self, field: str, selected_button: QPushButton) -> None:
        if selected_button.isChecked():
            self._selected_field = field
            for button in self._field_buttons:
                if button is not selected_button:
                    button.setChecked(False)
        else:
            self._selected_field = None
        self._refresh_change_table()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.strip()
        self._refresh_change_table()

    def _clear_filters(self) -> None:
        for button in self._field_buttons:
            button.setChecked(False)
        self._selected_field = None
        self._search_text = ""
        for child in self.findChildren(QLineEdit):
            child.clear()
        self._refresh_change_table()

    def _field_counts(self) -> list[tuple[str, int]]:
        counts: Counter[str] = Counter()
        for changes in self._suggestion.changes_by_track.values():
            counts.update(changes.keys())
        return sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))

    def _filtered_preview_rows(self) -> tuple[list[tuple[dict, str, Any, Any]], int]:
        rows: list[tuple[dict, str, Any, Any]] = []
        matching_count = 0
        query = self._search_text
        for track in self._tracks:
            changes = self._suggestion.changes_by_track.get(id(track), {})
            for key, new_value in sorted(changes.items(), key=lambda item: item[0].casefold()):
                old_value = track.get(key)
                if self._selected_field and key != self._selected_field:
                    continue
                if query and not matches_search(
                    query,
                    self._preview_search_text(track, key, old_value, new_value),
                ):
                    continue
                matching_count += 1
                if len(rows) >= _PREVIEW_ROW_LIMIT:
                    continue
                rows.append((track, key, old_value, new_value))
        return rows, matching_count

    def _preview_search_text(self, track: dict, key: str, old_value: Any, new_value: Any) -> str:
        return "\n".join(
            (
                _track_label(track),
                key,
                _value_text(old_value),
                _value_text(new_value),
            )
        )

    def _total_change_count(self) -> int:
        return sum(len(changes) for changes in self._suggestion.changes_by_track.values())
