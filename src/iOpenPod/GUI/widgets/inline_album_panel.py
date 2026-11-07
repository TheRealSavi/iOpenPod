# Hallmark · component: inline Album details · theme: iOpenPod / artwork
# pre-emit critique: P5 H4 E4 S5 R5 V4 · contrast: pass
"""Artwork-colored, compact Album contents revealed inside the Album grid."""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QPointF,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QToolButton,
    QWidget,
)

from iOpenPod.app.models.album_list_model import AlbumSummary
from iOpenPod.app.models.track_columns import TrackColumn, track_column_display_value
from iOpenPod.app.models.track_order import album_track_sort_key
from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.dynamic import colorful_card_fill
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.presentation.track_drag import TrackDragController
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iPodDB.library import Track

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.library_workspace import LibraryWorkspace
    from iOpenPod.app.models.collection_list_model import CollectionSummary
    from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager

_ROOT = QModelIndex()
_POINTER_HEIGHT = 12
_COVER_SIZE = 240
_COMPACT_COVER_SIZE = 64
_MAX_VISIBLE_ROWS = 14
_MIN_TRACK_COLUMN_WIDTH = 330


class _AlbumTracksModel(QAbstractTableModel):
    """Arrange immutable Tracks down each visual column without duplicating them."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.tracks: tuple[Track, ...] = ()
        self.columns = 1
        self.show_rating = True
        self.accessible_text: Callable[[Track], str] | None = None

    def set_tracks(self, tracks: tuple[Track, ...], columns: int) -> None:
        if tracks == self.tracks and columns == self.columns:
            return
        self.beginResetModel()
        self.tracks = tracks
        self.columns = columns
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else ceil(len(self.tracks) / self.columns)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else self.columns

    def track_at(self, index: QModelIndex | QPersistentModelIndex) -> Track | None:
        position = index.column() * self.rowCount() + index.row()
        if index.isValid() and 0 <= position < len(self.tracks):
            return self.tracks[position]
        return None

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        track = self.track_at(index)
        if track is None:
            return None
        if role == TrackRole.TRACK:
            return track
        if role == TrackRole.TRACK_ID:
            return track.track_id
        if role == Qt.ItemDataRole.DisplayRole:
            return track_column_display_value(track, TrackColumn.TITLE)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            if self.accessible_text is not None:
                return self.accessible_text(track)
            return ", ".join(
                track_column_display_value(track, column)
                for column in (
                    TrackColumn.NUMBER,
                    TrackColumn.TITLE,
                    *((TrackColumn.RATING,) if self.show_rating else ()),
                    TrackColumn.TIME,
                )
            )
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        if self.track_at(index) is None:
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
        )


class _AlbumTracksView(QTableView):
    """Drag selected track cells in Album order through the shared interface."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._drag_controller = TrackDragController(
            self, theme_manager, artwork_provider
        )

    def set_library_workspace(self, workspace: LibraryWorkspace) -> None:
        self._drag_controller.set_library_workspace(workspace)

    def selected_tracks(self) -> tuple[Track, ...]:
        return tuple(
            track
            for index in sorted(
                self.selectionModel().selectedIndexes(),
                key=lambda index: (index.column(), index.row()),
            )
            if isinstance(track := index.data(TrackRole.TRACK), Track)
        )

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        self._drag_controller.start(self.selected_tracks())


