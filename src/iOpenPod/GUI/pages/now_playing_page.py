"""Window-filling playback presentation over the existing runtime controller."""

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    QSignalBlocker,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QResizeEvent,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.models.artwork_seed import stable_artwork_seed
from iOpenPod.app.playback.artwork import artwork_time_at, playback_artwork_times
from iOpenPod.app.playback.chapters import chapter_at, playback_chapters
from iOpenPod.app.playback_controller import PlaybackController
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.elided_label import ElidedLabel
from iOpenPod.GUI.widgets.now_playing_backdrop import NowPlayingBackdrop
from iOpenPod.GUI.widgets.playback_pane import PlaybackQueueView
from iOpenPod.GUI.widgets.seek_slider import SeekSlider, format_playback_time
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    IconButton,
    IconButtonKind,
)
from iPodDB.library import Track, TrackChapter


class NowPlayingPage(QWidget):
    """Compose artwork, transport and the shared pending Playback Queue."""

    closeRequested = Signal()

    def __init__(
        self,
        controller: PlaybackController,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("nowPlayingPage")
        self._controller = controller
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self._track: Track | None = None
        self._chapters: tuple[TrackChapter, ...] = ()
        self._artwork_times: tuple[int, ...] = ()
        self._artwork_key: tuple[int, int | None] = (0, None)
        self._backdrop = NowPlayingBackdrop(theme_manager.tokens, self)
        self._background_cache_key: int | None = None

        self._layout = QVBoxLayout(self)
        # Artwork adapts to available space; its last size must not become a
        # minimum window height when the user shrinks the window.
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_md, LAYOUT.space_lg, LAYOUT.space_lg
        )
        self._layout.setSpacing(LAYOUT.space_sm)
        header = QHBoxLayout()
        self._close = IconButton(
            "x", self.tr("Close Now Playing"), self, kind=IconButtonKind.QUIET
        )
        self._close.setObjectName("nowPlayingClose")
        self._close.setFixedSize(
            LAYOUT.minimum_touch_target, LAYOUT.minimum_touch_target
        )
        self._close.clicked.connect(self.closeRequested.emit)
        header.addWidget(self._close)
        header.addStretch()
        self._layout.addLayout(header)

        self._columns = QHBoxLayout()
        self._columns.setSpacing(LAYOUT.space_xl * 2)
        self._player = QWidget(self)
        self._player.setObjectName("nowPlayingControls")
        self._player.setMinimumWidth(0)
        self._player.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._player.setMaximumWidth(LAYOUT.now_playing_column_maximum_width)
        left = QVBoxLayout(self._player)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(LAYOUT.space_sm)
        self._artwork = ArtworkView(theme_manager, artwork_provider, self._player)
        self._artwork.setObjectName("nowPlayingArtwork")
        self._artwork.setFixedSize(240, 240)
        self._shadow = QGraphicsDropShadowEffect(self._artwork)
        self._artwork.setGraphicsEffect(self._shadow)
        left.addWidget(self._artwork, alignment=Qt.AlignmentFlag.AlignHCenter)
        left.addSpacing(LAYOUT.space_md)

        self._metadata = QWidget(self._player)
        metadata = QVBoxLayout(self._metadata)
        metadata.setContentsMargins(0, 0, 0, 0)
        metadata.setSpacing(LAYOUT.space_3xs)
        self._title = ElidedLabel(1, self._metadata)
        self._title.setObjectName("nowPlayingTitle")
        self._artist = ElidedLabel(1, self._metadata)
        self._artist.setObjectName("nowPlayingArtist")
        self._album = ElidedLabel(1, self._metadata)
        self._album.setObjectName("nowPlayingAlbum")
        for label in (self._title, self._artist, self._album):
            metadata.addWidget(label)
        left.addWidget(self._metadata, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._timeline = QWidget(self._player)
        timeline = QVBoxLayout(self._timeline)
        timeline.setContentsMargins(0, 0, 0, 0)
        timeline.setSpacing(0)
        self._position = SeekSlider(Qt.Orientation.Horizontal, self._timeline)
        self._position.setObjectName("nowPlayingProgress")
        self._position.setSingleStep(1000)
        self._position.setPageStep(10_000)
        timeline.addWidget(self._position)
        times = QHBoxLayout()
        self._elapsed = QLabel(self._timeline)
        self._elapsed.setObjectName("nowPlayingElapsed")
        self._duration = QLabel(self._timeline)
        self._duration.setObjectName("nowPlayingDuration")
        times.addWidget(self._elapsed)
        times.addStretch()
        times.addWidget(self._duration)
        timeline.addLayout(times)
        left.addWidget(self._timeline, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._transport = QWidget(self._player)
        transport = QHBoxLayout(self._transport)
        transport.setContentsMargins(0, 0, 0, 0)
        transport.setSpacing(LAYOUT.space_xl)
        self._previous = IconButton(
            "skip-back",
            self.tr("Previous Track"),
            self._transport,
            kind=IconButtonKind.QUIET,
            glyph_size=LAYOUT.player_skip_icon_size,
        )
        self._previous.setObjectName("nowPlayingPrevious")
        self._play = IconButton(
            "play",
            self.tr("Play"),
            self._transport,
            kind=IconButtonKind.QUIET,
            glyph_size=LAYOUT.now_playing_play_icon_size,
        )
        self._play.setObjectName("nowPlayingPlayPause")
        self._next = IconButton(
            "skip-forward",
            self.tr("Next Track"),
            self._transport,
            kind=IconButtonKind.QUIET,
            glyph_size=LAYOUT.player_skip_icon_size,
        )
        self._next.setObjectName("nowPlayingNext")
        transport.addStretch()
        for button in (self._previous, self._play, self._next):
            button.setFixedSize(
                LAYOUT.control_height_large, LAYOUT.control_height_large
            )
            transport.addWidget(button)
        transport.addStretch()
        left.addWidget(self._transport, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._columns.addWidget(self._player, 5, Qt.AlignmentFlag.AlignVCenter)

        self._queue = QWidget(self)
        self._queue.setObjectName("nowPlayingQueue")
        self._queue.setMinimumWidth(0)
        self._queue.setMaximumWidth(LAYOUT.now_playing_column_maximum_width)
        queue = QVBoxLayout(self._queue)
        queue.setContentsMargins(0, 0, 0, 0)
        queue.setSpacing(LAYOUT.space_sm)
        queue_header = QHBoxLayout()
        self._queue_title = QLabel(self._queue)
        self._queue_title.setObjectName("nowPlayingQueueTitle")
        queue_header.addWidget(self._queue_title)
        queue_header.addStretch()
        self._clear = ActionButton(parent=self._queue, kind=ActionButtonKind.QUIET)
        self._clear.setObjectName("nowPlayingClearQueue")
        self._clear.clicked.connect(controller.clear_queue)
        queue_header.addWidget(self._clear)
        queue.addLayout(queue_header)
        self._queue_view = PlaybackQueueView(
            controller, theme_manager, artwork_provider, self._queue
        )
        self._queue_view.setObjectName("nowPlayingQueueView")
        self._queue_view.setMinimumWidth(0)
        self._queue_view.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._queue_view.setVerticalScrollMode(
            PlaybackQueueView.ScrollMode.ScrollPerPixel
        )
        queue.addWidget(self._queue_view, 1)
        self._empty = QLabel(self._queue_view.viewport())
        self._empty.setObjectName("nowPlayingQueueEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._queue_view.viewport().installEventFilter(self)
        self._player.installEventFilter(self)
        self._columns.addWidget(self._queue, 5)
        self._layout.addLayout(self._columns, 1)

        self._previous.clicked.connect(controller.previous)
        self._play.clicked.connect(controller.toggle_play_pause)
        self._next.clicked.connect(controller.next)
        self._position.valueChanged.connect(self._scrubbed)
        self._position.sliderReleased.connect(self._seek_released)
        controller.currentTrackChanged.connect(self._set_track)
        controller.positionChanged.connect(self._set_position)
        controller.seeked.connect(self._set_position)
        controller.playingChanged.connect(self._set_playing)
        model = controller.queue_model
        model.rowsInserted.connect(self._refresh_queue)
        model.rowsRemoved.connect(self._refresh_queue)
        model.modelReset.connect(self._refresh_queue)
        artwork_provider.artworkChanged.connect(self._artwork_changed)
        artwork_provider.cleared.connect(self._artwork_cleared)
        theme_manager.effectiveThemeChanged.connect(self._theme_changed)
        shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.closeRequested.emit)
        self._set_track(controller.current_track)
        self._set_playing(controller.playing)
        self.retranslate_ui()

    def focus_close(self) -> None:
        self._close.setFocus(Qt.FocusReason.OtherFocusReason)

    def minimumSizeHint(self) -> QSize:
        # A QStackedWidget also asks hidden pages for their minimum. The cover's
        # current dimensions must never enlarge the normal shell's minimum.
        return QSize(0, 0)

    def _set_track(self, track: Track | None) -> None:
        # A new entry can arrive while the pointer is still scrubbing the old one.
        with QSignalBlocker(self._position):
            self._position.setSliderDown(False)
            self._position.setRange(0, max(0, track.length_ms) if track else 0)
        self._track = track
        self._chapters = playback_chapters(track)
        self._position.set_chapters(self._chapters)
        for widget in (self._previous, self._play, self._next, self._position):
            widget.setEnabled(track is not None)
        self._artwork.set_seed(stable_artwork_seed(track.album_key) if track else 0)
        self._refresh_artwork_times()
        if track is None:
            self._backdrop.set_artwork(
                QImage(), self._theme_manager.tokens, animate=False
            )
        self._set_position(self._controller.position_ms)
        self.retranslate_ui()

    def _set_playing(self, playing: bool) -> None:
        self._play.set_glyph("pause" if playing else "play")
        name = self.tr("Pause") if playing else self.tr("Play")
        self._play.setAccessibleName(name)
        self._play.setToolTip(name)

    def _set_position(self, position_ms: int) -> None:
        if self._position.isSliderDown():
            return
        with QSignalBlocker(self._position):
            self._position.setValue(position_ms)
        self._render_position(self._position.value())

    def _scrubbed(self, position_ms: int) -> None:
        self._render_position(position_ms)
        if not self._position.isSliderDown():
            self._controller.seek(position_ms)

    def _seek_released(self) -> None:
        self._controller.seek(self._position.value())

    def _render_position(self, position_ms: int) -> None:
        self._elapsed.setText(format_playback_time(position_ms))
        self._refresh_title()
        track = self._track
        time = artwork_time_at(self._artwork_times, position_ms)
        key = (track.artwork_id if track and time is not None else 0, time)
        if key != self._artwork_key:
            self._artwork_key = key
            self._artwork.set_artwork_id(key[0], display_time_ms=key[1])
            self._background_cache_key = None
            self._refresh_background()

    def _refresh_title(self) -> None:
        track = self._track
        title = (
            (
                track.title
                or QCoreApplication.translate("LibraryLabels", "Untitled Track")
            )
            if track
            else self.tr("Nothing playing")
        )
        chapter = chapter_at(self._chapters, self._position.value())
        if chapter is not None:
            title = self.tr("{track} — {chapter}").format(
                track=title,
                chapter=chapter.title.strip() or self.tr("Untitled Chapter"),
            )
        if self._title.text() != title:
            self._title.setText(title)

    def _refresh_artwork_times(self) -> None:
        self._artwork_times = playback_artwork_times(
            self._artwork_provider.display_times(self._track.artwork_id)
            if self._track
            else ()
        )

    def _artwork_cleared(self) -> None:
        self._refresh_artwork_times()
        self._background_cache_key = None
        # An invalidated provider belongs to an obsolete device session.
        self._backdrop.set_artwork(QImage(), self._theme_manager.tokens, animate=False)
        self._render_position(self._position.value())
        self._refresh_background()

    def _artwork_changed(self, artwork_id: int) -> None:
        if artwork_id == self._artwork_key[0]:
            self._refresh_background()

    def _refresh_background(self) -> None:
        if self.isVisible():
            artwork_id, time = self._artwork_key
            pixmap = self._artwork_provider.pixmap(
                artwork_id, 96, 1.0, display_time_ms=time
            )
            if pixmap is None:
                self._backdrop.set_artwork(QImage(), self._theme_manager.tokens)
                self._background_cache_key = None
            elif pixmap.cacheKey() != self._background_cache_key:
                self._backdrop.set_artwork(pixmap.toImage(), self._theme_manager.tokens)
                self._background_cache_key = pixmap.cacheKey()

    def _theme_changed(self, _theme: str) -> None:
        self._background_cache_key = None
        self._refresh_background()
        self._refresh_shadow()

    def _refresh_shadow(self) -> None:
        color = QColor(self._theme_manager.tokens.window).darker(400)
        color.setAlpha(150)
        self._shadow.setColor(color)
        self._shadow.setBlurRadius(40 * self.devicePixelRatioF())
        self._shadow.setOffset(0, 14 * self.devicePixelRatioF())

    def _refresh_queue(self, *_args: object) -> None:
        count = self._controller.queue_model.rowCount()
        self._clear.setEnabled(count > 0)
        self._empty.setVisible(count == 0)

    def retranslate_ui(self) -> None:
        self._close.setAccessibleName(self.tr("Close Now Playing"))
        self._close.setToolTip(self.tr("Close Now Playing (Esc)"))
        self._queue_title.setText(self.tr("Queue"))
        self._clear.setText(self.tr("Clear Queue"))
        self._empty.setText(self.tr("Queue is empty"))
        self._queue_view.setAccessibleName(self.tr("Playback Queue"))
        self._position.setAccessibleName(self.tr("Playback position"))
        chapters = self._chapters
        for button, name in (
            (
                self._previous,
                self.tr("Previous Chapter") if chapters else self.tr("Previous Track"),
            ),
            (
                self._next,
                self.tr("Next Chapter") if chapters else self.tr("Next Track"),
            ),
        ):
            button.setAccessibleName(name)
            button.setToolTip(name)
        track = self._track
        self._refresh_title()
        self._artist.setText(
            (
                track.artist
                or QCoreApplication.translate("LibraryLabels", "Unknown Artist")
            )
            if track
            else ""
        )
        self._album.setText(
            (
                track.album
                or QCoreApplication.translate("LibraryLabels", "Unknown Album")
            )
            if track
            else ""
        )
        self._duration.setText(format_playback_time(track.length_ms if track else 0))
        self._set_playing(self._controller.playing)
        self._refresh_queue()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        if event.type() in {
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        } and hasattr(self, "_transport"):
            self._fit_artwork()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._fit_artwork()
        self._refresh_shadow()
        self._refresh_background()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._backdrop.setGeometry(self.rect())
        self._fit_artwork()
        self._refresh_shadow()

    def _fit_artwork(self) -> None:
        # The two columns remain side by side at the app's desktop minimum size.
        minimum_gap = LAYOUT.space_lg if self.width() < 1000 else LAYOUT.space_xl * 2
        margins = self._layout.contentsMargins()
        content_width = self.width() - margins.left() - margins.right()
        column_width = LAYOUT.now_playing_column_maximum_width
        inset = min(
            LAYOUT.now_playing_maximum_edge_margin - margins.left(),
            max(0, (content_width - column_width * 2 - minimum_gap) // 2),
        )
        self._columns.setContentsMargins(inset, 0, inset, 0)
        # Once the outer margins reach their cap, all extra width belongs in
        # the middle, keeping each column anchored to its own window edge.
        self._columns.setSpacing(
            max(minimum_gap, content_width - inset * 2 - column_width * 2)
        )
        available_height = self.height() - (
            self._close.height()
            + self._metadata.sizeHint().height()
            + self._timeline.sizeHint().height()
            + self._transport.sizeHint().height()
            + self._layout.contentsMargins().top()
            + self._layout.contentsMargins().bottom()
            + LAYOUT.space_md
            + LAYOUT.space_sm * 5
        )
        side = max(
            48,
            min(
                self._player.width() - LAYOUT.space_md * 2,
                available_height,
                LAYOUT.now_playing_artwork_maximum_size,
            ),
        )
        self._artwork.setFixedSize(side, side)
        for widget in (self._metadata, self._timeline, self._transport):
            widget.setFixedWidth(side)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._player and event.type() == QEvent.Type.Resize:
            self._fit_artwork()
        if (
            watched is self._queue_view.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self._empty.setGeometry(self._queue_view.viewport().rect())
        return super().eventFilter(watched, event)
