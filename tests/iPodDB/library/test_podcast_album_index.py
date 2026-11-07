"""Podcast sort-36 traversal is independent of Playlist display sort and sort 4."""

from dataclasses import replace
from hashlib import sha256

import pytest
from tests.iPodDB.library.test_album_browse_repair import album_orders, album_source
from tests.iPodDB.library.test_album_index import index_tracks

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTableEntry,
    MhodLibraryJumpTablePayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.device_time import MAC_EPOCH_UNIX_OFFSET
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, WriteResources, _write_preparation
from iPodDB.library.writing import FileDependency, PreparedMedia
from iPodDB.shared.chunk import DatabaseDocument


def podcast_source(*, sort_order: int = 3, media_type: int = 5) -> IPodLibrary:
    source = album_source(("Podcast", "Record"))
    document = parse_iTunesDB(source.serialize().itunes)
    for selection in document.find_chunks(MhitHeader):
        header = selection.chunk.header
        if header.track_id > 2:
            continue
        document = document.replace_chunk(
            selection,
            replace(
                selection.chunk,
                header=replace(
                    header,
                    media_type=media_type,
                    disc_number=0,
                    date_released=MAC_EPOCH_UNIX_OFFSET + header.track_id * 1000,
                ),
            ),
        )
    for album in document.find_chunks(MhiaHeader):
        if album.chunk.header.album_id == 10:
            document = document.replace_chunk(
                album,
                replace(
                    album.chunk,
                    header=replace(album.chunk.header, content_type_flag=3),
                ),
            )
    positions = {track_id: i for i, track_id in enumerate((4, 2, 3, 1))}
    for index in document.find_chunks(MhodHeader):
        payload = index.chunk.payload
        if isinstance(payload, MhodLibraryIndexPayload):
            payload = replace(
                payload, indices=tuple(positions[i] for i in (1, 2, 3, 4))
            )
        elif isinstance(payload, MhodLibraryJumpTablePayload):
            payload = replace(
                payload,
                entries=(
                    MhodLibraryJumpTableEntry(
                        letter_code=80, start_index=0, entry_count=2
                    ),
                    MhodLibraryJumpTableEntry(
                        letter_code=82, start_index=2, entry_count=2
                    ),
                ),
            )
        else:
            continue
        document = document.replace_chunk(index, replace(index.chunk, payload=payload))
    for playlist in document.find_chunks(MhypHeader):
        chunk = playlist.chunk
        if chunk.header.master_flag:
            chunk = replace(
                chunk,
                children=(
                    *(c for c in chunk.children if isinstance(c.header, MhodHeader)),
                    new_itunes_chunk(
                        MHOD,
                        MhodHeader(mhod_type=52),
                        prefix=MhodLibraryIndexPrefix(sort_type=36),
                        payload=MhodLibraryIndexPayload(
                            tuple(positions[i] for i in (2, 1, 3, 4)), b"sort36-tail"
                        ),
                    ),
                    *(
                        c
                        for c in chunk.children
                        if not isinstance(c.header, MhodHeader)
                    ),
                ),
            )
        else:
            chunk = replace(
                chunk,
                header=replace(
                    chunk.header, playlist_kind_flags=1, sort_order=sort_order
                ),
            )
        document = document.replace_chunk(playlist, chunk)
    return IPodLibrary(write_iTunesDB(document))


@pytest.mark.parametrize("sort_order", [1, 3])
@pytest.mark.parametrize("media_type", [5, 6])
def test_disc_edits_keep_podcasts_newest_first_and_music_ascending(
    sort_order: int, media_type: int
) -> None:
    source = podcast_source(sort_order=sort_order, media_type=media_type)
    original = source.serialize().itunes
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared is not None, noop.issues
    assert noop.prepared.itunes == original
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, disc_number=1))
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert index_tracks(result.prepared.itunes) == {2: (2, 1, 3, 4), 3: (2, 1, 3, 4)}
    assert album_orders(result.prepared.itunes) == {2: (1, 2, 3, 4), 3: (1, 2, 3, 4)}
    assert source.serialize().itunes == original


@pytest.mark.parametrize(
    ("release_date", "expected"),
    [(3000, (1, 2, 3, 4)), (2000, (2, 1, 3, 4)), (0, (2, 1, 3, 4))],
)
def test_publication_date_edits_rebuild_podcast_order_with_stable_ties(
    release_date: int, expected: tuple[int, ...]
) -> None:
    source = podcast_source()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, release_date=release_date))
            if t.track_id == 1
            else t
            for t in source.snapshot.tracks
        ),
    )
    plan = source.analyze(source.begin_draft(desired))
    assert plan.resolution is not None
    assert any("sort type 36" in e.reason for e in plan.resolution.effects)
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    assert index_tracks(result.prepared.itunes) == {2: expected, 3: expected}


def test_master_reordering_keeps_podcast_order() -> None:
    source = podcast_source()
    desired = replace(source.snapshot, tracks=tuple(reversed(source.snapshot.tracks)))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert index_tracks(result.prepared.itunes) == {2: (2, 1, 3, 4), 3: (2, 1, 3, 4)}


@pytest.mark.parametrize(("release_date", "position"), [(3000, 0), (2000, 1), (0, 2)])
def test_new_episode_joins_by_publication_date_after_retained_date_ties(
    release_date: int, position: int
) -> None:
    source = podcast_source()
    first = source.snapshot.tracks[0]
    added = replace(
        first,
        track_id=-1,
        title="New episode",
        track_number=999,
        size_bytes=4,
        ipod=None,
        metadata=replace(
            first.metadata,
            release_date=release_date,
            location="iPod_Control/Music/F00/added.mp3",
            sample_rate_hz=44100,
            file_format="MPEG audio file",
        ),
    )
    desired = replace(source.snapshot, tracks=(*source.snapshot.tracks, added))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(
            media=(
                PreparedMedia(
                    -1,
                    FileDependency(
                        added.metadata.location, 4, sha256(b"test").hexdigest()
                    ),
                    int.from_bytes(b"MP3 ", "big"),
                    1,
                    0xFFFF,
                    12,
                    0,
                ),
            ),
            pending_playback_sidecars=False,
        ),
    )
    assert result.prepared is not None, result.issues
    identity = next(
        m.output_id
        for m in result.prepared.identities
        if m.subject == "track" and m.draft_id == -1
    )
    expected = [2, 1, 3, 4]
    expected.insert(position, identity)
    assert index_tracks(result.prepared.itunes) == {
        2: tuple(expected),
        3: tuple(expected),
    }


def test_verifier_rejects_podcast_members_reversed_to_oldest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = podcast_source()

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        for selection in document.find_chunks(MhodHeader):
            chunk = selection.chunk
            if (
                isinstance(chunk.prefix, MhodLibraryIndexPrefix)
                and chunk.prefix.sort_type == 36
            ):
                assert isinstance(chunk.payload, MhodLibraryIndexPayload)
                indices = chunk.payload.indices
                document = document.replace_chunk(
                    selection,
                    replace(
                        chunk,
                        payload=replace(
                            chunk.payload,
                            indices=(3, 2, *indices[2:]),
                        ),
                    ),
                )
        return write_iTunesDB(document)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    desired = replace(source.snapshot, tracks=tuple(reversed(source.snapshot.tracks)))
    result = source.prepare(
        source.analyze(source.begin_draft(desired)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert any(i.code == "verification.playlist_index" for i in result.issues)
