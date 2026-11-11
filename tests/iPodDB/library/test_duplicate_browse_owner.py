"""Membership changes preserve the native ownership of retained Tracks."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_artist_browse_case import (
    add_track,
    artist_source,
    prepare_tracks,
)
from tests.iPodDB.library.test_browse_relationships import browse_source, text

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary
from iPodDB.library._group_verification import verify_browse_groups
from iPodDB.library._track_writing import edit_text
from iPodDB.library.writing import IssueSeverity, PreparedLibrary


def duplicate_source(kind: str, *, three_tracks: bool = False) -> IPodLibrary:
    names = ("Artist A", "Artist B") if kind == "artist" else ("Artist A", "Artist A")
    source = artist_source(names, shared=kind == "album")
    if three_tracks:
        added = add_track(source, "Artist A", filename="third.mp3")
        assert added.prepared is not None, added.issues
        source = IPodLibrary(added.prepared.itunes)
    document = parse_iTunesDB(source.serialize().itunes)
    track = document.find_chunks(MhitHeader)[1]
    if kind == "artist":
        document = document.replace_chunk(
            track, edit_text(track.chunk, MhodType.ARTIST, "Artist A")
        )
        row = document.find_chunks(MhiiHeader)[1]
        document = document.replace_chunk(
            row, edit_text(row.chunk, MhodType.ARTIST_ITEM_ARTIST, "Artist A")
        )
    else:
        document = document.replace_chunk(
            track, replace(track.chunk, header=replace(track.chunk.header, album_id=8))
        )
        first, second = document.find_chunks(MhiaHeader)
        document = document.replace_chunk(
            second,
            replace(
                first.chunk,
                header=replace(
                    first.chunk.header,
                    album_id=8,
                    sql_id=80,
                    album_track_db_id=track.chunk.header.db_track_id,
                ),
            ),
        )
    return IPodLibrary(write_iTunesDB(document))


def native_links(library: IPodLibrary | PreparedLibrary, kind: str) -> tuple[int, ...]:
    field = "artist_id_ref" if kind == "artist" else "album_id"
    result = []
    for track in library.snapshot.tracks:
        assert track.ipod is not None
        result.append(
            track.ipod.artist_id_ref
            if field == "artist_id_ref"
            else track.ipod.album_id
        )
    return tuple(result)


@pytest.mark.parametrize(("kind", "winner"), [("album", 5), ("artist", 6)])
@pytest.mark.parametrize("three_tracks", [False, True])
def test_addition_uses_existing_owner_without_relinking_retained_tracks(
    kind: str, winner: int, three_tracks: bool
) -> None:
    source = duplicate_source(kind, three_tracks=three_tracks)
    if three_tracks:
        document = parse_iTunesDB(source.serialize().itunes)
        third = document.find_chunks(MhitHeader)[2]
        winner = 9 if kind == "artist" else 8
        header = (
            replace(third.chunk.header, artist_id_ref=winner)
            if kind == "artist"
            else replace(third.chunk.header, album_id=winner)
        )
        document = document.replace_chunk(third, replace(third.chunk, header=header))
        source = IPodLibrary(write_iTunesDB(document))
    result = add_track(source, "Artist A")
    assert result.prepared is not None, result.issues
    assert native_links(result.prepared, kind) == (*native_links(source, kind), winner)
    assert any(
        issue.code == "library.ambiguous_group"
        and issue.severity is IssueSeverity.WARNING
        for issue in result.issues
    )
    checked = parse_iTunesDB(result.prepared.itunes)
    definition = MhiiHeader if kind == "artist" else MhiaHeader
    assert len(checked.find_chunks(definition)) == 2


@pytest.mark.parametrize("kind", ["album", "artist"])
def test_removal_keeps_both_retained_browse_owners(kind: str) -> None:
    source = duplicate_source(kind, three_tracks=True)
    result = prepare_tracks(source, source.snapshot.tracks[1:])
    assert result.prepared is not None, result.issues
    assert native_links(result.prepared, kind) == native_links(source, kind)[1:]
    if kind == "album":
        checked = parse_iTunesDB(result.prepared.itunes)
        owners = {
            s.chunk.header.album_id: s.chunk.header.album_track_db_id
            for s in checked.find_chunks(MhiaHeader)
        }
        last = result.prepared.snapshot.tracks[-1].ipod
        assert last is not None
        assert owners[5] == last.db_track_id


def test_compilation_membership_keeps_native_album_artist() -> None:
    source = artist_source(("Artist A", "Artist B"), shared=True, label="Artist")
    document = parse_iTunesDB(source.serialize().itunes)
    for track in document.find_chunks(MhitHeader):
        document = document.replace_chunk(
            track,
            replace(
                track.chunk, header=replace(track.chunk.header, compilation_flag=1)
            ),
        )
    source = IPodLibrary(write_iTunesDB(document))
    removed = prepare_tracks(source, source.snapshot.tracks[1:])
    assert removed.prepared is not None, removed.issues
    assert native_links(removed.prepared, "artist") == (6,)

    added = add_track(source, "Artist C")
    assert added.prepared is not None, added.issues
    assert native_links(added.prepared, "artist") == (6, 6, 6)


def test_addition_refuses_duplicate_album_records_with_conflicting_metadata() -> None:
    source = duplicate_source("album")
    document = parse_iTunesDB(source.serialize().itunes)
    row = document.find_chunks(MhiaHeader)[1]
    document = document.replace_chunk(
        row, edit_text(row.chunk, MhodType.ALBUM_ITEM_SORT_ARTIST, "Different sort")
    )
    source = IPodLibrary(write_iTunesDB(document))
    result = add_track(source, "Artist A")
    assert result.prepared is None
    assert any(
        issue.code == "library.ambiguous_group" and issue.field == "album"
        for issue in result.issues
    )


def test_verifier_rejects_relinking_to_another_retained_owner() -> None:
    source = duplicate_source("artist", three_tracks=True)
    result = prepare_tracks(source, source.snapshot.tracks[1:])
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    first = checked.find_chunks(MhitHeader)[0]
    tampered = checked.replace_chunk(
        first, replace(first.chunk, header=replace(first.chunk.header, artist_id_ref=6))
    )
    issues = verify_browse_groups(
        parse_iTunesDB(source.serialize().itunes),
        parse_iTunesDB(write_iTunesDB(tampered)),
        source.snapshot,
        replace(source.snapshot, tracks=source.snapshot.tracks[1:]),
        (),
    )
    assert any(
        issue.code == "verification.browse_retained_reference" for issue in issues
    )


def test_removal_repairs_representative_without_rewriting_album_metadata() -> None:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    album = document.find_chunks(MhiaHeader)[0]
    document = document.replace_chunk(
        album, edit_text(album.chunk, MhodType.ALBUM_ITEM_SORT_ARTIST, "Native sort")
    )
    source = IPodLibrary(write_iTunesDB(document))
    result = prepare_tracks(source, source.snapshot.tracks[1:])
    assert result.prepared is not None, result.issues
    row = parse_iTunesDB(result.prepared.itunes).find_chunks(MhiaHeader)[0].chunk
    assert row.header.album_track_db_id == 102
    assert text(row, MhodType.ALBUM_ITEM_SORT_ARTIST) == "Native sort"
