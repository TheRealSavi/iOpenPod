"""A content-sized collection surface for the Alarms and Tones workspaces."""

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT


class _CollectionList(QTreeWidget):
    """Prefer the saved rows' height, while leaving long collections scrollable."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setProperty("extrasList", True)
        self.setProperty("extrasCollectionList", True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setRootIsDecorated(False)
        self.setHeaderHidden(True)
        self.setMouseTracking(True)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        model = self.model()
        model.rowsInserted.connect(self.updateGeometry)
        model.rowsRemoved.connect(self.updateGeometry)
        model.modelReset.connect(self.updateGeometry)
        model.dataChanged.connect(self.updateGeometry)

    def sizeHint(self) -> QSize:
        margins = self.contentsMargins()
        height = margins.top() + margins.bottom()
        for row in range(min(self.topLevelItemCount(), LAYOUT.extras_visible_rows)):
            height += self.sizeHintForIndex(self.model().index(row, 0)).height()
        return QSize(LAYOUT.extras_collection_width, height)

    def minimumSizeHint(self) -> QSize:
        # Short windows keep the action bar reachable and scroll the rows.
        return QSize(0, LAYOUT.control_height_large * 2)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.updateGeometry()


class ExtrasCollection(QFrame):
    """One rounded panel, a native list/empty state, and an attached action bar."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setProperty("extrasCollection", True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.view = _CollectionList(self)
        self.empty = QLabel(self)
        self.empty.setWordWrap(True)
        self.empty.setTextFormat(Qt.TextFormat.PlainText)
        self.empty.setProperty("extrasEmpty", True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(LAYOUT.control_height_large * 4)
        footer = QFrame(self)
        footer.setProperty("extrasCollectionActions", True)
        self.action_layout = QHBoxLayout(footer)
        self.action_layout.setContentsMargins(
            LAYOUT.space_md, LAYOUT.space_sm, LAYOUT.space_md, LAYOUT.space_sm
        )
        self.action_layout.setSpacing(LAYOUT.space_xs)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.empty, 1)
        layout.addWidget(footer)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        # Clearing the list must not collapse the panel around its empty label.
        hint.setWidth(LAYOUT.extras_collection_width)
        return hint
