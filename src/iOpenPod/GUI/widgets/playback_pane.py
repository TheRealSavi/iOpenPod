"""Runtime Playback Queue, Playback History, and current Track lyrics."""

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QContextMenuEvent,
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QHideEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QPlainTextEdit,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.lyrics_controller import LyricsController, LyricsState
from iOpenPod.app.models.artwork_seed import stable_artwork_seed
from iOpenPod.app.models.library_drag import PLAYLIST_MIME_TYPE, TRACK_MIME_TYPE
from iOpenPod.app.models.playback_models import (
    QUEUE_ENTRY_MIME_TYPE,
    PlaybackQueueModel,
    PlaybackRole,
)
from iOpenPod.app.playback_controller import PlaybackController
from iOpenPod.GUI.presentation.artwork import (
    paint_artwork_pixmap,
    paint_artwork_placeholder,
)
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.presentation.track_drag_preview import (
    drag_preview_hot_spot,
    render_single_track_drag_preview,
)
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind
from iPodDB.library import Track

_REMOVE_KEYS = {
    Qt.Key.Key_Backspace,
    Qt.Key.Key_Delete,
    Qt.Key.Key_Enter,
    Qt.Key.Key_Return,
    Qt.Key.Key_Space,
}


class _PlaybackListDelegate(QStyledItemDelegate):
    """Paint compact Track rows without allocating child widgets per entry."""

    def __init__(
        self,
        *,
        queue: bool,
        parent: QWidget,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
    ) -> None:
        super().__init__(parent)
        self._queue = queue
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        styled.text = ""
        widget = option.widget
        style = widget.style()
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, styled, painter, widget
        )

        painter.save()
        artwork_rect = _artwork_rect(option.rect)
        self._paint_artwork(painter, option, index, artwork_rect)
        content_left = round(artwork_rect.right()) + LAYOUT.space_sm
        content = option.rect.adjusted(
            content_left - option.rect.left(),
            LAYOUT.space_2xs,
            -(LAYOUT.minimum_touch_target + LAYOUT.space_sm)
            if self._queue
            else -LAYOUT.space_sm,
            -LAYOUT.space_2xs,
        )
        self._paint_track_metadata(painter, option, index, content)

        if bool(index.data(PlaybackRole.IS_CURRENT)):
            painter.fillRect(
                QRect(option.rect.left(), option.rect.top(), 3, option.rect.height()),
                option.palette.color(option.palette.ColorRole.Accent),
            )

        if self._queue:
            self._paint_remove_action(painter, option)
        painter.restore()

    def _paint_track_metadata(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        content: QRect,
    ) -> None:
        title_font = QFont(option.font)
        title_font.setWeight(QFont.Weight.DemiBold)
        detail_font = QFont(option.font)
        detail_font.setPointSizeF(max(1.0, detail_font.pointSizeF() - 1.0))
        title_height = QFontMetrics(title_font).height()
        detail_height = QFontMetrics(detail_font).height()
        stack_height = title_height + (detail_height * 2)
        line_top = content.center().y() - (stack_height // 2)
        lines = (
            (
                str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
                title_font,
                title_height,
                option.palette.ColorRole.Text,
            ),
            (
                str(index.data(PlaybackRole.ARTIST) or ""),
                detail_font,
                detail_height,
                option.palette.ColorRole.PlaceholderText,
            ),
            (
                str(index.data(PlaybackRole.ALBUM) or ""),
                detail_font,
                detail_height,
                option.palette.ColorRole.PlaceholderText,
            ),
        )
        for text, font, line_height, color_role in lines:
            painter.setFont(font)
            painter.setPen(option.palette.color(color_role))
            metrics = painter.fontMetrics()
            painter.drawText(
                QRect(content.left(), line_top, content.width(), line_height),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                metrics.elidedText(
                    text,
                    Qt.TextElideMode.ElideRight,
                    content.width(),
                ),
            )
            line_top += line_height

    def _paint_remove_action(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
    ) -> None:
        action_rect = _remove_action_visual_rect(option.rect)
        palette = option.palette
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(
            palette.color(
                palette.ColorRole.Midlight if hovered else palette.ColorRole.Button
            )
        )
        painter.setPen(QPen(palette.color(palette.ColorRole.Mid), 1))
        painter.drawRoundedRect(
            QRectF(action_rect),
            float(LAYOUT.radius_control),
            float(LAYOUT.radius_control),
        )
        minus_pen = QPen(palette.color(palette.ColorRole.ButtonText), 2)
        minus_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(minus_pen)
        center = action_rect.center()
        half_width = LAYOUT.space_2xs
        painter.drawLine(
            QPoint(center.x() - half_width, center.y()),
            QPoint(center.x() + half_width, center.y()),
        )

    def _paint_artwork(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        rect: QRectF,
    ) -> None:
        track = index.data(PlaybackRole.TRACK)
        if not isinstance(track, Track):
            return
        tokens = self._theme_manager.tokens
        pixmap = self._artwork_provider.pixmap(
            track.artwork_id,
            LAYOUT.playback_row_artwork_size,
            option.widget.devicePixelRatioF(),
        )
        if pixmap is None:
            paint_artwork_placeholder(
                painter,
                rect,
                stable_artwork_seed(track.album_key),
                tokens,
                float(LAYOUT.radius_control),
            )
            return
        paint_artwork_pixmap(
            painter,
            rect,
            pixmap,
            tokens,
            float(LAYOUT.radius_control),
        )

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        del option, index
        return QSize(0, LAYOUT.playback_row_height)


class _PlaybackListView(QListView):
    """Share artwork-aware presentation behavior across playback lists."""

    def __init__(
        self,
        *,
        queue: bool,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.setItemDelegate(
            _PlaybackListDelegate(
                queue=queue,
                parent=self,
                theme_manager=theme_manager,
                artwork_provider=artwork_provider,
            )
        )
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setUniformItemSizes(True)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        theme_manager.effectiveThemeChanged.connect(self._update_viewport)
        artwork_provider.artworkChanged.connect(self._artwork_changed)
        artwork_provider.cleared.connect(self._update_viewport)

    def _artwork_changed(self, artwork_id: int) -> None:
        model = self.model()
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            track = index.data(PlaybackRole.TRACK)
            if isinstance(track, Track) and track.artwork_id == artwork_id:
                self.viewport().update(self.visualRect(index))

    def _update_viewport(self, *_args: object) -> None:
        self.viewport().update()


class _QueueListView(_PlaybackListView):
    """Add Queue row actions and direct keyboard reordering."""

    def __init__(
        self,
        controller: PlaybackController,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget,
    ) -> None:
        super().__init__(
            queue=True,
            theme_manager=theme_manager,
            artwork_provider=artwork_provider,
            parent=parent,
        )
        self._controller = controller
        self.setObjectName("playbackQueueView")
        self.setAccessibleName(self.tr("Playback Queue"))
        self.setModel(controller.queue_model)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _is_external_library_drag(event):
            event.setDropAction(Qt.DropAction.CopyAction)
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if _is_external_library_drag(event):
            event.setDropAction(Qt.DropAction.CopyAction)
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if _is_external_library_drag(event):
            event.setDropAction(Qt.DropAction.CopyAction)
        super().dropEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        index = self.currentIndex()
        if index.isValid() and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            if event.key() == Qt.Key.Key_Up:
                self._move_current(index.row() - 1)
                event.accept()
                return
            if event.key() == Qt.Key.Key_Down:
                self._move_current(index.row() + 1)
                event.accept()
                return
        if index.isValid() and event.key() in _REMOVE_KEYS:
            entry_id = index.data(PlaybackRole.ENTRY_ID)
            if isinstance(entry_id, int):
                self._controller.remove_queue_entry(entry_id)
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.position().toPoint())
        if (
            event.button() is Qt.MouseButton.LeftButton
            and index.isValid()
            and _remove_action_rect(self.visualRect(index)).contains(
                event.position().toPoint()
            )
        ):
            entry_id = index.data(PlaybackRole.ENTRY_ID)
            if isinstance(entry_id, int):
                self._controller.remove_queue_entry(entry_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _move_current(self, destination_row: int) -> None:
        current_row = self.currentIndex().row()
        if not self._controller.move_queue_entry(current_row, destination_row):
            return
        self.setCurrentIndex(self.model().index(destination_row, 0))


class _HistoryListView(_PlaybackListView):
    """Expose History entries through the shared Track menu and copy drag."""

    trackContextMenuRequested = Signal(object, QPoint)

    def __init__(
        self,
        controller: PlaybackController,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget,
    ) -> None:
        super().__init__(
            queue=False,
            theme_manager=theme_manager,
            artwork_provider=artwork_provider,
            parent=parent,
        )
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self.setObjectName("playbackHistoryView")
        self.setAccessibleName(self.tr("Playback History"))
        self.setModel(controller.history_model)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        keyboard = event.reason() is QContextMenuEvent.Reason.Keyboard
        index = self.currentIndex() if keyboard else self.indexAt(event.pos())
        track = index.data(PlaybackRole.TRACK)
        if not isinstance(track, Track):
            event.ignore()
            return
        self.setCurrentIndex(index)
        position = (
            self.viewport().mapToGlobal(self.visualRect(index).center())
            if keyboard
            else event.globalPos()
        )
        self.trackContextMenuRequested.emit(track, position)
        event.accept()

    def startDrag(self, supported_actions: Qt.DropAction) -> None:
        if not supported_actions & Qt.DropAction.CopyAction:
            return
        indexes = self.selectedIndexes()
        if not indexes:
            return
        track = indexes[0].data(PlaybackRole.TRACK)
        data = self.model().mimeData(indexes)
        if not isinstance(track, Track) or not data.hasFormat(TRACK_MIME_TYPE):
            return
        pixmap = render_single_track_drag_preview(
            track,
            title=track.title or self.tr("Untitled Track"),
            artist=track.artist or self.tr("Unknown Artist"),
            album=track.album or self.tr("Unknown Album"),
            base_font=self.font(),
            tokens=self._theme_manager.tokens,
            artwork_provider=self._artwork_provider,
            device_pixel_ratio=self.devicePixelRatioF(),
        )
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.setPixmap(pixmap)
        drag.setHotSpot(drag_preview_hot_spot(pixmap))
        drag.exec(Qt.DropAction.CopyAction)


class PlaybackPane(QFrame):
    """Show Queue, History, and read-only lyrics beside the body."""

    visibilityChanged = Signal(bool)
    trackContextMenuRequested = Signal(object, QPoint)

    def __init__(
        self,
        controller: PlaybackController,
        lyrics_controller: LyricsController,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._lyrics_controller = lyrics_controller
        self.setObjectName("playbackPane")
        self.setFixedWidth(LAYOUT.playback_pane_width)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("playbackTabs")
        self._tabs.setDocumentMode(True)
        self._tabs.setUsesScrollButtons(False)
        self._tabs.tabBar().setExpanding(True)

        queue_tab = QWidget(self._tabs)
        queue_tab.setObjectName("playbackQueueTab")
        queue_layout = QVBoxLayout(queue_tab)
        queue_layout.setContentsMargins(
            LAYOUT.space_md,
            LAYOUT.space_sm,
            LAYOUT.space_md,
            LAYOUT.space_md,
        )
        queue_layout.setSpacing(LAYOUT.space_sm)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(LAYOUT.space_sm)
        self._queue_count = QLabel(queue_tab)
        self._queue_count.setObjectName("playbackQueueCount")
        header.addWidget(self._queue_count)
        header.addStretch(1)
        self._clear_queue = ActionButton(
            self.tr("Clear Queue"),
            queue_tab,
            kind=ActionButtonKind.QUIET,
        )
        self._clear_queue.setObjectName("playbackClearQueue")
        self._clear_queue.clicked.connect(controller.clear_queue)
        header.addWidget(self._clear_queue)
        queue_layout.addLayout(header)

        self._queue_stack = QStackedWidget(queue_tab)
        self._queue_stack.setObjectName("playbackQueueStack")
        (
            self._queue_empty,
            self._queue_empty_title,
            self._queue_empty_detail,
        ) = _empty_state(
            self.tr("Queue is empty"),
            self.tr(
                "Drag Tracks or Playlists here, or double-click a Track, Album, or collection."
            ),
            self._queue_stack,
            drop_model=controller.queue_model,
        )
        self._queue_view = _QueueListView(
            controller,
            theme_manager,
            artwork_provider,
            self._queue_stack,
        )
        self._queue_stack.addWidget(self._queue_empty)
        self._queue_stack.addWidget(self._queue_view)
        queue_layout.addWidget(self._queue_stack, 1)

        history_tab = QWidget(self._tabs)
        history_tab.setObjectName("playbackHistoryTab")
        history_layout = QVBoxLayout(history_tab)
        history_layout.setContentsMargins(
            LAYOUT.space_md,
            LAYOUT.space_sm,
            LAYOUT.space_md,
            LAYOUT.space_md,
        )
        history_layout.setSpacing(LAYOUT.space_sm)
        history_header = QHBoxLayout()
        history_header.setContentsMargins(0, 0, 0, 0)
        history_header.addStretch(1)
        self._clear_history = ActionButton(
            self.tr("Clear History"),
            history_tab,
            kind=ActionButtonKind.QUIET,
        )
        self._clear_history.setObjectName("playbackClearHistory")
        self._clear_history.clicked.connect(controller.clear_history)
        history_header.addWidget(self._clear_history)
        history_layout.addLayout(history_header)
        self._history_stack = QStackedWidget(history_tab)
        self._history_stack.setObjectName("playbackHistoryStack")
        (
            self._history_empty,
            self._history_empty_title,
            self._history_empty_detail,
        ) = _empty_state(
            self.tr("History is empty"),
            self.tr("Started Tracks appear here for this session."),
            self._history_stack,
        )
        self._history_view = _HistoryListView(
            controller,
            theme_manager,
            artwork_provider,
            self._history_stack,
        )
        self._history_view.trackContextMenuRequested.connect(
            self.trackContextMenuRequested.emit
        )
        self._history_stack.addWidget(self._history_empty)
        self._history_stack.addWidget(self._history_view)
        history_layout.addWidget(self._history_stack, 1)

        lyrics_tab = QWidget(self._tabs)
        lyrics_tab.setObjectName("playbackLyricsTab")
        lyrics_layout = QVBoxLayout(lyrics_tab)
        lyrics_layout.setContentsMargins(
            LAYOUT.space_md,
            LAYOUT.space_sm,
            LAYOUT.space_md,
            LAYOUT.space_md,
        )
        self._lyrics_text = QPlainTextEdit(lyrics_tab)
        self._lyrics_text.setObjectName("playbackLyricsText")
        self._lyrics_text.setReadOnly(True)
        lyrics_layout.addWidget(self._lyrics_text)

        self._tabs.addTab(queue_tab, self.tr("Queue"))
        self._tabs.addTab(history_tab, self.tr("History"))
        self._tabs.addTab(lyrics_tab, self.tr("Lyrics"))
        self._tabs.currentChanged.connect(self._lyrics_visibility_changed)
        lyrics_controller.changed.connect(self._refresh_lyrics)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._tabs)

        for model in (controller.queue_model, controller.history_model):
            model.rowsInserted.connect(self._refresh_states)
            model.rowsRemoved.connect(self._refresh_states)
            model.modelReset.connect(self._refresh_states)
        self._refresh_states()
        self.retranslate_ui()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._lyrics_visibility_changed()
        self.visibilityChanged.emit(True)

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self._lyrics_visibility_changed()
        self.visibilityChanged.emit(False)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def retranslate_ui(self) -> None:
        self._tabs.setTabText(0, self.tr("Queue"))
        self._tabs.setTabText(1, self.tr("History"))
        self._tabs.setTabText(2, self.tr("Lyrics"))
        self._lyrics_text.setAccessibleName(self.tr("Lyrics"))
        self._refresh_lyrics()
        self._clear_queue.setText(self.tr("Clear Queue"))
        self._clear_history.setText(self.tr("Clear History"))
        self._queue_view.setAccessibleName(self.tr("Playback Queue"))
        self._history_view.setAccessibleName(self.tr("Playback History"))
        self._queue_empty_title.setText(self.tr("Queue is empty"))
        self._queue_empty_detail.setText(
            self.tr(
                "Drag Tracks or Playlists here, or double-click a Track, Album, or collection."
            )
        )
        self._history_empty_title.setText(self.tr("History is empty"))
        self._history_empty_detail.setText(
            self.tr("Started Tracks appear here for this session.")
        )
        self._refresh_states()

    def _lyrics_visibility_changed(self) -> None:
        self._lyrics_controller.set_active(
            self.isVisible() and self._tabs.currentIndex() == 2
        )

    def _refresh_lyrics(self) -> None:
        controller = self._lyrics_controller
        # Preserve selection and scrolling on language changes or repeated state.
        text = controller.text.replace("\r\n", "\n").replace("\r", "\n")
        if self._lyrics_text.toPlainText() != text:
            self._lyrics_text.setPlainText(text)
        match controller.state:
            case LyricsState.NO_TRACK:
                placeholder = self.tr("Play a track to see its lyrics.")
            case LyricsState.NOT_LOADED | LyricsState.LOADING:
                placeholder = self.tr("Loading lyrics…")
            case LyricsState.UNAVAILABLE:
                placeholder = self.tr("Lyrics could not be loaded for this track.")
            case LyricsState.READY:
                placeholder = self.tr("No lyrics available for this track.")
        self._lyrics_text.setPlaceholderText(placeholder)

    def _refresh_states(self) -> None:
        queue_count = self._controller.queue_model.rowCount()
        history_count = self._controller.history_model.rowCount()
        self._queue_stack.setCurrentWidget(
            self._queue_view if queue_count else self._queue_empty
        )
        self._history_stack.setCurrentWidget(
            self._history_view if history_count else self._history_empty
        )
        self._clear_queue.setEnabled(queue_count > 0)
        self._clear_history.setEnabled(history_count > 0)
        self._queue_count.setText(self.tr("%n pending", None, queue_count))


class PlaybackPaneHost(QFrame):
    """Reserve final body width while sliding the pane inside a clipped slot."""

    def __init__(
        self,
        pane: PlaybackPane,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._pane = pane
        self._target_open = False
        self.setObjectName("playbackPaneHost")
        self.setFixedWidth(LAYOUT.playback_pane_width)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        pane.setParent(self)
        pane.hide()

        self._animation = QPropertyAnimation(pane, b"pos", self)
        self._animation.finished.connect(self._animation_finished)
        self.hide()

    def set_open(self, open_: bool) -> None:
        """Move the pane without changing its reserved layout width per frame."""

        self._target_open = open_
        if open_:
            if self.isHidden():
                self.show()
                self._pane.resize(self.size())
                self._pane.move(self.width(), 0)
                self._pane.show()
            self._animate_to(0, QEasingCurve.Type.OutCubic)
            return
        if self.isHidden():
            return
        self._animate_to(self.width(), QEasingCurve.Type.InCubic)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._pane.resize(event.size())
        self._pane.move(self._pane.x(), 0)

    def _animate_to(
        self,
        target_x: int,
        easing: QEasingCurve.Type,
    ) -> None:
        current = self._pane.pos()
        target = QPoint(target_x, 0)
        self._animation.stop()
        if current == target:
            self._animation_finished()
            return
        distance = abs(target_x - current.x())
        duration = max(
            1,
            round(
                LAYOUT.playback_pane_animation_ms
                * distance
                / LAYOUT.playback_pane_width
            ),
        )
        self._animation.setDuration(duration)
        self._animation.setEasingCurve(easing)
        self._animation.setStartValue(current)
        self._animation.setEndValue(target)
        self._animation.start()

    def _animation_finished(self) -> None:
        if self._target_open:
            self._pane.move(0, 0)
            return
        self._pane.move(self.width(), 0)
        self._pane.hide()
        self.hide()


class _PlaybackEmptyState(QWidget):
    """Optionally keep an empty Queue available as a Library drop target."""

    def __init__(
        self,
        parent: QWidget,
        *,
        drop_model: PlaybackQueueModel | None,
    ) -> None:
        super().__init__(parent)
        self._drop_model = drop_model
        self.setAcceptDrops(drop_model is not None)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._can_drop(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._can_drop(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        model = self._drop_model
        if model is not None and model.dropMimeData(
            event.mimeData(),
            Qt.DropAction.CopyAction,
            -1,
            0,
            QModelIndex(),
        ):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def _can_drop(self, event: QDragEnterEvent | QDragMoveEvent) -> bool:
        model = self._drop_model
        return model is not None and model.canDropMimeData(
            event.mimeData(),
            Qt.DropAction.CopyAction,
            -1,
            0,
            QModelIndex(),
        )


def _empty_state(
    title: str,
    detail: str,
    parent: QWidget,
    *,
    drop_model: PlaybackQueueModel | None = None,
) -> tuple[QWidget, QLabel, QLabel]:
    empty = _PlaybackEmptyState(parent, drop_model=drop_model)
    empty.setProperty("playbackEmpty", True)
    title_label = QLabel(title, empty)
    title_label.setObjectName("playbackEmptyTitle")
    title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    detail_label = QLabel(detail, empty)
    detail_label.setObjectName("playbackEmptyDetail")
    detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    detail_label.setWordWrap(True)
    title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    detail_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    layout = QVBoxLayout(empty)
    layout.setContentsMargins(
        LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
    )
    layout.setSpacing(LAYOUT.space_xs)
    layout.addStretch(1)
    layout.addWidget(title_label)
    layout.addWidget(detail_label)
    layout.addStretch(1)
    return empty, title_label, detail_label


def _is_external_library_drag(
    event: QDragEnterEvent | QDragMoveEvent | QDropEvent,
) -> bool:
    data = event.mimeData()
    return not data.hasFormat(QUEUE_ENTRY_MIME_TYPE) and (
        data.hasFormat(TRACK_MIME_TYPE) or data.hasFormat(PLAYLIST_MIME_TYPE)
    )


def _remove_action_rect(row_rect: QRect) -> QRect:
    return QRect(
        row_rect.right() - LAYOUT.minimum_touch_target - LAYOUT.space_xs + 1,
        row_rect.center().y() - (LAYOUT.minimum_touch_target // 2),
        LAYOUT.minimum_touch_target,
        LAYOUT.minimum_touch_target,
    )


def _remove_action_visual_rect(row_rect: QRect) -> QRect:
    hit_rect = _remove_action_rect(row_rect)
    size = LAYOUT.control_height_compact
    return QRect(
        hit_rect.center().x() - (size // 2),
        hit_rect.center().y() - (size // 2),
        size,
        size,
    )


def _artwork_rect(row_rect: QRect) -> QRectF:
    size = LAYOUT.playback_row_artwork_size
    return QRectF(
        row_rect.left() + LAYOUT.space_xs,
        row_rect.top() + ((row_rect.height() - size) / 2.0),
        size,
        size,
    )


__all__ = ["PlaybackPane", "PlaybackPaneHost"]
