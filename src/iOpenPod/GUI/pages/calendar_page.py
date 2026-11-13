"""Device Calendar events and To Dos, preserving untouched imported date forms."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QCoreApplication,
    QDate,
    QEvent,
    QLocale,
    QPoint,
    Qt,
    QTime,
    Signal,
)
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTimeEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from whenever import SYSTEM_TZ, Date, Instant, PlainDateTime, Time

from iOpenPod.GUI.delegates.extras_delegate import ExtrasDelegate
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.calendar_month import CalendarMarker, CalendarMonth
from iOpenPod.GUI.widgets.calendar_options import CalendarOptions
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iPodDB.calendar import (
    UNCHANGED,
    CalendarDateForm,
    CalendarDateTime,
    CalendarEntryChanges,
    CalendarEntryDraft,
    CalendarEntryKind,
    CalendarExceptions,
    CalendarOccurrence,
    CalendarRecurrenceRule,
    CalendarReminderDraft,
    CalendarTodoStatus,
    project_occurrences,
    skippable_occurrence_start,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QAction, QResizeEvent, QShowEvent

    from iOpenPod.app.extras_controller import ExtrasController
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.models.extras import CalendarGroup, CalendarItem


_TODO_STATES = (
    None,
    CalendarTodoStatus.IN_PROCESS,
    CalendarTodoStatus.COMPLETED,
    CalendarTodoStatus.CANCELLED,
)
_OCCURRENCE_ROLE = Qt.ItemDataRole.UserRole + 1


def _todo_state_text(status: CalendarTodoStatus | None) -> str:
    if status is CalendarTodoStatus.IN_PROCESS:
        return QCoreApplication.translate("CalendarPage", "In progress")
    if status is CalendarTodoStatus.COMPLETED:
        return QCoreApplication.translate("CalendarPage", "Completed")
    if status is CalendarTodoStatus.CANCELLED:
        return QCoreApplication.translate("CalendarPage", "Cancelled")
    return QCoreApplication.translate("CalendarPage", "Open")


def _entry_marker(item: CalendarItem) -> CalendarMarker | None:
    """Turn a saved span or one projected day into a month-grid marker."""
    entry = item.entry
    if item.occurrence is not None and (day := item.occurrence.day) is not None:
        date = QDate(day.year, day.month, day.day)
        return CalendarMarker(
            date,
            date,
            entry.summary or QCoreApplication.translate("CalendarPage", "Untitled"),
        )
    start = (
        (item.occurrence.start if item.occurrence else entry.start)
        if entry.kind is CalendarEntryKind.EVENT
        else entry.due
    )
    if start is None or start.value is None:
        return None
    value = start.value
    local = value.to_tz("UTC").to_plain() if isinstance(value, Instant) else value
    first = QDate(local.year, local.month, local.day)
    last = first
    occurrence_end = item.occurrence.end if item.occurrence else entry.end
    if entry.kind is CalendarEntryKind.EVENT and occurrence_end is not None:
        end = occurrence_end.value
        end = end.to_tz("UTC").to_plain() if isinstance(end, Instant) else end
        if (
            end is not None
            and occurrence_end.form == start.form
            and occurrence_end.tzid == start.tzid
        ):
            last = QDate(end.year, end.month, end.day)
            if isinstance(end, Date) or end.time() == Time(0):
                last = last.addDays(-1)
    return CalendarMarker(
        first,
        max(first, last),
        entry.summary or QCoreApplication.translate("CalendarPage", "Untitled"),
    )


def _today() -> Date:
    """Host today only seeds a new draft; existing device dates never use it."""
    now = Instant.now()
    try:
        return now.to_tz(SYSTEM_TZ).date()
    except (OSError, OverflowError, ValueError):
        return now.to_tz("UTC").date()


def _today_for_widget() -> QDate:
    today = _today()
    return QDate(today.year, today.month, today.day)


def _entry_order(item: CalendarItem) -> tuple[bool, int, int, str]:
    entry = item.entry
    marker = _entry_marker(item)
    date = (
        (item.occurrence.start if item.occurrence else entry.start)
        if entry.kind is CalendarEntryKind.EVENT
        else entry.due
    )
    value = date.value if date else None
    local = value.to_tz("UTC").to_plain() if isinstance(value, Instant) else value
    seconds = (
        local.hour * 3600 + local.minute * 60 + local.second
        if isinstance(local, PlainDateTime)
        else -1
    )
    return (
        entry.completed,
        marker.first.toJulianDay() if marker else 2**31,
        seconds,
        entry.summary.casefold(),
    )


def _display_date(value: CalendarDateTime | None) -> str:
    if value is None:
        return "—"
    date = value.value
    local = date.to_tz("UTC").to_plain() if isinstance(date, Instant) else date
    if isinstance(local, (Date, PlainDateTime)):
        locale = QLocale()
        text = locale.toString(
            QDate(local.year, local.month, local.day), QLocale.FormatType.ShortFormat
        )
        if isinstance(local, PlainDateTime):
            text += " " + locale.toString(
                QTime(local.hour, local.minute, local.second),
                QLocale.FormatType.ShortFormat,
            )
        if value.form is CalendarDateForm.UTC:
            text += " UTC"
        elif value.tzid:
            text += " · " + value.tzid
        return text
    return value.raw or "—"


class _DateInput(QWidget):
    """QDate/QTime are widget adapters; the edited value remains a civil date."""

    def __init__(
        self,
        name: str,
        value: Date | PlainDateTime | Instant | None,
        parent: QWidget,
        *,
        utc: bool = False,
    ) -> None:
        super().__init__(parent)
        self._utc = utc or isinstance(value, Instant)
        local = value.to_tz("UTC").to_plain() if isinstance(value, Instant) else value
        today = _today()
        self.include = QCheckBox(self)
        self.include.setObjectName(name + "Enabled")
        self.include.setChecked(value is not None)
        self.date = QDateEdit(self)
        self.date.setObjectName(name + "Date")
        self.date.setDateRange(QDate(100, 1, 1), QDate(9999, 12, 31))
        self.date.setCalendarPopup(True)
        self.date.setDate(
            QDate(local.year, local.month, local.day)
            if isinstance(local, (Date, PlainDateTime))
            else QDate(today.year, today.month, today.day)
        )
        self.time = QTimeEdit(self)
        self.time.setObjectName(name + "Time")
        self.time.setTime(
            QTime(local.hour, local.minute, local.second)
            if isinstance(local, PlainDateTime)
            else QTime(9, 0)
        )
        self.zone = QLabel("UTC" if self._utc else "", self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.include)
        layout.addWidget(self.date)
        layout.addWidget(self.time)
        layout.addWidget(self.zone)
        layout.addStretch(1)
        self.include.toggled.connect(self._availability)
        self._availability()

    def _availability(self) -> None:
        self.date.setEnabled(self.include.isChecked())
        self.time.setEnabled(self.include.isChecked())

    def snapshot(self) -> tuple[bool, int, int, int, int, int, int]:
        date, time = self.date.date(), self.time.time()
        return (
            self.include.isChecked(),
            date.year(),
            date.month(),
            date.day(),
            time.hour(),
            time.minute(),
            time.second(),
        )

    def value(
        self, *, all_day: bool, utc: bool | None = None
    ) -> Date | PlainDateTime | Instant | None:
        if not self.include.isChecked():
            return None
        date, time = self.date.date(), self.time.time()
        civil = Date(date.year(), date.month(), date.day())
        if all_day:
            return civil
        local = civil.at(Time(time.hour(), time.minute(), time.second()))
        return local.assume_utc() if (self._utc if utc is None else utc) else local


class CalendarEditor(QDialog):
    """Edit text independently of timing, including unresolvable imported dates."""

    def __init__(
        self,
        kind: CalendarEntryKind,
        item: CalendarItem | None,
        parent: QWidget | None = None,
        *,
        initial_date: Date | None = None,
        zone_names: tuple[str, ...] = (),
    ) -> None:
        super().__init__(parent)
        self.setObjectName("calendarEditor")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(520)
        self._kind = kind
        self._item = item
        entry = item.entry if item else None
        self._timing_editable = entry is None or entry.timing_editable
        if entry is not None:
            for value in (entry.start, entry.end, entry.due):
                if value is not None and (
                    value.form is CalendarDateForm.INVALID
                    or value.value is None
                    or (
                        isinstance(value.value, (Date, PlainDateTime))
                        and value.value.year < 100
                    )
                ):
                    self._timing_editable = False
        self._summary = QLineEdit(entry.summary if entry else "", self)
        self._summary.setObjectName("calendarSummary")
        self._location = QLineEdit(entry.location if entry else "", self)
        self._location.setObjectName("calendarLocation")
        self._description = QPlainTextEdit(self)
        self._description.setObjectName("calendarDescription")
        self._description.setPlainText(entry.description if entry else "")
        self._description.setMaximumHeight(130)
        self._all_day = QCheckBox(self)
        self._all_day.setObjectName("calendarAllDay")
        initial = (
            entry.due
            if entry and kind is CalendarEntryKind.TODO
            else (entry.start if entry else None)
        )
        self._all_day.setChecked(
            initial.form is CalendarDateForm.DATE
            if initial is not None
            else kind is CalendarEntryKind.TODO
        )
        today = initial_date or _today()
        start = entry.start.value if entry and entry.start else None
        end = entry.end.value if entry and entry.end else None
        due = entry.due.value if entry and entry.due else None
        if entry is None and kind is CalendarEntryKind.EVENT:
            start, end = today.at(Time(9)), today.at(Time(10))
        utc = isinstance(start, Instant) or isinstance(due, Instant)
        self._start = _DateInput("calendarStart", start, self, utc=utc)
        self._end = _DateInput("calendarEnd", end, self, utc=utc)
        self._due = _DateInput("calendarDue", due, self, utc=utc)
        if entry is not None:
            for control, value in ((self._start, entry.start), (self._end, entry.end)):
                if value is not None and value.tzid:
                    control.zone.setText(value.tzid)
        self._has_saved_zone = bool(
            entry and any(value and value.tzid for value in (entry.start, entry.end))
        )
        self._zone_names = zone_names
        self._time_basis = AppComboBox(self)
        self._time_basis.setObjectName("calendarTimeBasis")
        self._time_basis.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._time_basis.setMinimumContentsLength(8)
        self._time_basis.addItems(["", "UTC", *zone_names])
        for index, name in enumerate(zone_names, start=2):
            self._time_basis.setItemData(index, name, Qt.ItemDataRole.ToolTipRole)
        saved_tzid = entry.start.tzid if entry and entry.start else None
        if isinstance(start, Instant) or (saved_tzid and saved_tzid.casefold() == "z"):
            self._time_basis.setCurrentIndex(1)
        elif saved_tzid is not None:
            for index, name in enumerate(zone_names, start=2):
                if name.casefold() == saved_tzid.casefold():
                    self._time_basis.setCurrentIndex(index)
                    break
        self._initial_basis = self._time_basis.currentIndex()
        self._show_time_basis = (
            kind is CalendarEntryKind.EVENT and self._timing_editable
        )
        self._todo_state = AppComboBox(self)
        self._todo_state.setObjectName("calendarTodoStatus")
        self._todo_state.addItems([""] * len(_TODO_STATES))
        self._todo_state.setCurrentIndex(
            _TODO_STATES.index(entry.todo_status if entry else None)
        )
        self._timing_note = QLabel(self)
        self._timing_note.setObjectName("pageDescription")
        self._timing_note.setWordWrap(True)
        self._timing_note.setTextFormat(Qt.TextFormat.PlainText)
        self._error = QLabel(self)
        self._error.setWordWrap(True)
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setObjectName("calendarEditorError")
        self._labels: list[tuple[QLabel, str]] = []
        form = QFormLayout()
        form.setSpacing(LAYOUT.space_sm)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        for label, widget in [
            ("Title", self._summary),
            ("Location", self._location),
            ("Notes", self._description),
        ]:
            field = QLabel(self)
            field.setBuddy(widget)
            self._labels.append((field, label))
            form.addRow(field, widget)
        form.addRow(self._all_day)
        fields = (
            [("Due", self._due)]
            if kind is CalendarEntryKind.TODO
            else [("Starts", self._start), ("Ends", self._end)]
        )
        for label, widget in fields:
            field = QLabel(self)
            field.setBuddy(widget.date)
            self._labels.append((field, label))
            form.addRow(field, widget)
        for widget in (self._start, self._end):
            widget.setVisible(kind is CalendarEntryKind.EVENT)
        self._due.setVisible(kind is CalendarEntryKind.TODO)
        for label, choice, visible in (
            (
                "Time zone",
                self._time_basis,
                self._show_time_basis,
            ),
            ("Status", self._todo_state, kind is CalendarEntryKind.TODO),
        ):
            field = QLabel(self)
            field.setBuddy(choice)
            self._labels.append((field, label))
            form.addRow(field, choice)
            form.setRowVisible(choice, visible)
        form.addRow(self._timing_note)
        self._options = CalendarOptions(entry, kind, today, self)
        form.addRow(self._options)
        self._cancel = ActionButton(parent=self)
        self._cancel.clicked.connect(self.reject)
        self._save = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._save.setObjectName("calendarEditorSave")
        self._save.setDefault(True)
        self._save.clicked.connect(self._accept_valid)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_sm)
        fields_panel = QWidget(self)
        fields_layout = QVBoxLayout(fields_panel)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.addLayout(form)
        fields_layout.addWidget(self._error)
        fields_layout.addStretch(1)
        self._fields_scroll = QScrollArea(self)
        self._fields_scroll.setObjectName("calendarEditorFields")
        self._fields_scroll.setWidgetResizable(True)
        self._fields_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._fields_scroll.setWidget(fields_panel)
        self._fields_scroll.setMinimumHeight(min(520, fields_panel.sizeHint().height()))
        layout.addWidget(self._fields_scroll, 1)
        layout.addLayout(actions)
        self._all_day.setEnabled(self._timing_editable and not self._has_saved_zone)
        for widget in (self._start, self._end, self._due):
            widget.setEnabled(self._timing_editable)
        self._initial_dates = tuple(
            w.snapshot() for w in (self._start, self._end, self._due)
        )
        self._initial_all_day = self._all_day.isChecked()
        self._all_day.toggled.connect(self._all_day_changed)
        self.retranslate_ui()
        self._update_dates()

    def set_writable(self, writable: bool) -> None:
        self._save.setEnabled(writable)

    def _all_day_changed(self, checked: bool) -> None:
        # A newly authored all-day event has an exclusive end. Qt only carries
        # widget components; Whenever owns this calendar arithmetic.
        if checked and self._item is None and self._kind is CalendarEntryKind.EVENT:
            start = self._start.value(all_day=True)
            end = self._end.value(all_day=True)
            if isinstance(start, Date) and isinstance(end, Date) and end <= start:
                try:
                    following = start.add(days=1)
                except (ValueError, OverflowError):
                    pass
                else:
                    self._end.date.setDate(
                        QDate(following.year, following.month, following.day)
                    )
        self._update_dates()

    def _update_dates(self) -> None:
        all_day = self._all_day.isChecked()
        for widget in (self._start, self._end, self._due):
            widget.time.setVisible(not all_day)
            widget.zone.setVisible(not all_day and not self._show_time_basis)
        self._time_basis.setEnabled(not all_day)
        self._refresh_timing_note()

    def _refresh_timing_note(self) -> None:
        entry = self._item.entry if self._item else None
        if not self._timing_editable and entry is not None:
            dates = [
                self.tr("Starts") + ": " + _display_date(entry.start),
                self.tr("Ends") + ": " + _display_date(entry.end),
            ]
            if self._kind is CalendarEntryKind.TODO:
                dates = [self.tr("Due") + ": " + _display_date(entry.due)]
            self._timing_note.setText(
                self.tr(
                    "Imported dates are preserved. The available controls show which settings can be edited."
                )
                + "\n"
                + "\n".join(dates)
            )
        elif self._all_day.isChecked() and self._kind is CalendarEntryKind.EVENT:
            self._timing_note.setText(
                self.tr("The end date is the first day after this all-day event.")
            )
        elif self._show_time_basis:
            self._timing_note.setText(
                self.tr("Changing the time zone keeps the clock times shown above.")
            )
        else:
            self._timing_note.setText(
                self.tr("Times use the iPod's local clock unless marked UTC.")
            )

    def selected_edit(self) -> CalendarEntryDraft | CalendarEntryChanges:
        edit = self._base_edit()
        recurrence = self._options.recurrence_change()
        exceptions = self._options.exceptions_change()
        reminder = self._options.reminder_change()
        if isinstance(edit, CalendarEntryDraft):
            return replace(
                edit,
                recurrence=recurrence
                if isinstance(recurrence, CalendarRecurrenceRule)
                else None,
                exceptions=exceptions
                if isinstance(exceptions, CalendarExceptions)
                else None,
                reminder=reminder
                if isinstance(reminder, CalendarReminderDraft)
                else None,
            )
        return replace(
            edit, recurrence=recurrence, exceptions=exceptions, reminder=reminder
        )

    def _base_edit(self) -> CalendarEntryDraft | CalendarEntryChanges:
        all_day = self._all_day.isChecked()
        status = _TODO_STATES[self._todo_state.currentIndex()]
        event = self._kind is CalendarEntryKind.EVENT
        basis = self._time_basis.currentIndex() if event and not all_day else 0
        tzid = self._zone_names[basis - 2] if basis >= 2 else None
        if self._item is None:
            return CalendarEntryDraft(
                kind=self._kind,
                summary=self._summary.text().strip(),
                location=self._location.text(),
                description=self._description.toPlainText(),
                start=self._start.value(all_day=all_day, utc=basis == 1)
                if event
                else None,
                end=self._end.value(all_day=all_day, utc=basis == 1) if event else None,
                tzid=tzid,
                due=self._due.value(all_day=all_day)
                if self._kind is CalendarEntryKind.TODO
                else None,
                todo_status=status,
            )
        entry = self._item.entry
        zone_changed = (
            self._show_time_basis and not all_day and basis != self._initial_basis
        )
        utc = basis == 1 if zone_changed else None
        changed = [
            self._timing_editable
            and (widget.snapshot() != original or all_day != self._initial_all_day)
            for widget, original in zip(
                (self._start, self._end, self._due), self._initial_dates, strict=True
            )
        ]
        return CalendarEntryChanges(
            summary=self._summary.text().strip()
            if self._summary.text().strip() != entry.summary
            else None,
            location=self._location.text()
            if self._location.text() != entry.location
            else None,
            description=self._description.toPlainText()
            if self._description.toPlainText() != entry.description
            else None,
            start=self._start.value(all_day=all_day, utc=utc)
            if event and (changed[0] or zone_changed)
            else UNCHANGED,
            end=self._end.value(all_day=all_day, utc=utc)
            if event and (changed[1] or zone_changed)
            else UNCHANGED,
            tzid=tzid if zone_changed else UNCHANGED,
            due=self._due.value(all_day=all_day)
            if changed[2] and self._kind is CalendarEntryKind.TODO
            else UNCHANGED,
            todo_status=status if status != entry.todo_status else UNCHANGED,
        )

    def _accept_valid(self) -> None:
        if not self._save.isEnabled():
            return
        if not self._summary.text().strip():
            self._error.setText(self.tr("Enter a title."))
            self._summary.setFocus()
            return
        if (
            self._item is None
            and self._kind is CalendarEntryKind.EVENT
            and not self._start.include.isChecked()
        ):
            self._error.setText(self.tr("Choose a start date for the event."))
            return
        error = self._timing_error()
        if error:
            self._error.setText(error)
            return
        edit = self._base_edit()
        start = edit.start
        end = edit.end
        if isinstance(edit, CalendarEntryChanges) and self._item is not None:
            if start is UNCHANGED:
                start = self._item.entry.start.value if self._item.entry.start else None
            if end is UNCHANGED:
                end = self._item.entry.end.value if self._item.entry.end else None
        option_error = self._options.validation_error(start, end)
        if option_error:
            self._error.setText(option_error)
            return
        self.accept()

    def _timing_error(self) -> str:
        """Validate explicit edits only; retained bad dates never gate text edits."""
        edit = self.selected_edit()
        if isinstance(edit, CalendarEntryDraft):
            start, end = edit.start, edit.end
        else:
            end_edit = edit.end if self._kind is CalendarEntryKind.EVENT else edit.due
            if edit.start is UNCHANGED and end_edit is UNCHANGED:
                return ""
            entry = self._item.entry if self._item else None
            original_start = entry.start.value if entry and entry.start else None
            original_end = (
                (entry.end if self._kind is CalendarEntryKind.EVENT else entry.due)
                if entry
                else None
            )
            start = original_start if edit.start is UNCHANGED else edit.start
            end = (
                (original_end.value if original_end else None)
                if end_edit is UNCHANGED
                else end_edit
            )
        if self._kind is CalendarEntryKind.EVENT and start is None:
            return self.tr("Choose a start date for the event.")
        if start is None or end is None:
            return ""
        if type(start) is not type(end):
            return self.tr("Start and end must use the same date form.")
        if isinstance(start, Date) and isinstance(end, Date) and end <= start:
            return self.tr(
                "The end date must be the first day after this all-day event, or later."
            )
        if (
            isinstance(start, PlainDateTime)
            and isinstance(end, PlainDateTime)
            and end <= start
        ):
            return self.tr("The end must be later than the start.")
        if isinstance(start, Instant) and isinstance(end, Instant) and end <= start:
            return self.tr("The end must be later than the start.")
        return ""

    def retranslate_ui(self) -> None:
        self._options.retranslate_ui()
        if self._kind is CalendarEntryKind.EVENT:
            self.setWindowTitle(
                self.tr("Edit event") if self._item else self.tr("New event")
            )
        else:
            self.setWindowTitle(
                self.tr("Edit To Do") if self._item else self.tr("New To Do")
            )
        labels = {
            "Time zone": self.tr("Time zone"),
            "Status": self.tr("Status"),
            "Title": self.tr("Title"),
            "Location": self.tr("Location"),
            "Notes": self.tr("Notes"),
            "Due": self.tr("Due"),
            "Starts": self.tr("Starts"),
            "Ends": self.tr("Ends"),
        }
        for label, source in self._labels:
            label.setText(labels[source])
        self._all_day.setText(self.tr("All day"))
        self._time_basis.setItemText(0, self.tr("iPod local time"))
        for index, status in enumerate(_TODO_STATES):
            self._todo_state.setItemText(index, _todo_state_text(status))
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))
        self._save.setText(self.tr("Save"))
        for widget in (self._start, self._end, self._due):
            widget.include.setText(self.tr("Set"))
            widget.date.setDisplayFormat(
                QLocale().dateFormat(QLocale.FormatType.ShortFormat)
            )
            widget.time.setDisplayFormat("HH:mm:ss")
        self._refresh_timing_note()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


class _CalendarEntryList(QTreeWidget):
    """Anchor the entry menu to a clicked row or the keyboard's current row."""

    entryMenuRequested = Signal(QTreeWidgetItem, QPoint)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        keyboard = event.reason() == QContextMenuEvent.Reason.Keyboard
        row = self.currentItem() if keyboard else self.itemAt(event.pos())
        if row is None:
            return
        self.setCurrentItem(row)
        point = event.globalPos()
        if keyboard:
            self.scrollToItem(row)
            point = self.viewport().mapToGlobal(self.visualItemRect(row).center())
        self.entryMenuRequested.emit(row, point)
        event.accept()


