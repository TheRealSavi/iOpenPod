"""Video viewing keeps the existing Playback Entry, transport and shell state."""

from collections.abc import Callable
from dataclasses import replace

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QSlider, QStackedWidget, QToolButton, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.playback.backend import PlaybackFailure
from iOpenPod.app.playback.video_output import PlaybackSubtitleTrack
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.pages.now_playing_page import NowPlayingPage
from iOpenPod.GUI.pages.video_player_page import VideoPlayerPage
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import IconButton
from iPodDB.library import MediaType, Track


class _VideoOutput:
    def __init__(self) -> None:
        self.output: QObject | None = None
        self.subtitle_tracks: tuple[PlaybackSubtitleTrack, ...] = ()
        self.active_subtitle_track = -1
        self.subtitle_choices: list[int] = []
        self._subtitle_callbacks: list[Callable[[], None]] = []

    def set_video_output(self, output: QObject | None) -> None:
        self.output = output

    def current_output(self) -> QObject | None:
        return self.output

    def subscribe_subtitles_changed(self, callback: Callable[[], None]) -> None:
        self._subtitle_callbacks.append(callback)

    def set_subtitle_track(self, index: int) -> None:
        self.subtitle_choices.append(index)
        self.active_subtitle_track = index
        self.notify_subtitles_changed()

    def notify_subtitles_changed(self) -> None:
        for callback in self._subtitle_callbacks:
            callback()


def _child[T: QWidget](parent: QWidget, kind: type[T], name: str) -> T:
    child = parent.findChild(kind, name)
    assert child is not None
    return child


def _video(number: int = 1, media_type: MediaType = MediaType.VIDEO) -> Track:
    return Track(
        number, f"Video {number}", "Artist", "Album", 180_000, media_types=(media_type,)
    )


@pytest.mark.parametrize(
    "media_type",
    (
        MediaType.VIDEO,
        MediaType.AUDIO_VIDEO,
        MediaType.TV_SHOW,
        MediaType.MUSIC_VIDEO,
        MediaType.VIDEO_PODCAST,
    ),
)
@pytest.mark.parametrize("paused", (False, True))
def test_artwork_opens_video_and_escape_restores_shell_without_restarting(
    media_type: MediaType,
    paused: bool,
) -> None:
    backend = FakePlaybackBackend()
    output = _VideoOutput()
    context = replace(
        build_context(playback_backend=backend), playback_video_output=output
    )
    controller = context.playback_controller
    track = _video(media_type=media_type)
    controller.play_now((track, _video(2)))
    backend.emit_position(42_000)
    if paused:
        controller.pause()
    window = MainWindow(context, auto_discover=False)
    try:
        window.resize(1100, 720)
        window.show()
        window.activateWindow()
        APPLICATION.processEvents()
        workspaces = _child(window, QStackedWidget, "workspaceStack")
        workspaces.setCurrentWidget(_child(window, QWidget, "syncWorkspace"))
        entry = controller.current_entry_id
        pending = controller.queue_model.entries
        history = controller.history_model.entries
        artwork = _child(window, QToolButton, "playerArtworkButton")
        assert artwork.toolTip() == "Open video player"
        artwork.click()
        page = _child(window, VideoPlayerPage, "videoPlayerPage")
        assert page.isVisible()
        assert not _child(window, NowPlayingPage, "nowPlayingPage").isVisible()
        assert output.current_output() is _child(
            page, QVideoWidget, "videoPlayerSurface"
        )
        assert _child(page, QSlider, "videoPlayerProgress").value() == 42_000
        assert window.statusBar().isHidden()
        QTest.keyClick(_child(page, IconButton, "videoPlayerClose"), Qt.Key.Key_Escape)
        assert output.output is None
        assert _child(window, QWidget, "appShell").isVisible()
        assert workspaces.currentWidget() is _child(window, QWidget, "syncWorkspace")
        assert not window.statusBar().isHidden()
        assert artwork.hasFocus()
        assert controller.current_entry_id == entry
        assert controller.position_ms == 42_000
        assert controller.playing is not paused
        assert controller.queue_model.entries == pending
        assert controller.history_model.entries == history
        assert backend.started == [track]
        assert backend.seeks == []
    finally:
        window.close()
        context.shutdown()


