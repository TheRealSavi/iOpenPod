"""Draggable context and search surface between Library item views."""

from PySide6.QtCore import QByteArray, QCoreApplication, QEvent, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSplitter,
    QSplitterHandle,
    QWidget,
)

from iOpenPod.app.core.settings.definitions import TrackTitleBarStyle
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.dynamic import (
    colorful_header_colors,
    round_header_colors,
)
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.search_field import SearchField


class TrackListHeader(QSplitterHandle):
    """Make Track context and search part of the real splitter handle."""

    queryChanged = Signal(str)

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QSplitter,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
    ) -> None:
        super().__init__(orientation, parent)
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self.setObjectName("trackListHeader")
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self._context_title: str | None = None
        self._artwork_id = 0

        self._title = QLabel(self)
        self._title.setObjectName("trackListTitle")
        self._title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._search = SearchField(self)
        self._search.setObjectName("trackListSearch")
        self._search.setMaximumWidth(260)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_sm,
            LAYOUT.space_2xs,
            LAYOUT.space_sm,
            LAYOUT.space_2xs,
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addStretch(1)
        layout.addWidget(self._search)

        self._search.queryChanged.connect(self.queryChanged.emit)
        theme_manager.effectiveThemeChanged.connect(self._presentation_changed)
        theme_manager.colorfulModeChanged.connect(self._presentation_changed)
        theme_manager.trackTitleBarStyleChanged.connect(self._title_bar_style_changed)
        artwork_provider.artworkChanged.connect(self._artwork_changed)
        artwork_provider.cleared.connect(self.update)
        self.retranslate_ui()
        self._title_bar_style_changed(theme_manager.track_title_bar_style.value)

    def set_context(self, title: str | None, artwork_id: int = 0) -> None:
        self._context_title = title
        self._artwork_id = max(0, artwork_id)
        self._refresh_title()
        self.update()

    def set_query(self, query: str) -> None:
        self._search.set_query(query)

    def retranslate_ui(self) -> None:
        self.setAccessibleName(self.tr("Resize Track list"))
        self.setToolTip(self.tr("Drag to resize the Track list"))
        self._search.setPlaceholderText(
            QCoreApplication.translate("LibraryLabels", "Search Tracks")
        )
        self._search.setAccessibleName(
            QCoreApplication.translate("LibraryLabels", "Search Tracks")
        )
        self._search.setToolTip(self.tr("Search within the Tracks shown in this list"))
        self._refresh_title()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        color = None
        if self._theme_manager.colorful_mode and self._artwork_id > 0:
            color = self._artwork_provider.dominant_color(
                self._artwork_id,
                80,
                self.devicePixelRatioF(),
            )
        tokens = self._theme_manager.tokens
        if self._theme_manager.track_title_bar_style is TrackTitleBarStyle.ROUND:
            accent = QColor(tokens.accent)
            round_colors = round_header_colors(
                color or (accent.red(), accent.green(), accent.blue()), tokens
            )
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(self.rect(), QColor(tokens.surface))
            radius = LAYOUT.radius_control
            # Extend the rounded bottom beyond the handle: only the upper corners
            # curve, so the title bar joins the Track table without a gap.
            shape = QPainterPath()
            shape.addRoundedRect(
                QRectF(0, 0, self.width(), self.height() + radius),
                radius,
                radius,
            )
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0, round_colors.top)
            gradient.setColorAt(0.18, round_colors.highlight)
            gradient.setColorAt(0.55, round_colors.fill)
            gradient.setColorAt(1, round_colors.bottom)
            painter.fillPath(shape, QBrush(gradient))
            return

        super().paintEvent(event)
        if color is None:
            return

        colors = colorful_header_colors(color, tokens)
        painter = QPainter(self)
        painter.fillRect(self.rect(), colors.fill)
        border_pen = QPen(colors.separator)
        border_pen.setWidthF(1.0)
        painter.setPen(border_pen)
        painter.drawLine(self.rect().topLeft(), self.rect().topRight())
        painter.drawLine(self.rect().bottomLeft(), self.rect().bottomRight())

    def _artwork_changed(self, artwork_id: int) -> None:
        if artwork_id == self._artwork_id:
            self.update()

    def _presentation_changed(self, _value: object) -> None:
        self.update()

    def _title_bar_style_changed(self, value: str) -> None:
        self._search.setProperty(
            "roundTitleBar", value == TrackTitleBarStyle.ROUND.value
        )
        style = self._search.style()
        style.unpolish(self._search)
        style.polish(self._search)
        self._search.update()
        self.update()

    def _refresh_title(self) -> None:
        self._title.setText(self._context_title or self.tr("All Tracks"))


class LibrarySplitter(QSplitter):
    """Vertical Library splitter whose visible handle is the Track header."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(Qt.Orientation.Vertical, parent)
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self.setObjectName("librarySplitter")
        self.setHandleWidth(LAYOUT.track_list_handle_height)
        self.setChildrenCollapsible(False)

    @property
    def track_header(self) -> TrackListHeader:
        handle = self.handle(1)
        if not isinstance(handle, TrackListHeader):
            raise RuntimeError("Library splitter did not create its Track header")
        return handle

    def restoreState(
        self,
        state: QByteArray | bytes | bytearray | memoryview,
    ) -> bool:
        """Restore user sizes without restoring obsolete visual metrics."""

        restored = super().restoreState(state)
        self.setHandleWidth(LAYOUT.track_list_handle_height)
        return restored

    def createHandle(self) -> QSplitterHandle:
        return TrackListHeader(
            self.orientation(),
            self,
            self._theme_manager,
            self._artwork_provider,
        )
