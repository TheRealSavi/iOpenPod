"""Application Podcast publication uses native type 4 without rewriting reads."""

from dataclasses import replace

import pytest
from tests.iOpenPod.app.podcast_sync_test_support import podcast_addition
from tests.iPodDB.library.test_finder_podcasts import finder_source

from iOpenPod.app.podcasts.media import episode_track
from iOpenPod.app.track_playback_policy import enforce_library_playback_policy
from iPodDB.iTunesDB.cdb import compress_iTunesCDB, decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, MediaType, WriteResources, WriteTarget


@pytest.mark.parametrize("video", (False, True))
def test_incoming_episode_uses_podcast_classification(video: bool) -> None:
    track = episode_track(podcast_addition(), video=video)

    assert track.media_types == (
        MediaType.VIDEO_PODCAST if video else MediaType.PODCAST,
    )


@pytest.mark.parametrize("compressed", (False, True))
@pytest.mark.parametrize("retained_type", (4, 5, 6))
def test_application_save_writes_audio_podcast_type_four(
    compressed: bool, retained_type: int
) -> None:
    document = parse_iTunesDB(finder_source().serialize().itunes)
    for selection in document.find_chunks(MhitHeader):
        document = document.replace_chunk(
            selection,
            replace(
                selection.chunk,
                header=replace(selection.chunk.header, media_type=retained_type),
            ),
        )
    raw = write_iTunesDB(document)
    original = compress_iTunesCDB(raw) if compressed else raw
    source = IPodLibrary(original)
    unchanged = source.prepare(source.analyze(source.begin_draft()))
    assert unchanged.prepared is not None, unchanged.issues
    assert unchanged.prepared.itunes == original

    desired = enforce_library_playback_policy(source.snapshot)
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired),
            WriteTarget(compressed_database=compressed),
        ),
        WriteResources(pending_playback_sidecars=False),
    )

    assert result.prepared is not None, result.issues
    data = result.prepared.itunes
    checked = parse_iTunesDB(
        decompress_iTunesCDB(data).logical_bytes if compressed else data
    )
    headers = [s.chunk.header for s in checked.find_chunks(MhitHeader)]
    assert headers
    assert {h.media_type for h in headers} == {6 if retained_type == 6 else 4}
    assert all(h.remember_position and h.skip_when_shuffling for h in headers)
    assert all(h.podcast_now_playing_flag for h in headers)
    assert [t.metadata.location for t in result.prepared.snapshot.tracks] == [
        t.metadata.location for t in source.snapshot.tracks
    ]
    assert source.serialize().itunes == original