def test_video_transport_and_mixed_queue_follow_one_controller() -> None:
    backend = FakePlaybackBackend()
    output = _VideoOutput()
    context = replace(
        build_context(playback_backend=backend), playback_video_output=output
    )
    controller = context.playback_controller
    audio = Track(3, "Audio", "Artist", "Album", 180_000)
    controller.play_now((_video(), _video(2), audio, _video(4)))
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        window.activateWindow()
        APPLICATION.processEvents()
        _child(window, QToolButton, "playerArtworkButton").click()
        page = _child(window, VideoPlayerPage, "videoPlayerPage")
        play = _child(page, IconButton, "videoPlayerPlayPause")
        play.click()
        assert not controller.playing and backend.pause_calls == 1
        QTest.keyClick(play, Qt.Key.Key_Space)
        assert controller.playing and backend.play_calls == 1
        slider = _child(page, QSlider, "videoPlayerProgress")
        backend.emit_position(40_000)
        assert slider.value() == 40_000 and backend.seeks == []
        slider.setSliderDown(True)
        slider.setValue(12_000)
        backend.emit_position(45_000)
        assert slider.value() == 12_000
        assert _child(page, QLabel, "videoPlayerElapsed").text() == "0:12"
        slider.setSliderDown(False)
        assert backend.seeks == [12_000]
        QTest.keyClick(slider, Qt.Key.Key_Right)
        assert backend.seeks[-1] == 13_000
        volume = _child(page, QSlider, "videoPlayerVolume")
        volume.setValue(23)
        assert controller.volume_percent == backend.volume_percent == 23
        controller.set_volume(48)
        assert volume.value() == 48
        slider.setSliderDown(True)
        slider.setValue(22_000)
        _child(page, IconButton, "videoPlayerNext").click()
        assert controller.current_track == _video(2)
        assert not slider.isSliderDown() and slider.value() == 0
        assert backend.seeks == [12_000, 13_000]
        _child(page, IconButton, "videoPlayerPrevious").click()
        assert controller.current_track == _video()
        backend.finish()
        backend.finish()
        assert controller.current_track == audio
        assert output.output is None
        assert _child(window, NowPlayingPage, "nowPlayingPage").isVisible()
        backend.finish()
        assert page.isVisible() and output.output is not None
        controller.clear_session()
        assert output.output is None
        assert _child(window, QWidget, "appShell").isVisible()
        assert not window.statusBar().isHidden()
    finally:
        window.close()
        context.shutdown()


def test_video_errors_remain_visible_and_play_retries_the_current_entry() -> None:
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    controller = context.playback_controller
    page = VideoPlayerPage(controller, _VideoOutput())
    try:
        controller.play_now((_video(),))
        entry = controller.current_entry_id
        attempt = backend.current_attempt_id
        assert attempt is not None
        backend.fail(
            PlaybackFailure(attempt, 1, "Unsupported video codec", "FormatError")
        )
        page.show()
        message = _child(page, QLabel, "videoPlayerUnavailable")
        assert message.isVisible() and message.text() == "Unsupported video codec"
        assert not controller.playing
        _child(page, IconButton, "videoPlayerPlayPause").click()
        assert controller.playing and message.isHidden()
        assert controller.current_entry_id == entry
        assert backend.started == [_video(), _video()]
    finally:
        page.close()
        context.shutdown()


def test_subtitle_choices_follow_decoder_state_without_transport_intents() -> None:
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    controller = context.playback_controller
    output = _VideoOutput()
    page = VideoPlayerPage(controller, output)
    try:
        controller.play_now((_video(),))
        controller.pause()
        page.show()
        selector = _child(page, AppComboBox, "videoPlayerSubtitles")
        assert not selector.isEnabled()
        assert selector.toolTip() == "No embedded subtitles"
        output.subtitle_tracks = (
            PlaybackSubtitleTrack(0, "Dialogue", "English"),
            PlaybackSubtitleTrack(1, language="Spanish"),
            PlaybackSubtitleTrack(2),
        )
        output.notify_subtitles_changed()
        assert selector.isEnabled()
        assert [selector.itemText(row) for row in range(selector.count())] == [
            "Off",
            "Dialogue · English",
            "Spanish",
            "Subtitle 3",
        ]
        assert output.subtitle_choices == []
        selector.setCurrentIndex(2)
        assert output.subtitle_choices == [1]
        page.hide()
        page.show()
        page.retranslate_ui()
        assert selector.currentData() == 1
        assert output.subtitle_choices == [1]
        selector.setCurrentIndex(0)
        assert output.subtitle_choices == [1, -1]
        output.subtitle_tracks = ()
        output.active_subtitle_track = -1
        output.notify_subtitles_changed()
        assert not selector.isEnabled() and selector.currentText() == "Off"
        assert not controller.playing
        assert backend.seeks == [] and backend.started == [_video()]
        assert backend.play_calls == 0 and backend.pause_calls == 1
    finally:
        page.close()
        context.shutdown()
