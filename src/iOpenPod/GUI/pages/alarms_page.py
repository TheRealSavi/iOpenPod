"""Existing iPod alarms and on-device sleep-timer guidance.

Alarm dates are device calendar coordinates, never Host timezone conversions.
Only the qualified time/repeat payloads are editable; retained enable, sound and
label values do not acquire invented meanings. See the Calendar/Alarm research.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QDate, QEvent, QLocale, Qt, QTime
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QTimeEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from whenever import PlainDateTime, Time

from device_registry import AlarmFormat, FeatureSupport
from iOpenPod.GUI.delegates.extras_delegate import ExtrasDelegate
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from PySide6.QtGui import QShowEvent

    from iOpenPod.app.extras_controller import ExtrasController
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.models.extras import AlarmItem


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

    def __init__(self, item: AlarmItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if item.time is None:
            raise ValueError("An alarm editor needs a captured valid time.")
        self.setObjectName("alarmEditor")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(400)
        self._item = item
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
        self._time.setTime(QTime(item.time.hour, item.time.minute, item.time.second))
        self._time.setDisplayFormat(
            "HH:mm:ss" if isinstance(item.time, PlainDateTime) else "HH:mm"
        )
        self._repeat = AppComboBox(self)
        self._repeat.setObjectName("alarmRepeat")
        self._repeat.setEnabled(item.repeat_editable)
        self._date_label = QLabel(self)
        self._time_label = QLabel(self)
        self._repeat_label = QLabel(self)
        self._date_label.setBuddy(self._date)
        self._time_label.setBuddy(self._time)
        self._repeat_label.setBuddy(self._repeat)
        form = QFormLayout()
        form.addRow(self._date_label, self._date)
        form.addRow(self._time_label, self._time)
        form.addRow(self._repeat_label, self._repeat)
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
        self.retranslate_ui()

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

    def _accept_valid(self) -> None:
        if not self._save.isEnabled():
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
        self.setWindowTitle(self.tr("Edit alarm"))
        self._date_label.setText(self.tr("Date"))
        self._time_label.setText(self.tr("Time"))
        self._repeat_label.setText(self.tr("Repeat"))
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
        self._note.setText(
            self.tr(
                "Times follow the iPod's clock. Check that the alarm is enabled and its sound is set on the iPod."
            )
        )
        self._save.setText(self.tr("Save"))
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


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
        self._edit = ActionButton(parent=alarms, kind=ActionButtonKind.PRIMARY)
        self._edit.setObjectName("alarmEdit")
        actions = QHBoxLayout()
        actions.addWidget(self._intro)
        actions.addStretch(1)
        actions.addWidget(self._edit)
        alarm_layout = QVBoxLayout(content)
        alarm_layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        alarm_layout.setSpacing(LAYOUT.space_md)
        alarm_layout.addLayout(actions)
        alarm_layout.addWidget(self._hint)
        alarm_layout.addWidget(self._tree, 1)
        alarm_layout.addWidget(self._empty, 1)
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
        sleep_text = QVBoxLayout(sleep_content)
        sleep_text.setContentsMargins(
            LAYOUT.space_xl, LAYOUT.space_xl, LAYOUT.space_xl, LAYOUT.space_xl
        )
        sleep_text.setSpacing(LAYOUT.space_lg)
        sleep_text.addWidget(self._sleep_title)
        sleep_text.addWidget(self._sleep_subtitle)
        sleep_text.addWidget(self._sleep)
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
                        part for part in (self._repeat_text(item.repeat), date) if part
                    ),
                    self.tr("Read only") if not item.editable else "",
                ]
            )
            row.setData(0, Qt.ItemDataRole.UserRole, item.index)
            row.setToolTip(
                0,
                "\n".join(
                    part
                    for part in (
                        row.text(0),
                        _display_time(item.time),
                        row.text(2),
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
                or self._editing not in self._controller.catalog.alarms
            ):
                self._dialog.reject()
            else:
                self._dialog.set_writable(self._writable())
        self.retranslate_ui()

    def _selection_changed(self) -> None:
        item = self._selected()
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
        dialog = AlarmEditor(item, self)
        self._dialog = dialog
        self._editing = item
        self._dialog_target = self._controller.active_ipod

        def submit() -> None:
            if self._dialog_target is self._controller.active_ipod and self._writable():
                self._controller.save_alarm(
                    item, dialog.selected_time(), dialog.selected_repeat()
                )

        def finished(_result: int) -> None:
            self._dialog = None
            self._editing = None
            self._dialog_target = None
            dialog.deleteLater()

        dialog.accepted.connect(submit)
        dialog.finished.connect(finished)
        dialog.open()

    def retranslate_ui(self) -> None:
        support = self._controller.catalog.support
        projection = support is not None and support.alarm_format is AlarmFormat.VIDEO
        alarm_heading = (
            self.tr("Clock alarm snapshot") if projection else self.tr("Saved alarms")
        )
        self._header.set_title(self.tr("Alarms"))
        self._refresh_button.setText(
            QCoreApplication.translate("CommonActions", "Refresh")
        )
        self._refresh_button.setEnabled(
            self._controller.active_ipod is not None and not self._controller.busy
        )
        self._tabs.setTabText(0, self.tr("Alarms"))
        self._tabs.setTabText(1, self.tr("Sleep Timer"))
        self._intro.setText(alarm_heading)
        self._hint.setText(
            self.tr(
                "Times follow your iPod's clock. Turn alarms on or off and choose their sound on the iPod."
            )
        )
        self._tree.setAccessibleName(alarm_heading)
        self._sleep_title.setText(self.tr("Fall asleep to your music"))
        self._sleep_subtitle.setText(
            self.tr(
                "Let your iPod stop playback after a little while. Set a Sleep Timer directly on the device."
            )
        )
        self._tree.setHeaderLabels(
            [self.tr("Alarm"), self.tr("Time"), self.tr("Repeat")]
        )
        self._edit.setText(self.tr("Edit alarm…"))
        active = self._controller.active_ipod
        qualification = ""
        if (
            active is not None
            and support is not None
            and support.alarm_format is AlarmFormat.VIDEO
        ):
            qualification = self.tr(
                "This read-only snapshot is the iPod's saved alarm time. It may be disabled or out of date. Manage saved alarms on the iPod."
            )
        elif active is not None and support is not None and not support.alarm_write:
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
                        self.tr(
                            "Some alarm details could not be read. Available alarms are shown below."
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
        elif support.alarm_format is AlarmFormat.VIDEO:
            self._empty.setText(
                self.tr(
                    "The clock alarm snapshot could not be read. Check saved alarms on your iPod."
                )
            )
        else:
            self._empty.setText(
                self.tr(
                    "No saved alarms were found. Create an alarm on the iPod, then refresh this page."
                )
            )
        if active is None:
            self._sleep.setText(
                self.tr("Choose an iPod to see its sleep-timer instructions.")
            )
        elif active.profile.capabilities.extras.sleep_timer is FeatureSupport.SUPPORTED:
            if active.profile.family == "iPod Classic":
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

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._controller.refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._refresh()
        super().changeEvent(event)