class CalendarPage(QWidget):
    """Browse and author events/To Dos through the connection-bound controller."""

    def __init__(
        self, controller: ExtrasController, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("calendarPage")
        self._controller = controller
        self._shown_device: ActiveIPod | None = controller.active_ipod
        self._dialog: CalendarEditor | None = None
        self._dialog_target: ActiveIPod | None = None
        self._editing: CalendarItem | None = None
        self._header = PageHeader(self)
        self._import = ActionButton(parent=self._header, kind=ActionButtonKind.QUIET)
        self._import.setObjectName("calendarImport")
        self._new = ActionButton(parent=self._header, kind=ActionButtonKind.PRIMARY)
        self._new.setObjectName("calendarNew")
        self._refresh_button = ActionButton(
            parent=self._header, kind=ActionButtonKind.QUIET
        )
        self._refresh_button.setObjectName("calendarRefresh")
        for button in (self._refresh_button, self._import, self._new):
            self._header.add_action(button)
        self._calendar_filter = AppComboBox(self)
        self._calendar_filter.setObjectName("calendarSelector")
        self._create_calendar = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        self._create_calendar.setObjectName("calendarCreate")
        self._rename_calendar = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        self._rename_calendar.setObjectName("calendarRename")
        self._status = QLabel(self)
        self._status.setObjectName("calendarStatus")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("calendarTabs")
        self._tabs.setProperty("extrasTabs", True)
        self._month = CalendarMonth(self, today=_today_for_widget)
        self._agenda_title = QLabel(self)
        self._agenda_title.setObjectName("calendarAgendaTitle")
        self._agenda_title.setProperty("extrasHeading", True)
        self._scope = AppComboBox(self)
        self._scope.setObjectName("calendarScope")
        self._scope.addItems(["", ""])
        self._search = SearchField(self)
        self._search.setObjectName("calendarSearch")
        self._search.setFixedWidth(220)
        search_corner = QWidget(self._tabs)
        search_layout = QHBoxLayout(search_corner)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.addWidget(self._search)
        self._tabs.setCornerWidget(search_corner, Qt.Corner.TopRightCorner)
        self._trees: list[QTreeWidget] = []
        for name in ("calendarEvents", "calendarTodos"):
            tree = _CalendarEntryList(self._tabs)
            tree.setObjectName(name)
            tree.setRootIsDecorated(False)
            tree.setProperty("extrasList", True)
            tree.setFrameShape(QFrame.Shape.NoFrame)
            tree.setMouseTracking(True)
            tree.setHeaderHidden(True)
            tree.setItemDelegate(ExtrasDelegate(tree))
            tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            tree.setColumnCount(4)
            for column in (1, 2, 3):
                tree.hideColumn(column)
            tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            tree.entryMenuRequested.connect(self._show_entry_menu)
            tree.itemActivated.connect(self._activate_entry)
            self._trees.append(tree)
        agenda = QWidget(self)
        self._agenda_layout = QVBoxLayout(agenda)
        self._agenda_layout.setContentsMargins(LAYOUT.space_md, 0, 0, 0)
        self._agenda_layout.setSpacing(LAYOUT.space_sm)
        self._agenda_layout.addWidget(self._agenda_title)
        self._agenda_layout.addWidget(self._scope)
        self._agenda_layout.addWidget(self._trees[0], 1)
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.setObjectName("calendarSplit")
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._month)
        self._splitter.addWidget(agenda)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([640, 320])
        self._tabs.addTab(self._splitter, "")
        todos = QWidget(self)
        self._todo_layout = QVBoxLayout(todos)
        self._todo_layout.setContentsMargins(0, 0, 0, 0)
        self._todo_layout.addWidget(self._trees[1], 1)
        self._tabs.addTab(todos, "")
        self._empty = QLabel(self)
        self._empty.setObjectName("calendarEmpty")
        self._empty.setWordWrap(True)
        self._empty.setProperty("extrasMuted", True)
        self._agenda_layout.addWidget(self._empty)
        self._note = QLabel(self)
        self._note.setWordWrap(True)
        self._note.setProperty("extrasMuted", True)
        body = QVBoxLayout()
        body.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_sm, LAYOUT.space_lg, LAYOUT.space_lg
        )
        body.setSpacing(LAYOUT.space_sm)
        calendar_actions = QHBoxLayout()
        calendar_actions.addWidget(self._calendar_filter, 1)
        calendar_actions.addWidget(self._create_calendar)
        calendar_actions.addWidget(self._rename_calendar)
        body.addLayout(calendar_actions)
        body.addWidget(self._status)
        body.addWidget(self._tabs, 1)
        body.addWidget(self._note)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addLayout(body, 1)
        self._calendar_filter.currentIndexChanged.connect(self._refresh)
        self._create_calendar.clicked.connect(self._create_named_calendar)
        self._rename_calendar.clicked.connect(self._rename_named_calendar)
        self._new.clicked.connect(lambda: self._open_editor())
        self._import.clicked.connect(self._import_file)
        self._refresh_button.clicked.connect(controller.refresh)
        self._tabs.currentChanged.connect(self._tab_changed)
        self._month.selected.connect(self._refresh)
        self._scope.currentIndexChanged.connect(self._refresh)
        self._search.queryChanged.connect(self._refresh)
        controller.changed.connect(self._refresh)
        self._refresh()

    def _selected_calendar(self) -> CalendarGroup | None:
        from iOpenPod.app.models.extras import CalendarGroup

        value = self._calendar_filter.currentData()
        return value if isinstance(value, CalendarGroup) else None

    def _calendar_label(self, group: CalendarGroup) -> str:
        return (
            " ".join(group.name.split()) if group.name else self.tr("Other (unnamed)")
        )

    def _create_named_calendar(self) -> None:
        active = self._controller.active_ipod
        if not self._writable():
            return
        name, accepted = QInputDialog.getText(
            self, self.tr("New calendar"), self.tr("Calendar name:")
        )
        if (
            accepted
            and name.strip()
            and active is self._controller.active_ipod
            and self._writable()
        ):
            self._controller.create_calendar(name)

    def _rename_named_calendar(self) -> None:
        group = self._selected_calendar()
        active = self._controller.active_ipod
        if group is None or not group.editable or not self._writable():
            return
        name, accepted = QInputDialog.getText(
            self,
            self.tr("Rename calendar"),
            self.tr("Calendar name:"),
            text=group.name or "",
        )
        if (
            accepted
            and name.strip()
            and active is self._controller.active_ipod
            and self._writable()
        ):
            self._controller.rename_calendar(group, name)

    def _tab_changed(self) -> None:
        # The empty message follows its list rather than occupying the month grid.
        if self._tabs.currentIndex() == 0:
            self._agenda_layout.addWidget(self._empty)
        else:
            self._todo_layout.addWidget(self._empty)
        self._note.setVisible(
            self._tabs.currentIndex() == 0
            and any(
                item.entry.has_recurrence for item in self._controller.catalog.calendar
            )
        )
        self._update_list_state()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        stacked = self.width() < 780
        orientation = Qt.Orientation.Vertical if stacked else Qt.Orientation.Horizontal
        if self._splitter.orientation() != orientation:
            self._splitter.setOrientation(orientation)
            self._agenda_layout.setContentsMargins(
                0 if stacked else LAYOUT.space_md,
                LAYOUT.space_sm if stacked else 0,
                0,
                0,
            )
            self._splitter.setSizes([380, 240] if stacked else [640, 320])

    def _writable(self) -> bool:
        support = self._controller.catalog.support
        return bool(self._controller.can_write and support and support.calendar_write)

    def _source_item(self, row: QTreeWidgetItem | None) -> CalendarItem | None:
        if row is None:
            return None
        key: object = row.data(0, Qt.ItemDataRole.UserRole)
        return next(
            (
                item
                for item in self._controller.catalog.calendar
                if (item.document_key, item.index) == key
            ),
            None,
        )

    def _activate_entry(self, row: QTreeWidgetItem) -> None:
        if (item := self._source_item(row)) is not None:
            self._open_editor(item)

    def _show_entry_menu(self, row: QTreeWidgetItem, position: QPoint) -> None:
        item = self._source_item(row)
        active = self._controller.active_ipod
        if item is None or active is None:
            return
        entry = item.entry
        occurrence: object = row.data(0, _OCCURRENCE_ROLE)
        day = occurrence.day if isinstance(occurrence, CalendarOccurrence) else None
        start = (
            skippable_occurrence_start(entry, occurrence)
            if isinstance(occurrence, CalendarOccurrence)
            else None
        )

        menu = QMenu(self)
        menu.setObjectName("calendarEntryMenu")
        edit = menu.addAction(
            self.tr("Edit series") if entry.has_recurrence else self.tr("Edit")
        )
        skip = (
            menu.addAction(self.tr("Skip this occurrence"))
            if day is not None and start is not None
            else None
        )
        complete = (
            menu.addAction(
                self.tr("Mark incomplete")
                if entry.completed
                else self.tr("Mark complete")
            )
            if entry.kind is CalendarEntryKind.TODO
            else None
        )
        menu.addSeparator()
        remove = menu.addAction(
            self.tr("Remove series") if entry.has_recurrence else self.tr("Remove")
        )
        can_edit = entry.editable and self._writable()
        for action in (edit, skip, complete, remove):
            if action is not None:
                action.setEnabled(can_edit)

        def run(chosen: QAction) -> None:
            if (
                not can_edit
                or active is not self._controller.active_ipod
                or item not in self._controller.catalog.calendar
                or not self._writable()
            ):
                return
            if chosen is edit:
                self._open_editor(item)
            elif chosen is skip and day is not None and start is not None:
                self._controller.skip_calendar_occurrence(item, day, start)
            elif chosen is complete:
                self._controller.save_calendar(
                    CalendarEntryChanges(completed=not entry.completed), item
                )
            elif chosen is remove:
                self._remove_entry(item)

        menu.triggered.connect(run)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(position)

    def _refresh(self) -> None:
        selected = self._source_item(
            self._trees[self._tabs.currentIndex()].currentItem()
        )
        if self._shown_device is not self._controller.active_ipod:
            self._shown_device = self._controller.active_ipod
            selected = None
            self._calendar_filter.blockSignals(True)
            self._calendar_filter.setCurrentIndex(0)
            self._calendar_filter.blockSignals(False)
            self._search.set_query("")
            self._scope.blockSignals(True)
            self._scope.setCurrentIndex(0)
            self._scope.blockSignals(False)
        selected_group = self._selected_calendar()
        self._calendar_filter.blockSignals(True)
        self._calendar_filter.clear()
        self._calendar_filter.addItem(self.tr("All calendars"), None)
        for group in self._controller.catalog.calendars:
            self._calendar_filter.addItem(self._calendar_label(group), group)
            if selected_group is not None and group.name == selected_group.name:
                self._calendar_filter.setCurrentIndex(self._calendar_filter.count() - 1)
        self._calendar_filter.blockSignals(False)
        selected_group = self._selected_calendar()
        self._create_calendar.setEnabled(self._writable())
        self._rename_calendar.setEnabled(
            bool(self._writable() and selected_group and selected_group.editable)
        )
        visible_items = tuple(
            item
            for item in self._controller.catalog.calendar
            if selected_group is None
            or (
                item.document_key in selected_group.document_keys
                and item.calendar_name == selected_group.name
            )
        )
        day = self._month.grid.selectedDate()
        self._month.grid.set_today(_today_for_widget())
        query = self._search.text().strip().casefold()
        first_qdate = QDate(
            self._month.grid.yearShown(), self._month.grid.monthShown(), 1
        ).addDays(-7)
        last_qdate = first_qdate.addDays(48)
        first_date = Date(first_qdate.year(), first_qdate.month(), first_qdate.day())
        last = Date(last_qdate.year(), last_qdate.month(), last_qdate.day())
        self._unexpanded_recurrence = False
        projected_items: list[CalendarItem] = []
        for source in visible_items:
            if source.entry.kind is not CalendarEntryKind.EVENT:
                projected_items.append(source)
                continue
            result = project_occurrences(
                source.entry,
                first_date,
                last,
            )
            if source.entry.has_recurrence and not result.expanded:
                self._unexpanded_recurrence = True
            if result.expanded:
                projected_items.extend(
                    replace(source, occurrence=occurrence)
                    for occurrence in result.occurrences
                )
            else:
                projected_items.append(source)
        markers = tuple(
            marker
            for item in projected_items
            if item.entry.kind is CalendarEntryKind.EVENT
            and (marker := _entry_marker(item)) is not None
        )
        if self._scope.currentIndex() == 0 and not query:
            visible_items = tuple(projected_items)
        self._month.grid.set_markers(markers)
        for tree, kind in zip(
            self._trees, (CalendarEntryKind.EVENT, CalendarEntryKind.TODO), strict=True
        ):
            tree.blockSignals(True)
            tree.clear()
            for item in sorted(visible_items, key=_entry_order):
                entry = item.entry
                if entry.kind is not kind:
                    continue
                if (
                    query
                    and query
                    not in " ".join(
                        (entry.summary, entry.location, entry.description)
                    ).casefold()
                ):
                    continue
                marker = _entry_marker(item)
                if (
                    kind is CalendarEntryKind.EVENT
                    and self._scope.currentIndex() == 0
                    and not query
                    and (marker is None or not marker.first <= day <= marker.last)
                ):
                    continue
                row = QTreeWidgetItem(
                    [
                        entry.summary or self.tr("Untitled"),
                        _display_date(
                            (item.occurrence.start if item.occurrence else entry.start)
                            if kind is CalendarEntryKind.EVENT
                            else entry.due
                        ),
                        " · ".join(
                            part
                            for part in (
                                item.calendar_name or self.tr("Other (unnamed)"),
                                entry.location,
                            )
                            if part
                        ),
                        _todo_state_text(entry.todo_status)
                        if entry.todo_status is not None
                        else (self.tr("Repeating") if entry.has_recurrence else ""),
                    ]
                )
                row.setData(
                    0, Qt.ItemDataRole.UserRole, (item.document_key, item.index)
                )
                if item.occurrence is not None:
                    row.setData(0, _OCCURRENCE_ROLE, item.occurrence)
                row.setToolTip(1, row.text(1))
                row.setToolTip(
                    0,
                    "\n".join(
                        row.text(column) for column in range(4) if row.text(column)
                    ),
                )
                row.setData(0, Qt.ItemDataRole.AccessibleTextRole, row.toolTip(0))
                tree.addTopLevelItem(row)
                if selected is not None and (selected.document_key, selected.index) == (
                    item.document_key,
                    item.index,
                ):
                    tree.setCurrentItem(row)
            if (
                tree.currentItem() is None
                and (first := tree.topLevelItem(0)) is not None
            ):
                tree.setCurrentItem(first)
            tree.blockSignals(False)
        if self._dialog is not None:
            if self._dialog_target is not self._controller.active_ipod or (
                self._editing is not None
                and self._editing not in self._controller.catalog.calendar
            ):
                self._dialog.reject()
            else:
                self._dialog.set_writable(self._writable())
        self.retranslate_ui()

    def _update_list_state(self) -> None:
        writable = self._writable()
        self._new.setText(
            self.tr("New event")
            if self._tabs.currentIndex() == 0
            else self.tr("New To Do")
        )
        self._empty.setVisible(
            self._trees[self._tabs.currentIndex()].topLevelItemCount() == 0
        )
        if self._controller.active_ipod is None:
            self._empty.clear()
        elif self._controller.busy:
            self._empty.setText(self.tr("Loading Calendar…"))
        elif self._search.text().strip():
            self._empty.setText(self.tr("No matching entries. Try another search."))
        elif (
            self._tabs.currentIndex() == 0
            and self._scope.currentIndex() == 0
            and self._unexpanded_recurrence
        ):
            self._empty.setText(
                self.tr(
                    "No entries for this day. Some imported repeats are shown only on their saved dates."
                )
            )
        elif self._tabs.currentIndex() == 0:
            self._empty.setText(
                self.tr(
                    "Nothing planned for this day. Add an event or choose another date."
                )
                if self._scope.currentIndex() == 0 and writable
                else self.tr(
                    "No events for this day. Choose another date or view all events."
                )
                if self._scope.currentIndex() == 0
                else self.tr("No events on this iPod.")
            )
        else:
            self._empty.setText(self.tr("No To Dos on this iPod."))

    def _open_editor(self, item: CalendarItem | None = None) -> None:
        active = self._controller.active_ipod
        if not self._writable() or self._dialog is not None:
            return
        if item is not None and not item.entry.editable:
            return
        kind = (
            item.entry.kind
            if item is not None
            else CalendarEntryKind.EVENT
            if self._tabs.currentIndex() == 0
            else CalendarEntryKind.TODO
        )
        destination = self._selected_calendar() if item is None else None
        if item is None and destination is None:
            groups = [
                group for group in self._controller.catalog.calendars if group.editable
            ]
            if groups:
                labels = [self._calendar_label(group) for group in groups]
                labels = [
                    f"{label} ({index + 1})" if labels.count(label) > 1 else label
                    for index, label in enumerate(labels)
                ]
                chosen, accepted = QInputDialog.getItem(
                    self, self.tr("New entry"), self.tr("Calendar:"), labels, 0, False
                )
                if not accepted:
                    return
                if active is not self._controller.active_ipod or not self._writable():
                    return
                destination = groups[labels.index(chosen)]
        if destination is not None and not destination.editable:
            return
        zones = destination.zones if destination else ()
        if (
            item is not None
            and item.entry.timing_editable
            and kind is CalendarEntryKind.EVENT
        ):
            zones = item.zone_names
        date = self._month.grid.selectedDate()
        dialog = CalendarEditor(
            kind,
            item,
            self,
            initial_date=Date(date.year(), date.month(), date.day()),
            zone_names=zones,
        )
        self._dialog = dialog
        self._editing = item
        self._dialog_target = self._controller.active_ipod

        def submit() -> None:
            if self._dialog_target is self._controller.active_ipod and self._writable():
                if destination is None:
                    self._controller.save_calendar(dialog.selected_edit(), item)
                else:
                    self._controller.save_calendar(
                        dialog.selected_edit(), item, destination=destination
                    )

        def finished(_result: int) -> None:
            self._dialog = None
            self._editing = None
            self._dialog_target = None
            dialog.deleteLater()

        dialog.accepted.connect(submit)
        dialog.finished.connect(finished)
        dialog.open()

    def _remove_entry(self, item: CalendarItem) -> None:
        active = self._controller.active_ipod
        question = QMessageBox(self)
        question.setWindowTitle(
            self.tr("Remove entire repeating series?")
            if item.entry.has_recurrence
            else self.tr("Remove Calendar entry?")
        )
        question.setTextFormat(Qt.TextFormat.PlainText)
        question.setText(
            self.tr('Remove "{title}" from this iPod?').format(
                title=item.entry.summary or self.tr("Untitled")
            )
        )
        question.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        question.setDefaultButton(QMessageBox.StandardButton.Cancel)
        answer = question.exec()
        if (
            answer == QMessageBox.StandardButton.Yes
            and active is self._controller.active_ipod
            and item in self._controller.catalog.calendar
            and self._writable()
        ):
            self._controller.remove_calendar(item)

    def _import_file(self) -> None:
        active = self._controller.active_ipod
        if not self._writable():
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            self.tr("Import Calendar"),
            "",
            self.tr("Calendar files (*.ics *.vcs);;All files (*)"),
        )
        if path and active is self._controller.active_ipod and self._writable():
            name, accepted = QInputDialog.getText(
                self,
                self.tr("Import Calendar"),
                self.tr("Calendar name (leave blank to keep names in the file):"),
            )
            if accepted and active is self._controller.active_ipod and self._writable():
                self._controller.import_calendar(path, name if name.strip() else None)

    def retranslate_ui(self) -> None:
        self._header.set_title(self.tr("Calendar"))
        self._create_calendar.setText(self.tr("New calendar…"))
        self._rename_calendar.setText(self.tr("Rename calendar…"))
        self._calendar_filter.setAccessibleName(self.tr("Calendar to show"))
        self._calendar_filter.setItemText(0, self.tr("All calendars"))
        self._tabs.setTabText(0, self.tr("Calendar"))
        self._tabs.setTabText(1, self.tr("To Dos"))
        self._trees[0].setHeaderLabels(
            [
                self.tr("Title"),
                self.tr("Starts"),
                self.tr("Location"),
                self.tr("Status"),
            ]
        )
        self._trees[1].setHeaderLabels(
            [self.tr("Title"), self.tr("Due"), self.tr("Location"), self.tr("Status")]
        )
        self._import.setText(self.tr("Import Calendar…"))
        self._refresh_button.setText(
            QCoreApplication.translate("CommonActions", "Refresh")
        )
        self._search.setPlaceholderText(self.tr("Search entries"))
        self._search.setAccessibleName(self.tr("Search Calendar and To Dos"))
        self._scope.setItemText(0, self.tr("Selected day"))
        self._scope.setItemText(1, self.tr("All saved entries"))
        self._scope.setAccessibleName(self.tr("Events to show"))
        self._agenda_title.setText(
            self.tr("Search results")
            if self._search.text().strip()
            else QLocale().toString(self._month.grid.selectedDate(), "dddd, d MMMM")
            if self._scope.currentIndex() == 0
            else self.tr("All saved entries")
        )
        self._scope.setEnabled(not self._search.text().strip())
        self._trees[0].setAccessibleName(self.tr("Events"))
        self._trees[1].setAccessibleName(self.tr("To Dos"))
        self._note.setText(self.tr("All saved entries lists each series once."))
        self._note.setVisible(
            self._tabs.currentIndex() == 0
            and any(
                item.entry.has_recurrence for item in self._controller.catalog.calendar
            )
        )
        self._import.setEnabled(self._writable())
        group = self._selected_calendar()
        self._new.setEnabled(
            bool(self._writable() and (group is None or group.editable))
        )
        self._refresh_button.setEnabled(
            self._controller.active_ipod is not None and not self._controller.busy
        )
        active = self._controller.active_ipod
        support = self._controller.catalog.support
        qualification = ""
        if active is not None and support is not None and not support.calendar_write:
            qualification = self.tr(
                "Calendar editing is unavailable for {model}."
            ).format(model=active.profile.display_name)
        if active is None:
            self._status.setText(self.tr("Choose an iPod to view its Calendar."))
        else:
            self._status.setText(
                "\n".join(
                    filter(
                        None,
                        (
                            qualification,
                            self._controller.message,
                            self.tr(
                                "Some Calendar files could not be opened. Other entries are still available."
                            )
                            if self._controller.catalog.issues
                            else "",
                        ),
                    )
                )
            )
        self._status.setVisible(bool(self._status.text()))
        self._status.setToolTip("\n".join(self._controller.catalog.issues))
        self._update_list_state()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._controller.refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._refresh()
        super().changeEvent(event)
