"""Realistic membership edits carry source-bound occurrences without native work."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_album_write_regressions import album_source
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.library import IPodLibrary, PlaylistEntry, WriteResources


def positioned_source(*, podcasts: bool) -> IPodLibrary:
    if podcasts:
        return album_source(grouped=True)
    source = library()
    playlist = source.snapshot.playlists[0]
    desired = replace(
        source.snapshot,
        playlists=(
            replace(
                playlist,
                entries=tuple(
                    replace(e, position=i) for i, e in enumerate(playlist.entries)
                ),
            ),
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    return IPodLibrary(result.prepared.itunes)


@pytest.mark.parametrize("podcasts", [False, True])
@pytest.mark.parametrize("delete_track", [False, True])
def test_membership_edits_retain_occurrences_and_derive_output_positions(
    podcasts: bool, delete_track: bool
) -> None:
    source = positioned_source(podcasts=podcasts)
    before = source.snapshot
    original = source.serialize()
    removed_id = before.playlists[0].entries[0].track_id
    desired = replace(
        before,
        tracks=tuple(
            t for t in before.tracks if not delete_track or t.track_id != removed_id
        ),
        playlists=tuple(
            replace(
                p,
                entries=tuple(e for e in p.entries if e.track_id != removed_id)
                if delete_track
                else tuple(reversed(p.entries)),
            )
            for p in before.playlists
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=delete_track)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert source.serialize() == original
    assert {t.track_id for t in result.prepared.snapshot.tracks} == {
        t.track_id for t in desired.tracks
    }
    checked = parse_iTunesDB(result.prepared.itunes)
    for dataset in checked.find_chunks(MhsdHeader):
        if dataset.chunk.header.dataset_type not in (2, 3):
            continue
        for playlist in dataset.find_chunks(MhypHeader):
            if playlist.chunk.header.playlist_id != before.playlists[0].playlist_id:
                continue
            episodes = tuple(
                s.chunk
                for s in playlist.find_chunks(MhipHeader)
                if s.chunk.header.track_id
            )
            for i, item in enumerate(episodes):
                expected = (
                    item.header.group_id
                    if podcasts and dataset.chunk.header.dataset_type == 3
                    else i
                )
                positions = tuple(
                    c.prefix.position
                    for c in item.children
                    if isinstance(c.prefix, MhodPlaylistPositionPrefix)
                )
                assert positions and set(positions) == {expected}


@pytest.mark.parametrize("new_occurrence", [False, True])
def test_explicit_conflicting_positions_remain_invalid(new_occurrence: bool) -> None:
    source = positioned_source(podcasts=False)
    playlist = source.snapshot.playlists[0]
    changed = (
        PlaylistEntry("new", 1, 999)
        if new_occurrence
        else replace(playlist.entries[0], position=999)
    )
    entries = (
        (*playlist.entries, changed)
        if new_occurrence
        else (changed, *playlist.entries[1:])
    )
    desired = replace(source.snapshot, playlists=(replace(playlist, entries=entries),))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any(i.code == "playlist.invalid_position" for i in result.issues)