class _TrackDelegate(QStyledItemDelegate):
    def __init__(self, panel: InlineAlbumPanel) -> None:
        super().__init__(panel)
        self._panel = panel

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return QSize(_MIN_TRACK_COLUMN_WIDTH, self._panel.row_height)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        track = index.data(TrackRole.TRACK)
        if not isinstance(track, Track):
            return
        painter.save()
        rect = option.rect.adjusted(0, 0, -LAYOUT.space_sm, 0)
        ink = self._panel.ink
        if option.state & (
            QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver
        ):
            highlight = QColor(ink)
            highlight.setAlpha(
                42 if option.state & QStyle.StateFlag.State_Selected else 20
            )
            painter.fillRect(rect, highlight)
        painter.setFont(option.font)
        painter.setPen(ink)
        metrics = option.fontMetrics
        gap = LAYOUT.space_xs
        number_width = metrics.horizontalAdvance("000") + gap
        time = track_column_display_value(track, TrackColumn.TIME)
        time_width = max(
            metrics.horizontalAdvance("00:00"), metrics.horizontalAdvance(time)
        )
        stars = "★" * min(5, max(0, round(track.rating / 20)))
        rating_width = (
            metrics.horizontalAdvance("★★★★★") + gap if not self._panel.stacked else 0
        )
        number = str(track.track_number) if track.track_number else ""
        number_rect = QRect(rect.left(), rect.top(), number_width, rect.height())
        time_rect = QRect(
            rect.right() - time_width, rect.top(), time_width, rect.height()
        )
        rating_rect = QRect(
            time_rect.left() - gap - rating_width,
            rect.top(),
            rating_width,
            rect.height(),
        )
        title_rect = QRect(
            number_rect.right() + gap,
            rect.top(),
            max(0, rating_rect.left() - number_rect.right() - 2 * gap),
            rect.height(),
        )
        align = Qt.AlignmentFlag.AlignVCenter
        painter.drawText(number_rect, align | Qt.AlignmentFlag.AlignRight, number)
        title_font = QFont(option.font)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.drawText(
            title_rect,
            align | Qt.AlignmentFlag.AlignLeft,
            QFontMetrics(title_font).elidedText(
                track_column_display_value(track, TrackColumn.TITLE),
                Qt.TextElideMode.ElideRight,
                title_rect.width(),
            ),
        )
        painter.setFont(option.font)
        if not self._panel.stacked:
            painter.drawText(rating_rect, align | Qt.AlignmentFlag.AlignRight, stars)
        painter.drawText(time_rect, align | Qt.AlignmentFlag.AlignRight, time)
        if option.state & QStyle.StateFlag.State_HasFocus:
            pen = QPen(ink)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
        painter.restore()


