"""Replacing media reconciles a retained lyrics flag with the verified new file."""

import shutil
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_lyrics import read_lyrics
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_media_lyrics import fixture, media_payload
from tests.iOpenPod.app.test_sync_execution import (
    _host,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.media.lyrics import rewrite_lyrics
from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor, SyncOptions
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB


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
