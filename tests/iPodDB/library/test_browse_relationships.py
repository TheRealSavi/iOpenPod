"""Native browse metadata and verification through public Library preparation."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk, new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import DEFINITION as MHIA
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhii import DEFINITION as MHII
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhla import DEFINITION as MHLA
from iPodDB.iTunesDB.shared.chunk_defs.mhli import DEFINITION as MHLI
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, _write_preparation
from iPodDB.library._reconcile import reconcile
from iPodDB.library._resolved_write import ResolvedWrite
from iPodDB.library._track_writing import edit_text
from iPodDB.library.writing import IdentityMapping, WriteIssue, WriteResources
from iPodDB.shared.chunk import (
    ChunkHeader,
    DatabaseDocument,
    EmptyChunkHeader,
    ParsedChunk,
)


def text(chunk: ParsedChunk[ChunkHeader], kind: MhodType) -> str:
    return next(
        (
            c.payload.value
            for c in reversed(chunk.children)
            if isinstance(c.header, MhodHeader)
            and c.header.mhod_type == kind
            and isinstance(c.payload, MhodStringPayload)
        ),
        "",
    )


def browse_source() -> IPodLibrary:
    document = parse_iTunesDB(library().serialize().itunes)
    master = next(
        s for s in document.find_chunks(MhypHeader) if s.chunk.header.master_flag
    )
    document = document.replace_chunk(
        master,
        replace(
            master.chunk,
            children=(
                *master.chunk.children,
                *(new_itunes_chunk(MHIP, MhipHeader(track_id=i)) for i in (1, 2)),
            ),
        ),
    )
    for selection in document.find_chunks(MhitHeader):
        document = document.replace_chunk(
            selection,
            replace(
                selection.chunk,
                header=replace(
                    selection.chunk.header, album_id=5, artist_id_ref=6, composer_id=7
                ),
                children=(
                    *selection.chunk.children,
                    new_string_mhod(MhodType.ALBUM, "Album"),
                    new_string_mhod(MhodType.ARTIST, "Artist"),
                    new_string_mhod(MhodType.COMPOSER, "Composer"),
                    new_string_mhod(MhodType.SORT_ALBUM_ARTIST, "Old sort"),
                ),
            ),
        )
    for kind, definition, rows in (
        (
            4,
            MHLA,
            (
                new_itunes_chunk(
                    MHIA,
                    MhiaHeader(album_id=5, sql_id=50, album_track_db_id=101),
                    children=(
                        new_string_mhod(MhodType.ALBUM_ITEM_ALBUM, "Album"),
                        new_string_mhod(MhodType.ALBUM_ITEM_ARTIST, "Artist"),
                        new_string_mhod(MhodType.ALBUM_ITEM_SORT_ARTIST, "Old sort"),
                    ),
                ),
                new_itunes_chunk(
                    MHIA,
                    MhiaHeader(album_id=8, sql_id=80),
                    children=(new_string_mhod(MhodType.ALBUM_ITEM_ALBUM, "Unrelated"),),
                ),
            ),
        ),
        (
            8,
            MHLI,
            (
                new_itunes_chunk(
                    MHII,
                    MhiiHeader(artist_id=6, sql_id=60),
                    children=(new_string_mhod(MhodType.ARTIST_ITEM_ARTIST, "Artist"),),
                ),
                new_itunes_chunk(
                    MHII,
                    MhiiHeader(artist_id=9, sql_id=90),
                    children=(
                        new_string_mhod(MhodType.ARTIST_ITEM_ARTIST, "Unrelated"),
                    ),
                ),
            ),
        ),
    ):
        document = document.append_child(
            new_itunes_chunk(
                MHSD,
                MhsdHeader(dataset_type=kind),
                children=(
                    new_itunes_chunk(definition, EmptyChunkHeader(), children=rows),
                ),
            )
        )
    return IPodLibrary(write_iTunesDB(document))


@pytest.mark.parametrize("rename", [False, True])
@pytest.mark.parametrize(
    "field, kind",
    [
        ("sort_album_artist", MhodType.ALBUM_ITEM_SORT_ARTIST),
        ("podcast_rss_url", MhodType.ALBUM_ITEM_PODCAST_URL),
    ],
)
def test_album_browse_metadata_follows_track_edits(
    rename: bool, field: str, kind: MhodType
) -> None:
    source = browse_source()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(
                t,
                album="Renamed" if rename else t.album,
                metadata=replace(t.metadata, sort_album_artist="New value")
                if field == "sort_album_artist"
                else replace(t.metadata, podcast_rss_url="New value"),
            )
            for t in source.snapshot.tracks
        ),
    )
    plan = source.analyze(source.begin_draft(desired))
    assert plan.resolution is not None
    assert any(e.code == "library.browse_groups" for e in plan.resolution.effects)
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    row = parse_iTunesDB(result.prepared.itunes).find_chunks(MhiaHeader)[0].chunk
    assert text(row, kind) == "New value"
    assert (row.header.album_id, row.header.sql_id, row.header.album_track_db_id) == (
        5,
        50,
        101,
    )


def test_album_show_and_sort_fallback_are_derived_from_resulting_members() -> None:
    source = browse_source()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(
                t,
                show="New show",
                metadata=replace(
                    t.metadata, sort_album_artist="", sort_artist="Fallback"
                ),
            )
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    row = parse_iTunesDB(result.prepared.itunes).find_chunks(MhiaHeader)[0].chunk
    assert text(row, MhodType.ALBUM_ITEM_SHOW) == "New show"
    assert text(row, MhodType.ALBUM_ITEM_SORT_ARTIST) == "Fallback"


def test_album_split_merge_and_representative_deletion_keep_valid_identities() -> None:
    source = browse_source()
    first, second = source.snapshot.tracks
    split = replace(
        source.snapshot,
        tracks=(replace(first, album="Split", artist="Split artist"), second),
    )
    result = source.prepare(source.analyze(source.begin_draft(split)))
    assert result.prepared is not None, result.issues
    document = parse_iTunesDB(result.prepared.itunes)
    native = {
        s.chunk.header.track_id: s.chunk.header
        for s in document.find_chunks(MhitHeader)
    }
    albums = {
        s.chunk.header.album_id: s.chunk for s in document.find_chunks(MhiaHeader)
    }
    assert native[1].album_id not in (0, 5, 6, 7, 8, 9)
    assert native[1].artist_id_ref not in (0, 5, 6, 7, 8, 9, native[1].album_id)
    assert native[2].album_id == 5
    assert albums[5].header.album_track_db_id == 102
    assert albums[native[1].album_id].header.album_track_db_id == 101
    assert len({s.chunk.header.sql_id for s in document.find_chunks(MhiaHeader)}) == 3

    source = IPodLibrary(result.prepared.itunes)
    merged = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, album="Album", artist="Artist") for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(merged)))
    assert result.prepared is not None, result.issues
    document = parse_iTunesDB(result.prepared.itunes)
    assert {s.chunk.header.album_id for s in document.find_chunks(MhitHeader)} == {5}
    assert {s.chunk.header.artist_id_ref for s in document.find_chunks(MhitHeader)} == {
        6
    }

    source = IPodLibrary(result.prepared.itunes)
    deleted = replace(
        source.snapshot,
        tracks=source.snapshot.tracks[1:],
        playlists=tuple(
            replace(p, entries=tuple(e for e in p.entries if e.track_id != 1))
            for p in source.snapshot.playlists
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(deleted, delete_omissions=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    remaining_albums = {
        s.chunk.header.album_id: s.chunk.header
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhiaHeader)
    }
    assert remaining_albums[5].album_track_db_id == 102
    assert remaining_albums[native[1].album_id].album_track_db_id == 0


def test_album_metadata_selection_follows_first_nonempty_value_in_track_order() -> None:
    source = browse_source()
    first, second = source.snapshot.tracks
    desired = replace(
        source.snapshot,
        tracks=(
            replace(
                first,
                metadata=replace(
                    first.metadata,
                    sort_album_artist="",
                    sort_artist="Fallback",
                    podcast_rss_url="",
                ),
            ),
            replace(
                second,
                metadata=replace(
                    second.metadata,
                    sort_album_artist="Preferred",
                    podcast_rss_url="Feed",
                ),
            ),
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    row = parse_iTunesDB(result.prepared.itunes).find_chunks(MhiaHeader)[0].chunk
    assert text(row, MhodType.ALBUM_ITEM_SORT_ARTIST) == "Preferred"
    assert text(row, MhodType.ALBUM_ITEM_PODCAST_URL) == "Feed"

    # With distinct explicit values, changing Library order changes selection.
    source = IPodLibrary(result.prepared.itunes)
    desired = replace(
        source.snapshot,
        tracks=(
            replace(
                source.snapshot.tracks[0],
                metadata=replace(
                    source.snapshot.tracks[0].metadata, sort_album_artist="First"
                ),
            ),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    source = IPodLibrary(result.prepared.itunes)
    desired = replace(source.snapshot, tracks=tuple(reversed(source.snapshot.tracks)))
    plan = source.analyze(source.begin_draft(desired))
    assert plan.resolution is not None
    assert any(e.code == "library.browse_groups" for e in plan.resolution.effects)
    result = source.prepare(plan, WriteResources(pending_playback_sidecars=False))
    assert result.prepared is not None, result.issues
    row = parse_iTunesDB(result.prepared.itunes).find_chunks(MhiaHeader)[0].chunk
    assert text(row, MhodType.ALBUM_ITEM_SORT_ARTIST) == "Preferred"


@pytest.mark.parametrize(
    "anomaly", ["duplicate", "missing_reference", "stale_metadata"]
)
def test_unrelated_title_edit_preserves_existing_browse_anomalies(anomaly: str) -> None:
    document = parse_iTunesDB(browse_source().serialize().itunes)
    if anomaly == "duplicate":
        dataset = next(
            s
            for s in document.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 4
        )
        container = dataset.chunk.children[0]
        document = document.replace_chunk(
            dataset,
            replace(
                dataset.chunk, children=(container.append_child(container.children[0]),)
            ),
        )
    elif anomaly == "missing_reference":
        selection = document.find_chunks(MhitHeader)[0]
        document = document.replace_chunk(
            selection,
            replace(
                selection.chunk, header=replace(selection.chunk.header, album_id=999)
            ),
        )
    else:
        row = document.find_chunks(MhiaHeader)[0]
        document = document.replace_chunk(
            row, edit_text(row.chunk, MhodType.ALBUM_ITEM_SORT_ARTIST, "Retain anomaly")
        )
    source = IPodLibrary(write_iTunesDB(document))
    source_bytes = source.serialize().itunes
    document = parse_iTunesDB(source_bytes)
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, title="New title") for t in source.snapshot.tracks),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    for before, after in zip(
        document.find_chunks(MhiaHeader), checked.find_chunks(MhiaHeader), strict=True
    ):
        assert (
            source_bytes[
                before.chunk.offset : before.chunk.offset
                + before.chunk.generic_header.length_or_child_count
            ]
            == result.prepared.itunes[
                after.chunk.offset : after.chunk.offset
                + after.chunk.generic_header.length_or_child_count
            ]
        )
    assert tuple(t.ipod for t in result.prepared.snapshot.tracks) == tuple(
        t.ipod for t in source.snapshot.tracks
    )


@pytest.mark.parametrize(
    "fault",
    [
        "missing_album",
        "wrong_album",
        "missing_artist",
        "wrong_artist",
        "composer",
        "representative",
        "album_title",
        "album_sort",
    ],
)
def test_verification_rejects_corrupted_native_browse_relationships(
    monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    source = browse_source()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(
                t,
                album="Renamed",
                artist="New artist",
                metadata=replace(t.metadata, composer="New composer"),
            )
            for t in source.snapshot.tracks
        ),
    )

    def corrupt(
        document: DatabaseDocument[MhbdHeader],
        resolved: ResolvedWrite,
        resources: WriteResources,
        issues: list[WriteIssue],
    ) -> tuple[DatabaseDocument[MhbdHeader], tuple[IdentityMapping, ...]]:
        candidate, mappings = reconcile(document, resolved, resources, issues)
        if fault in ("representative", "album_title", "album_sort"):
            row = candidate.find_chunks(MhiaHeader)[0]
            if fault == "representative":
                changed = replace(
                    row.chunk, header=replace(row.chunk.header, album_track_db_id=999)
                )
            else:
                changed = edit_text(
                    row.chunk,
                    MhodType.ALBUM_ITEM_ALBUM
                    if fault == "album_title"
                    else MhodType.ALBUM_ITEM_SORT_ARTIST,
                    "Wrong value",
                )
            candidate = candidate.replace_chunk(row, changed)
        else:
            track_row = candidate.find_chunks(MhitHeader)[0]
            header = track_row.chunk.header
            corrupted = {
                "missing_album": replace(header, album_id=999),
                "wrong_album": replace(header, album_id=8),
                "missing_artist": replace(header, artist_id_ref=999),
                "wrong_artist": replace(header, artist_id_ref=9),
                "composer": replace(header, composer_id=999),
            }[fault]
            candidate = candidate.replace_chunk(
                track_row,
                replace(track_row.chunk, header=corrupted),
            )
        return candidate, mappings

    monkeypatch.setattr(_write_preparation, "reconcile", corrupt)
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None, fault
    assert any(i.code.startswith("verification.browse_") for i in result.issues), (
        result.issues
    )
