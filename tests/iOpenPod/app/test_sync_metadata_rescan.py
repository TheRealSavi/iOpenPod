"""Real acoustic evidence survives Host and retained iPod metadata edits."""

import math
import random
import shutil
import struct
import wave
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import NoReturn

import pytest
from tests.iOpenPod.app.services.test_first_artwork_save import bare_device
from tests.iOpenPod.app.test_sync_updates import (
    _mp3_audio_bytes,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.export_tagging import ExportMediaTagger
from iOpenPod.app.host_media_library import (
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaScanner,
)
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.media.inspection import MediaInspector
from iOpenPod.app.media.transcoding import (
    LossyEncoder,
    MediaTranscoder,
    TranscodeSettings,
)
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
)
from iOpenPod.app.sync_plan import (
    SyncPlanAction,
    host_path_identity,
    prepare_sync_plan,
    select_sync_plan,
)
from iPodDB.library import ArtworkPixels, Track, TrackChapter
from storage import AtomicHostFile, HostPath
from storage.media_processing import run_media_tool

pytestmark = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe", "fpcalc")),
    reason="Real FFmpeg and Chromaprint tools are required",
)


class _NoMediaPreparation(MediaTranscoder):
    def preflight(self, *, checkpoint: Callable[[], None]) -> NoReturn:
        pytest.fail("A metadata-only rescan must not prepare replacement media")


def _write_audio(path: Path) -> None:
    """Supply repeatable changing audio long enough for actual Chromaprint."""
    rate = 22050
    rng = random.Random(563)
    samples = bytearray()
    for index in range(rate * 12):
        seconds = index / rate
        value = int(
            13000 * math.sin(2 * math.pi * (220 + 70 * int(seconds)) * seconds)
            + rng.uniform(-2000, 2000)
        )
        samples.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        stream.writeframes(samples)


def _m4a_with_cover_and_chapters(source: Path, codec: str) -> Path:
    output = source.with_suffix(".m4a")
    chapters = source.with_suffix(".ffmetadata")
    chapters.write_text(
        ";FFMETADATA1\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=6000\ntitle=Opening\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=6000\nEND=12000\ntitle=Closing\n",
        encoding="utf-8",
    )
    executable = shutil.which("ffmpeg")
    assert executable is not None
    run_media_tool(
        HostPath(executable),
        (
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source),
            "-f",
            "ffmetadata",
            "-i",
            str(chapters),
            "-map",
            "0:a:0",
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-c:a",
            codec,
            str(output),
        ),
        checkpoint=lambda: None,
        timeout_seconds=30,
    )
    ExportMediaTagger().prepare(
        HostPath(output),
        Track(1, "Song", "Artist", "Album", 12_000),
        ArtworkPixels(32, 32, bytes((30, 80, 140)) * 32 * 32),
    )
    observed = MediaInspector().inspect(HostPath(output), checkpoint=lambda: None)
    assert len(observed.audio_streams) == 1
    assert observed.audio_streams[0].codec == codec
    assert not observed.video_streams
    assert len(observed.chapters) == 2
    return output


def _media_payload(path: Path) -> bytes:
    if path.suffix == ".mp3":
        return _mp3_audio_bytes(path)
    # Compare actual M4A media/chapter bytes independently of scan evidence;
    # metadata edits may resize or move their enclosing container atoms.
    data = path.read_bytes()
    chunks: list[bytes] = []
    position = 0
    while position + 8 <= len(data):
        size = int.from_bytes(data[position : position + 4], "big")
        kind = data[position + 4 : position + 8]
        header_size = 8
        if size == 1:
            size = int.from_bytes(data[position + 8 : position + 16], "big")
            header_size = 16
        elif size == 0:
            size = len(data) - position
        assert header_size <= size <= len(data) - position
        if kind == b"mdat":
            chunks.append(data[position + header_size : position + size])
        position += size
    assert position == len(data) and chunks
    return b"".join(chunks)


