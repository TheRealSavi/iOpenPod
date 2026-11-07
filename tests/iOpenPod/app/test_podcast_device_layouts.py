"""Older Device Profiles can retain artist relationships during Podcast imports."""

from dataclasses import replace

import pytest
from tests.iOpenPod.app.podcast_sync_test_support import podcast_addition
from tests.iPodDB.library.test_browse_relationships import browse_source
from tests.iPodDB.library.test_device_header_layouts import short_browse_source
from tests.iPodDB.library.test_media_lifecycle import prepared_media

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.podcasts.media import episode_track
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, WriteResources, WriteTarget


@pytest.mark.parametrize("model", ["M9802", "MA002", "MA444"])
@pytest.mark.parametrize("retained_length", [328, 624])
@pytest.mark.parametrize("retained_version", [0x13, 0x75])
def test_podcast_addition_preserves_artist_links_with_older_device_profiles(
    model: str, retained_length: int, retained_version: int
) -> None:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number(model)
    assert profile is not None
    target = WriteTarget(database_version=profile.capabilities.database.binary_version)
    source = short_browse_source(328) if retained_length == 328 else browse_source()
    document = parse_iTunesDB(source.serialize().itunes)
    document = replace(
        document, header=replace(document.header, version=retained_version)
    )
    original = write_iTunesDB(document)
    source = IPodLibrary(original)

    unchanged = source.prepare(source.analyze(source.begin_draft(), target))
    assert unchanged.prepared is not None, unchanged.issues
    assert unchanged.prepared.itunes == original

    addition = podcast_addition()
    addition = replace(
        addition,
        subscription=replace(
            addition.subscription, author=source.snapshot.tracks[0].artist
        ),
    )
    episode = episode_track(addition, video=False)
    episode = replace(
        episode,
        track_id=-1,
        length_ms=1000,
        size_bytes=4,
        metadata=replace(
            episode.metadata,
            location="iPod_Control/Music/F00/podcast.m4a",
            file_format="AAC audio file",
            sample_rate_hz=44100,
        ),
    )
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, episode))
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        WriteResources(
            media=(prepared_media(episode, b"test"),), pending_playback_sidecars=False
        ),
    )

    assert result.prepared is not None, result.issues
    saved = parse_iTunesDB(result.prepared.itunes)
    tracks = [s.chunk for s in saved.find_chunks(MhitHeader)]
    # Adding to the same artist also requires references on retained short Tracks.
    assert [c.generic_header.header_length for c in tracks] == [624, 624, 624]
    artist_ids = {s.chunk.header.artist_id for s in saved.find_chunks(MhiiHeader)}
    references = {c.header.artist_id_ref for c in tracks}
    assert len(references) == 1 and 0 not in references
    assert references <= artist_ids
    if retained_length == 624:
        assert references == {6}
    assert tracks[-1].header.media_type == 4
    assert result.prepared.snapshot.tracks[-1].metadata.podcast_guid == (
        addition.episode.guid
    )
    assert saved.header.version == max(retained_version, 0x30)
    assert source.serialize().itunes == original
