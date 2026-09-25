"""Public-contract checks for the Qt Multimedia Playback Backend adapter."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QUrl, qInfo, qWarning
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytest import CaptureFixture, LogCaptureFixture

from iOpenPod.app.playback.backend import (
    PlaybackAttemptId,
    PlaybackFailure,
    PlaybackSourceError,
)
from iOpenPod.app.playback.qt_backend import QtPlaybackBackend
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
            raise PlaybackSourceError("source unavailable")

    backend = QtPlaybackBackend(_FailingProvider())
    attempt_id = PlaybackAttemptId(9)
    failures: list[PlaybackFailure] = []
    backend.subscribe_failed(failures.append)

    backend.start(attempt_id, Track(4, "Missing", "Artist", "Album", 20))

    assert len(failures) == 1
    failure = failures[0]
    assert failure.attempt_id == attempt_id
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
