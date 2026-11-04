"""Replacing media reconciles a retained lyrics flag with the verified new file."""

import io
import shutil
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_first_artwork_save import bare_device
from tests.iOpenPod.app.services.test_library_lyrics import read_lyrics
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_media_lyrics import (
    FRAMES,
    MP3_READER,
    WORDS,
    fixture,
    media_payload,
)
from tests.iOpenPod.app.test_sync_execution import (
    _host,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_library import HostMediaScanner
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.media.lyrics import embedded_lyrics, rewrite_lyrics
from iOpenPod.app.media.lyrics_compatibility import verify_native_lyrics
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionStatus,
    SyncExecutor,
    SyncOptions,
)
from iOpenPod.app.sync_plan import (
    host_path_identity,
    prepare_sync_plan,
    select_sync_plan,
)
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from storage import AtomicHostFile, HostPath


@pytest.mark.parametrize("rockbox", [False, True])
@pytest.mark.parametrize("update", [False, True])
@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="Sync media tools required",
)
def test_sync_converts_classic_lyrics_tags_without_changing_host_or_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rockbox: bool, update: bool
) -> None:
    def fingerprint(*args: object, **kwargs: object) -> str:
        return "1,2,3"

    monkeypatch.setattr(
        "iOpenPod.app.host_media_fingerprint.FpcalcFingerprinter.fingerprint",
        fingerprint,
    )
    path = tmp_path / "Lyrics.mp3"

    def write_source(words: str) -> None:
        stream = io.BytesIO(fixture("tone.mp3"))
        audio = MP3_READER(stream)
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        assert tags is not None
        tags.add(FRAMES.USLT(encoding=3, lang="eng", desc="", text=words))
        tags.add(FRAMES.TDOR(encoding=3, text="2001-02-03"))
        stream.seek(0)
        audio.save(stream, v2_version=4)
        path.write_bytes(stream.getvalue())

    device = bare_device(tmp_path, model_number="MC297")
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "host-cache.json"))
    ipod = IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
    try:
        for words in ("Old lyrics", WORDS * 8) if update else (WORDS * 8,):
            write_source(words)
            original = path.read_bytes()
            modified = path.stat().st_mtime_ns
            pending = scanner.scan((), files=(HostPath(path),), checkpoint=lambda: None)
            host = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
            plan = select_sync_plan(
                prepare_sync_plan(host, ipod, device.active.library),
                selected_host_paths=frozenset({host_path_identity(str(path))}),
                selected_ipod_removals=frozenset(),
            )
            if update and words != "Old lyrics":
                assert any(
                    item.metadata_changed and not item.audio_payload_changed
                    for item in plan.items
                )
            result = SyncExecutor(device.coordinator).execute(
                SyncExecutionRequest(
                    plan,
                    host,
                    ipod,
                    device.active,
                    1,
                    1,
                    options=SyncOptions(
                        analyze_for_genius=False,
                        rockbox_metadata=rockbox and words != "Old lyrics",
                    ),
                ),
                lambda _: None,
                Event(),
            )
            assert result.status is SyncExecutionStatus.SUCCESS, result.issues
            assert result.active is not None and result.helper is not None
            assert len(result.completed) == 1
            assert path.read_bytes() == original and path.stat().st_mtime_ns == modified
            track = next(
                track
                for track in result.active.library.tracks
                if track.metadata.lyrics == words
            )
            assert track.metadata.has_lyrics
            output = (device.root / track.metadata.location).read_bytes()
            assert track.size_bytes == len(output)
            assert embedded_lyrics(MP3_READER(io.BytesIO(output))) == words
            assert MP3_READER(io.BytesIO(output)).tags.version == (
                (2, 4, 0) if words == "Old lyrics" else (2, 3, 0)
            )
            assert media_payload(output, ".mp3") == media_payload(original, ".mp3")
            verify_native_lyrics(io.BytesIO(output), track.metadata.location, words)
            ipod = result.helper
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("rockbox", [False, True])
@pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe", "fpcalc")),
    reason="Sync media tools required",
)
def test_sync_replacement_clears_unloaded_old_lyrics_flag_after_verifying_empty_tags(
    tmp_path: Path, rockbox: bool
) -> None:
    original = rewrite_lyrics(fixture("tone.m4a"), "tone.m4a", "Old file-only lyrics")
    replacement = fixture("tone.m4a")
    device = build_device(tmp_path, media_payload=original)
    try:
        # A native database advertises file-only lyrics without an MHOD text copy.
        # Retain an upper bit too, so the result must be an authored canonical 0.
        device.coordinator.close()
        database = device.root / "iPod_Control/iTunes/iTunesDB"
        document = parse_iTunesDB(database.read_bytes())
        selected = document.find_chunks(MhitHeader)[0]
        document = document.replace_chunk(
            selected,
            replace(
                selected.chunk,
                header=replace(selected.chunk.header, lyrics_flag=3),
            ),
        )
        database.write_bytes(write_iTunesDB(document))
        device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        before, second = device.active.library.tracks
        assert before.metadata.has_lyrics and before.metadata.lyrics == ""
        host = _host(tmp_path, "Replacement", payload=replacement)
        request = replace(
            _request(device, host, update=True),
            options=SyncOptions(rockbox_metadata=rockbox),
        )
        result = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, [
            (issue.code, issue.message, issue.detail) for issue in result.issues
        ]
        assert result.active is not None
        updated = next(
            track
            for track in result.active.library.tracks
            if track.track_id == before.track_id
        )
        assert updated.metadata.lyrics == "" and not updated.metadata.has_lyrics
        written = (device.root / updated.metadata.location).read_bytes()
        assert read_lyrics(written) == ""
        assert media_payload(written, ".m4a") == media_payload(replacement, ".m4a")
        headers = {
            selection.chunk.header.track_id: selection.chunk.header
            for selection in parse_iTunesDB(database.read_bytes()).find_chunks(
                MhitHeader
            )
        }
        assert headers[before.track_id].lyrics_flag == 0
        assert (device.root / second.metadata.location).read_bytes() == original
    finally:
        device.coordinator.close()
