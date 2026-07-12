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
from iopenpod.itunesdb_shared.playlist_lifecycle import playlist_edit_payload
from iopenpod.itunesdb_shared.playlist_properties import (
    playlist_description_from_row,
    playlist_description_update_fields,
)

from ..glyphs import glyph_icon
from ..styles import (
    FONT_FAMILY,
    Colors,
    Design,
    Metrics,
    accent_btn_css,
    button_css,
    checkbox_css,
    combo_css,
    danger_btn_css,
    input_css,
    make_scroll_area,
    make_separator,
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
_UNSUPPORTED_FIELD_IDS = frozenset({0x39, 0x3E, 0x3F})

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
        return raw + 9 if upper_bound and raw else raw
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


def _subtle_label_css(color: str = Colors.TEXT_TERTIARY) -> str:
    return (
        f"color: {color}; background: transparent; border: none;"
        " text-transform: uppercase;"
    )


def _title_input_css() -> str:
    return title_input_css()


def _editor_panel_css(object_name: str) -> str:
    return panel_css(
        object_name,
        bg=Colors.SURFACE_ALT,
        radius=Metrics.BORDER_RADIUS_SM,
    )


def _editor_notice_css(object_name: str) -> str:
    return panel_css(
        object_name,
        bg=Colors.ACCENT_MUTED,
        border=f"1px solid {Colors.ACCENT_BORDER}",
        radius=Metrics.BORDER_RADIUS_SM,
    )


def _section_header(text: str) -> QWidget:
    widget = QWidget()
    widget.setStyleSheet("background: transparent; border: none;")
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    label = QLabel(text, widget)
    label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
    label.setStyleSheet(_subtle_label_css(Colors.TEXT_SECONDARY))
    layout.addWidget(label)
    layout.addWidget(make_separator(), 1)
    return widget


def _section_label_style() -> str:
    return (
        f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none; "
        f"font-size: {Metrics.FONT_SM}pt; font-weight: bold;"
    )


def _remove_btn_css() -> str:
    return danger_btn_css("sm")


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

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 5, 0, 5)
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
        _close_ic = glyph_icon("close", 12, Colors.DANGER)
        if _close_ic:
            self.remove_btn.setIcon(_close_ic)
        else:
            self.remove_btn.setText("✕")
        self.remove_btn.setFixedSize(
            Design.ICON_BUTTON_SIZE,
            Design.ICON_BUTTON_SIZE,
        )
        self.remove_btn.setStyleSheet(_remove_btn_css())
        self.remove_btn.setToolTip("Remove this rule")
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

        data: dict = {
            "field_id": fid or 0x02,
            "action_id": aid or 0x00000001,
            # Human-readable keys expected by format_smart_rule()
            "field": self.field_combo.currentText() or field_name,
            "action": self.action_combo.currentText() or "?",
            "field_type": ft,
            "string_value": None,
            "from_value": 0,
            "to_value": 0,
            "from_date": 0,
            "to_date": 0,
            "from_units": 0,
            "to_units": 0,
        }

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
            if len(spins) > 1:
                data["to_value"] = _int_raw_value(fid, spins[1].value(), upper_bound=True)
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
            if date_edits:
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
                f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;"
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
                f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;"
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

