"""Public-contract checks for the Qt Multimedia Playback Backend adapter."""

import logging
from base64 import b64decode
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer, QUrl, qInfo, qWarning
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytest import CaptureFixture, LogCaptureFixture

from iOpenPod.app.display_text import SourceText, source_text
from iOpenPod.app.playback.backend import (
    PlaybackAttemptId,
    PlaybackFailure,
    PlaybackSourceError,
)
from iOpenPod.app.playback.qt_backend import QtPlaybackBackend
from iOpenPod.app.playback.video_output import PlaybackSubtitleTrack
from iOpenPod.app.playback_controller import PlaybackController
from iPodDB.library import Track


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


def _request_log() -> list[tuple[int, int]]:
    return []


@dataclass(frozen=True, slots=True)
class _MemorySource:
    data: bytes
    file_name: str = "tone.wav"
    requests: list[tuple[int, int]] = field(
        default_factory=_request_log,
        compare=False,
    )

    @property
    def byte_count(self) -> int:
        return len(self.data)

    def read_at(self, offset: int, length: int) -> bytes:
        self.requests.append((offset, length))
        return self.data[offset : offset + length]


class _SourceProvider:
    def __init__(self, source: _MemorySource) -> None:
        self.source = source
        self.requested: list[Track] = []

    def open_playback_source(self, track: Track) -> _MemorySource:
        self.requested.append(track)
        return self.source


def test_qt_backend_opens_the_stream_and_accepts_bounded_volume() -> None:
    source = _MemorySource(_silent_wav())
    provider = _SourceProvider(source)
    backend = QtPlaybackBackend(provider)
    track = Track(1, "Tone", "Artist", "Album", 20)
    attempt_id = PlaybackAttemptId(7)

    backend.set_volume(125)
    backend.start(attempt_id, track)
    QTest.qWait(200)

    assert provider.requested == [track]

    backend.stop()
    backend.close()


def test_qt_backend_configuration_suppresses_ffmpeg_diagnostics(
    tmp_path: Path,
    capfd: CaptureFixture[str],
    caplog: LogCaptureFixture,
) -> None:
    source = _MemorySource(_silent_wav())
    backend = QtPlaybackBackend(_SourceProvider(source))
    media_path = tmp_path / "tone.wav"
    media_path.write_bytes(source.data)
    player = QMediaPlayer()

    player.setSource(QUrl.fromLocalFile(str(media_path)))
    QTest.qWait(300)
    caplog.set_level(logging.INFO, logger="qt")
    qInfo('"FFmpeg log: Input #0, diagnostic probe"')
    qWarning("Retained Qt diagnostic")

    assert player.mediaStatus() is not QMediaPlayer.MediaStatus.NoMedia
    assert "Retained Qt diagnostic" in caplog.messages
    assert all("FFmpeg log:" not in message for message in caplog.messages)
    player.stop()
    backend.close()
    captured = capfd.readouterr()
    diagnostics = captured.out + captured.err
    assert "FFmpeg log:" not in diagnostics
    assert "Input #0" not in diagnostics
    assert "Stream #0" not in diagnostics


def test_qt_backend_tags_source_failures_with_the_attempt() -> None:
    class _FailingProvider:
        def open_playback_source(self, track: Track) -> _MemorySource:
            del track
            raise PlaybackSourceError(
                source_text(
                    "The selected Track's media could not be opened: {error}",
                    error="native source unavailable",
                )
            )

    backend = QtPlaybackBackend(_FailingProvider())
    attempt_id = PlaybackAttemptId(9)
    failures: list[PlaybackFailure] = []
    backend.subscribe_failed(failures.append)

    backend.start(attempt_id, Track(4, "Missing", "Artist", "Album", 20))

    assert len(failures) == 1
    failure = failures[0]
    assert failure.attempt_id == attempt_id
    assert isinstance(failure.message, SourceText)
    assert failure.message.source == (
        "The selected Track's media could not be opened: {error}"
    )
    assert dict(failure.message.parameters) == {"error": "native source unavailable"}
    assert failure.error_type == "PlaybackSourceError"
    backend.close()


def _silent_wav() -> bytes:
    samples = b"\x00\x00" * 16
    sample_rate = 8_000
    byte_rate = sample_rate * 2
    header = (
        b"RIFF"
        + (36 + len(samples)).to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + sample_rate.to_bytes(4, "little")
        + byte_rate.to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
        + b"data"
        + len(samples).to_bytes(4, "little")
    )
    return header + samples


