# Hallmark · pre-emit critique: P5 H5 E5 S5 R5 V4
# Hallmark · genre: modern-minimal · macrostructure: Workbench · theme: iOpenPod runtime · enrichment: none · contrast: pass
"""
PlaylistEditor — Create & edit smart and regular playlists.

Provides:
    SmartPlaylistEditor  — full rule-based editor for smart playlists
    SmartRuleRow         — single editable rule (field + action + value)
    NewPlaylistDialog    — choose smart vs. regular when creating
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from PyQt6.QtCore import QDate, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QWheelEvent
from PyQt6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from iopenpod.itunesdb_shared.constants import PLAYLIST_SORT_ORDER_MAP
from iopenpod.itunesdb_shared.field_base import MAC_EPOCH_OFFSET
from iopenpod.itunesdb_shared.mhod_defs import (
    SPL_ACTION_MAP,
    SPL_AUTHORABLE_FIELD_IDS,
    SPL_CHOICE_FIELD_IDS,
    SPL_CHOICE_UNKNOWN_LABELS,
    SPL_CHOICE_VALUE_MAP,
    SPL_DATE_UNITS_MAP,
    SPL_FIELD_MAP,
    SPL_FIELD_TYPE_MAP,
    SPL_LIMIT_SORT_ALBUM,
    SPL_LIMIT_SORT_ARTIST,
    SPL_LIMIT_SORT_GENRE,
    SPL_LIMIT_SORT_HIGHEST_RATING,
    SPL_LIMIT_SORT_LEAST_OFTEN_PLAYED,
    SPL_LIMIT_SORT_LEAST_RECENTLY_ADDED,
    SPL_LIMIT_SORT_LEAST_RECENTLY_PLAYED,
    SPL_LIMIT_SORT_LOWEST_RATING,
    SPL_LIMIT_SORT_MAP,
    SPL_LIMIT_SORT_MOST_OFTEN_PLAYED,
    SPL_LIMIT_SORT_MOST_RECENTLY_ADDED,
    SPL_LIMIT_SORT_MOST_RECENTLY_PLAYED,
    SPL_LIMIT_SORT_RANDOM,
    SPL_LIMIT_SORT_SONG_NAME,
    SPL_LIMIT_TYPE_GB,
    SPL_LIMIT_TYPE_HOURS,
    SPL_LIMIT_TYPE_MAP,
    SPL_LIMIT_TYPE_MB,
    SPL_LIMIT_TYPE_MINUTES,
    SPL_LIMIT_TYPE_SONGS,
    SPLFT_BINARY_AND,
    SPLFT_BOOLEAN,
    SPLFT_DATE,
    SPLFT_INT,
    SPLFT_STRING,
)
from iopenpod.itunesdb_shared.playlist_kinds import (
    PLAYLIST_KIND_FOLDER,
    PLAYLIST_KIND_PODCAST,
    is_playlist_folder,
)
from iopenpod.itunesdb_shared.playlist_lifecycle import playlist_edit_payload
from iopenpod.itunesdb_shared.playlist_properties import (
    playlist_description_from_row,
    playlist_description_update_fields,
)

from ..glyphs import glyph_icon
from ..styles import (
    FONT_FAMILY,
    Design,
    Metrics,
    accent_btn_css,
    button_css,
    checkbox_css,
    combo_css,
    icon_btn_css,
    input_css,
    make_scroll_area,
    make_separator,
    paint_css,
    panel_css,
    spin_css,
    title_input_css,
)

log = logging.getLogger(__name__)


def _delete_embedded_widget(widget: QWidget | None) -> None:
    if widget is None:
        return
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()


# ─────────────────────────────────────────────────────────────────────────────
# Dropdown data derived from iTunesDB_Shared definitions
# ─────────────────────────────────────────────────────────────────────────────

_FIELD_OPTION_IDS = (
    0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09,
    0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x10, 0x12, 0x16,
    0x17, 0x18, 0x19, 0x1D, 0x1F, 0x23, 0x25, 0x27, 0x28, 0x29,
    0x36, 0x37, 0x39, 0x3C, 0x3E, 0x3F, 0x44,
    0x45, 0x47, 0x4E, 0x4F, 0x50, 0x51, 0x52, 0x53,
    0x59, 0x5A, 0x85, 0x86, 0x9A, 0x9C, 0x9F, 0xA0, 0xA1,
)
_FIELD_LABEL_OVERRIDES = {
    0x02: "Name",
    0x3E: "Video Show",
}
_UNSUPPORTED_FIELD_IDS = frozenset(_FIELD_OPTION_IDS) - SPL_AUTHORABLE_FIELD_IDS

FIELD_DEFS: dict[int, tuple[str, int]] = {
    field_id: (
        _FIELD_LABEL_OVERRIDES.get(field_id, SPL_FIELD_MAP[field_id]),
        SPL_FIELD_TYPE_MAP[field_id],
    )
    for field_id in _FIELD_OPTION_IDS
}

# Actions grouped by field type
STRING_ACTIONS: list[tuple[int, str]] = [
    (0x01000001, "is"),
    (0x03000001, "is not"),
    (0x01000002, "contains"),
    (0x03000002, "does not contain"),
    (0x01000004, "begins with"),
    (0x01000008, "ends with"),
]

INT_ACTIONS: list[tuple[int, str]] = [
    (0x00000001, "is"),
    (0x02000001, "is not"),
    (0x00000010, "is greater than"),
    (0x00000040, "is less than"),
    (0x00000100, "is in the range"),
]

DATE_ACTIONS: list[tuple[int, str]] = [
    (0x00000001, "is"),
    (0x02000001, "is not"),
    (0x00000010, "is after"),
    (0x00000040, "is before"),
    (0x00000100, "is in the range"),
    (0x00000200, "is in the last"),
    (0x02000200, "is not in the last"),
]

BOOLEAN_ACTIONS: list[tuple[int, str]] = [
    (0x00000001, "is true"),
    (0x02000001, "is false"),
]

BINARY_AND_ACTIONS: list[tuple[int, str]] = [
    (0x00000400, "includes"),
    (0x02000400, "excludes"),
]

PLAYLIST_ACTIONS: list[tuple[int, str]] = [
    (0x00000001, "is"),
    (0x02000001, "is not"),
]

CHOICE_ACTIONS: list[tuple[int, str]] = [
    (0x00000001, "is"),
    (0x02000001, "is not"),
]

LOCATION_CHOICE_ACTIONS: list[tuple[int, str]] = [
    (0x00000400, "is"),
    (0x02000400, "is not"),
]

DATE_UNITS: list[tuple[int, str]] = [
    (unit, SPL_DATE_UNITS_MAP[unit])
    for unit in (86400, 604800, 2628000)
]

LIMIT_TYPES: list[tuple[int, str]] = [
    (
        limit_type,
        "items" if limit_type == SPL_LIMIT_TYPE_SONGS else SPL_LIMIT_TYPE_MAP[limit_type],
    )
    for limit_type in (
        SPL_LIMIT_TYPE_SONGS,
        SPL_LIMIT_TYPE_MINUTES,
        SPL_LIMIT_TYPE_HOURS,
        SPL_LIMIT_TYPE_MB,
        SPL_LIMIT_TYPE_GB,
    )
]

LIMIT_SORTS: list[tuple[int, str]] = [
    (
        limit_sort,
        "name"
        if limit_sort == SPL_LIMIT_SORT_SONG_NAME
        else SPL_LIMIT_SORT_MAP[limit_sort].replace("_", " "),
    )
    for limit_sort in (
        SPL_LIMIT_SORT_RANDOM,
        SPL_LIMIT_SORT_SONG_NAME,
        SPL_LIMIT_SORT_ALBUM,
        SPL_LIMIT_SORT_ARTIST,
        SPL_LIMIT_SORT_GENRE,
        SPL_LIMIT_SORT_MOST_RECENTLY_ADDED,
        SPL_LIMIT_SORT_LEAST_RECENTLY_ADDED,
        SPL_LIMIT_SORT_MOST_OFTEN_PLAYED,
        SPL_LIMIT_SORT_LEAST_OFTEN_PLAYED,
        SPL_LIMIT_SORT_MOST_RECENTLY_PLAYED,
        SPL_LIMIT_SORT_LEAST_RECENTLY_PLAYED,
        SPL_LIMIT_SORT_HIGHEST_RATING,
        SPL_LIMIT_SORT_LOWEST_RATING,
    )
]


def _signed_i64(value: int) -> int:
    value = int(value or 0)
    if value >= (1 << 63):
        return value - (1 << 64)
    return value


def _relative_date_count(rule: dict) -> int:
    raw_date = int(rule.get("from_date", 0) or 0)
    if raw_date:
        return abs(raw_date)

    raw_value = _signed_i64(rule.get("from_value", 0) or 0)
    count = abs(raw_value)
    from_units = int(rule.get("from_units", 0) or 0)
    if from_units > 1 and count >= from_units and count % from_units == 0:
        return count // from_units
    return count


def _date_from_mac_timestamp(value: int) -> QDate:
    if not value:
        return QDate.currentDate()
    unix_ts = max(0, int(value) - MAC_EPOCH_OFFSET)
    dt = datetime.fromtimestamp(unix_ts, tz=UTC)
    return QDate(dt.year, dt.month, dt.day)


def _qdate_to_mac_start(date_value: QDate) -> int:
    dt = datetime(
        date_value.year(),
        date_value.month(),
        date_value.day(),
        tzinfo=UTC,
    )
    return int(dt.timestamp()) + MAC_EPOCH_OFFSET


def _qdate_to_mac_end(date_value: QDate) -> int:
    return _qdate_to_mac_start(date_value) + 86399


def _int_display_value(field_id: int, raw_value: int) -> int:
    if field_id in (0x19, 0x5A):  # Rating / Album Rating, raw stars * 20
        return max(0, min(5, int(raw_value) // 20))
    if field_id == 0x0C:  # Size, raw bytes
        return int(raw_value) // (1024 * 1024)
    return int(raw_value)


def _int_raw_value(field_id: int, display_value: int, *, upper_bound: bool = False) -> int:
    if field_id in (0x19, 0x5A):
        raw = max(0, min(5, int(display_value))) * 20
        return raw + 9 if upper_bound else raw
    if field_id == 0x0C:
        return max(0, int(display_value)) * 1024 * 1024
    return int(display_value)


# ─────────────────────────────────────────────────────────────────────────────
# Shared stylesheet helpers
# ─────────────────────────────────────────────────────────────────────────────

def _combo_css() -> str:
    return combo_css(padding="4px 8px", min_height=22, font_size=Metrics.FONT_LG)


def _input_css() -> str:
    return input_css(padding="4px 8px", min_height=22, font_size=Metrics.FONT_LG)


def _spinbox_css() -> str:
    return spin_css(padding="4px 8px", min_height=22, font_size=Metrics.FONT_LG)


def _checkbox_css() -> str:
    return checkbox_css(Metrics.FONT_LG)


def _label_css(color: str) -> str:
    return f"color: {color}; background: transparent; border: none;"


def _title_input_css(min_content_height: int) -> str:
    return title_input_css(min_height=min_content_height)


def _configure_title_input(line_edit: QLineEdit) -> None:
    """Keep title glyphs clear after the application QSS cascade is applied."""
    line_edit.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
    min_content_height = max(
        Design.CONTROL_HEIGHT_LG,
        line_edit.fontMetrics().height() + (Design.GRID * 2),
    )
    line_edit.setStyleSheet(_title_input_css(min_content_height))
    line_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def _editor_panel_css(object_name: str) -> str:
    return panel_css(
        object_name,
        bg=paint_css("surface.inset"),
        radius=Metrics.BORDER_RADIUS_SM,
    )


def _editor_notice_css(object_name: str) -> str:
    return panel_css(
        object_name,
        bg=paint_css("notice.info.fill"),
        border=f"1px solid {paint_css('notice.info.border')}",
        radius=Metrics.BORDER_RADIUS_SM,
    )


def _section_toolbar(text: str, *actions: QPushButton) -> QWidget:
    widget = QWidget()
    widget.setStyleSheet("background: transparent; border: none;")
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    label = QLabel(text, widget)
    label.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG, QFont.Weight.DemiBold))
    label.setStyleSheet(_label_css(paint_css("text.primary")))
    layout.addWidget(label)
    layout.addStretch()
    for action in actions:
        layout.addWidget(action)
    return widget


def _section_label_style() -> str:
    return (
        f"color: {paint_css('text.tertiary')}; background: transparent; border: none; "
        f"font-size: {Metrics.FONT_SM}pt; font-weight: bold;"
    )


def _rule_action_btn_css() -> str:
    return (
        button_css("secondary", "sm")
        + f"""
        QPushButton:focus {{
            border-color: {paint_css("focus.border")};
        }}
    """
    )


def _remove_btn_css() -> str:
    return (
        icon_btn_css(
            bg=paint_css("surface.raised"),
            bg_hover=paint_css("status.danger.subtle_fill"),
            bg_press=paint_css("status.danger.hover_fill"),
            fg=paint_css("status.danger.text"),
            border=f"1px solid {paint_css('border.subtle')}",
        )
        + f"""
        QPushButton:focus {{
            border-color: {paint_css("focus.border")};
        }}
    """
    )


class _RuleComboBox(QComboBox):
    """Combo box that lets wheel events scroll the rule list."""

    def wheelEvent(self, e: QWheelEvent | None) -> None:
        if e is not None:
            e.ignore()


class _RuleSpinBox(QSpinBox):
    """Spin box that lets wheel events scroll the rule list."""

    def wheelEvent(self, e: QWheelEvent | None) -> None:
        if e is not None:
            e.ignore()


class _RuleDateEdit(QDateEdit):
    """Date edit that lets wheel events scroll the rule list."""

    def wheelEvent(self, e: QWheelEvent | None) -> None:
        if e is not None:
            e.ignore()


# ─────────────────────────────────────────────────────────────────────────────
# SmartRuleRow — one editable rule
# ─────────────────────────────────────────────────────────────────────────────

class SmartRuleRow(QFrame):
    """Editable row for a single smart playlist rule.

    Layout:
        [Field ▼] [Action ▼] [Value ...] [×]

    The value widget changes depending on field type:
     - String:     QLineEdit
     - Int:        QSpinBox (or two for range)
     - Date:       QSpinBox + unit combo
     - Boolean:    (no value; action carries true/false)
     - Binary AND: QComboBox with media type flags
     - Playlist:   QComboBox with playlist names
    """

    remove_clicked = pyqtSignal(object)  # emits self
    changed = pyqtSignal()               # any field changed

    def __init__(
        self,
        parent: QWidget | None = None,
        playlist_options: list[tuple[int, str]] | None = None,
    ):
        super().__init__(parent)
        self.setStyleSheet("QFrame { background: transparent; border: none; }")
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._playlist_options = playlist_options or []
        self._original_rule: dict = {}

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(8)

        # ── Field selector ──
        self.field_combo = _RuleComboBox()
        self.field_combo.setStyleSheet(_combo_css())
        self.field_combo.setMinimumWidth(120)
        self.field_combo.setMaximumWidth(160)
        for fid, (name, _ftype) in sorted(FIELD_DEFS.items(), key=lambda x: x[1][0]):
            label = f"{name} (unsupported)" if fid in _UNSUPPORTED_FIELD_IDS else name
            self.field_combo.addItem(label, fid)
            if fid in _UNSUPPORTED_FIELD_IDS:
                self.field_combo.setItemData(
                    self.field_combo.count() - 1,
                    0,
                    Qt.ItemDataRole.UserRole - 1,
                )
        self._layout.addWidget(self.field_combo)

        # ── Action selector ──
        self.action_combo = _RuleComboBox()
        self.action_combo.setStyleSheet(_combo_css())
        self.action_combo.setMinimumWidth(130)
        self.action_combo.setMaximumWidth(180)
        self._layout.addWidget(self.action_combo)

        # ── Value area (container swapped based on field type) ──
        self._value_container = QWidget()
        self._value_container.setStyleSheet("background: transparent; border: none;")
        self._value_layout = QHBoxLayout(self._value_container)
        self._value_layout.setContentsMargins(0, 0, 0, 0)
        self._value_layout.setSpacing(4)
        self._layout.addWidget(self._value_container, stretch=1)

        # ── Remove button ──
        self.remove_btn = QPushButton()
        _close_ic = glyph_icon("trash", 14, paint_css("status.danger.text"))
        if _close_ic:
            self.remove_btn.setIcon(_close_ic)
        else:
            self.remove_btn.setText("−")
        self.remove_btn.setFixedSize(
            Design.ICON_BUTTON_SIZE,
            Design.ICON_BUTTON_SIZE,
        )
        self.remove_btn.setStyleSheet(_remove_btn_css())
        self.remove_btn.setToolTip("Delete rule")
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self))
        self._layout.addWidget(self.remove_btn)

        # Current value widgets (for cleanup)
        self._value_widgets: list[QWidget] = []
        self._current_field_type: int = SPLFT_STRING

        # Wiring
        self.field_combo.currentIndexChanged.connect(self._on_field_changed)
        self.action_combo.currentIndexChanged.connect(lambda: self.changed.emit())

        # Initialize
        self._on_field_changed()

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def set_playlist_options(self, playlist_options: list[tuple[int, str]]) -> None:
        self._playlist_options = playlist_options
        if self.field_combo.currentData() == 0x28:
            current_combo = self._find_value_combo()
            current = current_combo.currentData() if current_combo else 0
            self._on_field_changed()
            combo = self._find_value_combo()
            if combo:
                idx = combo.findData(current)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

    def get_rule_data(self) -> dict:
        """Return rule dict compatible with SmartPlaylistRule fields.

        Includes both raw IDs (field_id, action_id) for the writer and
        human-readable keys (field, action, field_type) for the formatter.
        """
        fid = self.field_combo.currentData()
        aid = self.action_combo.currentData()
        field_name, ft = FIELD_DEFS.get(fid, ("Unknown", SPLFT_STRING))

        data: dict = dict(self._original_rule)
        same_rule_kind = (
            fid == self._original_rule.get("field_id")
            and aid == self._original_rule.get("action_id")
        )
        raw_defaults = {
            "string_value": None,
            "from_value": 0,
            "to_value": 0,
            "from_date": 0,
            "to_date": 0,
            "from_units": 0,
            "to_units": 0,
            "unk052": 0,
            "unk056": 0,
            "unk060": 0,
            "unk064": 0,
            "unk068": 0,
        }
        if same_rule_kind:
            for key, value in raw_defaults.items():
                data.setdefault(key, value)
        else:
            data.update(raw_defaults)
        data.update({
            "field_id": fid or 0x02,
            "action_id": aid or 0x00000001,
            # Human-readable keys expected by format_smart_rule()
            "field": self.field_combo.currentText() or field_name,
            "action": self.action_combo.currentText() or "?",
            "field_type": ft,
        })

        if ft == SPLFT_STRING:
            w: QLineEdit | None = self._find_widget(QLineEdit)  # type: ignore[assignment]
            data["string_value"] = w.text() if w else ""
        elif fid in SPL_CHOICE_FIELD_IDS:
            combo = self._find_value_combo()
            if combo:
                value = combo.currentData()
                data["from_value"] = int(value) if isinstance(value, int) else 0
                data["to_value"] = data["from_value"]
                data["from_units"] = 1
                data["to_units"] = 1
        elif ft == SPLFT_INT:
            spins: list[QSpinBox] = self._find_widgets(QSpinBox)  # type: ignore[assignment]
            if spins:
                data["from_value"] = _int_raw_value(fid, spins[0].value())
            if aid in (0x00000100, 0x02000100) and len(spins) > 1:
                data["to_value"] = _int_raw_value(fid, spins[1].value(), upper_bound=True)
            if not same_rule_kind:
                data["from_units"] = 1
                data["to_units"] = 1
            # Rating special case — compute star values for formatter
            if fid == 0x19:  # Rating
                data["from_value_stars"] = spins[0].value() if spins else 0
                data["to_value_stars"] = spins[1].value() if len(spins) > 1 else 0
        elif ft == SPLFT_DATE:
            if aid in (0x00000200, 0x02000200):
                spin: QSpinBox | None = self._find_widget(QSpinBox)  # type: ignore[assignment]
                if spin:
                    data["from_date"] = -abs(spin.value())
                date_unit_combo = self._find_value_combo()
                if date_unit_combo:
                    data["from_units"] = date_unit_combo.currentData() or 86400
                    data["to_units"] = date_unit_combo.currentData() or 86400
                    data["units_name"] = date_unit_combo.currentText() or ""
            else:
                date_edits: list[QDateEdit] = self._find_widgets(QDateEdit)  # type: ignore[assignment]
                if date_edits:
                    data["from_value"] = _qdate_to_mac_start(date_edits[0].date())
                    data["from_units"] = 1
                    if aid == 0x00000100 and len(date_edits) > 1:
                        data["to_value"] = _qdate_to_mac_end(date_edits[1].date())
                    else:
                        data["to_value"] = _qdate_to_mac_end(date_edits[0].date())
                    data["to_units"] = 1
        elif ft == SPLFT_BOOLEAN:
            pass  # no value
        elif ft == SPLFT_BINARY_AND:
            combo = self._find_value_combo()
            if combo:
                data["from_value"] = combo.currentData() or 0x01
        return data

    def set_rule_data(self, rule: dict) -> None:
        """Populate the row from a parsed rule dict."""
        self._original_rule = dict(rule)
        fid = rule.get("field_id", 0x02)
        aid = rule.get("action_id", 0x01000002)

        # Set field
        idx = self.field_combo.findData(fid)
        if idx >= 0:
            self.field_combo.setCurrentIndex(idx)

        # Set action (after field change triggers action list rebuild)
        idx = self.action_combo.findData(aid)
        if idx < 0:
            label = SPL_ACTION_MAP.get(aid, f"action 0x{aid:08X}")
            self.action_combo.addItem(label, aid)
            idx = self.action_combo.findData(aid)
        if idx >= 0:
            self.action_combo.setCurrentIndex(idx)

        # Set value
        ft = FIELD_DEFS.get(fid, ("", SPLFT_STRING))[1]
        if fid in SPL_CHOICE_FIELD_IDS:
            combo = self._find_value_combo()
            if combo:
                val = rule.get("from_value", 0)
                idx = combo.findData(val)
                if idx < 0:
                    combo.addItem(f"raw value {val}", val)
                    idx = combo.findData(val)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
        elif ft == SPLFT_STRING:
            w_le: QLineEdit | None = self._find_widget(QLineEdit)  # type: ignore[assignment]
            if w_le:
                w_le.setText(rule.get("string_value", "") or "")
        elif ft == SPLFT_INT:
            spins_sb: list[QSpinBox] = self._find_widgets(QSpinBox)  # type: ignore[assignment]
            if spins_sb:
                v = _int_display_value(fid, rule.get("from_value", 0))
                spins_sb[0].setValue(max(spins_sb[0].minimum(), min(v, spins_sb[0].maximum())))
            if len(spins_sb) > 1:
                v2 = _int_display_value(fid, rule.get("to_value", 0))
                spins_sb[1].setValue(max(spins_sb[1].minimum(), min(v2, spins_sb[1].maximum())))
        elif ft == SPLFT_DATE:
            spin_sb: QSpinBox | None = self._find_widget(QSpinBox)  # type: ignore[assignment]
            date_edits: list[QDateEdit] = self._find_widgets(QDateEdit)  # type: ignore[assignment]
            if spin_sb:
                raw = _relative_date_count(rule)
                spin_sb.setValue(max(spin_sb.minimum(), min(raw, spin_sb.maximum())))
            unit_combo = self._find_value_combo()
            if unit_combo:
                units = rule.get("from_units", 86400) or 86400
                idx = unit_combo.findData(units)
                if idx >= 0:
                    unit_combo.setCurrentIndex(idx)
            if date_edits and aid not in (0x00000200, 0x02000200):
                date_edits[0].setDate(_date_from_mac_timestamp(rule.get("from_value", 0)))
                if len(date_edits) > 1:
                    date_edits[1].setDate(_date_from_mac_timestamp(rule.get("to_value", 0)))
            self._update_date_value_visibility()
        elif ft == SPLFT_BINARY_AND:
            combo = self._find_value_combo()
            if combo:
                val = rule.get("from_value", 0x01)
                idx = combo.findData(val)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

    # ─────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────

    def _on_field_changed(self) -> None:
        """Rebuild action list and value widgets when field changes."""
        fid = self.field_combo.currentData()
        if fid is None:
            return
        ft = FIELD_DEFS.get(fid, ("", SPLFT_STRING))[1]

        # Rebuild actions
        self.action_combo.blockSignals(True)
        self.action_combo.clear()
        actions = self._actions_for_field(fid, ft)
        for aid, label in actions:
            self.action_combo.addItem(label, aid)
        self.action_combo.blockSignals(False)

        # Rebuild value widgets
        self._clear_value_widgets()
        self._current_field_type = ft

        if fid in SPL_CHOICE_FIELD_IDS:
            combo = _RuleComboBox()
            combo.setStyleSheet(_combo_css())
            combo.setMinimumWidth(150)
            self._populate_choice_combo(combo, fid)
            combo.currentIndexChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(combo)

        elif ft == SPLFT_STRING:
            le = QLineEdit()
            le.setPlaceholderText("value")
            le.setStyleSheet(_input_css())
            le.setMinimumWidth(120)
            le.textChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(le)

        elif ft == SPLFT_INT:
            spin = _RuleSpinBox()
            max_value = 5 if fid in (0x19, 0x5A) else 999999
            if fid == 0x0C:
                max_value = 9999999
            spin.setRange(0, max_value)
            spin.setStyleSheet(_spinbox_css())
            spin.setMinimumWidth(80)
            spin.valueChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(spin)

            # "in range" needs a second spin
            self._range_label = QLabel("to")
            self._range_label.setStyleSheet(
                f"color: {paint_css('text.secondary')}; background: transparent; border: none;"
            )
            self._range_label.setVisible(False)
            self._add_value_widget(self._range_label)

            spin2 = _RuleSpinBox()
            spin2.setRange(0, max_value)
            spin2.setStyleSheet(_spinbox_css())
            spin2.setMinimumWidth(80)
            spin2.setVisible(False)
            spin2.valueChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(spin2)

            # Watch for range action
            self.action_combo.currentIndexChanged.connect(self._update_range_visibility)

        elif ft == SPLFT_DATE:
            date_edit = _RuleDateEdit()
            date_edit.setCalendarPopup(True)
            date_edit.setDate(QDate.currentDate())
            date_edit.setStyleSheet(_combo_css())
            date_edit.dateChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(date_edit)

            self._range_label = QLabel("to")
            self._range_label.setStyleSheet(
                f"color: {paint_css('text.secondary')}; background: transparent; border: none;"
            )
            self._add_value_widget(self._range_label)

            date_edit_2 = _RuleDateEdit()
            date_edit_2.setCalendarPopup(True)
            date_edit_2.setDate(QDate.currentDate())
            date_edit_2.setStyleSheet(_combo_css())
            date_edit_2.dateChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(date_edit_2)

            spin = _RuleSpinBox()
            spin.setRange(1, 99999)
            spin.setValue(30)
            spin.setStyleSheet(_spinbox_css())
            spin.setMinimumWidth(70)
            spin.valueChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(spin)

            unit_combo = _RuleComboBox()
            unit_combo.setStyleSheet(_combo_css())
            for uid, uname in DATE_UNITS:
                unit_combo.addItem(uname, uid)
            unit_combo.currentIndexChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(unit_combo)

            self.action_combo.currentIndexChanged.connect(self._update_date_value_visibility)
            self._update_date_value_visibility()

        elif ft == SPLFT_BOOLEAN:
            # No value needed; the action ID carries true/false.
            placeholder = QLabel("")
            placeholder.setStyleSheet("background: transparent; border: none;")
            self._add_value_widget(placeholder)

        elif ft == SPLFT_BINARY_AND:
            combo = _RuleComboBox()
            combo.setStyleSheet(_combo_css())
            combo.setMinimumWidth(120)
            for flag_val, flag_name in SPL_CHOICE_VALUE_MAP.get(0x3C, ()):
                combo.addItem(flag_name, flag_val)
            combo.currentIndexChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(combo)

        self.changed.emit()

    def _update_range_visibility(self) -> None:
        """Show/hide the second spin box for range actions."""
        if not hasattr(self, "_range_label"):
            return
        try:
            # Guard against deleted C++ objects
            import sip  # type: ignore[import-untyped]
            if sip.isdeleted(self._range_label):  # type: ignore[arg-type]
                return
        except (ImportError, TypeError):
            pass
        try:
            aid = self.action_combo.currentData()
            is_range = aid in (0x00000100, 0x02000100)
            spins = self._find_widgets(QSpinBox)
            if len(spins) > 1:
                spins[1].setVisible(is_range)
            self._range_label.setVisible(is_range)
        except RuntimeError:
            pass  # widget already deleted

    def _update_date_value_visibility(self) -> None:
        """Switch date rows between absolute-date and relative-count controls."""
        action_id = self.action_combo.currentData()
        is_relative = action_id in (0x00000200, 0x02000200)
        is_range = action_id == 0x00000100

        date_edits = self._find_widgets(QDateEdit)
        spins = self._find_widgets(QSpinBox)
        combo = self._find_value_combo()

        for index, date_edit in enumerate(date_edits):
            date_edit.setVisible(not is_relative and (index == 0 or is_range))
        if hasattr(self, "_range_label"):
            self._range_label.setVisible(not is_relative and is_range)
        for spin in spins:
            spin.setVisible(is_relative)
        if combo is not None:
            combo.setVisible(is_relative)

    def _actions_for_field(self, fid: int, ft: int) -> list[tuple[int, str]]:
        if fid == 0x85:
            return LOCATION_CHOICE_ACTIONS
        if fid in SPL_CHOICE_FIELD_IDS:
            return CHOICE_ACTIONS
        match ft:
            case 1:
                return STRING_ACTIONS
            case 2:
                return INT_ACTIONS
            case 3:
                return BOOLEAN_ACTIONS
            case 4:
                return DATE_ACTIONS
            case 5:
                return PLAYLIST_ACTIONS
            case 7:
                return BINARY_AND_ACTIONS
            case _:
                return INT_ACTIONS

    def _populate_choice_combo(self, combo: QComboBox, fid: int) -> None:
        if fid == 0x28:
            combo.addItem("(select playlist)", 0)
            for playlist_id, title in self._playlist_options:
                combo.addItem(title, playlist_id)
            return

        for raw_value, label in SPL_CHOICE_VALUE_MAP.get(fid, ()):
            combo.addItem(label, raw_value)

        for label in SPL_CHOICE_UNKNOWN_LABELS.get(fid, ()):
            combo.addItem(f"{label} (raw value unknown)", None)
            combo.setItemData(combo.count() - 1, 0, Qt.ItemDataRole.UserRole - 1)

    def _clear_value_widgets(self) -> None:
        # Disconnect the range visibility slot if it was connected
        try:
            self.action_combo.currentIndexChanged.disconnect(self._update_range_visibility)
        except (TypeError, RuntimeError):
            pass
        try:
            self.action_combo.currentIndexChanged.disconnect(self._update_date_value_visibility)
        except (TypeError, RuntimeError):
            pass
        if hasattr(self, "_range_label"):
            del self._range_label
        for w in self._value_widgets:
            _delete_embedded_widget(w)
        self._value_widgets.clear()

    def _add_value_widget(self, w: QWidget) -> None:
        self._value_layout.addWidget(w)
        self._value_widgets.append(w)

    def _find_widget(self, cls: type):
        for w in self._value_widgets:
            if isinstance(w, cls):
                return w
        return None

    def _find_widgets(self, cls: type) -> list:
        return [w for w in self._value_widgets if isinstance(w, cls)]

    def _find_value_combo(self) -> QComboBox | None:
        """Find the value combo box (not field_combo or action_combo)."""
        for w in self._value_widgets:
            if isinstance(w, QComboBox):
                return w
        return None


# ─────────────────────────────────────────────────────────────────────────────
# SmartPlaylistEditor — full editor panel
# ─────────────────────────────────────────────────────────────────────────────

class SmartRuleGroup(QFrame):
    """Recursive ALL/ANY container used by the smart-playlist editor."""

    remove_clicked = pyqtSignal(object)
    changed = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        playlist_options: list[tuple[int, str]] | None = None,
        depth: int = 1,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("smartRuleGroup")
        self._depth = max(1, int(depth))
        group_fill = paint_css("table.row.alternate_fill") if self._depth % 2 else paint_css("table.row.fill")
        self.setStyleSheet(f"QFrame#smartRuleGroup {{ background: {group_fill}; border: 1px solid {paint_css('border.subtle')}; border-radius: {Metrics.BORDER_RADIUS_SM}px; }}")
        self.setProperty("ruleGroupDepth", self._depth)
        self._playlist_options = playlist_options or []
        self._items: list[SmartRuleRow | SmartRuleGroup] = []
        self._rule_metadata: dict = {}
        self._group_metadata: dict = {"unk004": 0x00010001}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        label = QLabel("Match")
        label.setStyleSheet(_label_css(paint_css("text.secondary")))
        header.addWidget(label)

        self.conjunction_combo = _RuleComboBox()
        self.conjunction_combo.setObjectName("smartRuleGroupConjunction")
        self.conjunction_combo.setStyleSheet(_combo_css())
        self.conjunction_combo.addItem("all", "AND")
        self.conjunction_combo.addItem("any", "OR")
        self.conjunction_combo.setFixedWidth(72)
        self.conjunction_combo.currentIndexChanged.connect(self.changed.emit)
        header.addWidget(self.conjunction_combo)

        suffix = QLabel("of these")
        suffix.setStyleSheet(_label_css(paint_css("text.secondary")))
        header.addWidget(suffix)
        header.addStretch()

        self.add_rule_btn = QPushButton("Add Rule")
        self.add_rule_btn.setObjectName("smartRuleGroupAddRule")
        self.add_rule_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        add_rule_icon = glyph_icon("plus", 14, paint_css("text.secondary"))
        if add_rule_icon is not None:
            self.add_rule_btn.setIcon(add_rule_icon)
            self.add_rule_btn.setIconSize(QSize(14, 14))
        self.add_rule_btn.setStyleSheet(_rule_action_btn_css())
        self.add_rule_btn.setToolTip("Add a rule to this group")
        self.add_rule_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_rule_btn.clicked.connect(self.add_rule)
        header.addWidget(self.add_rule_btn)

        self.add_group_btn = QPushButton("Add Group")
        self.add_group_btn.setObjectName("smartRuleGroupAddGroup")
        self.add_group_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        add_group_icon = glyph_icon("folder", 14, paint_css("text.secondary"))
        if add_group_icon is not None:
            self.add_group_btn.setIcon(add_group_icon)
            self.add_group_btn.setIconSize(QSize(14, 14))
        self.add_group_btn.setStyleSheet(_rule_action_btn_css())
        self.add_group_btn.setToolTip("Add a nested rule group")
        self.add_group_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_group_btn.clicked.connect(self.add_group)
        header.addWidget(self.add_group_btn)

        self.remove_btn = QPushButton()
        self.remove_btn.setObjectName("smartRuleGroupRemove")
        remove_icon = glyph_icon("trash", 14, paint_css("status.danger.text"))
        if remove_icon is not None:
            self.remove_btn.setIcon(remove_icon)
            self.remove_btn.setIconSize(QSize(14, 14))
        else:
            self.remove_btn.setText("−")
        self.remove_btn.setFixedSize(
            Design.ICON_BUTTON_SIZE,
            Design.ICON_BUTTON_SIZE,
        )
        self.remove_btn.setStyleSheet(_remove_btn_css())
        self.remove_btn.setToolTip("Delete group")
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.clicked.connect(lambda: self.remove_clicked.emit(self))
        header.addWidget(self.remove_btn)
        layout.addLayout(header)

        self._items_widget = QWidget(self)
        self._items_widget.setStyleSheet("background: transparent; border: none;")
        self._items_layout = QVBoxLayout(self._items_widget)
        self._items_layout.setContentsMargins(16, 0, 0, 0)
        self._items_layout.setSpacing(4)
        self._items_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._items_widget)

    def set_playlist_options(self, playlist_options: list[tuple[int, str]]) -> None:
        self._playlist_options = playlist_options
        for item in self._items:
            item.set_playlist_options(playlist_options)

    def set_rule_data(self, rule: dict) -> None:
        """Load one parser group wrapper, retaining its opaque header fields."""
        self._rule_metadata = {key: value for key, value in rule.items() if key != "group"}
        raw_group = rule.get("group")
        group = raw_group if isinstance(raw_group, dict) else {}
        self._group_metadata = {
            key: value for key, value in group.items() if key not in ("conjunction", "rules")
        }
        conjunction = group.get("conjunction", "AND")
        if isinstance(conjunction, int):
            conjunction = "OR" if conjunction == 1 else "AND"
        index = self.conjunction_combo.findData(str(conjunction).upper())
        self.conjunction_combo.setCurrentIndex(max(0, index))
        self.clear_rules()
        rules = group.get("rules", [])
        if isinstance(rules, list):
            for child in rules:
                if isinstance(child, dict):
                    self._add_rule_data(child)

    def get_rule_data(self) -> dict:
        group = dict(self._group_metadata)
        group.update({
            "conjunction": self.conjunction_combo.currentData() or "AND",
            "rules": [item.get_rule_data() for item in self._items],
        })
        if "rule_count" in group:
            group["rule_count"] = len(group["rules"])
        wrapper = dict(self._rule_metadata)
        wrapper.setdefault("field_id", 0)
        wrapper.setdefault("action_id", 1)
        wrapper.setdefault("group_marker", 0x01000000)
        wrapper.setdefault("header_bytes", b"\0" * 40)
        wrapper["group"] = group
        return wrapper

    def add_rule(self) -> SmartRuleRow:
        row = SmartRuleRow(playlist_options=self._playlist_options)
        row.remove_clicked.connect(self._remove_item)
        row.changed.connect(self.changed.emit)
        self._items_layout.addWidget(row)
        self._items.append(row)
        self.changed.emit()
        return row

    def add_group(self) -> SmartRuleGroup:
        group = SmartRuleGroup(
            playlist_options=self._playlist_options,
            depth=self._depth + 1,
        )
        group.remove_clicked.connect(self._remove_item)
        group.changed.connect(self.changed.emit)
        group.add_rule()
        self._items_layout.addWidget(group)
        self._items.append(group)
        self.changed.emit()
        return group

    def clear_rules(self) -> None:
        for item in self._items:
            _delete_embedded_widget(item)
        self._items.clear()

    def _add_rule_data(self, rule: dict) -> SmartRuleRow | SmartRuleGroup:
        if isinstance(rule.get("group"), dict):
            group = SmartRuleGroup(
                playlist_options=self._playlist_options,
                depth=self._depth + 1,
            )
            group.remove_clicked.connect(self._remove_item)
            group.changed.connect(self.changed.emit)
            group.set_rule_data(rule)
            item: SmartRuleRow | SmartRuleGroup = group
        else:
            row = SmartRuleRow(playlist_options=self._playlist_options)
            row.remove_clicked.connect(self._remove_item)
            row.changed.connect(self.changed.emit)
            row.set_rule_data(rule)
            item = row
        self._items_layout.addWidget(item)
        self._items.append(item)
        return item

    def _remove_item(self, item: SmartRuleRow | SmartRuleGroup) -> None:
        if item not in self._items:
            return
        self._items.remove(item)
        _delete_embedded_widget(item)
        self.changed.emit()


class SmartPlaylistEditor(QFrame):
    """Full smart playlist editor replacing the info card when editing."""

    saved = pyqtSignal(dict)      # emits the full playlist dict
    cancelled = pyqtSignal()
    preview_changed = pyqtSignal()
    _RULES_PANEL_MIN_HEIGHT = 220
    _RULES_SCROLL_MIN_HEIGHT = 150

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("smartPlaylistEditor")
        self.setStyleSheet(f"QFrame#smartPlaylistEditor {{ background: {paint_css('surface.default')}; border: none; }}")

        self._editing_playlist: dict | None = None  # None → new playlist
        self._playlist_rows: list[dict] = []
        self._playlist_options: list[tuple[int, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── Identity + actions ─────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Playlist Name")
        _configure_title_input(self.name_input)
        title_col.addWidget(self.name_input)

        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("Playlist Description")
        self.description_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.description_input.setStyleSheet(_input_css())
        title_col.addWidget(self.description_input)

        header.addLayout(title_col, 1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(button_css("secondary", "sm"))
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save Playlist")
        self.save_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.Bold))
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _save_ic = glyph_icon("check-circle", 14, paint_css("control.primary.text"))
        if _save_ic:
            self.save_btn.setIcon(_save_ic)
            self.save_btn.setIconSize(QSize(14, 14))
        self.save_btn.setStyleSheet(accent_btn_css())
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        header.addLayout(btn_row)
        root.addLayout(header)
        root.addWidget(make_separator())

        body = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        self._body_layout = body

        rules_column = QVBoxLayout()
        rules_column.setContentsMargins(0, 0, 0, 0)
        rules_column.setSpacing(8)

        settings_column_widget = QWidget()
        settings_column_widget.setObjectName("smartPlaylistSettingsRail")
        settings_column_widget.setStyleSheet("background: transparent; border: none;")
        settings_column_widget.setMinimumWidth(320)
        settings_column_widget.setMaximumWidth(420)
        self._settings_rail = settings_column_widget
        settings_column = QVBoxLayout(settings_column_widget)
        settings_column.setContentsMargins(0, 0, 0, 0)
        settings_column.setSpacing(8)

        rules_panel = QFrame()
        rules_panel.setObjectName("smartPlaylistRulesPanel")
        rules_panel.setStyleSheet(
            panel_css(
                "smartPlaylistRulesPanel",
                bg=paint_css("table.row.fill"),
                border=f"1px solid {paint_css('border.subtle')}",
                radius=Metrics.BORDER_RADIUS_SM,
            )
        )
        rules_panel.setMinimumHeight(self._RULES_PANEL_MIN_HEIGHT)
        rules_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rules_panel_layout = QVBoxLayout(rules_panel)
        rules_panel_layout.setContentsMargins(12, 12, 12, 12)
        rules_panel_layout.setSpacing(8)

        conj_row = QHBoxLayout()
        conj_row.setContentsMargins(0, 0, 0, 0)
        conj_row.setSpacing(8)

        lbl = QLabel("Match")
        lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        lbl.setStyleSheet(_label_css(paint_css("text.secondary")))
        conj_row.addWidget(lbl)

        self.conjunction_combo = _RuleComboBox()
        self.conjunction_combo.setStyleSheet(_combo_css())
        self.conjunction_combo.addItem("all", "AND")
        self.conjunction_combo.addItem("any", "OR")
        self.conjunction_combo.setFixedWidth(72)
        self.conjunction_combo.currentIndexChanged.connect(self._notify_preview_changed)
        conj_row.addWidget(self.conjunction_combo)

        lbl2 = QLabel("of the following rules")
        lbl2.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        lbl2.setStyleSheet(_label_css(paint_css("text.secondary")))
        conj_row.addWidget(lbl2)
        conj_row.addStretch()

        self.add_rule_btn = QPushButton("Add Rule")
        self.add_rule_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.add_rule_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _add_ic = glyph_icon("plus", 14, paint_css("text.secondary"))
        if _add_ic:
            self.add_rule_btn.setIcon(_add_ic)
            self.add_rule_btn.setIconSize(QSize(14, 14))
        self.add_rule_btn.setStyleSheet(_rule_action_btn_css())
        self.add_rule_btn.setToolTip("Add a rule")
        self.add_rule_btn.clicked.connect(self._add_empty_rule)

        self.add_group_btn = QPushButton("Add Group")
        self.add_group_btn.setObjectName("smartPlaylistAddGroup")
        self.add_group_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.add_group_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _group_ic = glyph_icon("folder", 14, paint_css("text.secondary"))
        if _group_ic:
            self.add_group_btn.setIcon(_group_ic)
            self.add_group_btn.setIconSize(QSize(14, 14))
        self.add_group_btn.setStyleSheet(_rule_action_btn_css())
        self.add_group_btn.setToolTip("Add a nested rule group")
        self.add_group_btn.clicked.connect(self._add_group)
        rules_panel_layout.addLayout(conj_row)

        self._rules_scroll = make_scroll_area(
            transparent=False,
            extra_css="""
                QScrollArea {{
                    background: transparent;
                    border: none;
                }}
            """,
        )
        self._rules_scroll.setMinimumHeight(self._RULES_SCROLL_MIN_HEIGHT)
        self._rules_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._rules_widget = QWidget()
        self._rules_widget.setStyleSheet("background: transparent;")
        self._rules_layout = QVBoxLayout(self._rules_widget)
        self._rules_layout.setContentsMargins(0, 4, 0, 4)
        self._rules_layout.setSpacing(4)
        self._rules_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._rules_scroll.setWidget(self._rules_widget)
        rules_panel_layout.addWidget(self._rules_scroll, stretch=1)

        self._rule_rows: list[SmartRuleRow | SmartRuleGroup] = []
        self._rules_metadata: dict = {"unk004": 0x00010001}
        rules_column.addWidget(_section_toolbar("Rules", self.add_rule_btn, self.add_group_btn))
        rules_column.addWidget(rules_panel, stretch=1)

        opts_panel = QFrame()
        opts_panel.setObjectName("smartPlaylistBehaviorPanel")
        opts_panel.setStyleSheet(_editor_panel_css("smartPlaylistBehaviorPanel"))
        opts = QVBoxLayout(opts_panel)
        opts.setContentsMargins(12, 12, 12, 12)
        opts.setSpacing(8)

        parent_row = QHBoxLayout()
        parent_row.setContentsMargins(0, 0, 0, 0)
        parent_row.setSpacing(8)
        self.parent_folder_label = QLabel("Parent Folder")
        self.parent_folder_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.parent_folder_label.setStyleSheet(_label_css(paint_css("text.secondary")))
        parent_row.addWidget(self.parent_folder_label)

        self.parent_folder_combo = QComboBox()
        self.parent_folder_combo.setObjectName("smartPlaylistParentFolder")
        self.parent_folder_combo.setStyleSheet(_combo_css())
        self.parent_folder_combo.setMinimumWidth(180)
        self.parent_folder_combo.addItem("No parent (top level)", 0)
        parent_row.addWidget(self.parent_folder_combo)
        parent_row.addStretch()
        opts.addLayout(parent_row)

        # Limit row
        limit_row = QHBoxLayout()
        limit_row.setContentsMargins(0, 0, 0, 0)
        limit_row.setSpacing(8)

        self.limit_check = QCheckBox("Limit to")
        self.limit_check.setStyleSheet(_checkbox_css())
        self.limit_check.toggled.connect(self._on_limit_toggled)
        limit_row.addWidget(self.limit_check)

        self.limit_value_spin = QSpinBox()
        self.limit_value_spin.setRange(1, 99999)
        self.limit_value_spin.setValue(25)
        self.limit_value_spin.setStyleSheet(_spinbox_css())
        self.limit_value_spin.setFixedWidth(80)
        self.limit_value_spin.setEnabled(False)
        self.limit_value_spin.valueChanged.connect(self._notify_preview_changed)
        limit_row.addWidget(self.limit_value_spin)

        self.limit_type_combo = QComboBox()
        self.limit_type_combo.setStyleSheet(_combo_css())
        for lt_id, lt_name in LIMIT_TYPES:
            self.limit_type_combo.addItem(lt_name, lt_id)
        self.limit_type_combo.setFixedWidth(90)
        self.limit_type_combo.setEnabled(False)
        self.limit_type_combo.currentIndexChanged.connect(self._notify_preview_changed)
        limit_row.addWidget(self.limit_type_combo)
        limit_row.addStretch()
        opts.addLayout(limit_row)

        selected_by_row = QHBoxLayout()
        selected_by_row.setContentsMargins(0, 0, 0, 0)
        selected_by_row.setSpacing(8)
        self._selected_by_label = QLabel("Select by")
        self._selected_by_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._selected_by_label.setStyleSheet(f"color: {paint_css('text.secondary')}; background: transparent; border: none;")
        selected_by_row.addWidget(self._selected_by_label)

        self.limit_sort_combo = QComboBox()
        self.limit_sort_combo.setStyleSheet(_combo_css())
        for ls_id, ls_name in LIMIT_SORTS:
            self.limit_sort_combo.addItem(ls_name, ls_id)
        self.limit_sort_combo.setFixedWidth(170)
        self.limit_sort_combo.setEnabled(False)
        self.limit_sort_combo.currentIndexChanged.connect(self._notify_preview_changed)
        selected_by_row.addWidget(self.limit_sort_combo)
        selected_by_row.addStretch()
        opts.addLayout(selected_by_row)

        # Rule matching
        self.check_rules_check = QCheckBox("Match rules")
        self.check_rules_check.setStyleSheet(_checkbox_css())
        self.check_rules_check.setChecked(True)
        self.check_rules_check.toggled.connect(self._notify_preview_changed)
        opts.addWidget(self.check_rules_check)

        # Live updating
        self.live_update_check = QCheckBox("Live updating")
        self.live_update_check.setStyleSheet(_checkbox_css())
        self.live_update_check.setChecked(True)
        opts.addWidget(self.live_update_check)

        # Match only checked
        self.match_checked_check = QCheckBox("Match only checked items")
        self.match_checked_check.setStyleSheet(_checkbox_css())
        self.match_checked_check.toggled.connect(self._notify_preview_changed)
        opts.addWidget(self.match_checked_check)

        # Sort order
        sort_row = QHBoxLayout()
        sort_row.setContentsMargins(0, 0, 0, 0)
        sort_row.setSpacing(8)
        sort_lbl = QLabel("Sort Order")
        sort_lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        sort_lbl.setStyleSheet(_label_css(paint_css("text.secondary")))
        sort_row.addWidget(sort_lbl)

        self.sort_combo = QComboBox()
        self.sort_combo.setStyleSheet(_combo_css())
        self.sort_combo.setFixedWidth(170)
        for s_id, s_name in PLAYLIST_SORT_ORDERS:
            self.sort_combo.addItem(s_name, s_id)
        self.sort_combo.currentIndexChanged.connect(self._notify_preview_changed)
        sort_row.addWidget(self.sort_combo)
        sort_row.addStretch()
        opts.addLayout(sort_row)

        settings_column.addWidget(_section_toolbar("Behavior"))
        settings_column.addWidget(opts_panel)
        settings_column.addStretch()

        body.addLayout(rules_column, 1)
        body.addWidget(settings_column_widget)
        root.addLayout(body, 1)
        self._update_body_layout()

    def resizeEvent(self, a0) -> None:
        super().resizeEvent(a0)
        self._update_body_layout()

    def _update_body_layout(self) -> None:
        compact = self.width() < 960
        self._body_layout.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
        self._settings_rail.setMinimumWidth(0 if compact else 320)
        self._settings_rail.setMaximumWidth(16777215 if compact else 420)

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def set_playlist_options(self, playlists: list[dict]) -> None:
        self._playlist_rows = list(playlists)
        options: list[tuple[int, str]] = []
        seen: set[int] = set()
        for playlist in playlists:
            playlist_id = playlist.get("playlist_id")
            if not isinstance(playlist_id, int) or playlist_id in seen:
                continue
            seen.add(playlist_id)
            title = str(playlist.get("Title") or f"Playlist {playlist_id}")
            dataset = playlist.get("_mhsd_dataset_type")
            if dataset in (2, 3, 5):
                title = f"{title} (MHSD {dataset})"
            options.append((playlist_id, title))
        self._playlist_options = options
        for row in self._rule_rows:
            row.set_playlist_options(options)
        self._populate_parent_folder_combo()

    def new_playlist(self) -> None:
        """Set up for creating a brand-new smart playlist."""
        self._editing_playlist = None
        self.name_input.setText("")
        self.name_input.setPlaceholderText("New Smart Playlist")
        self.description_input.setText("")
        self._populate_parent_folder_combo(0)
        self._rules_metadata = {"unk004": 0x00010001}
        self.conjunction_combo.setCurrentIndex(0)  # all (AND)
        self.limit_check.setChecked(False)
        self.check_rules_check.setChecked(True)
        self.live_update_check.setChecked(True)
        self.match_checked_check.setChecked(False)
        self.sort_combo.setCurrentIndex(0)  # Manual
        self._clear_rules()
        self._add_empty_rule()  # Start with one rule
        self.name_input.setFocus()

    def edit_playlist(self, playlist: dict) -> None:
        """Populate the editor from an existing parsed smart playlist dict."""
        self._editing_playlist = playlist
        self.name_input.setText(playlist.get("Title", ""))
        self.description_input.setText(playlist_description_from_row(playlist))

        prefs = playlist.get("smart_playlist_data", {})
        rules = playlist.get("smart_playlist_rules", {})
        self._rules_metadata = {
            key: value for key, value in rules.items() if key not in ("conjunction", "rules")
        }
        parent_folder_id = int(playlist.get("parent_folder_playlist_id", 0) or 0)
        self._populate_parent_folder_combo(parent_folder_id)

        # Conjunction
        conj = rules.get("conjunction", "AND")
        if isinstance(conj, int):
            conj = "OR" if conj == 1 else "AND"
        else:
            conj = str(conj).upper()
        idx = self.conjunction_combo.findData(conj)
        if idx >= 0:
            self.conjunction_combo.setCurrentIndex(idx)

        # Limits
        check_limits = prefs.get("check_limits", False)
        self.limit_check.setChecked(check_limits)
        self.limit_value_spin.setValue(prefs.get("limit_value", 25))
        lt_idx = self.limit_type_combo.findData(prefs.get("limit_type", 0x03))
        if lt_idx >= 0:
            self.limit_type_combo.setCurrentIndex(lt_idx)
        limit_sort = prefs.get("limit_sort", 0x02)
        if prefs.get("reverse_sort", False):
            limit_sort |= 0x80000000
        ls_idx = self.limit_sort_combo.findData(limit_sort)
        if ls_idx >= 0:
            self.limit_sort_combo.setCurrentIndex(ls_idx)

        # Rule matching, live update & match checked
        self.check_rules_check.setChecked(prefs.get("check_rules", True))
        self.live_update_check.setChecked(prefs.get("live_update", True))
        self.match_checked_check.setChecked(prefs.get("match_checked_only", False))

        # Sort order
        sort_order = playlist.get("sort_order", 1)
        so_idx = self.sort_combo.findData(sort_order)
        if so_idx >= 0:
            self.sort_combo.setCurrentIndex(so_idx)
        else:
            self.sort_combo.setCurrentIndex(0)

        # Rules
        self._clear_rules()
        rule_list = rules.get("rules", [])
        for r in rule_list:
            self._add_rule_data(r)

        self.name_input.setFocus()
        self.name_input.selectAll()

    def get_playlist_data(self) -> dict:
        """Build a dict representing the current editor state.

        Returns a dict with keys matching the parsed playlist format:
            Title, isSmartPlaylist, smart_playlist_data, smart_playlist_rules, _isNew
        """
        smart_state = self._smart_state()

        changes = {
            "Title": self.name_input.text().strip() or "Untitled Playlist",
            "_isNew": self._editing_playlist is None,
            "_source": "regular",
            "sort_order": self.sort_combo.currentData() or 1,
            "parent_folder_playlist_id": self.parent_folder_combo.currentData() or 0,
            "unk0x30_playlist_ref": self.parent_folder_combo.currentData() or 0,
            "smart_playlist_data": smart_state["smart_playlist_data"],
            "smart_playlist_rules": smart_state["smart_playlist_rules"],
        }
        changes.update(
            playlist_description_update_fields(
                self.description_input.text().strip(),
                self._editing_playlist,
            )
        )
        return playlist_edit_payload(self._editing_playlist, changes)

    def get_preview_data(self) -> dict:
        """Return the current rule state used by the transient live preview."""
        return self._smart_state()

    def _smart_state(self) -> dict:
        rules = [row.get_rule_data() for row in self._rule_rows]
        rules_data = dict(self._rules_metadata)
        rules_data.update({
            "conjunction": self.conjunction_combo.currentData() or "AND",
            "rules": rules,
        })
        if "rule_count" in rules_data:
            rules_data["rule_count"] = len(rules)

        return {
            "smart_playlist_data": {
                "live_update": self.live_update_check.isChecked(),
                "check_rules": self.check_rules_check.isChecked(),
                "check_limits": self.limit_check.isChecked(),
                "limit_type": self.limit_type_combo.currentData() or 0x03,
                "limit_sort": self.limit_sort_combo.currentData() or 0x02,
                "limit_value": self.limit_value_spin.value(),
                "match_checked_only": self.match_checked_check.isChecked(),
            },
            "smart_playlist_rules": rules_data,
            "sort_order": self.sort_combo.currentData() or 1,
        }

    # ─────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────

    def _populate_parent_folder_combo(self, selected_id: int | None = None) -> None:
        if selected_id is None:
            selected_id = int(self.parent_folder_combo.currentData() or 0)
        editing_id = int((self._editing_playlist or {}).get("playlist_id", 0) or 0)
        self.parent_folder_combo.blockSignals(True)
        self.parent_folder_combo.clear()
        self.parent_folder_combo.addItem("No parent (top level)", 0)
        seen: set[int] = set()
        for playlist in self._playlist_rows:
            playlist_id = int(playlist.get("playlist_id", 0) or 0)
            if not playlist_id or playlist_id in seen or playlist_id == editing_id:
                continue
            if not is_playlist_folder(playlist):
                continue
            seen.add(playlist_id)
            self.parent_folder_combo.addItem(
                str(playlist.get("Title") or f"Folder {playlist_id}"),
                playlist_id,
            )
        index = self.parent_folder_combo.findData(selected_id)
        self.parent_folder_combo.setCurrentIndex(max(0, index))
        self.parent_folder_combo.blockSignals(False)

    def _add_empty_rule(self) -> SmartRuleRow:
        row = SmartRuleRow(playlist_options=self._playlist_options)
        row.remove_clicked.connect(self._remove_rule)
        row.changed.connect(self._notify_preview_changed)
        self._rules_layout.addWidget(row)
        self._rule_rows.append(row)
        self._notify_preview_changed()
        return row

    def _add_group(self) -> SmartRuleGroup:
        group = SmartRuleGroup(
            playlist_options=self._playlist_options,
            depth=1,
        )
        group.remove_clicked.connect(self._remove_rule)
        group.changed.connect(self._notify_preview_changed)
        group.add_rule()
        self._rules_layout.addWidget(group)
        self._rule_rows.append(group)
        return group

    def _add_rule_data(self, rule: dict) -> SmartRuleRow | SmartRuleGroup:
        if isinstance(rule.get("group"), dict):
            group = SmartRuleGroup(
                playlist_options=self._playlist_options,
                depth=1,
            )
            group.remove_clicked.connect(self._remove_rule)
            group.changed.connect(self._notify_preview_changed)
            group.set_rule_data(rule)
            item: SmartRuleRow | SmartRuleGroup = group
        else:
            row = SmartRuleRow(playlist_options=self._playlist_options)
            row.remove_clicked.connect(self._remove_rule)
            row.changed.connect(self._notify_preview_changed)
            row.set_rule_data(rule)
            item = row
        self._rules_layout.addWidget(item)
        self._rule_rows.append(item)
        return item

    def _remove_rule(self, row: SmartRuleRow | SmartRuleGroup) -> None:
        if row in self._rule_rows:
            self._rule_rows.remove(row)
            _delete_embedded_widget(row)
            self._notify_preview_changed()

    def _clear_rules(self) -> None:
        for row in self._rule_rows:
            _delete_embedded_widget(row)
        self._rule_rows.clear()

    def _on_limit_toggled(self, checked: bool) -> None:
        self.limit_value_spin.setEnabled(checked)
        self.limit_type_combo.setEnabled(checked)
        self.limit_sort_combo.setEnabled(checked)
        self._notify_preview_changed()

    def _notify_preview_changed(self, *_args) -> None:
        self.preview_changed.emit()

    def _on_save(self) -> None:
        data = self.get_playlist_data()
        self.saved.emit(data)


# ─────────────────────────────────────────────────────────────────────────────
# RegularPlaylistEditor — simple editor for normal (non-smart) playlists
# ─────────────────────────────────────────────────────────────────────────────

_PLAYLIST_SORT_OPTION_IDS = (
    1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
    14, 15, 16, 17, 18, 20, 21, 22, 23, 24, 25, 26,
)
_PLAYLIST_SORT_LABEL_OVERRIDES = {
    1: "Manual",
    23: "Rating",
}

PLAYLIST_SORT_ORDERS: list[tuple[int, str]] = [
    (
        sort_order,
        _PLAYLIST_SORT_LABEL_OVERRIDES.get(
            sort_order,
            PLAYLIST_SORT_ORDER_MAP[sort_order].title(),
        ),
    )
    for sort_order in _PLAYLIST_SORT_OPTION_IDS
]


class RegularPlaylistEditor(QFrame):
    """Editor for creating / editing regular (non-smart) playlists.

    Layout:
        ┌───────────────────────────────────────────────────────┐
        │  📋 Playlist Name: [________________]                 │
        ├───────────────────────────────────────────────────────┤
        │  Sort Order:  [Manual ▼]                              │
        ├───────────────────────────────────────────────────────┤
        │                               [Cancel] [Save]         │
        └───────────────────────────────────────────────────────┘

    Signals:
        saved(dict)   — emitted when user clicks Save
        cancelled()   — emitted when user clicks Cancel
    """

    saved = pyqtSignal(dict)
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("regularPlaylistEditor")
        self.setStyleSheet(f"QFrame#regularPlaylistEditor {{ background: {paint_css('surface.default')}; border: none; }}")

        self._editing_playlist: dict | None = None  # None → new playlist
        self._creating_folder = False
        self._playlist_rows: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── Identity + actions ─────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Playlist Name")
        _configure_title_input(self.name_input)
        title_col.addWidget(self.name_input)

        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("Playlist Description")
        self.description_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.description_input.setStyleSheet(_input_css())
        title_col.addWidget(self.description_input)

        header.addLayout(title_col, 1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(button_css("secondary", "sm"))
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.Bold))
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _save_ic = glyph_icon("check-circle", 14, paint_css("control.primary.text"))
        if _save_ic:
            self.save_btn.setIcon(_save_ic)
            self.save_btn.setIconSize(QSize(14, 14))
        self.save_btn.setStyleSheet(accent_btn_css())
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        header.addLayout(btn_row)
        root.addLayout(header)
        root.addWidget(make_separator())

        root.addWidget(_section_toolbar("Details"))

        settings_panel = QFrame()
        settings_panel.setObjectName("regularPlaylistSettingsPanel")
        settings_panel.setStyleSheet(_editor_panel_css("regularPlaylistSettingsPanel"))
        settings_panel.setMaximumWidth(640)
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(10, 8, 10, 9)
        settings_layout.setSpacing(8)

        sort_row = QHBoxLayout()
        sort_row.setContentsMargins(0, 0, 0, 0)
        sort_row.setSpacing(8)
        sort_label = QLabel("Sort Order")
        sort_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        sort_label.setStyleSheet(_label_css(paint_css("text.secondary")))
        sort_row.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.sort_combo.setMinimumWidth(180)
        self.sort_combo.setStyleSheet(_combo_css())
        for sort_id, sort_name in PLAYLIST_SORT_ORDERS:
            self.sort_combo.addItem(sort_name, sort_id)
        sort_row.addWidget(self.sort_combo)
        sort_row.addStretch()
        settings_layout.addLayout(sort_row)

        parent_row = QHBoxLayout()
        parent_row.setContentsMargins(0, 0, 0, 0)
        parent_row.setSpacing(8)
        self.parent_folder_label = QLabel("Parent Folder")
        self.parent_folder_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.parent_folder_label.setStyleSheet(_label_css(paint_css("text.secondary")))
        parent_row.addWidget(self.parent_folder_label)

        self.parent_folder_combo = QComboBox()
        self.parent_folder_combo.setObjectName("playlistParentFolder")
        self.parent_folder_combo.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.parent_folder_combo.setMinimumWidth(180)
        self.parent_folder_combo.setStyleSheet(_combo_css())
        self.parent_folder_combo.addItem("No parent (top level)", 0)
        parent_row.addWidget(self.parent_folder_combo)
        parent_row.addStretch()
        settings_layout.addLayout(parent_row)

        root.addWidget(settings_panel)

        add_tracks_note = QFrame()
        add_tracks_note.setObjectName("regularPlaylistAddTracksNote")
        add_tracks_note.setStyleSheet(_editor_notice_css("regularPlaylistAddTracksNote"))
        note_layout = QHBoxLayout(add_tracks_note)
        note_layout.setContentsMargins(10, 8, 10, 8)
        note_layout.setSpacing(8)

        note_icon = QLabel("?", add_tracks_note)
        note_icon.setFixedSize(18, 18)
        note_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note_icon.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
        note_icon.setStyleSheet(
            f"color: {paint_css('status.info.text')};"
            "background: transparent;"
            f"border: 1px solid {paint_css('notice.info.border')};"
            "border-radius: 9px;"
        )
        note_layout.addWidget(note_icon, 0, Qt.AlignmentFlag.AlignTop)

        self.note_text = QLabel(
            "Add tracks from the library: right-click a track, then choose Add to Playlist.",
            add_tracks_note,
        )
        self.note_text.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.note_text.setStyleSheet(_label_css(paint_css("text.secondary")))
        self.note_text.setWordWrap(True)
        note_layout.addWidget(self.note_text, 1)

        root.addWidget(add_tracks_note)
        root.addStretch()

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def set_playlist_options(self, playlists: list[dict]) -> None:
        """Set rows used by the parent-folder chooser."""
        self._playlist_rows = list(playlists)
        self._populate_parent_folder_combo()

    def new_playlist(self) -> None:
        """Set up for creating a brand-new regular playlist."""
        self._editing_playlist = None
        self._creating_folder = False
        self.name_input.setText("")
        self.name_input.setPlaceholderText("New Playlist")
        self.description_input.setText("")
        self.sort_combo.setCurrentIndex(0)  # Manual
        self._populate_parent_folder_combo(0)
        self._update_kind_labels()
        self.name_input.setFocus()

    def new_folder(self) -> None:
        """Set up for creating a playlist folder."""
        self._editing_playlist = None
        self._creating_folder = True
        self.name_input.setText("")
        self.name_input.setPlaceholderText("New Playlist Folder")
        self.description_input.setText("")
        self.sort_combo.setCurrentIndex(0)
        self._populate_parent_folder_combo(0)
        self._update_kind_labels()
        self.name_input.setFocus()

    def edit_playlist(self, playlist: dict) -> None:
        """Populate the editor from an existing regular playlist dict."""
        self._editing_playlist = playlist
        self._creating_folder = is_playlist_folder(playlist)
        self.name_input.setText(playlist.get("Title", ""))
        self.description_input.setText(playlist_description_from_row(playlist))

        # Restore sort order
        sort_order = playlist.get("sort_order", 1)
        idx = self.sort_combo.findData(sort_order)
        if idx >= 0:
            self.sort_combo.setCurrentIndex(idx)
        else:
            self.sort_combo.setCurrentIndex(0)

        parent_folder_id = int(playlist.get("parent_folder_playlist_id", 0) or 0)
        self._populate_parent_folder_combo(parent_folder_id)
        self._update_kind_labels()

        self.name_input.setFocus()
        self.name_input.selectAll()

    def get_playlist_data(self) -> dict:
        """Build a dict representing the current editor state.

        Returns a dict with keys matching the parsed playlist format.
        """
        parent_folder_id = self.parent_folder_combo.currentData() or 0
        changes: dict = {
            "Title": self.name_input.text().strip() or "Untitled Playlist",
            "_isNew": self._editing_playlist is None,
            "_source": "regular",
            "sort_order": self.sort_combo.currentData() or 1,
            "parent_folder_playlist_id": parent_folder_id,
            "unk0x30_playlist_ref": parent_folder_id,
        }
        if self._editing_playlist is None:
            changes["items"] = []
        if self._creating_folder:
            existing_flags = int(
                (self._editing_playlist or {}).get(
                    "playlist_kind_flags",
                    (self._editing_playlist or {}).get("podcast_flag", 0),
                )
                or 0
            )
            kind_flags = (existing_flags | PLAYLIST_KIND_FOLDER) & ~PLAYLIST_KIND_PODCAST
            changes.update({
                "playlist_kind_flags": kind_flags,
                "podcast_flag": kind_flags,
                "is_folder": True,
                "is_podcast": False,
            })
        changes.update(
            playlist_description_update_fields(
                self.description_input.text().strip(),
                self._editing_playlist,
            )
        )
        return playlist_edit_payload(self._editing_playlist, changes)

    # ─────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────

    def _populate_parent_folder_combo(self, selected_id: int | None = None) -> None:
        if selected_id is None:
            selected_id = int(self.parent_folder_combo.currentData() or 0)
        editing_id = int((self._editing_playlist or {}).get("playlist_id", 0) or 0)
        excluded = {editing_id} if editing_id else set()
        changed = True
        while changed:
            changed = False
            for playlist in self._playlist_rows:
                playlist_id = int(playlist.get("playlist_id", 0) or 0)
                parent_id = int(playlist.get("parent_folder_playlist_id", 0) or 0)
                if playlist_id and parent_id in excluded and playlist_id not in excluded:
                    excluded.add(playlist_id)
                    changed = True

        self.parent_folder_combo.blockSignals(True)
        self.parent_folder_combo.clear()
        self.parent_folder_combo.addItem("No parent (top level)", 0)
        seen: set[int] = set()
        for playlist in self._playlist_rows:
            playlist_id = int(playlist.get("playlist_id", 0) or 0)
            if not playlist_id or playlist_id in seen or playlist_id in excluded:
                continue
            if not is_playlist_folder(playlist):
                continue
            seen.add(playlist_id)
            self.parent_folder_combo.addItem(
                str(playlist.get("Title") or f"Folder {playlist_id}"),
                playlist_id,
            )
        index = self.parent_folder_combo.findData(selected_id)
        self.parent_folder_combo.setCurrentIndex(max(0, index))
        self.parent_folder_combo.blockSignals(False)

    def _update_kind_labels(self) -> None:
        self.parent_folder_label.setVisible(True)
        self.parent_folder_combo.setVisible(True)
        self.parent_folder_combo.setEnabled(True)
        if self._creating_folder:
            self.note_text.setText("Move playlists into or out of this folder from the playlist sidebar.")
            self.save_btn.setText("Save Folder")
        else:
            self.note_text.setText("Add tracks from the library: right-click a track, then choose Add to Playlist.")
            self.save_btn.setText("Save Playlist")

    def _on_save(self) -> None:
        data = self.get_playlist_data()
        self.saved.emit(data)


# ─────────────────────────────────────────────────────────────────────────────
# NewPlaylistDialog — choose between smart and regular
# ─────────────────────────────────────────────────────────────────────────────

class NewPlaylistDialog(QDialog):
    """Small dialog to choose what type of playlist to create."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("New Playlist")
        self.setFixedSize((440), (200))
        self.setStyleSheet(f"""
            QDialog {{
                background: {paint_css('modal.background')};
                color: {paint_css('text.primary')};
            }}
        """)

        self._choice: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins((24), (20), (24), (20))
        layout.setSpacing(12)

        title = QLabel("Create New Playlist")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {paint_css('text.primary')};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Choose a playlist type:")
        subtitle.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        subtitle.setStyleSheet(f"color: {paint_css('text.secondary')};")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        _ic_sz = QSize((20), (20))

        # Playlist folder button
        self.folder_btn = QPushButton("Folder")
        self.folder_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self.folder_btn.setMinimumHeight(44)
        self.folder_btn.setStyleSheet(button_css("secondary", "lg"))
        _ic = glyph_icon("folder", (20), paint_css("text.secondary"))
        if _ic:
            self.folder_btn.setIcon(_ic)
            self.folder_btn.setIconSize(_ic_sz)
        self.folder_btn.clicked.connect(lambda: self._select("folder"))
        btn_row.addWidget(self.folder_btn)

        # Regular playlist button
        self.regular_btn = QPushButton("Regular")
        self.regular_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self.regular_btn.setMinimumHeight(44)
        self.regular_btn.setStyleSheet(button_css("secondary", "lg"))
        _ic = glyph_icon(_ICON_REGULAR, (20), paint_css("text.secondary"))
        if _ic:
            self.regular_btn.setIcon(_ic)
            self.regular_btn.setIconSize(_ic_sz)
        self.regular_btn.clicked.connect(lambda: self._select("regular"))
        btn_row.addWidget(self.regular_btn)

        # Smart playlist button
        self.smart_btn = QPushButton("Smart")
        self.smart_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self.smart_btn.setMinimumHeight(44)
        self.smart_btn.setStyleSheet(accent_btn_css("lg"))
        _ic = glyph_icon(_ICON_SMART, (20), paint_css("control.primary.text"))
        if _ic:
            self.smart_btn.setIcon(_ic)
            self.smart_btn.setIconSize(_ic_sz)
        self.smart_btn.clicked.connect(lambda: self._select("smart"))
        btn_row.addWidget(self.smart_btn)

        layout.addLayout(btn_row)

    def _select(self, choice: str) -> None:
        self._choice = choice
        self.accept()

    def get_choice(self) -> str | None:
        return self._choice


# Re-export icons used by playlist browser
_ICON_REGULAR = "playlist"
_ICON_SMART = "filter"
