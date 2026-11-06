"""Video presentation and transport intents for the existing Playback Entry."""

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QHideEvent, QKeySequence, QShortcut, QShowEvent
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.playback.backend import PlaybackFailure
from iOpenPod.app.playback.chapters import playback_chapters
from iOpenPod.app.playback.video_output import PlaybackVideoOutput
from iOpenPod.app.playback_controller import PlaybackController
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.elided_label import ElidedLabel
from iOpenPod.GUI.widgets.seek_slider import SeekSlider, format_playback_time
from iOpenPod.GUI.widgets.themed_buttons import IconButton, IconButtonKind
from iPodDB.library import Track


class VideoPlayerPage(QWidget):
    """Show native, aspect-preserving video with controller-owned transport."""

    closeRequested = Signal()

    def __init__(
        self,
        controller: PlaybackController,
        video_output: PlaybackVideoOutput | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("videoPlayerPage")
        self._controller = controller
        self._video_output = video_output
        self._failure: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_md, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_sm)
        header = QHBoxLayout()
        self._close = IconButton(
            "x", self.tr("Close video player"), self, kind=IconButtonKind.QUIET
        )
        self._close.setObjectName("videoPlayerClose")
        self._close.clicked.connect(self.closeRequested.emit)
        header.addWidget(self._close)
        self._title = ElidedLabel(1, self)
        self._title.setObjectName("videoPlayerTitle")
        header.addWidget(self._title, 1)
        layout.addLayout(header)

        self._video = QVideoWidget(self)
        self._video.setObjectName("videoPlayerSurface")
        self._video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self._video.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored
        )
        self._video.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self._video, 1)
        self._unavailable = QLabel(self)
        self._unavailable.setObjectName("videoPlayerUnavailable")
        self._unavailable.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._unavailable.setWordWrap(True)
        self._unavailable.setVisible(video_output is None)
        layout.addWidget(self._unavailable)

        self._position = SeekSlider(Qt.Orientation.Horizontal, self)
        self._position.setObjectName("videoPlayerProgress")
        self._position.setSingleStep(1000)
        self._position.setPageStep(10_000)
        layout.addWidget(self._position)
        times = QHBoxLayout()
        self._elapsed = QLabel(self)
        self._elapsed.setObjectName("videoPlayerElapsed")
        self._duration = QLabel(self)
        self._duration.setObjectName("videoPlayerDuration")
        times.addWidget(self._elapsed)
        times.addStretch()
        times.addWidget(self._duration)
        layout.addLayout(times)

        transport = QHBoxLayout()
        self._previous = IconButton("skip-back", "", self, kind=IconButtonKind.QUIET)
        self._previous.setObjectName("videoPlayerPrevious")
        self._play = IconButton("play", "", self, kind=IconButtonKind.QUIET)
        self._play.setObjectName("videoPlayerPlayPause")
        self._next = IconButton("skip-forward", "", self, kind=IconButtonKind.QUIET)
        self._next.setObjectName("videoPlayerNext")
        for button in (self._previous, self._play, self._next):
            transport.addWidget(button)
        transport.addStretch()
        self._subtitle_label = QLabel(self)
        transport.addWidget(self._subtitle_label)
        self._subtitles = AppComboBox(self)
        self._subtitles.setObjectName("videoPlayerSubtitles")
        self._subtitles.setSizeAdjustPolicy(
            AppComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._subtitles.setMinimumContentsLength(12)
        self._subtitle_label.setBuddy(self._subtitles)
        transport.addWidget(self._subtitles)
        transport.addSpacing(LAYOUT.space_sm)
        self._volume_label = QLabel(self)
        transport.addWidget(self._volume_label)
        self._volume = QSlider(Qt.Orientation.Horizontal, self)
        self._volume.setObjectName("videoPlayerVolume")
        self._volume.setRange(0, 100)
        self._volume.setMaximumWidth(LAYOUT.player_volume_width)
        self._volume_label.setBuddy(self._volume)
        transport.addWidget(self._volume)
        layout.addLayout(transport)

        self._previous.clicked.connect(controller.previous)
        self._play.clicked.connect(controller.toggle_play_pause)
        self._next.clicked.connect(controller.next)
        self._position.valueChanged.connect(self._scrubbed)
        self._position.sliderReleased.connect(self._seek_released)
        self._volume.valueChanged.connect(controller.set_volume)
        self._subtitles.currentIndexChanged.connect(self._subtitle_selected)
        if video_output is not None:
            video_output.subscribe_subtitles_changed(self._refresh_subtitles)
        controller.currentTrackChanged.connect(self._set_track)
        controller.positionChanged.connect(self._set_position)
        controller.seeked.connect(self._set_position)
        controller.playingChanged.connect(self._set_playing)
        controller.volumeChanged.connect(self._set_volume)
        controller.playbackFailed.connect(self._playback_failed)
        for key, action in (
            (Qt.Key.Key_Escape, self.closeRequested.emit),
            (Qt.Key.Key_Space, controller.toggle_play_pause),
        ):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)
        self._set_track(controller.current_track)
        self._set_volume(controller.volume_percent)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)

    def focus_close(self) -> None:
        self._close.setFocus(Qt.FocusReason.OtherFocusReason)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._video_output is not None:
            self._video_output.set_video_output(self._video)

    def hideEvent(self, event: QHideEvent) -> None:
        if self._video_output is not None:
            self._video_output.set_video_output(None)
        super().hideEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _set_track(self, track: Track | None) -> None:
        self._failure = None
        with QSignalBlocker(self._position):
            self._position.setSliderDown(False)
            self._position.setRange(0, max(0, track.length_ms) if track else 0)
        self._position.set_chapters(playback_chapters(track))
        for widget in (self._previous, self._play, self._next, self._position):
            widget.setEnabled(track is not None)
        self._set_position(self._controller.position_ms)
        self.retranslate_ui()

    def _set_position(self, position_ms: int) -> None:
        if self._position.isSliderDown():
            return
        with QSignalBlocker(self._position):
            self._position.setValue(position_ms)
        self._elapsed.setText(format_playback_time(self._position.value()))

    def _scrubbed(self, position_ms: int) -> None:
        self._elapsed.setText(format_playback_time(position_ms))
        if not self._position.isSliderDown():
            self._controller.seek(position_ms)

    def _seek_released(self) -> None:
        self._controller.seek(self._position.value())

    def _set_playing(self, playing: bool) -> None:
        if playing and self._failure is not None:
            self._failure = None
            self._refresh_message()
        self._play.set_glyph("pause" if playing else "play")
        name = self.tr("Pause") if playing else self.tr("Play")
        self._play.setAccessibleName(name)
        self._play.setToolTip(name)

    def _set_volume(self, percent: int) -> None:
        with QSignalBlocker(self._volume):
            self._volume.setValue(percent)

    def _refresh_subtitles(self) -> None:
        output = self._video_output
        tracks = output.subtitle_tracks if output is not None else ()
        active = output.active_subtitle_track if output is not None else -1
        with QSignalBlocker(self._subtitles):
            self._subtitles.clear()
            self._subtitles.addItem(self.tr("Off"), -1)
            for track in tracks:
                label = " · ".join(
                    part for part in (track.title, track.language) if part
                )
                self._subtitles.addItem(
                    label
                    or self.tr("Subtitle {number}").format(number=track.index + 1),
                    track.index,
                )
            self._subtitles.setCurrentIndex(max(0, self._subtitles.findData(active)))
        self._subtitles.setEnabled(bool(tracks))
        self._subtitles.setToolTip(
            self.tr("Subtitles") if tracks else self.tr("No embedded subtitles")
        )

    def _subtitle_selected(self, _row: int) -> None:
        index = self._subtitles.currentData()
        if self._video_output is not None and isinstance(index, int):
            self._video_output.set_subtitle_track(index)

    def _playback_failed(self, value: object) -> None:
        if isinstance(value, PlaybackFailure):
            self._failure = value.message
            self._refresh_message()

    def _refresh_message(self) -> None:
        self._unavailable.setText(
            workflow_text(self._failure)
            if self._failure is not None
            else self.tr("Video output is unavailable.")
        )
        self._unavailable.setVisible(
            self._failure is not None or self._video_output is None
        )

    def retranslate_ui(self) -> None:
        track = self._controller.current_track
        self._title.setText(
            (track.title or self.tr("Untitled Track"))
            if track
            else self.tr("Nothing playing")
        )
        self._duration.setText(format_playback_time(self._position.maximum()))
        self._position.setAccessibleName(self.tr("Playback position"))
        self._volume.setAccessibleName(self.tr("Volume"))
        self._volume_label.setText(self.tr("Volume"))
        self._subtitle_label.setText(self.tr("Subtitles"))
        self._subtitles.setAccessibleName(self.tr("Subtitles"))
        self._refresh_subtitles()
        self._video.setAccessibleName(self.tr("Video"))
        self._refresh_message()
        chapters = playback_chapters(track)
        for button, name in (
            (self._close, self.tr("Close video player")),
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
        self._set_playing(self._controller.playing)
