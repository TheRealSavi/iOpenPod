"""Shared 12-hour time input with the application's field treatment."""

from PySide6.QtWidgets import QAbstractSpinBox, QTimeEdit, QWidget


class AppTimeEdit(QTimeEdit):
    """Keep native section editing, with AM/PM and no spinner buttons."""

    def __init__(
        self, parent: QWidget | None = None, *, show_seconds: bool = True
    ) -> None:
        super().__init__(parent)
        self.setProperty("themedTimeInput", True)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setDisplayFormat("h:mm:ss AP" if show_seconds else "h:mm AP")
