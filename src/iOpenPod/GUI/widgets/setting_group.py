"""Reusable Settings page grouping primitives."""

from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class SettingGroup(QFrame):
    """One semantic group of Setting rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingGroup")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def add_row(self, row: "SettingRow") -> None:
        row.setProperty("first", self._layout.count() == 0)
        self._layout.addWidget(row)


class SettingRow(QWidget):
    """Keep setting explanation and control aligned across pages."""

    def __init__(
        self,
        title: str,
        description: str,
        control: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingRow")
        self._title = QLabel(title, self)
        self._title.setObjectName("settingLabel")
        self._title.setBuddy(control)
        self._description = QLabel(description, self)
        self._description.setObjectName("settingDescription")
        self._description.setWordWrap(True)
        self._description.setMaximumWidth(720)
        self._description.setVisible(bool(description))

        copy_layout = QVBoxLayout()
        copy_layout.setContentsMargins(0, 0, 0, 0)
        copy_layout.setSpacing(LAYOUT.space_3xs)
        copy_layout.addWidget(self._title)
        copy_layout.addWidget(self._description)
        self._scope_hint = QLabel(self)
        self._scope_hint.setObjectName("settingDescription")
        self._scope_hint.setWordWrap(True)
        self._scope_hint.hide()
        copy_layout.addWidget(self._scope_hint)

        control.setMinimumWidth(220)
        control.setMaximumWidth(320)
        control.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_md,
            LAYOUT.space_sm,
            LAYOUT.space_md,
            LAYOUT.space_sm,
        )
        layout.setSpacing(LAYOUT.space_lg)
        layout.addLayout(copy_layout, 1)
        layout.addWidget(control)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_minimum_height()

    def _update_minimum_height(self) -> None:
        # Scroll areas use minimum heights when sizing their contents. A wrapped
        # description needs the row's height for its current width instead.
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        required_height = self.heightForWidth(self.width())
        if required_height > 0 and self.minimumHeight() != required_height:
            self.setMinimumHeight(required_height)

    def set_copy(self, title: str, description: str) -> None:
        self._title.setText(title)
        self._description.setText(description)
        self._description.setVisible(bool(description))
        self._update_minimum_height()

    def set_scope_hint(self, text: str) -> None:
        self._scope_hint.setText(text)
        self._scope_hint.setVisible(bool(text))
        self._update_minimum_height()
