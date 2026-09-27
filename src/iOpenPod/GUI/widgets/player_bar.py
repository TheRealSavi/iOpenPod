"""Persistent runtime Player surface for the application shell."""

from time import monotonic_ns

from PySide6.QtCore import (
    Property,
    QCoreApplication,
    QEasingCurve,
    QEvent,
    QMimeData,
    QObject,
    QPoint,
    QPropertyAnimation,
    QSignalBlocker,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QContextMenuEvent,
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.artwork_seed import stable_artwork_seed
from iOpenPod.app.models.library_drag import TrackSelectionMimeData, dropped_tracks
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.presentation.track_drag_preview import (
    drag_preview_hot_spot,
    render_single_track_drag_preview,
)
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.themed_buttons import IconButton, IconButtonKind
from iPodDB.library import Track

_MUTE_FADE_DURATION_MS = 180
_POSITION_FRAME_MS = 16
_POSITION_LOOKAHEAD_MS = 500
_POSITION_CORRECTION_MS = 500


class _ElidedLabel(QLabel):
    """Keep one full accessible value while painting a width-bounded label."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._refresh_height()

    @property
    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setText(text)
        self.setAccessibleName(text)
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(
            self.contentsRect(),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.fontMetrics().elidedText(
                self._full_text,
                Qt.TextElideMode.ElideRight,
                max(0, self.contentsRect().width()),
            ),
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange}:
            self._refresh_height()
            self.update()
        super().changeEvent(event)

    def _refresh_height(self) -> None:
        self.setFixedHeight(self.fontMetrics().height() + LAYOUT.space_3xs)


class _SeekSlider(QSlider):
    """Provide direct, continuous pointer control over a playback position."""

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        control = QStyle.ComplexControl.CC_Slider
        handle_control = QStyle.SubControl.SC_SliderHandle
        handle = style.subControlRect(control, option, handle_control, self)

        # QStyle rounds the handle position to whole logical pixels. At normal
        # Track lengths that leaves many animation frames visually identical.
        # Keep the native styling, but translate its handle by the fractional
        # remainder so antialiasing can show motion between pixel boundaries.
        endpoint = QStyleOptionSlider(option)
        endpoint.sliderPosition = option.minimum
        start = style.subControlRect(control, endpoint, handle_control, self).x()
        endpoint.sliderPosition = option.maximum
        end = style.subControlRect(control, endpoint, handle_control, self).x()
        fraction = (option.sliderPosition - option.minimum) / max(
            1, option.maximum - option.minimum
        )
        offset = start + fraction * (end - start) - handle.x()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        option.subControls = (
            QStyle.SubControl.SC_SliderGroove | QStyle.SubControl.SC_SliderTickmarks
        )
        style.drawComplexControl(control, option, painter, self)
        painter.translate(offset, 0.0)
        option.subControls = handle_control
        style.drawComplexControl(control, option, painter, self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() is not Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.setSliderDown(True)
        self._set_value_from_pointer(event.position().x())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not (self.isSliderDown() and event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        self._set_value_from_pointer(event.position().x())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() is not Qt.MouseButton.LeftButton or not self.isSliderDown():
            super().mouseReleaseEvent(event)
            return
        self._set_value_from_pointer(event.position().x())
        self.setSliderDown(False)
        event.accept()

    def _set_value_from_pointer(self, pointer_x: float) -> None:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle_length = self.style().pixelMetric(
            QStyle.PixelMetric.PM_SliderLength,
            option,
            self,
        )
        span = self.style().pixelMetric(
            QStyle.PixelMetric.PM_SliderSpaceAvailable,
            option,
            self,
        )
        handle_center = round(pointer_x) - (handle_length // 2)
        self.setValue(
            QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                handle_center,
                span,
                option.upsideDown,
            )
        )


class PlayerBar(QFrame):
    """Present runtime playback state and emit transport intent."""

    playPauseRequested = Signal()
    previousRequested = Signal()
    nextRequested = Signal()
    seekRequested = Signal(int)
    volumeChanged = Signal(int)
    queueVisibilityRequested = Signal(bool)
    clearQueueRequested = Signal()
    visualizerRequested = Signal()
    trackRatingRequested = Signal(int, int)
    trackContextMenuRequested = Signal(object, QPoint)
    tracksDropped = Signal(object)

    def __init__(
        self,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
        *,
        workspace: LibraryWorkspace | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("playerBar")
        self.setFixedHeight(LAYOUT.player_idle_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._track: Track | None = None
        self._playing = False
        self._target_height = LAYOUT.player_idle_height
        self._active_height = LAYOUT.player_height
        self._active_surface_height = LAYOUT.player_surface_height
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self._workspace = workspace
        self._drag_start: QPoint | None = None
        self.setAcceptDrops(workspace is not None)

        self._previous = IconButton(
            "skip-back",
            self.tr("Previous Track"),
            self,
            kind=IconButtonKind.SUBTLE,
            glyph_size=LAYOUT.player_skip_icon_size,
        )
        self._previous.setObjectName("playerPrevious")
        self._previous.setFixedSize(
            LAYOUT.minimum_touch_target,
            LAYOUT.minimum_touch_target,
        )
        self._play = IconButton(
            "play",
            self.tr("Play"),
            self,
            kind=IconButtonKind.QUIET,
            glyph_size=LAYOUT.player_play_icon_size,
        )
        self._play.setObjectName("playerPlayPause")
        self._play.setFixedSize(
            LAYOUT.minimum_touch_target,
            LAYOUT.minimum_touch_target,
        )
        self._next = IconButton(
            "skip-forward",
            self.tr("Next Track"),
            self,
            kind=IconButtonKind.SUBTLE,
            glyph_size=LAYOUT.player_skip_icon_size,
        )
        self._next.setObjectName("playerNext")
        self._next.setFixedSize(
            LAYOUT.minimum_touch_target,
            LAYOUT.minimum_touch_target,
        )

        self._left_zone = QWidget(self)
        self._left_zone.setObjectName("playerLeftZone")
        self._left_zone.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        left_layout = QHBoxLayout(self._left_zone)
        left_layout.setContentsMargins(
            LAYOUT.space_md,
            0,
            LAYOUT.space_md,
            0,
        )
        left_layout.setSpacing(LAYOUT.space_2xs)
        left_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        left_layout.addWidget(self._previous)
        left_layout.addWidget(self._play)
        left_layout.addWidget(self._next)

        self._now_playing = QFrame(self)
        self._now_playing.setObjectName("nowPlayingSurface")
        self._now_playing.setProperty("playbackState", "idle")
        self._now_playing.setMinimumWidth(320)
        self._now_playing.setMaximumWidth(LAYOUT.player_surface_maximum_width)
        self._now_playing.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._now_playing.setFixedHeight(LAYOUT.player_idle_surface_height)
        now_layout = QHBoxLayout(self._now_playing)
        now_layout.setContentsMargins(
            LAYOUT.space_sm,
            LAYOUT.space_2xs,
            LAYOUT.space_md,
            LAYOUT.space_2xs,
        )
        now_layout.setSpacing(LAYOUT.space_sm)

        self._artwork = ArtworkView(
            theme_manager,
            artwork_provider,
            self._now_playing,
        )
        self._artwork.setObjectName("playerArtwork")
        self._artwork.setFixedSize(
            LAYOUT.player_artwork_size,
            LAYOUT.player_artwork_size,
        )
        self._title = _ElidedLabel(self._now_playing)
        self._title.setObjectName("playerTrackTitle")
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._detail = _ElidedLabel(self._now_playing)
        self._detail.setObjectName("playerTrackDetail")
        self._title.installEventFilter(self)
        self._detail.installEventFilter(self)
        self._position = _SeekSlider(Qt.Orientation.Horizontal, self._now_playing)
        self._position.setObjectName("playerProgress")
        self._position.setRange(0, 0)
        self._position_anchor_ms = 0
        self._position_anchor_time = monotonic_ns()
        self._position_correction_ms = 0
        self._position_timer = QTimer(self)
        self._position_timer.setObjectName("playerProgressTimer")
        self._position_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._position_timer.setInterval(_POSITION_FRAME_MS)
        self._position_timer.timeout.connect(self._advance_position)
        self._elapsed = QLabel("0:00", self._now_playing)
        self._elapsed.setObjectName("playerTime")
        self._duration = QLabel("0:00", self._now_playing)
        self._duration.setObjectName("playerTime")

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        text.addWidget(self._title)
        text.addWidget(self._detail)

        self._timeline = QWidget(self._now_playing)
        self._timeline.setObjectName("playerTimeline")
        timeline = QHBoxLayout(self._timeline)
        timeline.setContentsMargins(0, 0, 0, 0)
        timeline.setSpacing(LAYOUT.space_xs)
        timeline.addWidget(self._elapsed)
        timeline.addWidget(self._position, 1)
        timeline.addWidget(self._duration)
        text.addWidget(self._timeline)

        now_layout.addWidget(self._artwork)
        now_layout.addLayout(text, 1)

        self._visualizer = IconButton(
            "synesthesia",
            self.tr("Open visualizer for current Track"),
            self._now_playing,
            kind=IconButtonKind.QUIET,
        )
        self._visualizer.setObjectName("playerVisualizer")
        self._visualizer.setFixedSize(
            LAYOUT.control_height_compact,
            LAYOUT.control_height_compact,
        )
        self._rating = QLabel(self._now_playing)
        self._rating.setObjectName("playerRating")
        self._rating.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._rating.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        self._rating.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._rating.setMouseTracking(True)
        self._rating_hover_stars: int | None = None
        self._rating_repolishing = False
        self._rating.setProperty("ratingHover", False)
        self._rating.installEventFilter(self)
        if workspace is not None:
            workspace.changed.connect(self._refresh_rating_editability)
        visualizer_layout = QVBoxLayout()
        visualizer_layout.setContentsMargins(0, 0, 0, 0)
        visualizer_layout.setSpacing(LAYOUT.space_3xs)
        visualizer_layout.addWidget(
            self._visualizer,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        visualizer_layout.addWidget(
            self._rating,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        now_layout.addLayout(visualizer_layout)
        self._refresh_active_height()

        center_zone = QWidget(self)
        center_zone.setObjectName("playerCenterZone")
        center_layout = QHBoxLayout(center_zone)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self._now_playing, 1)

        self._mute = IconButton(
            "volume",
            self.tr("Mute"),
            self,
            checkable=True,
            kind=IconButtonKind.SUBTLE,
        )
        self._mute.setObjectName("playerMute")
        self._mute.setFixedSize(
            LAYOUT.minimum_touch_target,
            LAYOUT.minimum_touch_target,
        )
        self._volume = QSlider(Qt.Orientation.Horizontal, self)
        self._volume.setObjectName("volumeSlider")
        self._volume.setRange(0, 100)
        self._last_audible_volume = self._volume.maximum()
        self._mute_fade_active = False
        self._emitting_volume_intent = False
        self._volume.setValue(0)
        self._volume.setMinimumWidth(LAYOUT.player_volume_minimum_width)
        self._volume.setMaximumWidth(LAYOUT.player_volume_width)
        self._volume.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._mute.setChecked(True)
        self._queue = IconButton(
            "playlist",
            self.tr("Show Queue, History, and Lyrics"),
            self,
            checkable=True,
        )
        self._queue.setObjectName("playerQueueToggle")
        self._queue.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._queue.customContextMenuRequested.connect(self._show_queue_context_menu)
        self._queue_menu = QMenu(self._queue)
        self._clear_queue = QAction(self._queue_menu)
        self._clear_queue.setEnabled(False)
        self._clear_queue.triggered.connect(self.clearQueueRequested.emit)
        self._queue_menu.addAction(self._clear_queue)
        self._queue.setFixedSize(
            LAYOUT.minimum_touch_target,
            LAYOUT.minimum_touch_target,
        )

        self._right_zone = QWidget(self)
        self._right_zone.setObjectName("playerRightZone")
        self._right_zone.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        right_layout = QHBoxLayout(self._right_zone)
        right_layout.setContentsMargins(0, 0, LAYOUT.space_lg, 0)
        right_layout.setSpacing(LAYOUT.space_2xs)
        right_layout.addStretch(1)
        right_layout.addWidget(self._mute)
        right_layout.addWidget(self._volume)
        right_layout.addSpacing(LAYOUT.space_xs)
        right_layout.addWidget(self._queue)

        edge_zone_width = max(
            left_layout.sizeHint().width(),
            right_layout.sizeHint().width(),
        )
        self._left_zone.setFixedWidth(edge_zone_width)
        self._right_zone.setFixedWidth(edge_zone_width)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(self._left_zone)
        self._layout.addWidget(center_zone, 1)
        self._layout.addWidget(self._right_zone)

        self._previous.clicked.connect(self.previousRequested.emit)
        self._play.clicked.connect(self.playPauseRequested.emit)
        self._next.clicked.connect(self.nextRequested.emit)
        self._mute.toggled.connect(self._mute_toggled)
        self._queue.toggled.connect(self._queue_toggled)
        self._visualizer.clicked.connect(self.visualizerRequested.emit)
        self._position.sliderPressed.connect(self._position_timer.stop)
        self._position.sliderReleased.connect(self._seek_released)
        self._position.valueChanged.connect(self._scrub_position_changed)
        self._volume.sliderPressed.connect(self._volume_interaction_started)
        self._volume.valueChanged.connect(self._volume_changed)
        self._mute_fade = QPropertyAnimation(self._volume, b"value", self)
        self._mute_fade.setObjectName("playerMuteFadeAnimation")
        self._mute_fade.setDuration(_MUTE_FADE_DURATION_MS)
        self._mute_fade.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._mute_fade.finished.connect(self._mute_fade_finished)
        self._height_animation = QPropertyAnimation(
            self,
            b"animated_height",
            self,
        )
        self._height_animation.setObjectName("playerHeightAnimation")
        self._height_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._height_animation.finished.connect(self._height_animation_finished)
        self.set_track(None)
        self.retranslate_ui()

    def _get_animated_height(self) -> int:
        return self.height()

    def _set_animated_height(self, height: int) -> None:
        bounded = min(
            self._active_height,
            max(LAYOUT.player_idle_height, height),
        )
        self.setFixedHeight(bounded)
        bar_range = self._active_height - LAYOUT.player_idle_height
        surface_range = self._active_surface_height - LAYOUT.player_idle_surface_height
        progress = (bounded - LAYOUT.player_idle_height) / max(1, bar_range)
        self._now_playing.setFixedHeight(
            LAYOUT.player_idle_surface_height + round(progress * surface_range)
        )

    animated_height = Property(
        int,
        _get_animated_height,
        _set_animated_height,
    )

    @property
    def track(self) -> Track | None:
        """Return the Track currently represented by the Player."""

        return self._track

    def set_track(self, track: Track | None) -> None:
        """Update the surface for the controller's current Track."""

        self._set_rating_hover(None)
        self._track = track
        enabled = track is not None
        self._previous.setEnabled(enabled)
        self._play.setEnabled(enabled)
        self._next.setEnabled(enabled)
        self._position.setEnabled(enabled)
        self._visualizer.setEnabled(enabled)
        if track is None:
            self._rating.setText("")
            self._refresh_rating_editability()
            self._position_timer.stop()
            self._queue.setChecked(False)
            self._title.set_full_text(self.tr("Nothing playing"))
            self._detail.set_full_text(self.tr("Drop a Track or Playlist to play it"))
            self._set_idle_presentation(True)
            self._position.setRange(0, 0)
            self._elapsed.setText("0:00")
            self._duration.setText("0:00")
            self._artwork.set_seed(0)
            self._artwork.set_artwork_id(0)
            self.set_playing(False)
            return

        self._set_idle_presentation(False)
        self._title.set_full_text(
            track.title or QCoreApplication.translate("LibraryLabels", "Untitled Track")
        )
        detail = " · ".join(part for part in (track.artist, track.album) if part)
        self._detail.set_full_text(detail or "—")
        stars = min(5, max(0, round(track.rating / 20)))
        self._rating.setText(("★" * stars) + ("☆" * (5 - stars)))
        self._refresh_rating_editability()
        self._position.setRange(0, max(0, track.length_ms))
        self._duration.setText(_format_duration(track.length_ms))
        self._artwork.set_seed(stable_artwork_seed(track.album_key))
        self._artwork.set_artwork_id(track.artwork_id)

    def set_playing(self, playing: bool) -> None:
        if playing != self._playing:
            self._position_anchor_ms = self._position.value()
            self._position_anchor_time = monotonic_ns()
            self._position_correction_ms = 0
        self._playing = playing
        self._refresh_position_timer()
        self._play.set_glyph("pause" if playing else "play")
        accessible_name = self.tr("Pause") if playing else self.tr("Play")
        self._play.setAccessibleName(accessible_name)
        self._play.setToolTip(accessible_name)

    def update_position(self, position_ms: int) -> None:
        """Reconcile ordinary backend reports without visible clock jitter."""

        self.set_position(position_ms, smooth=True)

    def set_position(self, position_ms: int, *, smooth: bool = False) -> None:
        """Relocate immediately for seeks, resets, and transport discontinuities."""

        if self._position.isSliderDown():
            return
        bounded = min(max(0, position_ms), self._position.maximum())
        now = monotonic_ns()
        correction = 0
        if (
            smooth
            and self._position_timer.isActive()
            and 0 < bounded < self._position.maximum()
            and bounded >= self._position_anchor_ms
        ):
            difference = self._predicted_position(now) - bounded
            # Gradually absorb small reporting delays. Limiting the correction
            # to half its decay window keeps forward motion at 0.5x to 1.5x speed.
            if abs(difference) <= _POSITION_CORRECTION_MS // 2:
                correction = difference
        self._position_anchor_ms = bounded
        self._position_anchor_time = now
        self._position_correction_ms = correction
        self._render_position(bounded + correction)
        self._refresh_position_timer()

    def _render_position(self, bounded: int) -> None:
        self._position.setValue(bounded)
        self._elapsed.setText(_format_duration(bounded))

    def _refresh_position_timer(self) -> None:
        if (
            self._playing
            and self._track is not None
            and not self._position.isSliderDown()
            and self._position.value() < self._position.maximum()
        ):
            if not self._position_timer.isActive():
                self._position_timer.start()
        else:
            self._position_timer.stop()

    def _advance_position(self) -> None:
        """Animate presentation only, with bounded drift if backend reports stop."""

        if not self._position_timer.isActive():
            return
        now = monotonic_ns()
        elapsed_ms = (now - self._position_anchor_time) // 1_000_000
        bounded = self._predicted_position(now)
        self._render_position(bounded)
        if elapsed_ms >= _POSITION_LOOKAHEAD_MS or bounded == self._position.maximum():
            self._position_timer.stop()

    def _predicted_position(self, now_ns: int) -> int:
        elapsed_ms = max(0, (now_ns - self._position_anchor_time) // 1_000_000)
        correction = self._position_correction_ms * max(
            0.0, 1 - elapsed_ms / _POSITION_CORRECTION_MS
        )
        return min(
            self._position.maximum(),
            round(
                self._position_anchor_ms
                + min(elapsed_ms, _POSITION_LOOKAHEAD_MS)
                + correction
            ),
        )

    def set_volume(self, percent: int) -> None:
        """Render controller-owned volume without feeding the change back."""

        bounded = min(100, max(0, percent))
        if self._mute_fade_active and not self._emitting_volume_intent:
            self._mute_fade.stop()
            self._mute_fade_active = False
        if bounded > 0 and not self._mute_fade_active:
            self._last_audible_volume = bounded
        with QSignalBlocker(self._volume):
            self._volume.setValue(bounded)
        with QSignalBlocker(self._mute):
            if not self._mute_fade_active:
                self._mute.setChecked(bounded == 0)
        self._refresh_mute_copy()

    def set_queue_visible(self, visible: bool) -> None:
        self._queue.setChecked(visible)

    def set_queue_count(self, count: int) -> None:
        self._clear_queue.setEnabled(count > 0)

    def _show_queue_context_menu(self, position: QPoint) -> None:
        self._queue_menu.exec(self._queue.mapToGlobal(position))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dropped_tracks(event.mimeData()) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._dropped_tracks(event.mimeData()) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        tracks = self._dropped_tracks(event.mimeData())
        if tracks is None:
            event.ignore()
            return
        self.tracksDropped.emit(tracks)
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()

    def retranslate_ui(self) -> None:
        """Refresh static playback copy without disturbing runtime state."""

        controls = (
            (self._previous, self.tr("Previous Track")),
            (self._next, self.tr("Next Track")),
        )
        for control, accessible_name in controls:
            control.setAccessibleName(accessible_name)
            control.setToolTip(accessible_name)
        self._refresh_mute_copy()
        self._refresh_queue_copy()
        self._clear_queue.setText(self.tr("Clear Queue"))
        visualizer_name = self.tr("Open visualizer for current Track")
        self._visualizer.setAccessibleName(visualizer_name)
        self._visualizer.setToolTip(visualizer_name)
        self.set_playing(self._playing)
        self._volume.setAccessibleName(self.tr("Volume"))
        self._position.setAccessibleName(self.tr("Playback position"))
        self._refresh_rating_editability()
        if self._track is None:
            self._title.set_full_text(self.tr("Nothing playing"))
            self._detail.set_full_text(self.tr("Drop a Track or Playlist to play it"))
        elif not self._track.title:
            self._title.set_full_text(
                QCoreApplication.translate("LibraryLabels", "Untitled Track")
            )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        } and hasattr(self, "_rating"):
            self._refresh_active_height()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is getattr(self, "_rating", None):
            if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange}:
                if not self._rating_repolishing:
                    QTimer.singleShot(0, self._refresh_active_height)
            elif event.type() is QEvent.Type.Leave:
                self._set_rating_hover(None)
            elif (
                isinstance(event, QMouseEvent) and event.type() is QEvent.Type.MouseMove
            ):
                self._set_rating_hover(
                    self._rating_stars_at(event.position().x())
                    if self._rating.isEnabled()
                    else None
                )
            elif (
                isinstance(event, QMouseEvent)
                and event.type() is QEvent.Type.MouseButtonRelease
            ):
                if (
                    event.button() is Qt.MouseButton.LeftButton
                    and self._rating.isEnabled()
                ):
                    stars = self._rating_stars_at(event.position().x())
                    if stars is not None:
                        self._request_rating(stars)
                        return True
            elif (
                isinstance(event, QKeyEvent)
                and event.type() is QEvent.Type.KeyPress
                and self._rating.isEnabled()
            ):
                current = (
                    min(5, max(0, round(self._track.rating / 20)))
                    if self._track is not None
                    else 0
                )
                key = event.key()
                if Qt.Key.Key_0 <= key <= Qt.Key.Key_5:
                    self._request_rating(key - Qt.Key.Key_0)
                    return True
                if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                    self._request_rating(
                        min(5, max(0, current + (1 if key == Qt.Key.Key_Right else -1)))
                    )
                    return True
                if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
                    self._request_rating(0 if key == Qt.Key.Key_Home else 5)
                    return True
            return super().eventFilter(watched, event)
        if watched not in (
            getattr(self, "_title", None),
            getattr(self, "_detail", None),
        ):
            return super().eventFilter(watched, event)
        if isinstance(event, QContextMenuEvent):
            if self._track is not None:
                self.trackContextMenuRequested.emit(self._track, event.globalPos())
                return True
        elif isinstance(event, QMouseEvent):
            if (
                event.type() is QEvent.Type.MouseButtonPress
                and event.button() is Qt.MouseButton.LeftButton
                and self._track is not None
            ):
                self._drag_start = event.position().toPoint()
            elif event.type() is QEvent.Type.MouseButtonRelease:
                self._drag_start = None
            elif (
                event.type() is QEvent.Type.MouseMove
                and self._drag_start is not None
                and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._drag_start).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                self._drag_start = None
                self._start_track_drag()
                return True
        return super().eventFilter(watched, event)

    def _refresh_rating_editability(self) -> None:
        track = self._track
        workspace = self._workspace
        editable = (
            track is not None
            and workspace is not None
            and not workspace.locked
            and workspace.track(track.track_id) == track
        )
        if not editable:
            self._set_rating_hover(None)
        self._rating.setEnabled(editable)
        self._rating.setCursor(
            Qt.CursorShape.PointingHandCursor
            if editable
            else Qt.CursorShape.ArrowCursor
        )
        if track is not None:
            stars = min(5, max(0, round(track.rating / 20)))
            self._rating.setAccessibleName(
                self.tr("Track rating: %1 of 5 stars").replace("%1", str(stars))
            )
        self._rating.setToolTip(
            self.tr("Click a star to rate this Track; click the selected star to clear")
            if editable
            else ""
        )

    def _set_rating_hover(self, stars: int | None) -> None:
        if stars == self._rating_hover_stars:
            return
        self._rating_hover_stars = stars
        self._rating.setProperty("ratingHover", stars is not None)
        style = self._rating.style()
        self._rating_repolishing = True
        try:
            style.unpolish(self._rating)
            style.polish(self._rating)
        finally:
            self._rating_repolishing = False
        if stars is None:
            track = self._track
            stars = 0 if track is None else min(5, max(0, round(track.rating / 20)))
        self._rating.setText(("★" * stars) + ("☆" * (5 - stars)))
        self._rating.update()

    def _rating_stars_at(self, pointer_x: float) -> int | None:
        text = self._rating.text()
        if len(text) != 5:
            return None
        metrics = self._rating.fontMetrics()
        widths = tuple(metrics.horizontalAdvance(character) for character in text)
        left = (self._rating.width() - sum(widths)) / 2
        if not left <= pointer_x < left + sum(widths):
            return None
        for stars, width in enumerate(widths, start=1):
            left += width
            if pointer_x < left:
                return stars
        return None

    def _request_rating(self, stars: int) -> None:
        track = self._track
        if track is None:
            return
        self._set_rating_hover(None)
        current = min(5, max(0, round(track.rating / 20)))
        value = 0 if stars == current and stars > 0 else stars * 20
        self.trackRatingRequested.emit(track.track_id, value)
        # The draft publishes before PlaybackController reconciles the Track.
        # That briefly disables this label and Qt moves focus to Mute.
        if self._rating.isEnabled() and self._rating.isVisible():
            self._rating.setFocus()

    def _seek_released(self) -> None:
        self.set_position(self._position.value())
        self.seekRequested.emit(self._position.value())

    def _scrub_position_changed(self, position_ms: int) -> None:
        if self._position.isSliderDown():
            self._elapsed.setText(_format_duration(position_ms))

    def _mute_toggled(self, muted: bool) -> None:
        self._refresh_mute_copy()
        if muted:
            if self._volume.value() > 0:
                self._last_audible_volume = self._volume.value()
                self._mute_fade_active = True
                self._mute_fade.setStartValue(self._volume.value())
                self._mute_fade.setEndValue(0)
                self._mute_fade.start()
            return
        if self._mute_fade_active:
            self._mute_fade.stop()
            self._mute_fade_active = False
        if self._volume.value() != self._last_audible_volume:
            self._volume.setValue(self._last_audible_volume)

    def _volume_changed(self, volume: int) -> None:
        if volume > 0 and not self._mute_fade_active:
            self._last_audible_volume = volume
            if self._mute.isChecked():
                self._mute.setChecked(False)
        self._emitting_volume_intent = True
        try:
            self.volumeChanged.emit(volume)
        finally:
            self._emitting_volume_intent = False

    def _volume_interaction_started(self) -> None:
        if not self._mute_fade_active:
            return
        self._mute_fade.stop()
        self._mute_fade_active = False
        with QSignalBlocker(self._mute):
            self._mute.setChecked(False)
        self._refresh_mute_copy()

    def _mute_fade_finished(self) -> None:
        self._mute_fade_active = False

    def _queue_toggled(self, visible: bool) -> None:
        self._refresh_queue_copy()
        self.queueVisibilityRequested.emit(visible)

    def _refresh_mute_copy(self) -> None:
        accessible_name = (
            self.tr("Unmute") if self._mute.isChecked() else self.tr("Mute")
        )
        self._mute.setAccessibleName(accessible_name)
        self._mute.setToolTip(accessible_name)

    def _refresh_queue_copy(self) -> None:
        accessible_name = (
            self.tr("Hide Queue, History, and Lyrics")
            if self._queue.isChecked()
            else self.tr("Show Queue, History, and Lyrics")
        )
        self._queue.setAccessibleName(accessible_name)
        self._queue.setToolTip(accessible_name)

    def _dropped_tracks(self, data: QMimeData) -> tuple[Track, ...] | None:
        workspace = self._workspace
        if workspace is None:
            return None
        return dropped_tracks(data, workspace)

    def _start_track_drag(self) -> None:
        track = self._track
        workspace = self._workspace
        if (
            track is None
            or workspace is None
            or workspace.track(track.track_id) is None
        ):
            return
        pixmap = render_single_track_drag_preview(
            track,
            title=track.title
            or QCoreApplication.translate("LibraryLabels", "Untitled Track"),
            artist=track.artist
            or QCoreApplication.translate("LibraryLabels", "Unknown Artist"),
            album=track.album
            or QCoreApplication.translate("LibraryLabels", "Unknown Album"),
            base_font=self.font(),
            tokens=self._theme_manager.tokens,
            artwork_provider=self._artwork_provider,
            device_pixel_ratio=self.devicePixelRatioF(),
        )
        drag = QDrag(self._now_playing)
        drag.setMimeData(TrackSelectionMimeData(workspace, (track.track_id,)))
        drag.setPixmap(pixmap)
        drag.setHotSpot(drag_preview_hot_spot(pixmap))
        drag.exec(Qt.DropAction.CopyAction)

    def _set_idle_presentation(self, idle: bool) -> None:
        self._left_zone.setVisible(not idle)
        self._now_playing.setVisible(not idle)
        self._right_zone.setVisible(not idle)
        self._now_playing.setProperty(
            "playbackState",
            "idle" if idle else "active",
        )
        self._now_playing.style().unpolish(self._now_playing)
        self._now_playing.style().polish(self._now_playing)
        self._now_playing.update()
        self._animate_height(LAYOUT.player_idle_height if idle else self._active_height)

    def _refresh_active_height(self) -> None:
        required_surface_height = (
            (2 * LAYOUT.space_2xs)
            + self._visualizer.height()
            + LAYOUT.space_3xs
            + self._rating.sizeHint().height()
        )
        player_height = max(
            LAYOUT.player_height,
            required_surface_height,
        )
        surface_height = player_height
        if (
            surface_height == self._active_surface_height
            and player_height == self._active_height
        ):
            return
        self._active_surface_height = surface_height
        self._active_height = player_height
        if self._track is not None:
            animation = getattr(self, "_height_animation", None)
            if animation is not None:
                animation.stop()
            self._target_height = player_height
            self._set_animated_height(player_height)

    def _animate_height(self, target_height: int) -> None:
        self._height_animation.stop()
        current_height = self.height()
        self._target_height = target_height
        if (
            current_height == target_height
            or not self.isVisible()
            or not self.style().styleHint(
                QStyle.StyleHint.SH_Widget_Animate,
                None,
                self,
            )
        ):
            self._set_animated_height(target_height)
            return

        distance = abs(target_height - current_height)
        full_distance = self._active_height - LAYOUT.player_idle_height
        duration = max(
            1,
            round(LAYOUT.player_transition_ms * distance / full_distance),
        )
        self._height_animation.setDuration(duration)
        self._height_animation.setStartValue(current_height)
        self._height_animation.setEndValue(target_height)
        self._height_animation.start()

    def _height_animation_finished(self) -> None:
        self._set_animated_height(self._target_height)


def _format_duration(length_ms: int) -> str:
    minutes, seconds = divmod(max(0, length_ms) // 1000, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"
