"""Membership changes preserve the native ownership of retained Tracks."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_artist_browse_case import (
    add_track,
    artist_source,
    assert_exact_artist_references,
    assert_original_artist_rows,
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


def duplicate_source(
    kind: str, *, three_tracks: bool = False, third_album: str = ""
) -> IPodLibrary:
    names = ("Artist A", "Artist B") if kind == "artist" else ("Artist A", "Artist A")
    source = artist_source(names, shared=kind == "album")
    if three_tracks or third_album:
        added = add_track(source, "Artist A", filename="third.mp3")
        assert added.prepared is not None, added.issues
        source = IPodLibrary(added.prepared.itunes)
    if third_album:
        first_track, second_track, third_track = source.snapshot.tracks
        moved = prepare_tracks(
            source, (first_track, second_track, replace(third_track, album=third_album))
        )
        assert moved.prepared is not None, moved.issues
        source = IPodLibrary(moved.prepared.itunes)
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
        first, second = document.find_chunks(MhiaHeader)[:2]
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
    result: list[int] = []
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


@pytest.mark.parametrize("direction", ["in", "out"])
def test_artist_rename_preserves_compatible_duplicate_owners(direction: str) -> None:
    source = duplicate_source("artist")
    seed = add_track(source, "Other Artist", filename="other.mp3")
    assert seed.prepared is not None, seed.issues
    source = IPodLibrary(seed.prepared.itunes)
    first, second, other = source.snapshot.tracks
    assert other.ipod is not None
    other_id = other.ipod.artist_id_ref
    if direction == "in":
        tracks = (first, second, replace(other, artist=first.artist))
        expected = (6, 9, 6)
    else:
        tracks = (replace(first, artist=other.artist), second, other)
        expected = (other_id, 9, other_id)

    result = prepare_tracks(source, tracks)

    assert result.prepared is not None, result.issues
    assert native_links(result.prepared, "artist") == expected
    assert_original_artist_rows(source.serialize().itunes, result.prepared.itunes)


@pytest.mark.parametrize("edited_owner", [0, 1])
def test_sort_edit_updates_only_the_tracks_native_album(edited_owner: int) -> None:
    source = duplicate_source("album")
    sort_artist = "Edited sort artist"
    tracks = tuple(
        replace(track, metadata=replace(track.metadata, sort_album_artist=sort_artist))
        if index == edited_owner
        else track
        for index, track in enumerate(source.snapshot.tracks)
    )

    result = prepare_tracks(source, tracks)

    assert result.prepared is not None, result.issues
    assert native_links(result.prepared, "album") == (5, 8)
    previous = parse_iTunesDB(source.serialize().itunes).find_chunks(MhiaHeader)
    checked = parse_iTunesDB(result.prepared.itunes)
    updated = checked.find_chunks(MhiaHeader)
    edited = updated[edited_owner]
    other = 1 - edited_owner
    assert edited.chunk.header.sql_id == previous[edited_owner].chunk.header.sql_id
    assert text(edited.chunk, MhodType.ALBUM_ITEM_SORT_ARTIST) == sort_artist
    assert updated[other].chunk.raw_header == previous[other].chunk.raw_header
    assert updated[other].chunk.raw_body == previous[other].chunk.raw_body

    for corrupted_row in (
        edit_text(edited.chunk, MhodType.ALBUM_ITEM_SORT_ARTIST, "Wrong sort"),
        edit_text(edited.chunk, MhodType.ALBUM_ITEM_ARTIST, "Wrong Album Artist"),
        replace(edited.chunk, raw_header=edited.chunk.raw_header[:-1] + b"\xff"),
    ):
        tampered = checked.replace_chunk(edited, corrupted_row)
        issues = verify_browse_groups(
            parse_iTunesDB(source.serialize().itunes),
            parse_iTunesDB(write_iTunesDB(tampered)),
            source.snapshot,
            replace(source.snapshot, tracks=tracks),
            (),
        )
        assert any(
            issue.code == "verification.browse_group_metadata" for issue in issues
        )


def test_sort_edit_and_add_choose_the_same_album_in_one_or_two_writes() -> None:
    source = duplicate_source("album")
    first, second = source.snapshot.tracks
    edited = replace(
        second, metadata=replace(second.metadata, sort_album_artist="New sort")
    )
    tracks = (first, edited)

    together = add_track(source, first.artist, retained=tracks)
    assert together.prepared is not None, together.issues
    first_write = prepare_tracks(source, tracks)
    assert first_write.prepared is not None, first_write.issues
    later = add_track(IPodLibrary(first_write.prepared.itunes), first.artist)

    assert later.prepared is not None, later.issues
    assert (
        native_links(together.prepared, "album")
        == native_links(later.prepared, "album")
        == (5, 8, 5)
    )
    for prepared in (together.prepared, later.prepared):
        row = parse_iTunesDB(prepared.itunes).find_chunks(MhiaHeader)[1].chunk
        assert text(row, MhodType.ALBUM_ITEM_SORT_ARTIST) == "New sort"


def with_store_album_ids(
    source: IPodLibrary, store_ids: tuple[int, ...]
) -> IPodLibrary:
    document = parse_iTunesDB(source.serialize().itunes)
    for track, store_id in zip(
        document.find_chunks(MhitHeader), store_ids, strict=True
    ):
        document = document.replace_chunk(
            track,
            replace(
                track.chunk, header=replace(track.chunk.header, store_album_id=store_id)
            ),
        )
    return IPodLibrary(write_iTunesDB(document))


@pytest.mark.parametrize(
    ("releases", "destination"),
    [
        ((400, 401, 400), 5),
        ((400, 401, 401), 8),
        ((400, 401, 0), 5),
        ((400, 401, 402), None),
        ((0, 401, 401), 8),
        ((400, 0, 401), None),
        ((0, 0, 401), 5),
        ((0, 401, 0), 8),
    ],
)
def test_move_uses_matching_store_release_when_available(
    releases: tuple[int, int, int], destination: int | None
) -> None:
    source = with_store_album_ids(
        duplicate_source("album", third_album="Other Album"), releases
    )
    first, second, third = source.snapshot.tracks

    result = prepare_tracks(source, (first, second, replace(third, album=first.album)))

    assert result.prepared is not None, result.issues
    first_id, second_id, moved_id = native_links(result.prepared, "album")
    assert (first_id, second_id) == (5, 8)
    if destination is None:
        assert moved_id not in (0, 5, 8, third.ipod.album_id if third.ipod else 0)
        assert any(
            i.code == "library.ambiguous_group"
            and i.field == "album"
            and i.severity is IssueSeverity.WARNING
            for i in result.issues
        )
    else:
        assert moved_id == destination


def test_move_from_duplicate_album_repairs_the_old_representative() -> None:
    source = duplicate_source("album", three_tracks=True)
    first, second, third = source.snapshot.tracks
    tracks = (replace(first, album="New Album"), second, third)

    result = prepare_tracks(source, tracks)

    assert result.prepared is not None, result.issues
    moved, kept_second, kept_third = native_links(result.prepared, "album")
    assert moved not in (0, 5, 8)
    assert (kept_second, kept_third) == (8, 5)
    assert third.ipod is not None
    checked = parse_iTunesDB(result.prepared.itunes)
    owners = {s.chunk.header.album_id: s.chunk for s in checked.find_chunks(MhiaHeader)}
    assert owners[5].header.album_track_db_id == third.ipod.db_track_id
    assert text(owners[moved], MhodType.ALBUM_ITEM_ALBUM) == "New Album"


def test_add_without_store_evidence_chooses_between_distinct_releases() -> None:
    source = with_store_album_ids(duplicate_source("album"), (400, 401))

    result = add_track(source, "Artist A")

    assert result.prepared is not None, result.issues
    assert native_links(result.prepared, "album") == (5, 8, 5)
    assert any(
        issue.code == "library.ambiguous_group"
        and issue.field == "album"
        and "{5: [400], 8: [401]}" in issue.detail
        for issue in result.issues
    )


@pytest.mark.parametrize("other_release", [False, True])
def test_move_into_duplicate_album_creates_a_record_for_unmatched_release(
    other_release: bool,
) -> None:
    source = duplicate_source("album", third_album="Other Album")
    if other_release:
        source = with_store_album_ids(source, (10, 10, 11))
    first, second, third = source.snapshot.tracks
    assert third.ipod is not None
    old_owner = third.ipod.album_id

    result = prepare_tracks(source, (first, second, replace(third, album=first.album)))

    assert result.prepared is not None, result.issues
    first_id, second_id, moved_id = native_links(result.prepared, "album")
    assert (first_id, second_id) == (5, 8)
    if other_release:
        assert moved_id not in (0, 5, 8, old_owner)
        assert any(
            i.code == "library.ambiguous_group" and i.field == "album"
            for i in result.issues
        )
    else:
        assert moved_id == 5
    owners = {
        s.chunk.header.album_id: s.chunk.header
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhiaHeader)
    }
    assert owners[old_owner].album_track_db_id == 0


@pytest.mark.parametrize("destination_releases", [(0, 0), (10, 11)])
def test_moves_into_one_duplicate_album_keep_store_releases_separate(
    destination_releases: tuple[int, int],
) -> None:
    source = duplicate_source("album", third_album="Other Album")
    added = add_track(source, "Artist A", filename="fourth.mp3")
    assert added.prepared is not None, added.issues
    source = IPodLibrary(added.prepared.itunes)
    first, second, third, fourth = source.snapshot.tracks
    moved = prepare_tracks(
        source, (first, second, third, replace(fourth, album="Fourth Album"))
    )
    assert moved.prepared is not None, moved.issues
    source = with_store_album_ids(
        IPodLibrary(moved.prepared.itunes), (*destination_releases, 10, 11)
    )
    first, second, third, fourth = source.snapshot.tracks

    result = prepare_tracks(
        source,
        (
            first,
            second,
            replace(third, album=first.album),
            replace(fourth, album=first.album),
        ),
    )

    assert result.prepared is not None, result.issues
    links = native_links(result.prepared, "album")
    if destination_releases == (0, 0):
        assert links[:2] == (5, 8)
        assert len(set(links)) == 4
        assert not {0, *native_links(source, "album")}.intersection(links[2:])
        assert any(
            i.code == "library.ambiguous_group" and i.field == "album"
            for i in result.issues
        )
    else:
        assert links == (5, 8, 5, 8)


@pytest.mark.parametrize("album_artist", ["", "New Album Artist"])
def test_addition_with_album_artist_edit_keeps_duplicate_artist_links(
    album_artist: str,
) -> None:
    source = duplicate_source("artist")
    first, second = source.snapshot.tracks
    retained = (first, replace(second, album_artist=album_artist))

    result = add_track(source, first.artist, retained=retained)

    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[1].album_artist == album_artist
    assert native_links(result.prepared, "artist") == (6, 9, 6)
    assert_original_artist_rows(source.serialize().itunes, result.prepared.itunes)


@pytest.mark.parametrize("label", ["Artist A", "Artist B", "Unknown artist"])
def test_addition_reconciles_duplicate_and_shared_artist_records(label: str) -> None:
    source = duplicate_source("artist", three_tracks=True)
    document = parse_iTunesDB(source.serialize().itunes)
    third_track = document.find_chunks(MhitHeader)[2]
    document = document.replace_chunk(
        third_track, edit_text(third_track.chunk, MhodType.ARTIST, "Artist B")
    )
    row = document.find_chunks(MhiiHeader)[0]
    document = document.replace_chunk(
        row, edit_text(row.chunk, MhodType.ARTIST_ITEM_ARTIST, label)
    )
    source = IPodLibrary(write_iTunesDB(document))

    result = add_track(source, "Artist A")

    assert result.prepared is not None, result.issues
    first, second, third, added = native_links(result.prepared, "artist")
    assert second == 9
    if label == "Artist A":
        assert (first, added) == (6, 6)
    else:
        assert (first, added) == (9, 9)
    if label == "Artist B":
        assert third == 6
    else:
        assert third not in (0, 6, 9)
    assert_exact_artist_references(parse_iTunesDB(result.prepared.itunes))
    assert_original_artist_rows(source.serialize().itunes, result.prepared.itunes)


def test_addition_allocates_artist_ids_for_incompatible_shared_sources() -> None:
    document = parse_iTunesDB(
        duplicate_source("artist", three_tracks=True).serialize().itunes
    )
    third = document.find_chunks(MhitHeader)[2]
    document = document.replace_chunk(
        third, edit_text(third.chunk, MhodType.ARTIST, "Artist B")
    )
    for row in document.find_chunks(MhiiHeader):
        document = document.replace_chunk(
            row, edit_text(row.chunk, MhodType.ARTIST_ITEM_ARTIST, "Unknown artist")
        )

    source = IPodLibrary(write_iTunesDB(document))
    result = add_track(source, "Artist A")

    assert result.prepared is not None, result.issues
    first, second, third_id, added = native_links(result.prepared, "artist")
    assert first == second == added
    assert first != third_id
    assert {first, third_id}.isdisjoint({0, 6, 9})
    assert_original_artist_rows(source.serialize().itunes, result.prepared.itunes)
    assert any(
        issue.code == "library.ambiguous_group" and issue.field == "artist"
        for issue in result.issues
    )


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


def test_addition_chooses_between_duplicate_albums_with_conflicting_feeds() -> None:
    source = duplicate_source("album")
    document = parse_iTunesDB(source.serialize().itunes)
    row = document.find_chunks(MhiaHeader)[1]
    document = document.replace_chunk(
        row,
        edit_text(
            row.chunk, MhodType.ALBUM_ITEM_PODCAST_URL, "https://example.invalid/feed"
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    result = add_track(source, "Artist A")
    assert result.prepared is not None, result.issues
    assert native_links(result.prepared, "album") == (5, 8, 5)
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
