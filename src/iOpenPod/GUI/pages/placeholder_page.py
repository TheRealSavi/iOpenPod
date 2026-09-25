"""Reusable page shape for feature surfaces awaiting Application Layer work."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from iOpenPod.GUI.navigation import PageId, page_label, placeholder_description
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class PlaceholderPage(QWidget):
    """Make an unfinished page explicit without inventing device behavior."""

    def __init__(
        self,
        page_id: PageId,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._page_id = page_id

        self._title = QLabel(self)
        self._title.setObjectName("pageTitle")
        self._description = QLabel(self)
        self._description.setObjectName("pageDescription")
        self._description.setWordWrap(True)

        surface = QFrame(self)
        surface.setObjectName("placeholderSurface")
        surface.setMaximumWidth(620)
        surface_layout = QVBoxLayout(surface)
        surface_layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        surface_layout.setSpacing(LAYOUT.space_xs)
        self._status = QLabel(surface)
        self._status.setObjectName("placeholderBadge")
        self._note = QLabel(surface)
        self._note.setObjectName("placeholderNote")
        self._note.setWordWrap(True)
        surface_layout.addWidget(self._status, 0, Qt.AlignmentFlag.AlignLeft)
        surface_layout.addWidget(self._note)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_xl,
            LAYOUT.space_xl,
            LAYOUT.space_xl,
            LAYOUT.space_lg,
        )
        layout.setSpacing(LAYOUT.space_xs)
        layout.addWidget(self._title)
        layout.addWidget(self._description)
        layout.addSpacing(LAYOUT.space_lg)
        layout.addWidget(surface)
        layout.addStretch(1)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._title.setText(page_label(self._page_id))
        self._description.setText(placeholder_description(self._page_id))
        self._status.setText(self.tr("UI placeholder"))
        self._note.setText(
            self.tr(
                "This page reserves the application structure. Its data and actions "
                "will be connected through an Application Layer module later."
            )
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
