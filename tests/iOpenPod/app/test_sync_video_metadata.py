"""Firmware subtitle descriptors follow final media through normal Sync."""

import hashlib
import json
import shutil
import sqlite3
import subprocess
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from threading import Event
from typing import NoReturn

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_music_import import build_nano5_device
from tests.iOpenPod.app.test_sync_execution import (
    _request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_stream_selection import host_library
from tests.iOpenPod.app.test_video_preparation import (
    _FFmpeg,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_video_preparation import captioned_video as captioned_video
from tests.iOpenPod.app.test_video_preparation import ffmpeg as ffmpeg
from tests.iOpenPod.app.test_video_preparation import video as video
from tests.iPodDB.SQLiteDB.sqlite_test_support import sqlite_rows

from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.media import MediaInspector
from iOpenPod.app.media.models import StreamKind
from iOpenPod.app.media.transcoding import MediaTranscoder
from iOpenPod.app.services import video_metadata
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
)
from iOpenPod.app.sync_plan import SyncPlan
from iPodDB.library import FileDependency, LibrarySnapshot
from storage import DevicePath, HostPath

_LIBRARY = "iPod_Control/iTunes/iTunes Library.itlp/Library.itdb"
_DESCRIPTORS = (
    "SELECT has_subtitles, has_closed_captions, characteristics_valid, "
    "subtitle_language, subtitle_track_index, subtitle_track_id FROM video_info"
)


@pytest.fixture
def subtitled_video(tmp_path: Path, video: Path, ffmpeg: _FFmpeg) -> Path:
    subtitles = tmp_path / "subtitles.srt"
    subtitles.write_text(
        "1\n00:00:00,200 --> 00:00:02,800\nBonjour\n", encoding="utf-8"
    )
    path = tmp_path / "subtitled.mp4"
    ffmpeg(
        "-i",
        str(video),
        "-i",
        str(subtitles),
        "-map",
        "0:v",
        "-map",
        "0:a",
        "-map",
        "1:s",
        "-c",
        "copy",
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        "language=fra",
        str(path),
    )
    return path


@pytest.mark.parametrize("captions", [False, True])
def test_normal_nano_sync_writes_final_video_descriptors(
    tmp_path: Path, subtitled_video: Path, captioned_video: Path, captions: bool
) -> None:
    device = build_nano5_device(tmp_path)
    try:
        result = SyncExecutor(device.coordinator).execute(
            _request(
                device, host_library(captioned_video if captions else subtitled_video)
            ),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert sqlite_rows((device.root / _LIBRARY).read_bytes(), _DESCRIPTORS) == (
            (0, 1, 1, None, None, None) if captions else (1, 0, 1, 6721, 2, 3),
        )
    finally:
        device.coordinator.close()


def _refresh(device: Device) -> SyncExecutionRequest:
    return SyncExecutionRequest(
        SyncPlan(()),
        HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats()),
        IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
        device.active,
        1,
        1,
        reconcile_playlists=False,
    )


def _legacy_video(device: Device, source: Path) -> Path:
    result = SyncExecutor(device.coordinator).execute(
        _request(device, host_library(source)), lambda _: None, Event()
    )
    assert result.status is SyncExecutionStatus.SUCCESS, result.issues
    track = next(t for t in device.active.library.tracks if t.title == "Edition")
    path = device.root / track.metadata.location
    with closing(sqlite3.connect(device.root / _LIBRARY)) as connection:
        connection.execute(
            "UPDATE video_info SET has_subtitles=NULL,has_closed_captions=NULL,"
            "characteristics_valid=NULL,subtitle_language=NULL,"
            "subtitle_track_index=NULL,subtitle_track_id=NULL,"
            "audio_language=1234,extended_content_rating='Keep me'"
        )
        connection.commit()
    return path


@pytest.mark.parametrize("captions", [False, True])
def test_unchanged_sync_repairs_existing_video_once_without_media_writes(
    tmp_path: Path,
    subtitled_video: Path,
    captioned_video: Path,
    captions: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_nano5_device(tmp_path)
    try:
        path = _legacy_video(device, captioned_video if captions else subtitled_video)
        before = hashlib.sha256(path.read_bytes()).digest(), path.stat().st_mtime_ns
        cdb = device.root / "iPod_Control/iTunes/iTunesCDB"
        original_cdb = cdb.read_bytes()

        def fail_preparation(
            _transcoder: MediaTranscoder, *, checkpoint: Callable[[], None]
        ) -> NoReturn:
            pytest.fail("Repair must not prepare media")

        monkeypatch.setattr(MediaTranscoder, "preflight", fail_preparation)
        result = SyncExecutor(device.coordinator).execute(
            _refresh(device), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert sqlite_rows((device.root / _LIBRARY).read_bytes(), _DESCRIPTORS) == (
            (0, 1, 1, None, None, None) if captions else (1, 0, 1, 6721, 2, 3),
        )
        assert sqlite_rows(
            (device.root / _LIBRARY).read_bytes(),
            "SELECT audio_language,extended_content_rating FROM video_info",
        ) == ((1234, "Keep me"),)
        assert cdb.read_bytes() == original_cdb
        assert (
            hashlib.sha256(path.read_bytes()).digest(),
            path.stat().st_mtime_ns,
        ) == before

        def fail_probe(_name: str) -> NoReturn:
            pytest.fail("Complete metadata must not probe retained video again")

        monkeypatch.setattr(video_metadata, "find_media_tool", fail_probe)
        repeated = SyncExecutor(device.coordinator).execute(
            _refresh(device), lambda _: None, Event()
        )
        assert repeated.status is SyncExecutionStatus.SUCCESS, repeated.issues
        assert cdb.read_bytes() == original_cdb
        assert (
            hashlib.sha256(path.read_bytes()).digest(),
            path.stat().st_mtime_ns,
        ) == before
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("captured_artwork", [False, True])
def test_repair_rechecks_video_before_publishing_metadata(
    tmp_path: Path,
    subtitled_video: Path,
    captured_artwork: bool,
) -> None:
    device = build_nano5_device(tmp_path)
    try:
        path = _legacy_video(device, subtitled_video)
        original = (device.root / _LIBRARY).read_bytes()
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                device.active.library,
                device.active,
                1,
                1,
                regenerate_sqlite=True,
                artwork_dependencies=(
                    FileDependency(
                        path.relative_to(device.root).as_posix(),
                        path.stat().st_size,
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    ),
                )
                if captured_artwork
                else (),
            ),
            lambda _: None,
            Event(),
            allow_unchanged=True,
        )
        assert review.result.prepared is not None, review.result.issues
        assert (
            review.resources is not None and len(review.resources.video_metadata) == 1
        )
        assert all(
            change.path.endswith((".itdb", ".cbk")) for change in review.file_changes
        )
        path.write_bytes(b"externally changed video")
        saved = device.save(review)
        assert saved.active is None
        assert (device.root / _LIBRARY).read_bytes() == original
        assert path.read_bytes() == b"externally changed video"
    finally:
        device.coordinator.close()


def test_unreadable_existing_video_warns_without_inventing_descriptors(
    tmp_path: Path,
    subtitled_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_nano5_device(tmp_path)
    try:
        path = _legacy_video(device, subtitled_video)
        before = path.read_bytes()

        def missing_tool(_name: str) -> None:
            return None

        monkeypatch.setattr(video_metadata, "find_media_tool", missing_tool)
        result = SyncExecutor(device.coordinator).execute(
            _refresh(device), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert any(
            issue.code == "video.metadata_unavailable" for issue in result.issues
        )
        assert sqlite_rows((device.root / _LIBRARY).read_bytes(), _DESCRIPTORS) == (
            (None, None, None, None, None, None),
        )
        assert path.read_bytes() == before
    finally:
        device.coordinator.close()


def test_classic_sync_keeps_subtitles_without_sqlite_observation(
    tmp_path: Path,
    subtitled_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_device(tmp_path)

    def fail_probe(_name: str) -> NoReturn:
        pytest.fail("Classic does not use SQLite video descriptors")

    monkeypatch.setattr(video_metadata, "find_media_tool", fail_probe)
    try:
        result = SyncExecutor(device.coordinator).execute(
            _request(device, host_library(subtitled_video)), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        track = next(t for t in device.active.library.tracks if t.title == "Edition")
        observed = MediaInspector().scan_metadata(
            HostPath(device.root / track.metadata.location), checkpoint=lambda: None
        )
        subtitles = tuple(s for s in observed.streams if s.kind is StreamKind.SUBTITLE)
        assert len(subtitles) == 1
        assert subtitles[0].codec_tag == "tx3g"
        assert not (device.root / _LIBRARY).exists()
        assert DevicePath(track.metadata.location).name.endswith(".m4v")
    finally:
        device.coordinator.close()


def test_video_repair_rejects_corrupt_library_before_publication(
    tmp_path: Path,
    subtitled_video: Path,
) -> None:
    device = build_nano5_device(tmp_path)
    try:
        path = _legacy_video(device, subtitled_video)
        media = path.read_bytes()
        (device.root / _LIBRARY).write_bytes(b"corrupt SQLite")
        result = SyncExecutor(device.coordinator).execute(
            _refresh(device), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.FAILED
        assert (device.root / _LIBRARY).read_bytes() == b"corrupt SQLite"
        assert path.read_bytes() == media
    finally:
        device.coordinator.close()


def test_mixed_video_descriptors_follow_final_track_identity(
    tmp_path: Path,
    subtitled_video: Path,
    captioned_video: Path,
    ffmpeg: _FFmpeg,
) -> None:
    mixed = tmp_path / "mixed.m4v"
    ffmpeg(
        "-i",
        str(subtitled_video),
        "-i",
        str(captioned_video),
        "-map",
        "0:v",
        "-map",
        "0:a",
        "-map",
        "1:s",
        "-map",
        "0:s",
        "-c",
        "copy",
        "-streamid",
        "3:81",
        "-use_stream_ids_as_track_ids",
        "1",
        "-f",
        "mov",
        str(mixed),
    )
    device = build_nano5_device(tmp_path)
    try:
        result = SyncExecutor(device.coordinator).execute(
            _request(device, host_library(mixed)), lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        executable = shutil.which("ffprobe")
        assert executable is not None
        track = next(t for t in device.active.library.tracks if t.title == "Edition")

        def text_track(path: Path) -> tuple[int, int]:
            output = subprocess.run(
                [
                    executable,
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=index,id,codec_tag_string",
                    "-of",
                    "json",
                    str(path),
                ],
                check=True,
                capture_output=True,
            )
            stream = next(
                s
                for s in json.loads(output.stdout)["streams"]
                if s.get("codec_tag_string") == "tx3g"
            )
            return int(stream["index"]), int(stream["id"], 0)

        assert text_track(mixed) == (3, 81)
        # Preparation may remux and renumber tracks. The final file is authoritative.
        index, identity = text_track(device.root / track.metadata.location)
        assert sqlite_rows((device.root / _LIBRARY).read_bytes(), _DESCRIPTORS) == (
            (1, 1, 1, 6721, index, identity),
        )
    finally:
        device.coordinator.close()
