"""Optional metadata timestamps with separate, themed date and time controls."""

from PySide6.QtCore import QDate, QEvent, QLocale, QTime, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from whenever import SYSTEM_TZ, Instant

from iOpenPod.app.core.dates import HostDateZone, parse_iso_instant
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_date_edit import AppDateEdit
from iOpenPod.GUI.widgets.app_time_edit import AppTimeEdit
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    IconButton,
    IconButtonKind,
)


def _civil_fields(timestamp: int) -> tuple[QDate, QTime] | None:
    try:
        instant = Instant.from_timestamp(timestamp)
        try:
            local = instant.to_tz(SYSTEM_TZ)
        except (ValueError, OSError, OverflowError):
            local = instant.to_tz("UTC")
        return (
            QDate(local.year, local.month, local.day),
            QTime(local.hour, local.minute, local.second),
        )
    except (ValueError, OSError, OverflowError):
        return None


class MetadataDateEdit(QWidget):
    """Keep unset, mixed and unrepresentable dates unchanged until explicitly edited.

    QDate/QTime are civil-field adapters only. Whenever interprets edits in the
    Host zone, while unchanged coordinates retain the exact original instant,
    including the later occurrence of a repeated DST hour.
    """

    valueChanged = Signal()

    def __init__(self, value: int, mixed: bool, parent: QWidget) -> None:
        super().__init__(parent)
        self._syncing = True
        self.date = AppDateEdit(self)
        self.date.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.date.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
        self.date.setKeyboardTracking(False)
        self.time = AppTimeEdit(self)
        self.time.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.time.setObjectName("metadataDateTime")
        self.time.setKeyboardTracking(False)
        self._status = QLabel(self)
        self._status.setObjectName("metadataDateStatus")
        self._status.setWordWrap(True)
        self._set_button = ActionButton(parent=self, glyph="plus")
        self._set_button.setObjectName("metadataDateSet")
        self._set_button.setAutoDefault(False)
        self._set_button.clicked.connect(self._set_date)
        self._clear_button = IconButton("x", "", self, kind=IconButtonKind.QUIET)
        self._clear_button.setObjectName("metadataDateClear")
        self._clear_button.clicked.connect(self.clear)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_2xs)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(LAYOUT.space_xs)
        controls.addWidget(self._set_button)
        controls.addWidget(self.date)
        controls.addWidget(self.time)
        controls.addWidget(self._clear_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        layout.addWidget(self._status)
        self.date.dateChanged.connect(self._edited)
        self.time.timeChanged.connect(self._edited)
        self.set_value(value, mixed=mixed)
        self._translate()

    def set_value(self, value: int, *, mixed: bool = False) -> None:
        """Load an original timestamp without reporting a user edit."""
        self._syncing = True
        self._original = value
        self._mixed = mixed
        fields = _civil_fields(value) if value and not mixed else None
        self._available = fields is not None
        self._unavailable = bool(value) and not mixed and fields is None
        if fields is not None:
            self.date.setDate(fields[0])
            self.time.setTime(fields[1])
        self._initial_state = self._state()
        self._syncing = False
        self._show_state()

    def is_modified(self) -> bool:
        return self._state() != self._initial_state

    def value(self) -> int:
        if not self.is_modified():
            return self._original
        if not self._available:
            return 0
        text = self.date.date().toString("yyyy-MM-dd")
        text += "T" + self.time.time().toString("HH:mm:ss")
        return parse_iso_instant(text, naive_zone=HostDateZone.SYSTEM).timestamp()

    def clear(self) -> None:
        """Explicitly clear a single timestamp or every date in a mixed selection."""
        self._mixed = self._unavailable = self._available = False
        self._show_state()
        self.valueChanged.emit()

    def _state(self) -> tuple[bool, bool, bool, QDate, QTime]:
        return (
            self._mixed,
            self._unavailable,
            self._available,
            self.date.date() if self._available else QDate(),
            self.time.time() if self._available else QTime(),
        )

    def _set_date(self) -> None:
        fields = _civil_fields(Instant.now().timestamp())
        assert fields is not None
        self._syncing = True
        self.date.setDate(fields[0])
        self.time.setTime(QTime(0, 0))
        self._mixed = self._unavailable = False
        self._available = True
        self._syncing = False
        self._show_state()
        self.date.setFocus()
        self.valueChanged.emit()

    def _edited(self) -> None:
        if not self._syncing:
            self.valueChanged.emit()

    def _show_state(self) -> None:
        self.date.setVisible(self._available)
        self.time.setVisible(self._available)
        self._status.setVisible(self._mixed or self._unavailable)
        self._set_button.setVisible(not self._available)
        self._clear_button.setVisible(
            self._available or self._mixed or self._unavailable
        )
        self._status.setText(
            self.tr("Mixed values — unchanged")
            if self._mixed
            else self.tr("Date unavailable")
            if self._unavailable
            else self.tr("Not set")
        )
        self._status.setToolTip(str(self._original) if self._unavailable else "")
        self.setFocusProxy(self.date if self._available else self._set_button)

    def _translate(self) -> None:
        self.date.setAccessibleName(self.tr("Date"))
        self.time.setAccessibleName(self.tr("Time"))
        self.time.setToolTip(self.tr("Hours, minutes, seconds"))
        self._set_button.setText(self.tr("Set date…"))
        self._clear_button.setAccessibleName(self.tr("Clear date"))
        self._clear_button.setToolTip(self.tr("Clear date"))
        date_format = self.locale().dateFormat(QLocale.FormatType.ShortFormat)
        if "yyyy" not in date_format:
            date_format = date_format.replace("yy", "yyyy")
        self.date.setDisplayFormat(date_format)
        self._show_state()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.Type.LanguageChange, QEvent.Type.LocaleChange):
            self._translate()
        super().changeEvent(event)
