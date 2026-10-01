"""Reusable Settings page grouping primitives."""

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

    def set_copy(self, title: str, description: str) -> None:
        self._title.setText(title)
        self._description.setText(description)
        self._description.setVisible(bool(description))
