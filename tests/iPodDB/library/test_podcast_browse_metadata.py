"""Metadata edits must respect shared native Podcast albums."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_browse_relationships import text
from tests.iPodDB.library.test_podcast_normalization import observed_source

from iPodDB.device_time import TimeConversion
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, _write_preparation
from iPodDB.library._reconcile import reconcile
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library._track_writing import edit_text
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.writing import IdentityMapping, WriteIssue, WriteResources
from iPodDB.shared.chunk import DatabaseDocument


def shared_podcast_source() -> IPodLibrary:
    document = parse_iTunesDB(observed_source(True).serialize().itunes)
    for selection in document.find_chunks(MhitHeader):
        if selection.chunk.header.track_id > 2:
            continue
        chunk = edit_text(selection.chunk, MhodType.ARTIST, "Publisher")
        chunk = edit_text(chunk, MhodType.ALBUM_ARTIST, "")
        if chunk.header.track_id == 2:
            chunk = edit_text(chunk, MhodType.ALBUM_ARTIST, "Publisher")
            chunk = edit_text(chunk, MhodType.SHOW, "Podcast")
        document = document.replace_chunk(selection, chunk)
    row = document.find_chunks(MhiaHeader)[0]
    album_chunk = edit_text(row.chunk, MhodType.ALBUM_ITEM_ARTIST, "Show publisher")
    album_chunk = edit_text(album_chunk, MhodType.ALBUM_ITEM_SHOW, "Podcast")
    document = document.replace_chunk(
        row,
        replace(
            album_chunk,
            header=replace(row.chunk.header, album_track_db_id=102, season_number=7),
        ),
    )
    return IPodLibrary(write_iTunesDB(document))


def sorted_podcasts(source: IPodLibrary) -> LibrarySnapshot:
    first, second, *music = source.snapshot.tracks
    return replace(
        source.snapshot,
        tracks=(
            replace(first, metadata=replace(first.metadata, sort_artist="Publisher")),
            replace(
                second,
                metadata=replace(second.metadata, sort_album_artist="Publisher"),
            ),
            *music,
        ),
    )


def test_sort_edits_preserve_shared_podcast_album_and_representative() -> None:
    source = shared_podcast_source()
    original = source.serialize().itunes
    result = source.prepare(source.analyze(source.begin_draft(sorted_podcasts(source))))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert [s.chunk.header.album_id for s in checked.find_chunks(MhitHeader)][:2] == [
        10,
        10,
    ]
    row = checked.find_chunks(MhiaHeader)[0].chunk
    assert (row.header.album_id, row.header.sql_id, row.header.album_track_db_id) == (
        10,
        10,
        102,
    )
    assert text(row, MhodType.ALBUM_ITEM_SORT_ARTIST) == "Publisher"
    assert text(row, MhodType.ALBUM_ITEM_ARTIST) == "Show publisher"
    assert text(row, MhodType.ALBUM_ITEM_SHOW) == "Podcast"
    assert row.header.season_number == 7
    assert b"private-album-data" in result.prepared.itunes
    assert source.serialize().itunes == original


@pytest.mark.parametrize("edit", ["noop", "title", "sort", "show", "season", "delete"])
def test_shared_podcast_album_handles_individual_episode_changes(edit: str) -> None:
    source = shared_podcast_source()
    original = source.serialize().itunes
    first, second, *music = source.snapshot.tracks
    changed = first
    if edit == "title":
        changed = replace(first, title="Edited Episode")
    elif edit == "sort":
        changed = replace(first, metadata=replace(first.metadata, sort_artist="Sorted"))
    elif edit == "show":
        changed = replace(first, show="Edited show")
    elif edit == "season":
        changed = replace(first, season_number=2)
    desired = replace(
        source.snapshot,
        tracks=(second, *music) if edit == "delete" else (changed, second, *music),
        playlists=tuple(
            replace(
                p, entries=tuple(e for e in p.entries if e.track_id != first.track_id)
            )
            if edit == "delete"
            else p
            for p in source.snapshot.playlists
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=edit == "delete")),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    row = checked.find_chunks(MhiaHeader)[0].chunk
    assert row.header.album_id == 10 and row.header.album_track_db_id == 102
    assert len(checked.find_chunks(MhiaHeader)) == 2
    assert text(row, MhodType.ALBUM_ITEM_SHOW) == (
        "Edited show" if edit == "show" else "Podcast"
    )
    if edit in ("noop", "title"):
        old = parse_iTunesDB(original).find_chunks(MhiaHeader)[0].chunk
        assert (
            original[old.offset : old.offset + old.generic_header.length_or_child_count]
            == result.prepared.itunes[
                row.offset : row.offset + row.generic_header.length_or_child_count
            ]
        )
    if edit == "noop":
        assert result.prepared.itunes == original
    if edit == "sort":
        assert text(row, MhodType.ALBUM_ITEM_SORT_ARTIST) == "Sorted"
    if edit == "season":
        assert row.header.season_number == 2


@pytest.mark.parametrize("split_field", ["album", "feed"])
def test_explicit_show_identity_edits_split_shared_podcast_album(
    split_field: str,
) -> None:
    source = shared_podcast_source()
    first, second, *music = source.snapshot.tracks
    changed = (
        replace(first, album="Different show")
        if split_field == "album"
        else replace(
            first,
            metadata=replace(
                first.metadata, podcast_rss_url="https://different.example/feed"
            ),
        )
    )
    desired = replace(source.snapshot, tracks=(changed, second, *music))
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    first_row, second_row, *_ = checked.find_chunks(MhitHeader)
    assert first_row.chunk.header.album_id not in (0, 10, 20)
    assert second_row.chunk.header.album_id == 10


def test_sort_edits_preserve_separate_source_podcast_albums() -> None:
    document = parse_iTunesDB(shared_podcast_source().serialize().itunes)
    second = document.find_chunks(MhitHeader)[1]
    document = document.replace_chunk(
        second, replace(second.chunk, header=replace(second.chunk.header, album_id=30))
    )
    dataset = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 4
    )
    container = dataset.chunk.children[0]
    original = document.find_chunks(MhiaHeader)[0].chunk
    duplicate = replace(
        original, header=replace(original.header, album_id=30, sql_id=30)
    )
    document = document.replace_chunk(
        dataset, replace(dataset.chunk, children=(container.append_child(duplicate),))
    )
    first_album = document.find_chunks(MhiaHeader)[0]
    document = document.replace_chunk(
        first_album,
        replace(
            first_album.chunk,
            header=replace(first_album.chunk.header, album_track_db_id=101),
        ),
    )
    source = IPodLibrary(write_iTunesDB(document))
    result = source.prepare(source.analyze(source.begin_draft(sorted_podcasts(source))))
    assert result.prepared is not None, result.issues
    assert [
        s.chunk.header.album_id
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
    ][:2] == [10, 30]


@pytest.mark.parametrize("conflict", ["feed", "music"])
def test_shared_album_with_incompatible_owners_blocks_sort_edits(conflict: str) -> None:
    document = parse_iTunesDB(shared_podcast_source().serialize().itunes)
    second = document.find_chunks(MhitHeader)[1]
    changed = (
        edit_text(
            second.chunk, MhodType.PODCAST_RSS_URL, "https://different.example/feed"
        )
        if conflict == "feed"
        else replace(second.chunk, header=replace(second.chunk.header, media_type=1))
    )
    document = document.replace_chunk(second, changed)
    source = IPodLibrary(write_iTunesDB(document))
    result = source.prepare(source.analyze(source.begin_draft(sorted_podcasts(source))))
    assert result.prepared is None
    assert any(i.code == "library.ambiguous_group" for i in result.issues)


@pytest.mark.parametrize("fault", ["representative", "sort", "show", "season"])
def test_verifier_still_rejects_corrupted_shared_podcast_album(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    source = shared_podcast_source()

    def corrupt(
        document: DatabaseDocument[MhbdHeader],
        resolved: ResolvedWrite,
        resources: WriteResources,
        issues: list[WriteIssue],
        device_time: TimeConversion = 0,
    ) -> tuple[DatabaseDocument[MhbdHeader], tuple[IdentityMapping, ...]]:
        candidate, mappings = reconcile(
            document, resolved, resources, issues, device_time
        )
        row = candidate.find_chunks(MhiaHeader)[0]
        if fault == "representative":
            changed = replace(
                row.chunk, header=replace(row.chunk.header, album_track_db_id=103)
            )
        elif fault == "season":
            changed = replace(
                row.chunk, header=replace(row.chunk.header, season_number=99)
            )
        else:
            changed = edit_text(
                row.chunk,
                MhodType.ALBUM_ITEM_SORT_ARTIST
                if fault == "sort"
                else MhodType.ALBUM_ITEM_SHOW,
                "Wrong",
            )
        return candidate.replace_chunk(row, changed), mappings

    monkeypatch.setattr(_write_preparation, "reconcile", corrupt)
    result = source.prepare(source.analyze(source.begin_draft(sorted_podcasts(source))))
    assert result.prepared is None
    assert any(i.code.startswith("verification.browse_") for i in result.issues)
