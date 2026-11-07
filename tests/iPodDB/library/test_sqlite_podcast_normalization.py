"""Nano Podcast authoring differs from Classic traversal, not show identity."""

from dataclasses import replace
from hashlib import sha256

import pytest
from tests.iPodDB.library.test_podcast_normalization import observed_source
from tests.iPodDB.SQLiteDB.sqlite_test_support import sqlite_rows

from iOpenPod.app.track_playback_policy import enforce_library_playback_policy
from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhii import DEFINITION as MHII
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhli import DEFINITION as MHLI
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, WriteResources
from iPodDB.library.sqlite import SQLiteSource
from iPodDB.library.writing import FileDependency, PreparedMedia, WriteTarget
from iPodDB.shared.chunk import EmptyChunkHeader


@pytest.mark.parametrize("baseline", [True, False])
def test_sqlite_sync_normalizes_both_inputs_adds_episodes_and_repeats(
    baseline: bool,
) -> None:
    source = observed_source(baseline, missing_index=True)
    if baseline:
        doc = parse_iTunesDB(source.serialize().itunes)
        doc = replace(
            doc,
            children=tuple(
                c
                for c in doc.children
                if not isinstance(c.header, MhsdHeader) or c.header.dataset_type != 2
            ),
        )
        source = IPodLibrary(write_iTunesDB(doc))
    first = source.snapshot.tracks[0]
    added = replace(
        first,
        track_id=-1,
        title="Episode between retained dates",
        show=first.album,
        artist="Different episode guest",
        ipod=None,
        size_bytes=4,
        metadata=replace(
            first.metadata,
            release_date=1500,
            location="iPod_Control/Music/F00/added.mp3",
            sample_rate_hz=44100,
            file_format="MPEG audio file",
        ),
    )
    new_show = replace(
        added,
        track_id=-2,
        title="New show episode",
        album="New show",
        show="New show",
        metadata=replace(
            added.metadata,
            location="iPod_Control/Music/F00/new.mp3",
            podcast_rss_url="https://publisher.example/new-feed",
        ),
    )
    desired = enforce_library_playback_policy(
        replace(source.snapshot, tracks=(*source.snapshot.tracks, added, new_show))
    )
    target = WriteTarget(sqlite_database=True)
    result = source.prepare(
        source.analyze(source.begin_draft(desired, normalize_podcasts=True), target),
        WriteResources(
            media=tuple(
                PreparedMedia(
                    t.track_id,
                    FileDependency(t.metadata.location, 4, sha256(b"test").hexdigest()),
                    int.from_bytes(b"MP3 ", "big"),
                    1,
                    0xFFFF,
                    12,
                    0,
                )
                for t in (added, new_show)
            ),
            pending_playback_sidecars=False,
        ),
    )
    assert result.prepared is not None, result.issues
    for _ in range(2):
        prepared = result.prepared
        assert prepared.sqlite is not None
        doc = parse_iTunesDB(prepared.itunes)
        assert (
            any(s.chunk.header.dataset_type == 2 for s in doc.find_chunks(MhsdHeader))
            is not baseline
        )
        assert not any(
            isinstance(s.chunk.prefix, MhodLibraryIndexPrefix)
            and s.chunk.prefix.sort_type == 36
            for s in doc.find_chunks(MhodHeader)
        )
        reloaded = IPodLibrary(prepared.itunes)
        tracks = {t.track_id: t for t in reloaded.snapshot.tracks}
        for selection in doc.find_chunks(MhypHeader):
            if not selection.chunk.header.playlist_kind_flags & 1:
                continue
            episodes = [
                tracks[r.chunk.header.track_id]
                for r in selection.find_chunks(MhipHeader)
                if not r.chunk.header.is_group
            ]
            assert [
                t.metadata.release_date for t in episodes if t.album == first.album
            ] == [1000, 1500, 2000]
        assert sqlite_rows(
            prepared.sqlite.library,
            "SELECT name,kind FROM album ORDER BY name",
        ) == (("New show", 3), ("Podcast", 3), ("Record", 2))
        assert sqlite_rows(
            prepared.sqlite.dynamic,
            "SELECT play_order,is_reversed FROM container_ui WHERE play_order=40",
        ) == ((40, 1),)
        result = reloaded.prepare(
            reloaded.analyze(reloaded.begin_draft(normalize_podcasts=True), target),
            WriteResources(
                pending_playback_sidecars=False,
                sqlite_sources=tuple(
                    SQLiteSource(name, data)
                    for name, data in prepared.sqlite.artifacts()
                    if name.endswith(".itdb")
                ),
            ),
        )
        assert result.prepared is not None, result.issues


def test_normalization_removes_only_unreferenced_artists_without_private_content() -> (
    None
):
    doc = parse_iTunesDB(observed_source(False).serialize().itunes)
    empty = new_itunes_chunk(MHII, MhiiHeader(artist_id=61, sql_id=61))
    private = new_itunes_chunk(MHII, MhiiHeader(artist_id=62, sql_id=62))
    raw = bytearray(80)
    raw[64] = 123
    private = replace(private, raw_header=bytes(raw))
    doc = doc.append_child(
        new_itunes_chunk(
            MHSD,
            MhsdHeader(dataset_type=8),
            children=(
                new_itunes_chunk(MHLI, EmptyChunkHeader(), children=(empty, private)),
            ),
        )
    )
    source = IPodLibrary(write_iTunesDB(doc))
    result = source.prepare(
        source.analyze(
            source.begin_draft(normalize_podcasts=True),
            WriteTarget(sqlite_database=True),
        ),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    artists = {
        s.chunk.header.artist_id: s.chunk for s in checked.find_chunks(MhiiHeader)
    }
    assert 61 not in artists and artists[62].raw_header[64] == 123
