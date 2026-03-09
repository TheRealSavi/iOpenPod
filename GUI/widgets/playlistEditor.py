"""
PlaylistEditor — Create & edit smart and regular playlists.

Provides:
    SmartPlaylistEditor  — full rule-based editor for smart playlists
    SmartRuleRow         — single editable rule (field + action + value)
    NewPlaylistDialog    — choose smart vs. regular when creating
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QVBoxLayout, QWidget,
)

from ..styles import Colors, FONT_FAMILY, Metrics, btn_css, accent_btn_css, scaled
from ..glyphs import glyph_icon, glyph_pixmap

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants for dropdowns (mirrored from iTunesDB_Parser/mhod_parser.py)
# ─────────────────────────────────────────────────────────────────────────────

# Field type enum
SPLFT_STRING = 1
SPLFT_INT = 2
SPLFT_BOOLEAN = 3
SPLFT_DATE = 4
SPLFT_PLAYLIST = 5
SPLFT_BINARY_AND = 7

# Field ID → (display name, field type)
FIELD_DEFS: dict[int, tuple[str, int]] = {
    0x02: ("Name", SPLFT_STRING),
    0x03: ("Album", SPLFT_STRING),
    0x04: ("Artist", SPLFT_STRING),
    0x05: ("Bitrate", SPLFT_INT),
    0x06: ("Sample Rate", SPLFT_INT),
    0x07: ("Year", SPLFT_INT),
    0x08: ("Genre", SPLFT_STRING),
    0x09: ("Kind", SPLFT_STRING),
    0x0A: ("Date Modified", SPLFT_DATE),
    0x0B: ("Track Number", SPLFT_INT),
    0x0C: ("Size", SPLFT_INT),
    0x0D: ("Time", SPLFT_INT),
    0x0E: ("Comment", SPLFT_STRING),
    0x10: ("Date Added", SPLFT_DATE),
    0x12: ("Composer", SPLFT_STRING),
    0x16: ("Play Count", SPLFT_INT),
    0x17: ("Last Played", SPLFT_DATE),
    0x18: ("Disc Number", SPLFT_INT),
    0x19: ("Rating", SPLFT_INT),
    0x1F: ("Compilation", SPLFT_BOOLEAN),
    0x23: ("BPM", SPLFT_INT),
    0x27: ("Grouping", SPLFT_STRING),
    0x28: ("Playlist", SPLFT_PLAYLIST),
    0x29: ("Has Video", SPLFT_BOOLEAN),
    0x36: ("Description", SPLFT_STRING),
    0x37: ("Category", SPLFT_STRING),
    0x39: ("Video Kind", SPLFT_INT),
    0x3C: ("Media Type", SPLFT_BINARY_AND),
    0x3E: ("Video Show", SPLFT_STRING),
    0x3F: ("Season Number", SPLFT_INT),
    0x40: ("Episode Number", SPLFT_INT),
    0x44: ("Skip Count", SPLFT_INT),
    0x45: ("Last Skipped", SPLFT_DATE),
    0x47: ("Album Artist", SPLFT_STRING),
    0x5A: ("Album Rating", SPLFT_INT),
}

# Actions grouped by field type
STRING_ACTIONS: list[tuple[int, str]] = [
    (0x01000001, "is"),
    (0x03000001, "is not"),
    (0x01000002, "contains"),
    (0x03000002, "does not contain"),
    (0x01000004, "starts with"),
    (0x03000004, "does not start with"),
    (0x01000008, "ends with"),
    (0x03000008, "does not end with"),
]

INT_ACTIONS: list[tuple[int, str]] = [
    (0x00000001, "is"),
    (0x02000001, "is not"),
    (0x00000010, "is greater than"),
    (0x00000040, "is less than"),
    (0x00000100, "is in the range"),
    (0x02000100, "is not in the range"),
]

DATE_ACTIONS: list[tuple[int, str]] = [
    (0x00000200, "is in the last"),
    (0x02000200, "is not in the last"),
]

BOOLEAN_ACTIONS: list[tuple[int, str]] = [
    (0x00000001, "is set"),
    (0x02000001, "is not set"),
]

BINARY_AND_ACTIONS: list[tuple[int, str]] = [
    (0x00000400, "includes"),
    (0x02000400, "excludes"),
]

PLAYLIST_ACTIONS: list[tuple[int, str]] = [
    (0x00000001, "is"),
    (0x02000001, "is not"),
]

# Date units for relative dates
DATE_UNITS: list[tuple[int, str]] = [
    (86400, "days"),
    (604800, "weeks"),
    (2628000, "months"),
    (3600, "hours"),
    (60, "minutes"),
]

# Limit types
LIMIT_TYPES: list[tuple[int, str]] = [
    (0x03, "items"),
    (0x01, "minutes"),
    (0x04, "hours"),
    (0x02, "MB"),
    (0x05, "GB"),
]

# Limit sort options
LIMIT_SORTS: list[tuple[int, str]] = [
    (0x02, "random"),
    (0x03, "name"),
    (0x04, "album"),
    (0x07, "artist"),
    (0x09, "genre"),
    (0x14, "most recently added"),
    (0x80000014, "least recently added"),
    (0x15, "most often played"),
    (0x80000015, "least often played"),
    (0x17, "most recently played"),
    (0x80000017, "least recently played"),
    (0x05, "highest rating"),
    (0x80000005, "lowest rating"),
]

# Media type bitmask flags for the Binary AND field
MEDIA_TYPE_FLAGS: list[tuple[int, str]] = [
    (0x01, "Music"),
    (0x02, "Video"),
    (0x04, "Podcast"),
    (0x06, "Video Podcast"),
    (0x08, "Audiobook"),
    (0x20, "Music Video"),
    (0x40, "TV Show"),
    (0x100, "Ringtone"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Shared stylesheet helpers
# ─────────────────────────────────────────────────────────────────────────────

def _combo_css() -> str:
    return f"""
    QComboBox {{
        background: {Colors.SURFACE_RAISED};
        border: 1px solid {Colors.BORDER_SUBTLE};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {Colors.TEXT_PRIMARY};
        padding: {scaled(4)}px {scaled(8)}px;
        font-family: {FONT_FAMILY};
        font-size: {Metrics.FONT_LG}px;
        min-height: {scaled(22)}px;
    }}
    QComboBox:hover {{
        border-color: {Colors.ACCENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: {scaled(20)}px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: {scaled(4)}px solid transparent;
        border-right: {scaled(4)}px solid transparent;
        border-top: {scaled(5)}px solid {Colors.TEXT_SECONDARY};
        margin-right: {scaled(6)}px;
    }}
    QComboBox QAbstractItemView {{
        background: {Colors.DROPDOWN_BG};
        border: 1px solid {Colors.BORDER};
        color: {Colors.TEXT_PRIMARY};
        selection-background-color: {Colors.ACCENT};
        selection-color: {Colors.TEXT_ON_ACCENT};
        padding: {scaled(2)}px;
    }}
"""


def _input_css() -> str:
    return f"""
    QLineEdit {{
        background: {Colors.SURFACE_RAISED};
        border: 1px solid {Colors.BORDER_SUBTLE};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {Colors.TEXT_PRIMARY};
        padding: {scaled(4)}px {scaled(8)}px;
        font-family: {FONT_FAMILY};
        font-size: {Metrics.FONT_LG}px;
        min-height: {scaled(22)}px;
    }}
    QLineEdit:hover {{
        border-color: {Colors.ACCENT};
    }}
    QLineEdit:focus {{
        border-color: {Colors.ACCENT};
    }}
"""


def _spinbox_css() -> str:
    return f"""
    QSpinBox {{
        background: {Colors.SURFACE_RAISED};
        border: 1px solid {Colors.BORDER_SUBTLE};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {Colors.TEXT_PRIMARY};
        padding: {scaled(4)}px {scaled(8)}px;
        font-family: {FONT_FAMILY};
        font-size: {Metrics.FONT_LG}px;
        min-height: {scaled(22)}px;
    }}
    QSpinBox:hover {{
        border-color: {Colors.ACCENT};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background: {Colors.SURFACE_HOVER};
        border: none;
        width: {scaled(16)}px;
    }}
    QSpinBox::up-arrow {{
        border-left: {scaled(3)}px solid transparent;
        border-right: {scaled(3)}px solid transparent;
        border-bottom: {scaled(4)}px solid {Colors.TEXT_SECONDARY};
    }}
    QSpinBox::down-arrow {{
        border-left: {scaled(3)}px solid transparent;
        border-right: {scaled(3)}px solid transparent;
        border-top: {scaled(4)}px solid {Colors.TEXT_SECONDARY};
    }}
"""


def _checkbox_css() -> str:
    return f"""
    QCheckBox {{
        color: {Colors.TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
        font-size: {Metrics.FONT_LG}px;
        spacing: {scaled(6)}px;
    }}
    QCheckBox::indicator {{
        width: {scaled(16)}px;
        height: {scaled(16)}px;
        border: 1px solid {Colors.BORDER_SUBTLE};
        border-radius: {scaled(3)}px;
        background: {Colors.SURFACE_RAISED};
    }}
    QCheckBox::indicator:hover {{
        border-color: {Colors.ACCENT};
    }}
    QCheckBox::indicator:checked {{
        background: {Colors.ACCENT};
        border-color: {Colors.ACCENT};
    }}
"""


def _section_label_style() -> str:
    return (
        f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none; "
        f"font-size: {Metrics.FONT_SM}px; font-weight: bold;"
    )


def _remove_btn_css() -> str:
    return btn_css(
        bg=Colors.DANGER_DIM,
        bg_hover=Colors.DANGER_HOVER,
        bg_press=Colors.DANGER_DIM,
        fg=Colors.DANGER,
        radius=Metrics.BORDER_RADIUS_SM,
        padding=f"{scaled(2)}px {scaled(6)}px",
    )


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
     - Boolean:    (no value — is set / is not set)
     - Binary AND: QComboBox with media type flags
     - Playlist:   QComboBox with playlist names
    """

    remove_clicked = pyqtSignal(object)  # emits self
    changed = pyqtSignal()               # any field changed

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setStyleSheet("QFrame { background: transparent; border: none; }")

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, scaled(2), 0, scaled(2))
        self._layout.setSpacing(scaled(6))

        # ── Field selector ──
        self.field_combo = QComboBox()
        self.field_combo.setStyleSheet(_combo_css())
        self.field_combo.setMinimumWidth(scaled(120))
        self.field_combo.setMaximumWidth(scaled(160))
        for fid, (name, _ftype) in sorted(FIELD_DEFS.items(), key=lambda x: x[1][0]):
            self.field_combo.addItem(name, fid)
        self._layout.addWidget(self.field_combo)

        # ── Action selector ──
        self.action_combo = QComboBox()
        self.action_combo.setStyleSheet(_combo_css())
        self.action_combo.setMinimumWidth(scaled(130))
        self.action_combo.setMaximumWidth(scaled(180))
        self._layout.addWidget(self.action_combo)

        # ── Value area (container swapped based on field type) ──
        self._value_container = QWidget()
        self._value_container.setStyleSheet("background: transparent; border: none;")
        self._value_layout = QHBoxLayout(self._value_container)
        self._value_layout.setContentsMargins(0, 0, 0, 0)
        self._value_layout.setSpacing(scaled(4))
        self._layout.addWidget(self._value_container, stretch=1)

        # ── Remove button ──
        self.remove_btn = QPushButton()
        _close_ic = glyph_icon("close", scaled(12), Colors.DANGER)
        if _close_ic:
            self.remove_btn.setIcon(_close_ic)
        else:
            self.remove_btn.setText("✕")
        self.remove_btn.setFixedSize(scaled(24), scaled(24))
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
        elif ft == SPLFT_INT:
            spins: list[QSpinBox] = self._find_widgets(QSpinBox)  # type: ignore[assignment]
            if spins:
                data["from_value"] = spins[0].value()
            if len(spins) > 1:
                data["to_value"] = spins[1].value()
            # Rating special case — compute star values for formatter
            if fid == 0x19:  # Rating
                data["from_value_stars"] = data["from_value"]
                data["to_value_stars"] = data["to_value"]
        elif ft == SPLFT_DATE:
            spin: QSpinBox | None = self._find_widget(QSpinBox)  # type: ignore[assignment]
            # date rule: from_value = negative count, from_units = seconds-per-unit
            if spin:
                data["from_value"] = -abs(spin.value())
                data["from_date"] = -abs(spin.value())
            date_unit_combo = self._find_value_combo()
            if date_unit_combo:
                data["from_units"] = date_unit_combo.currentData() or 86400
                data["to_units"] = date_unit_combo.currentData() or 86400
                data["units_name"] = date_unit_combo.currentText() or ""
        elif ft == SPLFT_BOOLEAN:
            pass  # no value
        elif ft == SPLFT_BINARY_AND:
            combo = self._find_value_combo()
            if combo:
                data["from_value"] = combo.currentData() or 0x01
        elif ft == SPLFT_PLAYLIST:
            # Playlist rules store the playlist ID as fromValue
            # For now, just store 0 — will need playlist list hookup
            pass

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
        if idx >= 0:
            self.action_combo.setCurrentIndex(idx)

        # Set value
        ft = FIELD_DEFS.get(fid, ("", SPLFT_STRING))[1]
        if ft == SPLFT_STRING:
            w_le: QLineEdit | None = self._find_widget(QLineEdit)  # type: ignore[assignment]
            if w_le:
                w_le.setText(rule.get("string_value", "") or "")
        elif ft == SPLFT_INT:
            spins_sb: list[QSpinBox] = self._find_widgets(QSpinBox)  # type: ignore[assignment]
            if spins_sb:
                spins_sb[0].setValue(rule.get("from_value", 0))
            if len(spins_sb) > 1:
                spins_sb[1].setValue(rule.get("to_value", 0))
        elif ft == SPLFT_DATE:
            spin_sb: QSpinBox | None = self._find_widget(QSpinBox)  # type: ignore[assignment]
            if spin_sb:
                spin_sb.setValue(abs(rule.get("from_value", 0) or rule.get("from_date", 0)))
            unit_combo = self._find_value_combo()
            if unit_combo:
                units = rule.get("from_units", 86400) or 86400
                idx = unit_combo.findData(units)
                if idx >= 0:
                    unit_combo.setCurrentIndex(idx)
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
        actions = self._actions_for_type(ft)
        for aid, label in actions:
            self.action_combo.addItem(label, aid)
        self.action_combo.blockSignals(False)

        # Rebuild value widgets
        self._clear_value_widgets()
        self._current_field_type = ft

        if ft == SPLFT_STRING:
            le = QLineEdit()
            le.setPlaceholderText("value")
            le.setStyleSheet(_input_css())
            le.setMinimumWidth(scaled(120))
            le.textChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(le)

        elif ft == SPLFT_INT:
            spin = QSpinBox()
            spin.setRange(-999999, 999999)
            spin.setStyleSheet(_spinbox_css())
            spin.setMinimumWidth(scaled(80))
            spin.valueChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(spin)

            # "in range" needs a second spin
            self._range_label = QLabel("to")
            self._range_label.setStyleSheet(
                f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;"
            )
            self._range_label.setVisible(False)
            self._add_value_widget(self._range_label)

            spin2 = QSpinBox()
            spin2.setRange(-999999, 999999)
            spin2.setStyleSheet(_spinbox_css())
            spin2.setMinimumWidth(scaled(80))
            spin2.setVisible(False)
            spin2.valueChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(spin2)

            # Watch for range action
            self.action_combo.currentIndexChanged.connect(self._update_range_visibility)

        elif ft == SPLFT_DATE:
            spin = QSpinBox()
            spin.setRange(1, 99999)
            spin.setValue(30)
            spin.setStyleSheet(_spinbox_css())
            spin.setMinimumWidth(scaled(70))
            spin.valueChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(spin)

            unit_combo = QComboBox()
            unit_combo.setStyleSheet(_combo_css())
            for uid, uname in DATE_UNITS:
                unit_combo.addItem(uname, uid)
            unit_combo.currentIndexChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(unit_combo)

        elif ft == SPLFT_BOOLEAN:
            # No value needed — action is "is set" / "is not set"
            placeholder = QLabel("")
            placeholder.setStyleSheet("background: transparent; border: none;")
            self._add_value_widget(placeholder)

        elif ft == SPLFT_BINARY_AND:
            combo = QComboBox()
            combo.setStyleSheet(_combo_css())
            combo.setMinimumWidth(scaled(120))
            for flag_val, flag_name in MEDIA_TYPE_FLAGS:
                combo.addItem(flag_name, flag_val)
            combo.currentIndexChanged.connect(lambda: self.changed.emit())
            self._add_value_widget(combo)

        elif ft == SPLFT_PLAYLIST:
            combo = QComboBox()
            combo.setStyleSheet(_combo_css())
            combo.setMinimumWidth(scaled(120))
            combo.addItem("(select playlist)", 0)
            # TODO: populate with actual playlists
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

    def _actions_for_type(self, ft: int) -> list[tuple[int, str]]:
        match ft:
            case 1: return STRING_ACTIONS
            case 2: return INT_ACTIONS
            case 3: return BOOLEAN_ACTIONS
            case 4: return DATE_ACTIONS
            case 5: return PLAYLIST_ACTIONS
            case 7: return BINARY_AND_ACTIONS
            case _: return INT_ACTIONS

    def _clear_value_widgets(self) -> None:
        # Disconnect the range visibility slot if it was connected
        try:
            self.action_combo.currentIndexChanged.disconnect(self._update_range_visibility)
        except (TypeError, RuntimeError):
            pass
        if hasattr(self, "_range_label"):
            del self._range_label
        for w in self._value_widgets:
            w.setParent(None)  # type: ignore
            w.deleteLater()
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

    def _find_value_combo(self) -> Optional[QComboBox]:
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

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("smartPlaylistEditor")
        self.setStyleSheet(f"""
            QFrame#smartPlaylistEditor {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_LG}px;
            }}
        """)

        self._editing_playlist: Optional[dict] = None  # None → new playlist

        root = QVBoxLayout(self)
        root.setContentsMargins(scaled(16), scaled(14), scaled(16), scaled(14))
        root.setSpacing(scaled(10))

        # ── Header: Name ──────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(scaled(8))
        icon = QLabel()
        _px = glyph_pixmap("filter", scaled(28), Colors.ACCENT)
        if _px:
            icon.setPixmap(_px)
        else:
            icon.setText("◇")
            icon.setFont(QFont(FONT_FAMILY, Metrics.FONT_HERO))
        icon.setStyleSheet("background: transparent; border: none;")
        header.addWidget(icon)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Playlist Name")
        self.name_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        self.name_input.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                border-bottom: 2px solid {Colors.BORDER_SUBTLE};
                color: {Colors.TEXT_PRIMARY};
                padding: {scaled(4)}px {scaled(2)}px;
                font-size: {Metrics.FONT_TITLE}px;
            }}
            QLineEdit:focus {{
                border-bottom-color: {Colors.ACCENT};
            }}
        """)
        header.addWidget(self.name_input, stretch=1)
        root.addLayout(header)

        # ── Conjunction row ───────────────────────────────────
        conj_row = QHBoxLayout()
        conj_row.setSpacing(scaled(6))

        lbl = QLabel("Match")
        lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        lbl.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
        conj_row.addWidget(lbl)

        self.conjunction_combo = QComboBox()
        self.conjunction_combo.setStyleSheet(_combo_css())
        self.conjunction_combo.addItem("all", "AND")
        self.conjunction_combo.addItem("any", "OR")
        self.conjunction_combo.setFixedWidth(scaled(70))
        conj_row.addWidget(self.conjunction_combo)

        lbl2 = QLabel("of the following rules:")
        lbl2.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        lbl2.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent; border: none;")
        conj_row.addWidget(lbl2)
        conj_row.addStretch()
        root.addLayout(conj_row)

        # ── Rules area (scrollable) ──────────────────────────
        self._rules_scroll = QScrollArea()
        self._rules_scroll.setWidgetResizable(True)
        self._rules_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rules_scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {Colors.SHADOW_LIGHT};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
            }}
        """)
        self._rules_scroll.setMinimumHeight(scaled(80))
        self._rules_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._rules_widget = QWidget()
        self._rules_widget.setStyleSheet("background: transparent;")
        self._rules_layout = QVBoxLayout(self._rules_widget)
        self._rules_layout.setContentsMargins(scaled(8), scaled(6), scaled(8), scaled(6))
        self._rules_layout.setSpacing(scaled(2))
        self._rules_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._rules_scroll.setWidget(self._rules_widget)
        root.addWidget(self._rules_scroll, stretch=1)

        self._rule_rows: list[SmartRuleRow] = []

        # ── Add Rule button ──────────────────────────────────
        add_row = QHBoxLayout()
        self.add_rule_btn = QPushButton("＋ Add Rule")
        self.add_rule_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self.add_rule_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_rule_btn.setStyleSheet(btn_css(
            bg="transparent",
            bg_hover=Colors.ACCENT_DIM,
            bg_press=Colors.ACCENT_PRESS,
            fg=Colors.ACCENT,
            border=f"1px solid {Colors.ACCENT_BORDER}",
            padding="5px 14px",
        ))
        self.add_rule_btn.clicked.connect(self._add_empty_rule)
        add_row.addWidget(self.add_rule_btn)
        add_row.addStretch()
        root.addLayout(add_row)

        # ── Separator ────────────────────────────────────────
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {Colors.BORDER_SUBTLE}; border: none;")
        root.addWidget(sep)

        # ── Options area ─────────────────────────────────────
        opts = QVBoxLayout()
        opts.setSpacing(scaled(8))

        # Limit row
        limit_row = QHBoxLayout()
        limit_row.setSpacing(scaled(6))

        self.limit_check = QCheckBox("Limit to")
        self.limit_check.setStyleSheet(_checkbox_css())
        self.limit_check.toggled.connect(self._on_limit_toggled)
        limit_row.addWidget(self.limit_check)

        self.limit_value_spin = QSpinBox()
        self.limit_value_spin.setRange(1, 99999)
        self.limit_value_spin.setValue(25)
        self.limit_value_spin.setStyleSheet(_spinbox_css())
        self.limit_value_spin.setFixedWidth(scaled(80))
        self.limit_value_spin.setEnabled(False)
        limit_row.addWidget(self.limit_value_spin)

        self.limit_type_combo = QComboBox()
        self.limit_type_combo.setStyleSheet(_combo_css())
        for lt_id, lt_name in LIMIT_TYPES:
            self.limit_type_combo.addItem(lt_name, lt_id)
        self.limit_type_combo.setFixedWidth(scaled(90))
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
        self.limit_sort_combo.setFixedWidth(scaled(170))
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
        sort_row.setSpacing(scaled(6))
        sort_lbl = QLabel("Sort Order:")
        sort_lbl.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        sort_lbl.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;"
        )
        sort_row.addWidget(sort_lbl)

        self.sort_combo = QComboBox()
        self.sort_combo.setStyleSheet(_combo_css())
        self.sort_combo.setFixedWidth(scaled(170))
        for s_id, s_name in PLAYLIST_SORT_ORDERS:
            self.sort_combo.addItem(s_name, s_id)
        sort_row.addWidget(self.sort_combo)
        sort_row.addStretch()
        opts.addLayout(sort_row)

        root.addLayout(opts)

        # ── Separator ────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background-color: {Colors.BORDER_SUBTLE}; border: none;")
        root.addWidget(sep2)

        # ── Button row ───────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(scaled(8))
        btn_row.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_HOVER,
            bg_press=Colors.SURFACE_ACTIVE,
            border=f"1px solid {Colors.BORDER_SUBTLE}",
            padding="6px 20px",
        ))
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        btn_row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save Playlist")
        self.save_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.Bold))
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet(accent_btn_css())
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        root.addLayout(btn_row)

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def new_playlist(self) -> None:
        """Set up for creating a brand-new smart playlist."""
        self._editing_playlist = None
        self.name_input.setText("")
        self.name_input.setPlaceholderText("New Smart Playlist")
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

        result = {
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

        # Preserve existing IDs when editing
        if self._editing_playlist:
            for key in ("playlist_id", "playlist_id_2", "unk0x24",
                        "timestamp", "timestamp_2",
                        "_source", "mhsd5_type"):
                if key in self._editing_playlist:
                    result[key] = self._editing_playlist[key]

        return result

    # ─────────────────────────────────────────────────────────────
    # Internal
    # ─────────────────────────────────────────────────────────────

    def _add_empty_rule(self) -> SmartRuleRow:
        row = SmartRuleRow()
        row.remove_clicked.connect(self._remove_rule)
        row.changed.connect(lambda: None)  # future: live preview
        self._rules_layout.addWidget(row)
        self._rule_rows.append(row)
        return row

    def _remove_rule(self, row: SmartRuleRow) -> None:
        if row in self._rule_rows:
            self._rule_rows.remove(row)
            row.setParent(None)  # type: ignore
            row.deleteLater()
        # Always keep at least one rule
        if not self._rule_rows:
            self._add_empty_rule()

    def _clear_rules(self) -> None:
        for row in self._rule_rows:
            row.setParent(None)  # type: ignore
            row.deleteLater()
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

# Sort order options for regular playlists (from libgpod ItdbPlaylistSortOrder)
PLAYLIST_SORT_ORDERS: list[tuple[int, str]] = [
    (1, "Manual"),
    (3, "Title"),
    (4, "Album"),
    (5, "Artist"),
    (6, "Bitrate"),
    (7, "Genre"),
    (8, "Kind"),
    (9, "Date Modified"),
    (10, "Track Number"),
    (11, "Size"),
    (12, "Time"),
    (13, "Year"),
    (14, "Sample Rate"),
    (15, "Comment"),
    (16, "Date Added"),
    (17, "Equalizer"),
    (18, "Composer"),
    (20, "Play Count"),
    (21, "Last Played"),
    (22, "Disc Number"),
    (23, "Rating"),
    (24, "Release Date"),
    (25, "BPM"),
    (26, "Grouping"),
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

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("regularPlaylistEditor")
        self.setStyleSheet(f"""
            QFrame#regularPlaylistEditor {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_LG}px;
            }}
        """)

        self._editing_playlist: Optional[dict] = None  # None → new playlist

        root = QVBoxLayout(self)
        root.setContentsMargins(scaled(16), scaled(14), scaled(16), scaled(14))
        root.setSpacing(scaled(12))

        # ── Header: Name ──────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(scaled(8))
        icon = QLabel()
        _px = glyph_pixmap("annotation-dots", scaled(28), Colors.ACCENT)
        if _px:
            icon.setPixmap(_px)
        else:
            icon.setText("≡")
            icon.setFont(QFont(FONT_FAMILY, Metrics.FONT_HERO))
        icon.setStyleSheet("background: transparent; border: none;")
        header.addWidget(icon)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Playlist Name")
        self.name_input.setFont(QFont(FONT_FAMILY, Metrics.FONT_TITLE, QFont.Weight.Bold))
        self.name_input.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                border-bottom: 2px solid {Colors.BORDER_SUBTLE};
                color: {Colors.TEXT_PRIMARY};
                padding: {scaled(4)}px {scaled(2)}px;
                font-size: {Metrics.FONT_TITLE}px;
            }}
            QLineEdit:focus {{
                border-bottom-color: {Colors.ACCENT};
            }}
        """)
        header.addWidget(self.name_input, stretch=1)
        root.addLayout(header)

        # ── Separator ─────────────────────────────────────────
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setStyleSheet(f"color: {Colors.BORDER_SUBTLE}; background: transparent;")
        root.addWidget(sep1)

        # ── Sort Order ────────────────────────────────────────
        sort_row = QHBoxLayout()
        sort_row.setSpacing(scaled(8))
        sort_label = QLabel("Sort Order:")
        sort_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        sort_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; background: transparent; border: none;")
        sort_row.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        self.sort_combo.setMinimumWidth(scaled(180))
        self.sort_combo.setStyleSheet(f"""
            QComboBox {{
                background: {Colors.SURFACE_RAISED};
                color: {Colors.TEXT_PRIMARY};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {scaled(4)}px;
                padding: {scaled(4)}px {scaled(8)}px;
            }}
            QComboBox:hover {{
                border-color: {Colors.ACCENT};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {scaled(20)}px;
            }}
            QComboBox QAbstractItemView {{
                background: {Colors.SURFACE_RAISED};
                color: {Colors.TEXT_PRIMARY};
                selection-background-color: {Colors.ACCENT_DIM};
                border: 1px solid {Colors.BORDER_SUBTLE};
            }}
        """)
        for sort_id, sort_name in PLAYLIST_SORT_ORDERS:
            self.sort_combo.addItem(sort_name, sort_id)
        sort_row.addWidget(self.sort_combo)
        sort_row.addStretch()
        root.addLayout(sort_row)

        # ── Info area (for future options) ────────────────────
        info_label = QLabel(
            "Tracks can be added to this playlist from the music browser."
        )
        info_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        info_label.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;"
        )
        info_label.setWordWrap(True)
        root.addWidget(info_label)

        # ── Spacer to push buttons to bottom ──────────────────
        root.addStretch()

        # ── Separator ─────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {Colors.BORDER_SUBTLE}; background: transparent;")
        root.addWidget(sep2)

        # ── Buttons ───────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(scaled(8))
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setMinimumWidth(scaled(80))
        cancel_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_HOVER,
            bg_press=Colors.SURFACE_ACTIVE,
            border=f"1px solid {Colors.BORDER_SUBTLE}",
            padding="6px 16px",
        ))
        cancel_btn.clicked.connect(self.cancelled.emit)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setMinimumWidth(scaled(80))
        save_btn.setStyleSheet(accent_btn_css())
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        root.addLayout(btn_row)

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────

    def new_playlist(self) -> None:
        """Set up for creating a brand-new regular playlist."""
        self._editing_playlist = None
        self.name_input.setText("")
        self.name_input.setPlaceholderText("New Playlist")
        self.sort_combo.setCurrentIndex(0)  # Manual
        self.name_input.setFocus()

    def edit_playlist(self, playlist: dict) -> None:
        """Populate the editor from an existing regular playlist dict."""
        self._editing_playlist = playlist
        self.name_input.setText(playlist.get("Title", ""))

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
        result: dict = {
            "Title": self.name_input.text().strip() or "Untitled Playlist",
            "_isNew": self._editing_playlist is None,
            "_source": "regular",
            "sort_order": self.sort_combo.currentData() or 1,
            "items": [],
        }

        # Preserve existing IDs / items when editing
        if self._editing_playlist:
            for key in ("playlist_id", "playlist_id_2", "unk0x24",
                        "timestamp", "timestamp_2", "items", "_source"):
                if key in self._editing_playlist:
                    result[key] = self._editing_playlist[key]

        return result

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

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("New Playlist")
        self.setFixedSize(scaled(320), scaled(200))
        self.setStyleSheet(f"""
            QDialog {{
                background: {Colors.DIALOG_BG};
                color: {Colors.TEXT_PRIMARY};
            }}
        """)

        self._choice: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled(24), scaled(20), scaled(24), scaled(20))
        layout.setSpacing(scaled(12))

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

        layout.addSpacing(scaled(8))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(scaled(12))

        _ic_sz = QSize(scaled(20), scaled(20))

        # Regular playlist button
        self.regular_btn = QPushButton("Regular")
        self.regular_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self.regular_btn.setMinimumHeight(scaled(44))
        self.regular_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_HOVER,
            bg_press=Colors.SURFACE_ACTIVE,
            border=f"1px solid {Colors.BORDER_SUBTLE}",
            padding=f"{scaled(10)}px {scaled(20)}px",
        ))
        _ic = glyph_icon(_ICON_REGULAR, scaled(20), Colors.TEXT_SECONDARY)
        if _ic:
            self.regular_btn.setIcon(_ic)
            self.regular_btn.setIconSize(_ic_sz)
        self.regular_btn.clicked.connect(lambda: self._select("regular"))
        btn_row.addWidget(self.regular_btn)

        # Smart playlist button
        self.smart_btn = QPushButton("Smart")
        self.smart_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_LG))
        self.smart_btn.setMinimumHeight(scaled(44))
        self.smart_btn.setStyleSheet(btn_css(
            bg=Colors.ACCENT_DIM,
            bg_hover=Colors.ACCENT_HOVER,
            bg_press=Colors.ACCENT_PRESS,
            fg=Colors.TEXT_ON_ACCENT,
            border=f"1px solid {Colors.ACCENT_BORDER}",
            padding=f"{scaled(10)}px {scaled(20)}px",
        ))
        _ic = glyph_icon(_ICON_SMART, scaled(20), Colors.TEXT_ON_ACCENT)
        if _ic:
            self.smart_btn.setIcon(_ic)
            self.smart_btn.setIconSize(_ic_sz)
        self.smart_btn.clicked.connect(lambda: self._select("smart"))
        btn_row.addWidget(self.smart_btn)

        layout.addLayout(btn_row)

    def _select(self, choice: str) -> None:
        self._choice = choice
        self.accept()

    def get_choice(self) -> Optional[str]:
        return self._choice


# Re-export icons used by playlist browser
_ICON_REGULAR = "annotation-dots"
_ICON_SMART = "filter"