class InlineAlbumPanel(QWidget):
    """One Album's context, virtualized Tracks, and cover inside an expanding gap."""

    closeRequested = Signal()
    currentTrackChanged = Signal(object)
    trackActivated = Signal(object)
    selectionChanged = Signal(object)
    contextMenuRequested = Signal(QPoint)
    preferredHeightChanged = Signal()
    playRequested = Signal(object)
    playNextRequested = Signal(object)
    queueRequested = Signal(object)

    def __init__(
        self,
        proxy: TrackFilterProxyModel,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
        *,
        stacked: bool = False,
        show_album_artist: bool = False,
    ) -> None:
        super().__init__(parent)
        self.stacked = stacked
        self._show_album_artist = show_album_artist
        self.setObjectName("inlineAlbumPanel")
        self._proxy = proxy
        self._theme_manager = theme_manager
        self._provider = artwork_provider
        self._summary: AlbumSummary | CollectionSummary | None = None
        self._pointer_x = 0
        self._fill = QColor(theme_manager.tokens.surface_alt)
        self.ink = QColor(theme_manager.tokens.text)
        self._title = QLabel(self)
        self._artist = QLabel(self)
        self._year = QLabel(self) if stacked else None
        if self._year is not None:
            self._year.setObjectName("albumSectionYear")
            self._year.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
        self._title.setObjectName(
            "albumSectionTitle" if stacked else "inlineAlbumTitle"
        )
        for label in (self._title, self._artist):
            label.setTextFormat(Qt.TextFormat.PlainText)
        self._close = QToolButton(self)
        self._close.setObjectName("inlineAlbumClose")
        self._close.setText("\u00d7")
        self._close.clicked.connect(self.closeRequested.emit)
        self._play = self._album_action_button("inlineAlbumPlay")
        self._play_next = self._album_action_button("inlineAlbumPlayNext")
        self._queue = self._album_action_button("inlineAlbumQueue")
        self._play.clicked.connect(self._play_album)
        self._play_next.clicked.connect(self._play_album_next)
        self._queue.clicked.connect(self._queue_album)
        self._cover = ArtworkView(theme_manager, artwork_provider, self)
        self._model = _AlbumTracksModel(self)
        self._model.show_rating = not stacked
        self._tracks = _AlbumTracksView(theme_manager, artwork_provider, self)
        self._tracks.setObjectName("inlineAlbumTracks")
        self._tracks.setModel(self._model)
        self._tracks.setItemDelegate(_TrackDelegate(self))
        self._tracks.setFrameShape(QFrame.Shape.NoFrame)
        self._tracks.setShowGrid(False)
        self._tracks.setMouseTracking(True)
        self._tracks.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tracks.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectItems
        )
        self._tracks.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tracks.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._tracks.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tracks.horizontalHeader().hide()
        self._tracks.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._tracks.verticalHeader().hide()
        self._tracks.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self._tracks.activated.connect(self._activate)
        self._tracks.selectionModel().currentChanged.connect(self._current_changed)
        self._tracks.selectionModel().selectionChanged.connect(self._selection_changed)
        self._tracks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tracks.customContextMenuRequested.connect(self._context_menu_requested)
        self._tracks.installEventFilter(self)
        self._close.installEventFilter(self)
        for button in (self._play, self._play_next, self._queue):
            button.installEventFilter(self)
        for signal in (
            ()
            if stacked
            else (
                proxy.modelReset,
                proxy.rowsInserted,
                proxy.rowsRemoved,
                proxy.dataChanged,
                proxy.layoutChanged,
            )
        ):
            signal.connect(self._refresh_tracks)
        for widget in (
            self._artist,
            self._close,
            self._play,
            self._play_next,
            self._queue,
        ):
            widget.setVisible(
                not stacked or (widget is self._artist and show_album_artist)
            )
        theme_manager.effectiveThemeChanged.connect(self._refresh_colors)
        artwork_provider.artworkChanged.connect(self._artwork_changed)
        artwork_provider.cleared.connect(self._refresh_colors)
        self.retranslate_ui()
        self._refresh_colors()

    @property
    def track_view(self) -> QTableView:
        """Expose the item view for the existing Library Track actions."""
        return self._tracks

    @property
    def row_height(self) -> int:
        return max(28, self._tracks.fontMetrics().height() + LAYOUT.space_xs)

    def set_context(
        self,
        summary: AlbumSummary | CollectionSummary,
        tracks: tuple[Track, ...] | None = None,
    ) -> None:
        self._summary = summary
        self._cover.set_seed(summary.artwork_seed)
        self._cover.set_artwork_id(self.artwork_id)
        if tracks is None:
            self._refresh_tracks()
        elif self.stacked:
            self._replace_tracks(tracks, 2)
        else:
            self._set_context_tracks(tracks)
        self._refresh_colors()
        self._arrange()

    @property
    def artwork_id(self) -> int:
        """Artwork driving the cover and colors of the current contents."""
        if isinstance(self._summary, AlbumSummary):
            return self._summary.artwork_id
        if self._summary is not None:
            return self._summary.representative_artwork_id
        return 0

    def _context_title(self) -> str:
        return (
            self._summary.title if self._summary is not None else ""
        ) or QCoreApplication.translate("LibraryLabels", "Unknown Album")

    def _context_subtitle(self) -> str:
        if not isinstance(self._summary, AlbumSummary):
            return ""
        artist = self._summary.artist or QCoreApplication.translate(
            "LibraryLabels", "Unknown Artist"
        )
        return f"{artist} ({self._summary.year})" if self._summary.year else artist

    def set_pointer_x(self, x: int) -> None:
        if x == self._pointer_x:
            return
        self._pointer_x = x
        self.update()

    def preferred_height(self, width: int) -> int:
        if self.stacked:
            return self.section_height(len(self._model.tracks))
        _, columns, cover_size, compact = self._dimensions(width)
        rows = min(_MAX_VISIBLE_ROWS, ceil(len(self._model.tracks) / columns))
        body_height = max(self.row_height, rows * self.row_height)
        if not compact:
            body_height = max(body_height, cover_size)
        return self._body_top(compact) + body_height + LAYOUT.space_lg

    def section_height(self, track_count: int) -> int:
        return 2 * LAYOUT.space_lg + max(
            _COMPACT_COVER_SIZE
            if self._show_album_artist
            else LAYOUT.album_artwork_size,
            self._title.fontMetrics().height()
            + LAYOUT.space_sm
            + max(1, ceil(track_count / 2)) * self.row_height,
        )

    def selected_tracks(self) -> tuple[Track, ...]:
        return self._tracks.selected_tracks()

    def set_library_workspace(self, workspace: LibraryWorkspace) -> None:
        self._tracks.set_library_workspace(workspace)

    def retranslate_ui(self) -> None:
        self._close.setAccessibleName(self.tr("Close album"))
        self._close.setToolTip(self.tr("Close album"))
        self._tracks.setAccessibleName(self.tr("Album tracks"))
        for button, label in (
            (self._play, self.tr("Play album now")),
            (self._play_next, self.tr("Add album to top of queue")),
            (self._queue, self.tr("Add album to bottom of queue")),
        ):
            button.setAccessibleName(label)
            button.setToolTip(label)
        self._arrange()
        self._tracks.viewport().update()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        elif event.type() in (
            QEvent.Type.FontChange,
            QEvent.Type.ApplicationFontChange,
        ):
            self._arrange()
            self.preferredHeightChanged.emit()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._arrange()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self.closeRequested.emit()
            return True
        if (
            watched is self._tracks
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            index = self._tracks.currentIndex()
            if index.isValid():
                self._tracks.doubleClicked.emit(index)
                self._activate(index)
            return True
        return super().eventFilter(watched, event)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        if self.stacked:
            painter.fillRect(self.rect(), self._fill)
            painter.setPen(QColor(self._theme_manager.tokens.border))
            painter.drawLine(
                LAYOUT.space_lg,
                self.height() - 1,
                self.width() - LAYOUT.space_lg,
                self.height() - 1,
            )
            return
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(
            QRect(0, _POINTER_HEIGHT, self.width(), self.height()), self._fill
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._fill)
        x = max(_POINTER_HEIGHT, min(self.width() - _POINTER_HEIGHT, self._pointer_x))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(x - _POINTER_HEIGHT, _POINTER_HEIGHT),
                    QPointF(x, 0),
                    QPointF(x + _POINTER_HEIGHT, _POINTER_HEIGHT),
                ]
            )
        )

    def _dimensions(self, width: int) -> tuple[int, int, int, bool]:
        compact = width < 680
        cover_size = _COMPACT_COVER_SIZE if compact else min(_COVER_SIZE, width // 4)
        track_width = max(
            1,
            width
            - 2 * LAYOUT.space_lg
            - (0 if compact else cover_size + LAYOUT.space_lg),
        )
        columns = 2 if track_width >= 2 * _MIN_TRACK_COLUMN_WIDTH else 1
        return track_width, columns, cover_size, compact

    def _body_top(self, compact: bool) -> int:
        return (
            _POINTER_HEIGHT
            + LAYOUT.space_lg
            + max(
                _COMPACT_COVER_SIZE,
                self._title.fontMetrics().height()
                + LAYOUT.space_2xs
                + self._artist.fontMetrics().height(),
            )
            + (LAYOUT.control_height_compact + LAYOUT.space_xs if compact else 0)
        )

    def _arrange(self) -> None:
        if not hasattr(self, "_tracks"):
            return
        if self.stacked:
            self._arrange_section()
            return
        width, columns, cover_size, compact = self._dimensions(self.width())
        self._replace_tracks(self._model.tracks, columns)
        top = _POINTER_HEIGHT + LAYOUT.space_md
        body_top = self._body_top(compact)
        self._close.setGeometry(LAYOUT.space_xs, top, 28, 28)
        buttons = (self._play, self._play_next, self._queue)
        button_size = LAYOUT.control_height_compact
        actions_width = (
            len(buttons) * button_size + (len(buttons) - 1) * LAYOUT.space_2xs
        )
        actions_left = self.width() - LAYOUT.space_lg - actions_width
        for position, button in enumerate(buttons):
            button.setGeometry(
                actions_left + position * (button_size + LAYOUT.space_2xs),
                top,
                button_size,
                button_size,
            )
        title_x = LAYOUT.space_2xl
        title_width = max(1, actions_left - LAYOUT.space_md - title_x)
        title_height = self._title.fontMetrics().height()
        self._title.setGeometry(title_x, top, title_width, title_height)
        self._artist.setGeometry(
            title_x,
            top + title_height + LAYOUT.space_2xs,
            title_width,
            self._artist.fontMetrics().height(),
        )
        if self._summary is not None:
            title = self._context_title()
            artist = self._context_subtitle()
            for label, text in ((self._title, title), (self._artist, artist)):
                label.setText(
                    label.fontMetrics().elidedText(
                        text, Qt.TextElideMode.ElideRight, label.width()
                    )
                )
                label.setAccessibleName(text)
        self._cover.setGeometry(
            self.width() - LAYOUT.space_lg - cover_size,
            top + button_size + LAYOUT.space_xs if compact else body_top,
            cover_size,
            cover_size,
        )
        self._tracks.verticalHeader().setDefaultSectionSize(self.row_height)
        self._tracks.setGeometry(
            LAYOUT.space_lg,
            body_top,
            width,
            max(
                self.row_height,
                self.preferred_height(self.width()) - body_top - LAYOUT.space_lg,
            ),
        )

    def _arrange_section(self) -> None:
        assert self._year is not None
        margin = LAYOUT.space_lg
        cover = (
            _COMPACT_COVER_SIZE
            if self._show_album_artist
            else min(LAYOUT.album_artwork_size, max(64, self.width() // 5))
        )
        width = max(1, self.width() - 3 * margin - cover)
        content_left = 2 * margin + cover
        title_height = self._title.fontMetrics().height()
        year_width = (
            self._year.fontMetrics().horizontalAdvance("0000") + LAYOUT.space_md
        )
        self._title.setGeometry(
            content_left, margin, max(1, width - year_width), title_height
        )
        self._year.setGeometry(
            content_left + width - year_width, margin, year_width, title_height
        )
        if isinstance(self._summary, AlbumSummary):
            title = self._summary.title or QCoreApplication.translate(
                "LibraryLabels", "Unknown Album"
            )
            if self._show_album_artist:
                artist = self._summary.artist or QCoreApplication.translate(
                    "LibraryLabels", "Unknown Artist"
                )
                byline = self.tr("by %1").replace("%1", artist)
                available = max(1, width - year_width)
                title_width = min(
                    self._title.fontMetrics().horizontalAdvance(title)
                    + LAYOUT.space_xs,
                    available * 2 // 3,
                )
                self._title.resize(title_width, title_height)
                self._artist.setGeometry(
                    content_left + title_width,
                    margin,
                    max(1, available - title_width),
                    title_height,
                )
                self._artist.setText(
                    self._artist.fontMetrics().elidedText(
                        byline, Qt.TextElideMode.ElideRight, self._artist.width()
                    )
                )
                self._artist.setAccessibleName(byline)
            self._title.setText(
                self._title.fontMetrics().elidedText(
                    title, Qt.TextElideMode.ElideRight, self._title.width()
                )
            )
            self._title.setAccessibleName(title)
            self._year.setText(str(self._summary.year) if self._summary.year else "")
        self._cover.setGeometry(margin, margin, cover, cover)
        self._tracks.verticalHeader().setDefaultSectionSize(self.row_height)
        self._tracks.setGeometry(
            content_left,
            margin + title_height + LAYOUT.space_sm,
            width,
            max(1, self._model.rowCount()) * self.row_height,
        )

    def _refresh_tracks(self, *_args: object) -> None:
        if self._summary is None:
            return
        track_ids = set(self._summary.track_ids)
        tracks = tuple(
            track
            for row in range(self._proxy.rowCount())
            if (track := self._proxy.track_at(self._proxy.index(row, 0))) is not None
            and (
                track.album_key == self._summary.key
                if isinstance(self._summary, AlbumSummary)
                else track.track_id in track_ids
            )
        )
        self._set_context_tracks(tracks)
        self._arrange()
        self.preferredHeightChanged.emit()

    def _set_context_tracks(self, tracks: tuple[Track, ...]) -> None:
        self._replace_tracks(
            tuple(sorted(tracks, key=album_track_sort_key)),
            self._dimensions(self.width())[1],
        )

    def _replace_tracks(self, tracks: tuple[Track, ...], columns: int) -> None:
        if tracks == self._model.tracks and columns == self._model.columns:
            return
        selected_ids = {track.track_id for track in self.selected_tracks()}
        current_id = self._tracks.currentIndex().data(TrackRole.TRACK_ID)
        selection = self._tracks.selectionModel()
        was_blocked = selection.blockSignals(True)
        try:
            self._model.set_tracks(tracks, columns)
            for button in (self._play, self._play_next, self._queue):
                button.setEnabled(bool(tracks))
            for column in range(columns):
                for row in range(self._model.rowCount()):
                    index = self._model.index(row, column)
                    track_id = index.data(TrackRole.TRACK_ID)
                    if track_id in selected_ids:
                        selection.select(
                            index, QItemSelectionModel.SelectionFlag.Select
                        )
                    if track_id == current_id and current_id is not None:
                        selection.setCurrentIndex(
                            index, QItemSelectionModel.SelectionFlag.NoUpdate
                        )
        finally:
            selection.blockSignals(was_blocked)
        self.selectionChanged.emit(self.selected_tracks())

    def _refresh_colors(self, *_args: object) -> None:
        tokens = self._theme_manager.tokens
        color = (
            None
            if self._summary is None
            else self._provider.dominant_color(
                self.artwork_id, _COVER_SIZE, self.devicePixelRatioF()
            )
        )
        self._fill = (
            QColor(tokens.surface if self.stacked else tokens.surface_alt)
            if color is None or self.stacked
            else colorful_card_fill(color, tokens, emphasized=True)
        )
        self.ink = QColor(tokens.text)
        ink = self.ink.name()
        typography = self._theme_manager.typography
        self._title.setStyleSheet(
            f"color: {ink}; background: transparent; font-size: {typography.album_card_title_pt:g}pt; font-weight: 700;"
        )
        self._artist.setStyleSheet(
            f"color: {tokens.text_secondary if self.stacked else ink}; background: transparent; font-size: {typography.album_card_detail_pt:g}pt; font-weight: 400;"
        )
        if self._year is not None:
            self._year.setStyleSheet(
                f"color: {tokens.text_secondary}; background: transparent; font-size: {typography.album_card_detail_pt:g}pt;"
            )
        self._tracks.setStyleSheet(
            f"QTableView {{ color: {ink}; background: transparent; border: none; font-size: {typography.body_pt:g}pt; font-weight: 400; }} QTableView::item {{ background: transparent; }}"
        )
        self._close.setStyleSheet(
            f"QToolButton {{ color: {ink}; background: transparent; border: 1px solid transparent; border-radius: 14px; font-size: {typography.title_pt:g}pt; }} QToolButton:hover, QToolButton:pressed {{ border-color: {ink}; }} QToolButton:focus {{ border-color: {ink}; border-style: dashed; }}"
        )
        for button, glyph in (
            (self._play, "play"),
            (self._play_next, "play-next"),
            (self._queue, "play-last"),
        ):
            button.setIcon(
                glyph_icon(glyph, LAYOUT.icon_size, self.ink, self.devicePixelRatioF())
            )
            rgb = f"{self.ink.red()}, {self.ink.green()}, {self.ink.blue()}"
            button.setStyleSheet(
                f"QToolButton {{ background: transparent; border: none; border-radius: {LAYOUT.radius_control}px; padding: 0; }}"
                f"QToolButton:hover, QToolButton:focus {{ background: rgba({rgb}, 26); }}"
                f"QToolButton:pressed {{ background: rgba({rgb}, 48); }}"
            )
        self._arrange()
        self._tracks.viewport().update()
        self.update()

    def _artwork_changed(self, artwork_id: int) -> None:
        if self._summary is not None and artwork_id == self.artwork_id:
            self._refresh_colors()

    def _album_action_button(self, name: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName(name)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIconSize(QSize(LAYOUT.icon_size, LAYOUT.icon_size))
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setEnabled(False)
        return button

    def _play_album(self) -> None:
        if self._model.tracks:
            self.playRequested.emit(self._model.tracks)

    def _play_album_next(self) -> None:
        if self._model.tracks:
            self.playNextRequested.emit(self._model.tracks)

    def _queue_album(self) -> None:
        if self._model.tracks:
            self.queueRequested.emit(self._model.tracks)

    def _context_menu_requested(self, point: QPoint) -> None:
        self.contextMenuRequested.emit(self._tracks.viewport().mapToGlobal(point))

    def _current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        track = self._model.track_at(current)
        if track is not None:
            self.currentTrackChanged.emit(track)

    def _selection_changed(self, *_args: object) -> None:
        self.selectionChanged.emit(self.selected_tracks())

    def _activate(self, index: QModelIndex) -> None:
        track = self._model.track_at(index)
        if track is not None:
            self.trackActivated.emit(track)
