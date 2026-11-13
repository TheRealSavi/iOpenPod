"""Firmware-qualified saved alarms and on-device countdown timer guidance.

Alarm dates are device calendar coordinates, never Host timezone conversions.
The editor offers native date/time, repeat, label, sound and enable controls only
where qualified. See docs/alarms.md and its firmware evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QDate, QEvent, QLocale, Qt, QTime
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QTabWidget,
    QTimeEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from whenever import PlainDateTime, Time

from device_registry import AlarmFormat, FeatureSupport
from iOpenPod.app.alarm_labels import ALARM_LABELS
from iOpenPod.app.models.extras import AlarmItem, AlarmSound
from iOpenPod.app.timer_sounds import TIMER_SOUND_LABELS
from iOpenPod.GUI.delegates.extras_delegate import ExtrasDelegate
from iOpenPod.GUI.dialogs.timer_editor import TimerEditor
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.clock_city_picker import ClockCityPicker
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from PySide6.QtGui import QShowEvent

    from iOpenPod.app.extras_controller import ExtrasController
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.models.extras import ExtrasCatalog
    from iPodDB.alarms import ClockCity


def _display_time(value: PlainDateTime | Time | None) -> str:
    if value is None:
        return "—"
    locale = QLocale()
    text = locale.toString(
        QTime(value.hour, value.minute, value.second), QLocale.FormatType.ShortFormat
    )
    if isinstance(value, PlainDateTime):
        text = (
            locale.toString(
                QDate(value.year, value.month, value.day),
                QLocale.FormatType.ShortFormat,
            )
            + " "
            + text
        )
    return text


class AlarmEditor(QDialog):
    """Widget adapters for one captured alarm; no synthetic enabled/default state."""

    def __init__(
        self,
        item: AlarmItem,
        parent: QWidget | None = None,
        *,
        creating: bool = False,
        sounds: tuple[AlarmSound, ...] = (),
        cities: tuple[ClockCity, ...] = (),
    ) -> None:
        super().__init__(parent)
        if item.time is None:
            raise ValueError("An alarm editor needs a captured valid time.")
        self.setObjectName("alarmEditor")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(400)
        self._item = item
        self._creating = creating
        self._sounds = sounds
        self._city = ClockCityPicker(cities, self)
        self._city_label = QLabel(self)
        self._city_label.setBuddy(self._city)
        self._city.setVisible(bool(cities) and creating)
        self._city_label.setVisible(bool(cities) and creating)
        self._daylight = QCheckBox(self)
        self._daylight.setObjectName("alarmDaylightSaving")
        self._daylight.setChecked(item.daylight_saving is True)
        if item.daylight_saving is None:
            self._daylight.setTristate(True)
            self._daylight.setCheckState(Qt.CheckState.PartiallyChecked)
        self._daylight.setVisible(item.daylight_saving_editable)
        self._date = QDateEdit(self)
        self._date.setObjectName("alarmDate")
        # Classic's u32 civil coordinate is bounded by its native serialization.
        # Date-only range here is an adapter; the codec validates the final time.
        self._date.setDateRange(QDate(1970, 1, 1), QDate(2106, 2, 7))
        self._date.setCalendarPopup(True)
        if isinstance(item.time, PlainDateTime):
            self._date.setDate(QDate(item.time.year, item.time.month, item.time.day))
        self._time = QTimeEdit(self)
        self._time.setObjectName("alarmTime")
        self._time.setMinimumHeight(LAYOUT.control_height_large * 2)
        self._time.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._time.setTime(QTime(item.time.hour, item.time.minute, item.time.second))
        self._repeat = AppComboBox(self)
        self._repeat.setObjectName("alarmRepeat")
        self._repeat.setEnabled(item.repeat_editable)
        self._enabled = QCheckBox(self)
        self._enabled.setObjectName("alarmEnabled")
        self._enabled.setChecked(item.enabled is True)
        self._enabled.setEnabled(item.enabled_editable)
        if item.enabled is None:
            self._enabled.setTristate(True)
            self._enabled.setCheckState(Qt.CheckState.PartiallyChecked)
        self._enabled.setVisible(item.enabled_editable or item.sound_editable)
        self._date_label = QLabel(self)
        self._time_label = QLabel(self)
        self._repeat_label = QLabel(self)
        self._label = AppComboBox(self)
        self._label.setObjectName("alarmLabel")
        self._label.setEnabled(item.label_editable)
        self._label_label = QLabel(self)
        self._label_label.setBuddy(self._label)
        self._sound = AppComboBox(self)
        self._sound.setObjectName("alarmSound")
        self._sound.setEnabled(item.sound_editable and bool(sounds))
        self._sound.currentIndexChanged.connect(self._sound_changed)
        self._sound_label = QLabel(self)
        self._sound_label.setBuddy(self._sound)
        self._date_label.setBuddy(self._date)
        self._time_label.setBuddy(self._time)
        self._repeat_label.setBuddy(self._repeat)
        form = QVBoxLayout()
        form.setSpacing(LAYOUT.space_sm)
        for label_widget, field_widget in (
            (self._city_label, self._city),
            (self._time_label, self._time),
            (self._date_label, self._date),
            (self._repeat_label, self._repeat),
            (self._label_label, self._label),
            (self._sound_label, self._sound),
        ):
            row = QVBoxLayout()
            row.setSpacing(LAYOUT.space_2xs)
            row.addWidget(label_widget)
            row.addWidget(field_widget)
            form.addLayout(row)
        form.addWidget(self._enabled)
        form.addWidget(self._daylight)
        self._label.setVisible(item.label_index is not None)
        self._label_label.setVisible(item.label_index is not None)
        for widget in (self._date, self._date_label):
            widget.setVisible(isinstance(item.time, PlainDateTime))
        for repeat_widget in (self._repeat, self._repeat_label):
            repeat_widget.setVisible(item.repeat is not None)
        self._note = QLabel(self)
        self._note.setWordWrap(True)
        self._note.setTextFormat(Qt.TextFormat.PlainText)
        self._error = QLabel(self)
        self._error.setObjectName("alarmEditorError")
        self._error.setWordWrap(True)
        self._error.setMinimumHeight(self.fontMetrics().height())
        self._city.editTextChanged.connect(self._error.clear)
        self._save = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._save.setObjectName("alarmEditorSave")
        self._save.setDefault(True)
        self._save.clicked.connect(self._accept_valid)
        self._cancel = ActionButton(parent=self)
        self._cancel.clicked.connect(self.reject)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addLayout(form)
        layout.addWidget(self._note)
        layout.addWidget(self._error)
        layout.addLayout(actions)
        self.setTabOrder(self._city, self._time)
        self.setTabOrder(self._time, self._date)
        self.setTabOrder(self._date, self._repeat)
        self.setTabOrder(self._repeat, self._label)
        self.setTabOrder(self._label, self._sound)
        self.setTabOrder(self._sound, self._enabled)
        self.setTabOrder(self._enabled, self._daylight)
        self.setTabOrder(self._daylight, self._cancel)
        self.setTabOrder(self._cancel, self._save)
        self.retranslate_ui()
        (self._city if cities and creating else self._time).setFocus()

    def selected_city(self) -> ClockCity | None:
        return self._city.selected_city() if self._creating else self._item.clock_city

    def selected_daylight_saving(self) -> bool | None:
        if (
            not self._item.daylight_saving_editable
            or self._daylight.checkState() is Qt.CheckState.PartiallyChecked
        ):
            return None
        value = self._daylight.isChecked()
        return value if self._creating or value != self._item.daylight_saving else None

    def selected_time(self) -> PlainDateTime | Time:
        time = self._time.time()
        if isinstance(self._item.time, PlainDateTime):
            date = self._date.date()
            return PlainDateTime(
                date.year(),
                date.month(),
                date.day(),
                time.hour(),
                time.minute(),
                time.second(),
            )
        return Time(time.hour(), time.minute())

    def selected_repeat(self) -> int | None:
        value: object = self._repeat.currentData()
        return (
            value
            if self._item.repeat_editable
            and isinstance(value, int)
            and value != self._item.repeat
            else None
        )

    def set_writable(self, writable: bool) -> None:
        self._save.setEnabled(writable)

    def selected_enabled(self) -> bool | None:
        if self._enabled.checkState() is Qt.CheckState.PartiallyChecked:
            return None
        value = self._enabled.isChecked()
        return (
            value
            if (self._item.enabled_editable and value != self._item.enabled)
            or self.selected_sound() is not None
            else None
        )

    def _sound_changed(self) -> None:
        if self._item.enabled is None and not self._item.enabled_editable:
            self._enabled.setCheckState(
                Qt.CheckState.Checked
                if self.selected_sound() is not None
                else Qt.CheckState.PartiallyChecked
            )
        self._enabled.setEnabled(
            self._item.enabled_editable or self.selected_sound() is not None
        )

    def selected_sound(self) -> AlarmSound | None:
        value: object = self._sound.currentData()
        return (
            value
            if isinstance(value, AlarmSound)
            and (self._creating or value != self._item.sound)
            else None
        )

    def selected_label(self) -> int | None:
        value: object = self._label.currentData()
        return (
            value
            if self._item.label_editable
            and type(value) is int
            and value != self._item.label_index
            else None
        )

    def _accept_valid(self) -> None:
        if not self._save.isEnabled():
            return
        if self._creating and self._city.count() and self.selected_city() is None:
            self._error.setText(self.tr("Choose a city from the list."))
            self._city.setFocus()
            return
        value = self.selected_time()
        if (
            isinstance(value, PlainDateTime)
            and value != self._item.time
            and value > PlainDateTime(2106, 2, 7, 6, 28, 14)
        ):
            self._error.setText(
                self.tr("Choose a time no later than February 7, 2106 at 06:28:14.")
            )
            return
        self.accept()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(
            self.tr("Add city")
            if self._creating and self._city.count()
            else self.tr("New alarm")
            if self._creating
            else self.tr("Edit {city} alarm").format(city=self._item.clock_city.name)
            if self._item.clock_city
            else self.tr("Edit alarm")
        )
        self._city_label.setText(self.tr("City"))
        self._city.retranslate_ui()
        self._daylight.setText(self.tr("Daylight saving time"))
        self._date_label.setText(self.tr("Date"))
        self._time_label.setText(self.tr("Time"))
        self._repeat_label.setText(self.tr("Repeat"))
        self._enabled.setText(self.tr("Enabled"))
        self._label_label.setText(self.tr("Label"))
        self._sound_label.setText(self.tr("Sound"))
        selected_sound: object = (
            self._sound.currentData() if self._sound.count() else self._item.sound
        )
        self._sound.clear()
        if selected_sound not in self._sounds:
            self._sound.addItem(
                workflow_text(self._item.sound_description)
                if self._item.sound_description
                else self.tr("Keep current sound"),
                None,
            )
        for sound in self._sounds:
            self._sound.addItem(
                workflow_text(sound.name)
                if sound.kind is AlarmSound.Kind.BEEP
                else self.tr("Playlist: {name}").format(name=sound.name)
                if sound.kind is AlarmSound.Kind.PLAYLIST
                else sound.name,
                sound,
            )
        self._sound.setCurrentIndex(max(0, self._sound.findData(selected_sound)))
        selected_label: object = (
            self._label.currentData() if self._label.count() else self._item.label_index
        )
        self._label.clear()
        for index, native_label in enumerate(ALARM_LABELS):
            self._label.addItem(workflow_text(native_label), index)
        if isinstance(selected_label, int) and not 0 <= selected_label < len(
            ALARM_LABELS
        ):
            self._label.addItem(
                self.tr("Keep current setting ({value})").format(value=selected_label),
                selected_label,
            )
        self._label.setCurrentIndex(self._label.findData(selected_label))
        selected: object = (
            self._repeat.currentData() if self._repeat.count() else self._item.repeat
        )
        self._repeat.clear()
        for index, label in enumerate(
            (
                self.tr("Once"),
                self.tr("Daily"),
                self.tr("Weekdays"),
                self.tr("Weekends"),
                self.tr("Weekly"),
                self.tr("Monthly"),
                self.tr("Yearly"),
            )
        ):
            self._repeat.addItem(label, index)
        if isinstance(selected, int) and not 0 <= selected <= 6:
            self._repeat.addItem(
                self.tr("Keep current setting ({value})").format(value=selected),
                selected,
            )
        self._repeat.setCurrentIndex(self._repeat.findData(selected))
        self._date.setDisplayFormat(
            QLocale().dateFormat(QLocale.FormatType.ShortFormat)
        )
        self._time.setDisplayFormat(
            QLocale().timeFormat(QLocale.FormatType.ShortFormat)
        )
        self._note.setText(
            self.tr(
                "The alarm uses this city's local time. Daylight saving time is set manually."
            )
            if self._item.daylight_saving_editable
            else self.tr(
                "Times follow the iPod's clock. Check the alarm on your iPod after ejecting."
            )
        )
        self._save.setText(
            self.tr("Add city")
            if self._creating and self._city.count()
            else self.tr("Save")
        )
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # The default dialog sizing caps height at two-thirds of the screen.
        # Keep the full form visible on smaller displays after styles resolve.
        self.resize(self.sizeHint().expandedTo(self.minimumSize()))


class AlarmsPage(QWidget):
    """Show saved alarms independently from optional sleep-timer host control."""

    def __init__(
        self, controller: ExtrasController, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("alarmsPage")
        self._controller = controller
        self._dialog: AlarmEditor | None = None
        self._dialog_target: ActiveIPod | None = None
        self._editing: AlarmItem | None = None
        self._creating = False
        self._dialog_catalog: ExtrasCatalog | None = None
        self._timer_dialog: TimerEditor | None = None
        self._timer_target: ActiveIPod | None = None
        self._timer_catalog: ExtrasCatalog | None = None
        self._header = PageHeader(self)
        self._refresh_button = ActionButton(
            parent=self._header, kind=ActionButtonKind.QUIET, glyph="refresh"
        )
        self._refresh_button.setObjectName("alarmsRefresh")
        self._header.add_action(self._refresh_button)
        self._status = QLabel(self)
        self._status.setObjectName("alarmsStatus")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("alarmsTabs")
        self._tabs.setProperty("extrasTabs", True)
        alarms = QWidget(self._tabs)
        content = QWidget(alarms)
        content.setMaximumWidth(960)
        self._intro = QLabel(content)
        self._intro.setProperty("extrasHeading", True)
        self._hint = QLabel(content)
        self._hint.setProperty("extrasMuted", True)
        self._hint.setWordWrap(True)
        self._tree = QTreeWidget(alarms)
        self._tree.setObjectName("alarmsList")
        self._tree.setRootIsDecorated(False)
        self._tree.setProperty("extrasList", True)
        self._tree.setFrameShape(QFrame.Shape.NoFrame)
        self._tree.setHeaderHidden(True)
        self._tree.setMouseTracking(True)
        self._tree.setItemDelegate(ExtrasDelegate(self._tree, alarms=True))
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setColumnCount(4)
        for column in (1, 2, 3):
            self._tree.hideColumn(column)
        self._tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._empty = QLabel(alarms)
        self._empty.setObjectName("alarmsEmpty")
        self._empty.setWordWrap(True)
        self._empty.setProperty("extrasEmpty", True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._details = QLabel(alarms)
        self._details.setObjectName("alarmDetails")
        self._details.setWordWrap(True)
        self._details.setTextFormat(Qt.TextFormat.PlainText)
        self._details.setProperty("extrasMuted", True)
        self._edit = ActionButton(parent=alarms)
        self._edit.setObjectName("alarmEdit")
        self._new = ActionButton(parent=alarms, kind=ActionButtonKind.PRIMARY)
        self._new.setObjectName("alarmNew")
        self._remove = ActionButton(parent=alarms, kind=ActionButtonKind.DANGER)
        self._remove.setObjectName("alarmRemove")
        actions = QHBoxLayout()
        actions.addWidget(self._intro)
        actions.addStretch(1)
        actions.addWidget(self._new)
        selection_actions = QHBoxLayout()
        selection_actions.addWidget(self._edit)
        selection_actions.addWidget(self._remove)
        selection_actions.addStretch(1)
        self._summary = QLabel(alarms)
        self._summary.setProperty("extrasMuted", True)
        selection_actions.addWidget(self._summary)
        alarm_layout = QVBoxLayout(content)
        alarm_layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        alarm_layout.setSpacing(LAYOUT.space_md)
        alarm_layout.addLayout(actions)
        alarm_layout.addWidget(self._hint)
        alarm_layout.addWidget(self._tree, 1)
        alarm_layout.addWidget(self._empty, 1)
        alarm_layout.addLayout(selection_actions)
        alarm_layout.addWidget(self._details)
        centered = QHBoxLayout(alarms)
        centered.setContentsMargins(0, 0, 0, 0)
        centered.addStretch(1)
        centered.addWidget(content, 6)
        centered.addStretch(1)
        sleep_page = QWidget(self._tabs)
        sleep_content = QFrame(sleep_page)
        sleep_content.setObjectName("sleepTimerPanel")
        sleep_content.setMaximumWidth(600)
        self._sleep_title = QLabel(sleep_content)
        self._sleep_title.setProperty("extrasTitle", True)
        self._sleep_title.setWordWrap(True)
        self._sleep_subtitle = QLabel(sleep_content)
        self._sleep_subtitle.setProperty("extrasMuted", True)
        self._sleep_subtitle.setWordWrap(True)
        self._sleep = QLabel(sleep_content)
        self._sleep.setObjectName("sleepTimerInstructions")
        self._sleep.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._sleep.setWordWrap(True)
        self._sleep.setTextFormat(Qt.TextFormat.PlainText)
        self._timer_duration = QLabel(sleep_content)
        self._timer_duration.setObjectName("timerSavedDuration")
        self._timer_duration.setWordWrap(True)
        self._timer_duration.setTextFormat(Qt.TextFormat.PlainText)
        sleep_text = QVBoxLayout(sleep_content)
        sleep_text.setContentsMargins(
            LAYOUT.space_xl, LAYOUT.space_xl, LAYOUT.space_xl, LAYOUT.space_xl
        )
        sleep_text.setSpacing(LAYOUT.space_lg)
        sleep_text.addWidget(self._sleep_title)
        sleep_text.addWidget(self._sleep_subtitle)
        sleep_text.addWidget(self._timer_duration)
        sleep_text.addWidget(self._sleep)
        self._timer_edit = ActionButton(
            parent=sleep_content, kind=ActionButtonKind.PRIMARY
        )
        self._timer_edit.setObjectName("timerEdit")
        timer_actions = QHBoxLayout()
        timer_actions.addStretch(1)
        timer_actions.addWidget(self._timer_edit)
        sleep_text.addLayout(timer_actions)
        sleep_row = QHBoxLayout()
        sleep_row.addStretch(1)
        sleep_row.addWidget(sleep_content, 4)
        sleep_row.addStretch(1)
        sleep_layout = QVBoxLayout(sleep_page)
        sleep_layout.addStretch(1)
        sleep_layout.addLayout(sleep_row)
        sleep_layout.addStretch(2)
        self._tabs.addTab(alarms, "")
        self._tabs.addTab(sleep_page, "")
        body = QVBoxLayout()
        body.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_sm, LAYOUT.space_lg, LAYOUT.space_lg
        )
        body.addWidget(self._status)
        body.addWidget(self._tabs, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addLayout(body, 1)
        self._tree.itemSelectionChanged.connect(self._selection_changed)
        self._tree.itemActivated.connect(lambda: self._open_editor())
        self._edit.clicked.connect(self._open_editor)
        self._new.clicked.connect(self._new_alarm)
        self._remove.clicked.connect(self._remove_alarm)
        self._timer_edit.clicked.connect(self._open_timer_editor)
        self._refresh_button.clicked.connect(controller.refresh)
        controller.changed.connect(self._refresh)
        self._refresh()

    def _writable(self) -> bool:
        support = self._controller.catalog.support
        return bool(self._controller.can_write and support and support.alarm_write)

    def _selected(self) -> AlarmItem | None:
        row = self._tree.currentItem()
        index: object = (
            row.data(0, Qt.ItemDataRole.UserRole) if row is not None else None
        )
        return next(
            (item for item in self._controller.catalog.alarms if item.index == index),
            None,
        )

    def _repeat_text(self, value: int | None) -> str:
        labels = (
            self.tr("Once"),
            self.tr("Daily"),
            self.tr("Weekdays"),
            self.tr("Weekends"),
            self.tr("Weekly"),
            self.tr("Monthly"),
            self.tr("Yearly"),
        )
        if value is None:
            return ""
        return labels[value] if 0 <= value < len(labels) else self.tr("Custom repeat")

    def _refresh(self) -> None:
        selected = self._selected()
        self._tree.blockSignals(True)
        self._tree.clear()
        for item in self._controller.catalog.alarms:
            time = item.time
            clock = (
                QLocale().toString(
                    QTime(time.hour, time.minute), QLocale.FormatType.ShortFormat
                )
                if time is not None
                else self.tr("Time unavailable")
            )
            date = (
                QLocale().toString(
                    QDate(time.year, time.month, time.day),
                    QLocale.FormatType.LongFormat,
                )
                if isinstance(time, PlainDateTime)
                else ""
            )
            row = QTreeWidgetItem(
                [
                    workflow_text(item.display_label),
                    clock,
                    " · ".join(
                        part
                        for part in (
                            self._repeat_text(item.repeat),
                            date,
                            workflow_text(item.sound.name)
                            if item.sound and item.sound.kind is AlarmSound.Kind.BEEP
                            else item.sound.name
                            if item.sound
                            else workflow_text(item.sound_description),
                        )
                        if part
                    ),
                    " · ".join(
                        part
                        for part in (
                            self.tr("Enabled")
                            if item.enabled is True
                            else self.tr("Disabled")
                            if item.enabled is False
                            else "",
                            self.tr("Read only") if not item.editable else "",
                        )
                        if part
                    ),
                ]
            )
            row.setData(0, Qt.ItemDataRole.UserRole, item.index)
            row.setData(0, int(Qt.ItemDataRole.UserRole) + 1, item.enabled)
            row.setToolTip(
                0,
                "\n".join(
                    part
                    for part in (
                        row.text(0),
                        _display_time(item.time),
                        row.text(2),
                        row.text(3),
                        item.detail,
                    )
                    if part
                ),
            )
            row.setData(0, Qt.ItemDataRole.AccessibleTextRole, row.toolTip(0))
            self._tree.addTopLevelItem(row)
            if selected is not None and selected.index == item.index:
                self._tree.setCurrentItem(row)
        if (
            self._tree.currentItem() is None
            and (first := self._tree.topLevelItem(0)) is not None
        ):
            self._tree.setCurrentItem(first)
        self._tree.blockSignals(False)
        if self._dialog is not None:
            if (
                self._dialog_target is not self._controller.active_ipod
                or self._dialog_catalog is not self._controller.catalog
                or (
                    not self._creating
                    and self._editing not in self._controller.catalog.alarms
                )
                or (self._creating and not self._controller.catalog.can_create_alarm)
            ):
                self._dialog.reject()
            else:
                self._dialog.set_writable(self._writable())
        if self._timer_dialog is not None:
            if (
                self._timer_target is not self._controller.active_ipod
                or self._timer_catalog is not self._controller.catalog
            ):
                self._timer_dialog.reject()
            else:
                self._timer_dialog.set_writable(self._timer_writable())
        self.retranslate_ui()

    def _timer_writable(self) -> bool:
        support = self._controller.catalog.support
        timer = self._controller.catalog.timer
        return bool(
            self._controller.can_write
            and support
            and support.timer_settings_write
            and timer
            and (
                timer.can_edit_duration or timer.can_edit_sleep or timer.can_edit_sound
            )
        )

    def _open_timer_editor(self) -> None:
        timer = self._controller.catalog.timer
        if (
            self._timer_dialog is not None
            or timer is None
            or not self._timer_writable()
        ):
            return
        dialog = TimerEditor(timer, self)
        self._timer_dialog = dialog
        self._timer_target = self._controller.active_ipod
        self._timer_catalog = self._controller.catalog

        def submit() -> None:
            if (
                self._timer_target is self._controller.active_ipod
                and self._timer_catalog is self._controller.catalog
                and self._timer_writable()
            ):
                self._controller.save_timer_settings(dialog.selected_changes())

        def finished(_result: int) -> None:
            self._timer_dialog = None
            self._timer_target = None
            self._timer_catalog = None
            dialog.deleteLater()

        dialog.accepted.connect(submit)
        dialog.finished.connect(finished)
        dialog.open()

    def _selection_changed(self) -> None:
        item = self._selected()
        support = self._controller.catalog.support
        collection = support is not None and support.alarm_format in (
            AlarmFormat.CLASSIC,
            AlarmFormat.CLOCK,
        )
        self._new.setVisible(collection)
        self._new.setEnabled(
            bool(self._writable() and self._controller.catalog.can_create_alarm)
        )
        self._remove.setVisible(collection)
        self._remove.setEnabled(bool(self._writable() and item and item.editable))
        self._edit.setEnabled(
            bool(self._writable() and item and item.editable and item.time is not None)
        )
        self._details.setText(
            self.tr(
                "This alarm can be viewed here. Change its other settings on your iPod."
            )
            if item and not item.editable
            else ""
        )
        self._details.setToolTip(item.detail if item else "")
        self._details.setVisible(bool(self._details.text()))

    def _open_editor(self) -> None:
        item = self._selected()
        if (
            self._dialog is not None
            or not self._writable()
            or item is None
            or not item.editable
            or item.time is None
        ):
            return
        self._edit_item(item)

    def _new_alarm(self) -> None:
        if (
            self._dialog is not None
            or not self._writable()
            or not self._controller.catalog.can_create_alarm
        ):
            return
        if self._controller.catalog.clock_cities:
            item = AlarmItem(
                -1,
                "",
                Time(0),
                None,
                True,
                enabled=False,
                enabled_editable=True,
                sound=self._controller.catalog.alarm_sounds[0]
                if self._controller.catalog.alarm_sounds
                else None,
                sound_editable=bool(self._controller.catalog.alarm_sounds),
                daylight_saving=False,
                daylight_saving_editable=True,
            )
            self._edit_item(item, creating=True)
            return
        date = QDate.currentDate()
        item = AlarmItem(
            -1,
            "",
            PlainDateTime(date.year(), date.month(), date.day(), 8),
            0,
            True,
            repeat_editable=True,
            enabled=True,
            enabled_editable=True,
            label_index=3,
            label_editable=True,
            sound=self._controller.catalog.alarm_sounds[0]
            if self._controller.catalog.alarm_sounds
            else None,
            sound_editable=bool(self._controller.catalog.alarm_sounds),
        )
        self._edit_item(item, creating=True)

    def _edit_item(self, item: AlarmItem, *, creating: bool = False) -> None:
        dialog = AlarmEditor(
            item,
            self,
            creating=creating,
            sounds=self._controller.catalog.alarm_sounds,
            cities=self._controller.catalog.clock_cities,
        )
        self._dialog = dialog
        self._editing = item
        self._creating = creating
        self._dialog_target = self._controller.active_ipod
        self._dialog_catalog = self._controller.catalog

        def submit() -> None:
            if (
                self._dialog_target is self._controller.active_ipod
                and self._dialog_catalog is self._controller.catalog
                and self._writable()
            ):
                if creating:
                    time = dialog.selected_time()
                    enabled = dialog.selected_enabled()
                    if isinstance(time, Time):
                        city = dialog.selected_city()
                        assert city is not None
                        self._controller.create_clock_alarm(
                            city,
                            time,
                            daylight_saving=dialog.selected_daylight_saving() is True,
                            enabled=enabled is True,
                            sound=dialog.selected_sound(),
                        )
                        return
                    label = dialog.selected_label()
                    self._controller.create_alarm(
                        time,
                        dialog.selected_repeat() or 0,
                        enabled=True if enabled is None else enabled,
                        label_index=3 if label is None else label,
                        sound=dialog.selected_sound(),
                    )
                else:
                    self._controller.save_alarm(
                        item,
                        dialog.selected_time(),
                        dialog.selected_repeat(),
                        enabled=dialog.selected_enabled(),
                        label_index=dialog.selected_label(),
                        sound=dialog.selected_sound(),
                        daylight_saving=dialog.selected_daylight_saving(),
                    )

        def finished(_result: int) -> None:
            self._dialog = None
            self._editing = None
            self._creating = False
            self._dialog_target = None
            self._dialog_catalog = None
            dialog.deleteLater()

        dialog.accepted.connect(submit)
        dialog.finished.connect(finished)
        dialog.open()

    def _remove_alarm(self) -> None:
        item = self._selected()
        active = self._controller.active_ipod
        catalog = self._controller.catalog
        if item is None or not item.editable or not self._writable():
            return
        city_alarm = (
            catalog.support is not None
            and catalog.support.alarm_format is AlarmFormat.CLOCK
        )
        answer = QMessageBox.question(
            self,
            self.tr("Remove city") if city_alarm else self.tr("Remove alarm"),
            self.tr("Remove {city} and its alarm from your iPod's clocks?").format(
                city=workflow_text(item.display_label)
            )
            if city_alarm
            else self.tr("Remove this saved alarm from your iPod?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if (
            answer is QMessageBox.StandardButton.Yes
            and active is self._controller.active_ipod
            and catalog is self._controller.catalog
            and self._writable()
        ):
            self._controller.remove_alarm(item)

    def retranslate_ui(self) -> None:
        support = self._controller.catalog.support
        active = self._controller.active_ipod
        countdown = bool(
            active
            and active.profile.family == "iPod Nano"
            and active.profile.generation in {"6th Gen", "7th Gen"}
        )
        city_alarms = support is not None and support.alarm_format is AlarmFormat.CLOCK
        alarm_heading = (
            self.tr("Cities & alarms") if city_alarms else self.tr("Saved alarms")
        )
        self._header.set_title(self.tr("Timer") if countdown else self.tr("Alarms"))
        self._refresh_button.setText(
            QCoreApplication.translate("CommonActions", "Refresh")
        )
        self._refresh_button.setEnabled(
            self._controller.active_ipod is not None and not self._controller.busy
        )
        self._tabs.setTabText(0, self.tr("Alarms"))
        self._tabs.setTabText(
            1, self.tr("Timer") if countdown else self.tr("Sleep Timer")
        )
        self._tabs.setTabVisible(0, not countdown)
        self._tabs.tabBar().setVisible(not countdown)
        if countdown:
            self._tabs.setCurrentIndex(1)
        self._intro.setText(alarm_heading)
        self._summary.setText(
            self.tr("{count} saved").format(count=len(self._controller.catalog.alarms))
        )
        self._hint.setText(
            self.tr(
                "Each city has its own alarm. Times follow that city's clock on your iPod."
            )
            if city_alarms
            else self.tr(
                "Times follow the saved clock on your iPod. Changes are saved to the device; check them after ejecting."
            )
        )
        self._tree.setAccessibleName(alarm_heading)
        self._sleep_title.setText(
            self.tr("Countdown timer")
            if countdown
            else self.tr("Fall asleep to your music")
        )
        self._sleep_subtitle.setText(
            self.tr("Saved duration and ending action.")
            if countdown
            else self.tr(
                "Let your iPod stop playback after a little while. Set a Sleep Timer directly on the device."
            )
        )
        self._tree.setHeaderLabels(
            [self.tr("Alarm"), self.tr("Time"), self.tr("Repeat")]
        )
        self._edit.setText(self.tr("Edit alarm…"))
        self._new.setText(
            self.tr("Add city…") if city_alarms else self.tr("New alarm…")
        )
        self._remove.setText(
            self.tr("Remove city") if city_alarms else self.tr("Remove alarm")
        )
        timer = self._controller.catalog.timer
        self._timer_edit.setText(self.tr("Edit timer settings…"))
        self._timer_edit.setVisible(countdown)
        self._timer_edit.setEnabled(self._timer_writable())
        duration = (
            self.tr("{hours} h {minutes} min").format(
                hours=timer.saved_hours, minutes=timer.saved_minutes
            )
            if timer is not None
            and timer.saved_hours is not None
            and timer.saved_minutes is not None
            else ""
        )
        self._timer_duration.setText(duration)
        self._timer_duration.setVisible(countdown and bool(duration))
        qualification = ""
        if (
            active is not None
            and support is not None
            and not support.alarm_write
            and not countdown
        ):
            qualification = (
                self.tr(
                    "{model} · Firmware {firmware}\nAlarm editing is unavailable because editing support could not be confirmed for this model and firmware."
                ).format(
                    model=active.profile.display_name, firmware=active.firmware_version
                )
                if active.firmware_version
                else self.tr(
                    "{model}: Alarm editing is unavailable because the iPod's firmware version could not be confirmed."
                ).format(model=active.profile.display_name)
            )
        self._status.setText(
            self.tr("Choose an iPod to view its alarms.")
            if active is None
            else "\n".join(
                filter(
                    None,
                    (
                        qualification,
                        self._controller.message,
                        (
                            self.tr(
                                "Some timer settings could not be read. Available settings are shown below."
                            )
                            if countdown
                            else self.tr(
                                "Some alarm details could not be read. Available alarms are shown below."
                            )
                        )
                        if self._controller.catalog.issues
                        else "",
                    ),
                )
            )
        )
        self._status.setVisible(bool(self._status.text()))
        self._status.setToolTip("\n".join(self._controller.catalog.issues))
        self._empty.setVisible(self._tree.topLevelItemCount() == 0)
        self._tree.setVisible(self._tree.topLevelItemCount() > 0)
        if active is None:
            self._empty.clear()
        elif self._controller.busy:
            self._empty.setText(self.tr("Loading alarms…"))
        elif support is None:
            self._empty.setText(self.tr("Saved alarms have not been loaded."))
        elif support.alarm_format is AlarmFormat.NONE:
            self._empty.setText(
                self.tr("Saved alarms cannot be read for this firmware.")
            )
        else:
            self._empty.setText(
                self.tr("No cities saved. Add a city to set its alarm.")
                if city_alarms and self._controller.catalog.can_create_alarm
                else self.tr("No saved alarms. Create an alarm to get started.")
                if self._controller.catalog.can_create_alarm
                else self.tr(
                    "No saved alarms were found. Create an alarm on the iPod, then refresh this page."
                )
            )
        if active is None:
            self._sleep.setText(
                self.tr("Choose an iPod to see its sleep-timer instructions.")
            )
        elif countdown:
            self._sleep.setText(self._timer_text())
        elif active.profile.capabilities.extras.sleep_timer is FeatureSupport.SUPPORTED:
            if active.profile.family == "iPod Classic" or (
                active.profile.family == "iPod Nano"
                and active.profile.generation in {"3rd Gen", "4th Gen", "5th Gen"}
            ):
                path = self.tr("Open Extras, then Alarms, then Sleep Timer.")
            elif active.profile.family == "iPod Mini":
                path = self.tr("Open Extras, then Clock, then Sleep Timer.")
            else:
                path = self.tr(
                    "Open Extras, then Clock. Select a clock if prompted, then choose Sleep Timer."
                )
            self._sleep.setText(
                self.tr("Start the timer on your iPod.")
                + "\n\n"
                + path
                + "\n\n"
                + self.tr(
                    "Select how long the iPod should play before sleeping.\n\niOpenPod cannot read or change it over this connection."
                )
            )
        else:
            self._sleep.setText(
                self.tr("Sleep-timer support has not been confirmed for this iPod.")
            )
        self._selection_changed()

    def _timer_text(self) -> str:
        timer = self._controller.catalog.timer
        lines: list[str] = []
        if timer is not None:
            if timer.sleep_ipod is not None:
                lines.append(
                    self.tr("When timer ends: Sleep iPod")
                    if timer.sleep_ipod
                    else self.tr("When timer ends: {sound}").format(
                        sound=workflow_text(TIMER_SOUND_LABELS[timer.sound_index])
                        if timer.sound_index is not None
                        and 0 <= timer.sound_index < len(TIMER_SOUND_LABELS)
                        else self.tr("Play a sound")
                    )
                )
            if timer.deadline is not None:
                lines.append(
                    self.tr("Saved end time: {time}").format(
                        time=_display_time(timer.deadline)
                    )
                )
        if not lines and not (
            timer and timer.saved_hours is not None and timer.saved_minutes is not None
        ):
            lines.append(self.tr("No saved timer settings are available."))
        lines.append(
            self.tr("Saved settings do not show whether the timer is running.")
        )
        lines.append(
            self.tr(
                "Open Clock on your iPod, then Timer. Choose a duration and sound, or Sleep iPod, then tap Start."
            )
        )
        return "\n\n".join(lines)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._controller.refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._refresh()
        super().changeEvent(event)
