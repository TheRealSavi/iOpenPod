"""Shared page-header and source-list chrome for application browsers."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class PageHeader(QFrame):
    """Own the compact title-and-actions row shared by application pages."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageHeader")
        self.setProperty("pageHeader", True)
        self.setFixedHeight(LAYOUT.page_header_height)

        self._title = QLabel(self)
        self._title.setObjectName("pageHeaderTitle")
        self._title.setProperty("browserTitle", True)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(
            LAYOUT.space_lg,
            0,
            LAYOUT.space_lg,
            0,
        )
        self._layout.setSpacing(LAYOUT.space_sm)
        self._layout.addWidget(self._title)
        self._layout.addStretch(1)

    @property
    def title_label(self) -> QLabel:
        """Return the title label for stable names and accessibility wiring."""

        return self._title

    def set_title(self, title: str) -> None:
        """Set the visible and accessible page title."""

        self._title.setText(title)
        self._title.setAccessibleName(title)

    def add_action(self, action: QWidget) -> None:
        """Append one page-owned action to the shared header rhythm."""

        self._layout.addWidget(action)


class SourceListPanel(QFrame):
    """Frame one titled source list with shared rail geometry and behavior."""

    def __init__(
        self,
        width: int = LAYOUT.source_list_width,
        parent: QWidget | None = None,
        *,
        minimum_width: int = LAYOUT.source_list_minimum_width,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sourceListPanel")
        self.setProperty("sourceListPanel", True)
        self.setMinimumWidth(minimum_width)
        self.resize(width, self.height())
        self._view: QListView | None = None

        self._title = QLabel(self)
        self._title.setObjectName("sourceListTitle")
        self._title.setProperty("sourceListTitle", True)
        self._count = QLabel(self)
        self._count.setObjectName("sourceListCount")
        self._count.setProperty("sourceListCount", True)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(LAYOUT.space_xs)
        heading.addWidget(self._title)
        heading.addWidget(self._count)
        heading.addStretch(1)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(
            LAYOUT.space_md,
            LAYOUT.space_md,
            LAYOUT.space_md,
            LAYOUT.space_md,
        )
        self._layout.setSpacing(LAYOUT.space_xs)
        self._layout.addLayout(heading)

    @property
    def title_label(self) -> QLabel:
        """Return the heading label for stable object naming."""

        return self._title

    @property
    def count_label(self) -> QLabel:
        """Return the count label for stable object naming."""

        return self._count

    def set_title(self, title: str) -> None:
        """Set the rail heading and use it as the list's accessible name."""

        self._title.setText(title)
        if self._view is not None:
            self._view.setAccessibleName(title)

    def set_count(self, count: int) -> None:
        """Present a non-negative source count beside the heading."""

        self._count.setText(str(max(0, count)))

    def set_view(
        self,
        view: QListView,
        *,
        standard_items: bool = True,
    ) -> None:
        """Install one list and apply the common source-navigation behavior."""

        if self._view is not None:
            raise RuntimeError("A SourceListPanel can own only one list view.")
        self._view = view
        view.setParent(self)
        view.setProperty("sourceList", True)
        view.setProperty("sourceListStandardItems", standard_items)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.setAccessibleName(self._title.text())
        self._layout.addWidget(view, 1)


__all__ = ["PageHeader", "SourceListPanel"]
