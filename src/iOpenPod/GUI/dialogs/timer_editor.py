"""Explicit saved countdown presets, independent of live timer state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.timer_sounds import TIMER_SOUND_LABELS
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iPodDB.alarms import (
    CountdownTimerChanges,
    CountdownTimerSnapshot,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QShowEvent


class TimerEditor(QDialog):
    """Edit captured duration and ending action without starting a countdown."""

    def __init__(
        self, timer: CountdownTimerSnapshot, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("timerEditor")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(400)
        self._timer = timer
        self._hours = QSpinBox(self)
        self._hours.setObjectName("timerHours")
        self._hours.setRange(-1, 23)
        self._hours.setValue(timer.saved_hours if timer.saved_hours is not None else -1)
        self._minutes = QSpinBox(self)
        self._minutes.setObjectName("timerMinutes")
        self._minutes.setRange(-1, 59)
        self._minutes.setValue(
            timer.saved_minutes if timer.saved_minutes is not None else -1
        )
        self._hours.setEnabled(timer.can_edit_duration)
        self._minutes.setEnabled(timer.can_edit_duration)
        self._hours_label = QLabel(self)
        self._minutes_label = QLabel(self)
        self._hours_label.setBuddy(self._hours)
        self._minutes_label.setBuddy(self._minutes)
        duration = QHBoxLayout()
        duration.setSpacing(LAYOUT.space_md)
        for label, field in (
            (self._hours_label, self._hours),
            (self._minutes_label, self._minutes),
        ):
            column = QVBoxLayout()
            column.setSpacing(LAYOUT.space_2xs)
            column.addWidget(label)
            column.addWidget(field)
            duration.addLayout(column)
        self._ending = AppComboBox(self)
        self._ending.setObjectName("timerEnding")
        self._ending.setEnabled(timer.can_edit_sleep or timer.can_edit_sound)
        self._ending_label = QLabel(self)
        self._ending_label.setBuddy(self._ending)
        ending = QVBoxLayout()
        ending.setSpacing(LAYOUT.space_2xs)
        ending.addWidget(self._ending_label)
        ending.addWidget(self._ending)
        self._note = QLabel(self)
        self._note.setWordWrap(True)
        self._note.setTextFormat(Qt.TextFormat.PlainText)
        self._save = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._save.setObjectName("timerEditorSave")
        self._save.setDefault(True)
        self._save.clicked.connect(self.accept)
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
        layout.setSpacing(LAYOUT.space_lg)
        layout.addLayout(duration)
        layout.addLayout(ending)
        layout.addWidget(self._note)
        layout.addLayout(actions)
        self.setTabOrder(self._hours, self._minutes)
        self.setTabOrder(self._minutes, self._ending)
        self.setTabOrder(self._ending, self._cancel)
        self.setTabOrder(self._cancel, self._save)
        self.retranslate_ui()

    def selected_changes(self) -> CountdownTimerChanges:
        hours = self._hours.value()
        minutes = self._minutes.value()
        ending: object = self._ending.currentData()
        sleep = None
        sound = None
        if ending == -1 and self._timer.can_edit_sleep:
            sleep = True if self._timer.sleep_ipod is not True else None
        elif (
            type(ending) is int
            and ending >= 0
            and self._timer.can_edit_sound
            and (
                ending != self._timer.sound_index or self._timer.sleep_ipod is not False
            )
        ):
            sound = ending
        return CountdownTimerChanges(
            saved_hours=(
                hours
                if self._timer.can_edit_duration
                and hours >= 0
                and hours != self._timer.saved_hours
                else None
            ),
            saved_minutes=(
                minutes
                if self._timer.can_edit_duration
                and minutes >= 0
                and minutes != self._timer.saved_minutes
                else None
            ),
            sleep_ipod=sleep,
            sound_index=sound,
        )

    def set_writable(self, writable: bool) -> None:
        self._save.setEnabled(writable)

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Timer settings"))
        self._hours_label.setText(self.tr("Hours"))
        self._minutes_label.setText(self.tr("Minutes"))
        self._hours.setSpecialValueText(self.tr("Unchanged"))
        self._minutes.setSpecialValueText(self.tr("Unchanged"))
        self._ending_label.setText(self.tr("When timer ends"))
        selected: object = (
            self._ending.currentData()
            if self._ending.count()
            else -1
            if self._timer.sleep_ipod is True
            else self._timer.sound_index
            if self._timer.sleep_ipod is False
            else None
        )
        self._ending.clear()
        if self._timer.can_edit_sleep or selected == -1:
            self._ending.addItem(self.tr("Sleep iPod"), -1)
        for index, name in enumerate(TIMER_SOUND_LABELS):
            if self._timer.can_edit_sound or selected == index:
                self._ending.addItem(workflow_text(name), index)
        if self._ending.findData(selected) < 0:
            self._ending.insertItem(0, self.tr("Keep current setting"), None)
            selected = None
        self._ending.setCurrentIndex(self._ending.findData(selected))
        self._note.setText(
            self.tr(
                "Your iPod loads these settings on restart. Start and stop the timer on the iPod."
            )
        )
        self._save.setText(self.tr("Save"))
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.resize(self.sizeHint().expandedTo(self.minimumSize()))