@pytest.mark.parametrize("edit", ["host", "ipod"])
@pytest.mark.parametrize(
    ("codec", "transcode"),
    [
        pytest.param("wav", True, id="wav-to-mp3"),
        pytest.param("aac", True, id="aac-to-mp3"),
        pytest.param("alac", True, id="alac-to-mp3"),
        pytest.param("aac", False, id="retained-aac"),
        pytest.param("alac", False, id="retained-alac"),
    ],
)
def test_metadata_edit_after_real_media_sync_and_rescan_retains_media(
    tmp_path: Path, edit: str, codec: str, transcode: bool
) -> None:
    path = tmp_path / "Song.wav"
    _write_audio(path)
    if codec != "wav":
        path = _m4a_with_cover_and_chapters(path, codec)
    cache = AtomicHostFile(tmp_path / "host-cache.json")

    def scan() -> HostMediaLibrary:
        scanner = HostMediaScanner(cache)
        pending = scanner.scan((), files=(HostPath(path),), checkpoint=lambda: None)
        return scanner.complete(pending, frozenset(), checkpoint=lambda: None)

    host = scan()
    assert host.sources[0].acoustic_fingerprint
    assert host.sources[0].kind is HostMediaFileKind.AUDIO
    if codec != "wav":
        assert host.snapshot.tracks[0].artwork_id
    selected_paths = frozenset({host_path_identity(str(path))})
    device = bare_device(tmp_path)
    try:
        empty = IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
        selected = select_sync_plan(
            prepare_sync_plan(host, empty, device.active.library),
            selected_host_paths=selected_paths,
            selected_ipod_removals=frozenset(),
        )
        initial = SyncExecutor(device.coordinator).execute(
            SyncExecutionRequest(
                selected,
                host,
                empty,
                device.active,
                1,
                1,
                settings=TranscodeSettings(
                    lossy_encoder=LossyEncoder.MP3,
                    lossless_to_lossy=transcode,
                    retranscode_lossy=transcode,
                ),
            ),
            lambda _: None,
            Event(),
        )
        assert initial.status is SyncExecutionStatus.SUCCESS, initial.issues
        assert initial.active is not None and initial.helper is not None
        track = next(t for t in initial.active.library.tracks if t.title == "Song")
        helper = next(t for t in initial.helper.tracks if t.track_id == track.track_id)
        assert helper.sync is not None
        assert helper.sync.was_transcoded is transcode
        if codec != "wav":
            assert track.metadata.chapters == (
                TrackChapter("Opening", 0),
                TrackChapter("Closing", 6_000),
            )
        output = device.root / track.metadata.location
        encoded_audio = _media_payload(output)
        reloaded = device.coordinator.scan_ipod_media(
            initial.active, lambda _: None, Event()
        )
        assert (
            next(t for t in reloaded.tracks if t.track_id == track.track_id) == helper
        )

        if edit == "host":
            ExportMediaTagger().prepare(
                HostPath(path),
                replace(host.snapshot.tracks[0], title="Updated"),
                None,
                preserve_artwork=True,
            )
        else:
            changed = replace(
                track,
                title="Updated",
                metadata=replace(track.metadata, lyrics="New words"),
            )
            review = device.prepare(
                replace(
                    initial.active.library,
                    tracks=tuple(
                        changed if t.track_id == track.track_id else t
                        for t in initial.active.library.tracks
                    ),
                )
            )
            # Use the ordinary editor save contract; Device.save deliberately
            # retains recovery for transaction tests and skips helper publication.
            saved = device.coordinator.save_library(
                review, device.active, lambda _: None, Event()
            )
            assert saved.active is not None, saved.issues

        host_after = scan()
        assert (
            host_after.sources[0].acoustic_fingerprint
            == host.sources[0].acoustic_fingerprint
        )
        fresh = device.coordinator.scan_ipod_media(
            device.active, lambda _: None, Event()
        )
        evidence = next(t for t in fresh.tracks if t.track_id == track.track_id)
        assert evidence.sync == helper.sync
        assert evidence.acoustic_fingerprint == helper.acoustic_fingerprint
        assert fresh.cache.fingerprinted == 0
        comparison = prepare_sync_plan(host_after, fresh, device.active.library)
        item = next(i for i in comparison.items if i.host_path == str(path))
        assert item.action is SyncPlanAction.UPDATE
        assert item.ipod_id == track.track_id
        assert item.metadata_changed
        assert not item.audio_payload_changed
        selected = select_sync_plan(
            comparison,
            selected_host_paths=selected_paths,
            selected_ipod_removals=frozenset(),
        )
        result = SyncExecutor(
            device.coordinator, transcoder=_NoMediaPreparation()
        ).execute(
            SyncExecutionRequest(selected, host_after, fresh, device.active, 1, 1),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None
        updated = next(
            t for t in result.active.library.tracks if t.track_id == track.track_id
        )
        assert updated.metadata.location == track.metadata.location
        assert updated.metadata.chapters == track.metadata.chapters
        assert _media_payload(output) == encoded_audio
        final = device.coordinator.scan_ipod_media(
            result.active, lambda _: None, Event()
        )
        repeated = prepare_sync_plan(host_after, final, result.active.library)
        assert (
            next(i for i in repeated.items if i.host_path == str(path)).action
            is SyncPlanAction.UNCHANGED
        )
    finally:
        device.coordinator.close()