class SmartPlaylistEditor(QFrame):
    """Full smart playlist editor replacing the info card when editing."""

    saved = pyqtSignal(dict)      # emits the full playlist dict
    cancelled = pyqtSignal()
    _RULES_PANEL_MIN_HEIGHT = 220
    _RULES_SCROLL_MIN_HEIGHT = 150

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("smartPlaylistEditor")
        self.setStyleSheet(panel_css(
            "smartPlaylistEditor",
            radius=Metrics.BORDER_RADIUS_LG,
        ))

        self._editing_playlist: dict | None = None  # None → new playlist
        self._playlist_options: list[tuple[int, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # ── Identity + actions ─────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Playlist Name")
        self.name_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
        self.name_input.setStyleSheet(_title_input_css())
        title_col.addWidget(self.name_input)

        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("Playlist Description")
        self.description_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.description_input.setStyleSheet(_input_css())
        title_col.addWidget(self.description_input)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(6)

        type_label = QLabel("Smart Playlist Editor")
        type_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
        type_label.setStyleSheet(_subtle_label_css(Colors.TEXT_SECONDARY))
        meta_row.addWidget(type_label, 0, Qt.AlignmentFlag.AlignVCenter)

        source_label = QLabel("Rule-based playlist")
        source_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        source_label.setStyleSheet(_label_css(Colors.TEXT_TERTIARY))
        meta_row.addWidget(source_label, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addStretch()
        title_col.addLayout(meta_row)
        header.addLayout(title_col, 1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(button_css("secondary", "sm"))
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save Playlist")
        self.save_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.Bold))
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _save_ic = glyph_icon("check-circle", 14, Colors.TEXT_ON_ACCENT)
        if _save_ic:
            self.save_btn.setIcon(_save_ic)
            self.save_btn.setIconSize(QSize(14, 14))
        self.save_btn.setStyleSheet(accent_btn_css())
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        header.addLayout(btn_row)
        root.addLayout(header)
        root.addWidget(make_separator())

        root.addWidget(_section_header("Rules"))

        rules_panel = QFrame()
        rules_panel.setObjectName("smartPlaylistRulesPanel")
        rules_panel.setStyleSheet(_editor_panel_css("smartPlaylistRulesPanel"))
        rules_panel.setMinimumHeight(self._RULES_PANEL_MIN_HEIGHT)
        rules_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rules_panel_layout = QVBoxLayout(rules_panel)
        rules_panel_layout.setContentsMargins(12, 10, 12, 12)
        rules_panel_layout.setSpacing(8)

        conj_row = QHBoxLayout()
        conj_row.setContentsMargins(0, 0, 0, 0)
        conj_row.setSpacing(6)

        lbl = QLabel("Match")
        lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        lbl.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        conj_row.addWidget(lbl)

        self.conjunction_combo = _RuleComboBox()
        self.conjunction_combo.setStyleSheet(_combo_css())
        self.conjunction_combo.addItem("all", "AND")
        self.conjunction_combo.addItem("any", "OR")
        self.conjunction_combo.setFixedWidth(70)
        conj_row.addWidget(self.conjunction_combo)

        lbl2 = QLabel("of the following rules")
        lbl2.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        lbl2.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        conj_row.addWidget(lbl2)
        conj_row.addStretch()

        self.add_rule_btn = QPushButton("Add Rule")
        self.add_rule_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.add_rule_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _add_ic = glyph_icon("plus", 14, Colors.TEXT_SECONDARY)
        if _add_ic:
            self.add_rule_btn.setIcon(_add_ic)
            self.add_rule_btn.setIconSize(QSize(14, 14))
        self.add_rule_btn.setStyleSheet(button_css("quiet", "sm"))
        self.add_rule_btn.clicked.connect(self._add_empty_rule)
        conj_row.addWidget(self.add_rule_btn, 0, Qt.AlignmentFlag.AlignRight)
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
        self._rules_layout.setContentsMargins(0, 2, 0, 2)
        self._rules_layout.setSpacing(4)
        self._rules_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._rules_scroll.setWidget(self._rules_widget)
        rules_panel_layout.addWidget(self._rules_scroll, stretch=1)

        self._rule_rows: list[SmartRuleRow] = []
        root.addWidget(rules_panel, stretch=1)

        root.addWidget(_section_header("Behavior"))

        opts_panel = QFrame()
        opts_panel.setObjectName("smartPlaylistBehaviorPanel")
        opts_panel.setStyleSheet(_editor_panel_css("smartPlaylistBehaviorPanel"))
        opts = QVBoxLayout(opts_panel)
        opts.setContentsMargins(10, 8, 10, 9)
        opts.setSpacing(8)

        # Limit row
        limit_row = QHBoxLayout()
        limit_row.setContentsMargins(0, 0, 0, 0)
        limit_row.setSpacing(6)

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
        limit_row.addWidget(self.limit_value_spin)

        self.limit_type_combo = QComboBox()
        self.limit_type_combo.setStyleSheet(_combo_css())
        for lt_id, lt_name in LIMIT_TYPES:
            self.limit_type_combo.addItem(lt_name, lt_id)
        self.limit_type_combo.setFixedWidth(90)
        self.limit_type_combo.setEnabled(False)
        limit_row.addWidget(self.limit_type_combo)

        self._selected_by_label = QLabel("selected by")
        self._selected_by_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self._selected_by_label.setStyleSheet(
            f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;"
        )
        limit_row.addWidget(self._selected_by_label)

        self.limit_sort_combo = QComboBox()
        self.limit_sort_combo.setStyleSheet(_combo_css())
        for ls_id, ls_name in LIMIT_SORTS:
            self.limit_sort_combo.addItem(ls_name, ls_id)
        self.limit_sort_combo.setFixedWidth(170)
        self.limit_sort_combo.setEnabled(False)
        limit_row.addWidget(self.limit_sort_combo)

        limit_row.addStretch()
        opts.addLayout(limit_row)

        # Live updating
        self.live_update_check = QCheckBox("Live updating")
        self.live_update_check.setStyleSheet(_checkbox_css())
        self.live_update_check.setChecked(True)
        opts.addWidget(self.live_update_check)

        # Match only checked
        self.match_checked_check = QCheckBox("Match only checked items")
        self.match_checked_check.setStyleSheet(_checkbox_css())
        opts.addWidget(self.match_checked_check)

        # Sort order
        sort_row = QHBoxLayout()
        sort_row.setContentsMargins(0, 0, 0, 0)
        sort_row.setSpacing(6)
        sort_lbl = QLabel("Sort Order")
        sort_lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        sort_lbl.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        sort_row.addWidget(sort_lbl)

        self.sort_combo = QComboBox()
        self.sort_combo.setStyleSheet(_combo_css())
        self.sort_combo.setFixedWidth(170)
        for s_id, s_name in PLAYLIST_SORT_ORDERS:
            self.sort_combo.addItem(s_name, s_id)
        sort_row.addWidget(self.sort_combo)
        sort_row.addStretch()
        opts.addLayout(sort_row)

        root.addWidget(opts_panel)

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def set_playlist_options(self, playlists: list[dict]) -> None:
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

    def new_playlist(self) -> None:
        """Set up for creating a brand-new smart playlist."""
        self._editing_playlist = None
        self.name_input.setText("")
        self.name_input.setPlaceholderText("New Smart Playlist")
        self.description_input.setText("")
        self.conjunction_combo.setCurrentIndex(0)  # all (AND)
        self.limit_check.setChecked(False)
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

        # Conjunction
        conj = rules.get("conjunction", "AND")
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
        ls_idx = self.limit_sort_combo.findData(prefs.get("limit_sort", 0x02))
        if ls_idx >= 0:
            self.limit_sort_combo.setCurrentIndex(ls_idx)

        # Live update & match checked
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
        if not rule_list:
            self._add_empty_rule()
        else:
            for r in rule_list:
                row = self._add_empty_rule()
                row.set_rule_data(r)

        self.name_input.setFocus()
        self.name_input.selectAll()

    def get_playlist_data(self) -> dict:
        """Build a dict representing the current editor state.

        Returns a dict with keys matching the parsed playlist format:
            Title, isSmartPlaylist, smart_playlist_data, smart_playlist_rules, _isNew
        """
        rules = [row.get_rule_data() for row in self._rule_rows]

        changes = {
            "Title": self.name_input.text().strip() or "Untitled Playlist",
            "_isNew": self._editing_playlist is None,
            "_source": "regular",
            "sort_order": self.sort_combo.currentData() or 1,
            "smart_playlist_data": {
                "live_update": self.live_update_check.isChecked(),
                "check_rules": True,
                "check_limits": self.limit_check.isChecked(),
                "limit_type": self.limit_type_combo.currentData() or 0x03,
                "limit_sort": self.limit_sort_combo.currentData() or 0x02,
                "limit_value": self.limit_value_spin.value(),
                "match_checked_only": self.match_checked_check.isChecked(),
            },
            "smart_playlist_rules": {
                "conjunction": self.conjunction_combo.currentData() or "AND",
                "rules": rules,
            },
        }
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

    def _add_empty_rule(self) -> SmartRuleRow:
        row = SmartRuleRow(playlist_options=self._playlist_options)
        row.remove_clicked.connect(self._remove_rule)
        row.changed.connect(lambda: None)  # future: live preview
        self._rules_layout.addWidget(row)
        self._rule_rows.append(row)
        return row

    def _remove_rule(self, row: SmartRuleRow) -> None:
        if row in self._rule_rows:
            self._rule_rows.remove(row)
            _delete_embedded_widget(row)
        # Always keep at least one rule
        if not self._rule_rows:
            self._add_empty_rule()

    def _clear_rules(self) -> None:
        for row in self._rule_rows:
            _delete_embedded_widget(row)
        self._rule_rows.clear()

    def _on_limit_toggled(self, checked: bool) -> None:
        self.limit_value_spin.setEnabled(checked)
        self.limit_type_combo.setEnabled(checked)
        self.limit_sort_combo.setEnabled(checked)

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
        self.setStyleSheet(panel_css(
            "regularPlaylistEditor",
            radius=Metrics.BORDER_RADIUS_LG,
        ))

        self._editing_playlist: dict | None = None  # None → new playlist

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # ── Identity + actions ─────────────────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Playlist Name")
        self.name_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_PAGE_TITLE, QFont.Weight.Bold))
        self.name_input.setStyleSheet(_title_input_css())
        title_col.addWidget(self.name_input)

        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("Playlist Description")
        self.description_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.description_input.setStyleSheet(_input_css())
        title_col.addWidget(self.description_input)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(6)

        type_label = QLabel("Playlist Editor")
        type_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS, QFont.Weight.Bold))
        type_label.setStyleSheet(_subtle_label_css(Colors.TEXT_SECONDARY))
        meta_row.addWidget(type_label, 0, Qt.AlignmentFlag.AlignVCenter)

        source_label = QLabel("Manual track playlist")
        source_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_XS))
        source_label.setStyleSheet(_label_css(Colors.TEXT_TERTIARY))
        meta_row.addWidget(source_label, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addStretch()
        title_col.addLayout(meta_row)
        header.addLayout(title_col, 1)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(button_css("secondary", "sm"))
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save")
        self.save_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM, QFont.Weight.Bold))
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        _save_ic = glyph_icon("check-circle", 14, Colors.TEXT_ON_ACCENT)
        if _save_ic:
            self.save_btn.setIcon(_save_ic)
            self.save_btn.setIconSize(QSize(14, 14))
        self.save_btn.setStyleSheet(accent_btn_css())
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        header.addLayout(btn_row)
        root.addLayout(header)
        root.addWidget(make_separator())

        root.addWidget(_section_header("Settings"))

        settings_panel = QFrame()
        settings_panel.setObjectName("regularPlaylistSettingsPanel")
        settings_panel.setStyleSheet(_editor_panel_css("regularPlaylistSettingsPanel"))
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(10, 8, 10, 9)
        settings_layout.setSpacing(8)

        sort_row = QHBoxLayout()
        sort_row.setContentsMargins(0, 0, 0, 0)
        sort_row.setSpacing(8)
        sort_label = QLabel("Sort Order")
        sort_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        sort_label.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
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
            f"color: {Colors.ACCENT};"
            "background: transparent;"
            f"border: 1px solid {Colors.ACCENT_BORDER};"
            "border-radius: 9px;"
        )
        note_layout.addWidget(note_icon, 0, Qt.AlignmentFlag.AlignTop)

        note_text = QLabel(
            "To add tracks, right-click a library track and choose this playlist from Add to Playlist.",
            add_tracks_note,
        )
        note_text.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        note_text.setStyleSheet(_label_css(Colors.TEXT_SECONDARY))
        note_text.setWordWrap(True)
        note_layout.addWidget(note_text, 1)

        root.addWidget(add_tracks_note)
        root.addStretch()

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def new_playlist(self) -> None:
        """Set up for creating a brand-new regular playlist."""
        self._editing_playlist = None
        self.name_input.setText("")
        self.name_input.setPlaceholderText("New Playlist")
        self.description_input.setText("")
        self.sort_combo.setCurrentIndex(0)  # Manual
        self.name_input.setFocus()

    def edit_playlist(self, playlist: dict) -> None:
        """Populate the editor from an existing regular playlist dict."""
        self._editing_playlist = playlist
        self.name_input.setText(playlist.get("Title", ""))
        self.description_input.setText(playlist_description_from_row(playlist))

        # Restore sort order
        sort_order = playlist.get("sort_order", 1)
        idx = self.sort_combo.findData(sort_order)
        if idx >= 0:
            self.sort_combo.setCurrentIndex(idx)
        else:
            self.sort_combo.setCurrentIndex(0)

        self.name_input.setFocus()
        self.name_input.selectAll()

    def get_playlist_data(self) -> dict:
        """Build a dict representing the current editor state.

        Returns a dict with keys matching the parsed playlist format.
        """
        changes: dict = {
            "Title": self.name_input.text().strip() or "Untitled Playlist",
            "_isNew": self._editing_playlist is None,
            "_source": "regular",
            "sort_order": self.sort_combo.currentData() or 1,
        }
        if self._editing_playlist is None:
            changes["items"] = []
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
        self.setFixedSize((320), (200))
        self.setStyleSheet(f"""
            QDialog {{
                background: {Colors.DIALOG_BG};
                color: {Colors.TEXT_PRIMARY};
            }}
        """)

        self._choice: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins((24), (20), (24), (20))
        layout.setSpacing(12)

        title = QLabel("Create New Playlist")
        title.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Choose a playlist type:")
        subtitle.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        subtitle.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(8)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        _ic_sz = QSize((20), (20))

        # Regular playlist button
        self.regular_btn = QPushButton("Regular")
        self.regular_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self.regular_btn.setMinimumHeight(44)
        self.regular_btn.setStyleSheet(button_css("secondary", "lg"))
        _ic = glyph_icon(_ICON_REGULAR, (20), Colors.TEXT_SECONDARY)
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
        _ic = glyph_icon(_ICON_SMART, (20), Colors.TEXT_ON_ACCENT)
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
