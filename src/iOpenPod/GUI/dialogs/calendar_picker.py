"""Choose a Calendar destination using shared application controls."""

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind


class CalendarPickerDialog(QDialog):
    """Return an index into the caller's captured destination list."""

    def __init__(self, labels: tuple[str, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("calendarPicker")
        self.setMinimumWidth(320)
        self._label = QLabel(self)
        self._calendar = AppComboBox(self)
        self._calendar.setObjectName("calendarDestination")
        self._calendar.addItems(labels)
        self._label.setBuddy(self._calendar)
        self._cancel = ActionButton(parent=self)
        self._cancel.clicked.connect(self.reject)
        self._accept = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._accept.setDefault(True)
        self._accept.setEnabled(bool(labels))
        self._accept.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(*(LAYOUT.space_md,) * 4)
        layout.setSpacing(LAYOUT.space_xs)
        layout.addWidget(self._label)
        layout.addWidget(self._calendar)
        layout.addSpacing(LAYOUT.space_xs)
        actions = QHBoxLayout()
        actions.setSpacing(LAYOUT.space_xs)
        actions.addStretch(1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._accept)
        layout.addLayout(actions)
        self._translate()
        self._calendar.setFocus()

    def selected_index(self) -> int:
        return self._calendar.currentIndex()

    def _translate(self) -> None:
        self.setWindowTitle(QCoreApplication.translate("CalendarPage", "New entry"))
        self._label.setText(QCoreApplication.translate("CalendarPage", "Calendar:"))
        self._calendar.setAccessibleName(self._label.text())
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))
        self._accept.setText(QCoreApplication.translate("CommonActions", "OK"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._translate()
        super().changeEvent(event)