@pytest.mark.parametrize("attach_while_paused", (False, True))
def test_video_output_preserves_paused_stream(attach_while_paused: bool) -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "media" / "silent.mp4.b64"
    source = _MemorySource(b64decode(fixture.read_bytes()), file_name="clip.mp4")
    provider = _SourceProvider(source)
    backend = QtPlaybackBackend(provider)
    surface = QVideoWidget()
    surface.resize(640, 360)
    surface.show()
    player = backend.findChild(QMediaPlayer)
    assert player is not None
    failures: list[PlaybackFailure] = []
    backend.subscribe_failed(failures.append)
    try:
        if not attach_while_paused:
            backend.set_video_output(surface)
        backend.start(PlaybackAttemptId(1), Track(1, "Video", "", "", 250))
        if attach_while_paused:
            for _ in range(100):
                if player.videoSink().videoFrame().isValid() or failures:
                    break
                _run_event_loop(5)
            backend.pause()
            backend.set_video_output(surface)
        for _ in range(100):
            if surface.videoSink().videoFrame().isValid() or failures:
                break
            _run_event_loop(20)
        backend.pause()
        frame = surface.videoSink().videoFrame()
        assert not failures
        assert frame.isValid()
        image = frame.toImage()
        assert (image.width(), image.height()) == (320, 240)
        color = image.pixelColor(image.width() // 2, image.height() // 2)
        assert color.blue() > 150 and color.red() < 80
        position = player.position()
        state = player.playbackState()
        assert state == QMediaPlayer.PlaybackState.PausedState
        backend.set_video_output(None)
        assert player.property("videoOutput") is None
        backend.set_video_output(surface)
        _run_event_loop(50)
        assert player.videoOutput() is surface
        assert player.position() == position
        assert player.playbackState() == state
        assert surface.videoSink().videoFrame().isValid()
        assert provider.requested == [Track(1, "Video", "", "", 250)]
        assert source.requests
        backend.close()
        assert player.property("videoOutput") is None
        assert not surface.videoSink().videoFrame().isValid()
        assert not player.videoSink().videoFrame().isValid()
        backend.set_video_output(surface)
        assert player.property("videoOutput") is None
    finally:
        backend.close()
        surface.close()


def _run_event_loop(milliseconds: int) -> None:
    # Unlike QTest.qWait, exec releases the GIL while Qt's render thread works.
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def test_shutdown_tolerates_a_video_surface_destroyed_by_its_owner() -> None:
    backend = QtPlaybackBackend(_SourceProvider(_MemorySource(_silent_wav())))
    surface = QVideoWidget()
    backend.set_video_output(surface)
    surface.deleteLater()
    _run_event_loop(20)
    backend.stop()
    backend.close()


def test_embedded_tx3g_subtitles_decode_and_follow_video_surface_lifetime() -> None:
    fixture = (
        Path(__file__).parents[2] / "fixtures" / "media" / "playback-subtitles.mp4.b64"
    )
    provider = _SourceProvider(
        _MemorySource(b64decode(fixture.read_bytes()), "clip.m4v")
    )
    backend = QtPlaybackBackend(provider)
    surface = QVideoWidget()
    player = backend.findChild(QMediaPlayer)
    assert player is not None
    notifications: list[tuple[PlaybackSubtitleTrack, ...]] = []
    backend.subscribe_subtitles_changed(
        lambda: notifications.append(backend.subtitle_tracks)
    )
    track = Track(1, "Subtitles", "", "", 4000)
    try:
        backend.start(PlaybackAttemptId(1), track)
        for _ in range(100):
            if backend.subtitle_tracks:
                break
            _run_event_loop(5)
        assert backend.subtitle_tracks == (
            PlaybackSubtitleTrack(0, language="English"),
        )
        assert any(notifications)
        assert backend.active_subtitle_track == -1
        backend.set_subtitle_track(0)
        for _ in range(300):
            if player.videoSink().subtitleText():
                break
            _run_event_loop(5)
        backend.pause()
        assert player.videoSink().subtitleText() == "Test subtitle"
        position = player.position()
        backend.set_video_output(surface)
        assert surface.videoSink().subtitleText() == "Test subtitle"
        backend.set_video_output(None)
        assert surface.videoSink().subtitleText() == ""
        assert player.videoSink().subtitleText() == "Test subtitle"
        backend.set_video_output(surface)
        assert surface.videoSink().subtitleText() == "Test subtitle"
        assert player.position() == position
        assert player.playbackState() == QMediaPlayer.PlaybackState.PausedState
        assert provider.requested == [track]
        backend.set_subtitle_track(99)
        assert backend.active_subtitle_track == 0
        backend.set_subtitle_track(-1)
        assert backend.active_subtitle_track == -1
        assert surface.videoSink().subtitleText() == ""
        backend.set_subtitle_track(0)
        backend.seek(1500)
        backend.play()
        for _ in range(100):
            if surface.videoSink().subtitleText():
                break
            _run_event_loop(5)
        backend.pause()
        assert surface.videoSink().subtitleText() == "Test subtitle"
        backend.stop()
        assert not backend.subtitle_tracks and backend.active_subtitle_track == -1
        assert surface.videoSink().subtitleText() == ""
        assert notifications[-1] == ()
        backend.start(PlaybackAttemptId(2), track)
        for _ in range(100):
            if backend.subtitle_tracks:
                break
            _run_event_loop(5)
        assert backend.subtitle_tracks and backend.active_subtitle_track == -1
    finally:
        backend.close()
        surface.close()


def test_subtitle_selection_at_start_does_not_finish_the_playback_entry() -> None:
    fixture = (
        Path(__file__).parents[2] / "fixtures" / "media" / "playback-subtitles.mp4.b64"
    )
    backend = QtPlaybackBackend(
        _SourceProvider(_MemorySource(b64decode(fixture.read_bytes()), "clip.mp4"))
    )
    controller = PlaybackController(backend)
    player = backend.findChild(QMediaPlayer)
    assert player is not None
    selections: list[int] = []

    def select_while_loading() -> None:
        if backend.subtitle_tracks and not selections:
            selections.append(player.position())
            backend.set_subtitle_track(0)

    backend.subscribe_subtitles_changed(select_while_loading)
    current = Track(1, "Current video", "", "", 4000)
    following = Track(2, "Queued video", "", "", 4000)
    try:
        controller.play_now((current, following))
        for _ in range(300):
            if player.videoSink().subtitleText():
                break
            _run_event_loop(5)
        controller.pause()
        assert selections == [0]
        assert controller.current_track == current
        assert controller.queue_model.rowCount() == 1
        assert player.position() < 1000
        assert player.videoSink().subtitleText() == "Test subtitle"
    finally:
        controller.shutdown()
