"""Album collisions and explicit repairs through retained Library preparation."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk, new_string_mhod
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import DEFINITION as MHIA
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhla import DEFINITION as MHLA
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTableEntry,
    MhodLibraryJumpTablePayload,
    MhodLibraryJumpTablePrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, _write_preparation
from iPodDB.library.writing import WriteChecksum, WriteResources, WriteTarget
from iPodDB.shared.chunk import (
    ChunkHeader,
    DatabaseDocument,
    EmptyChunkHeader,
    ParsedChunk,
)


def album_source(
    albums: tuple[str, str] = ("Nexus", "The Nexus"),
    *,
    explicit: bool = False,
    native: bool = True,
    jump_tables: bool = True,
    master_order: tuple[int, ...] = (4, 2, 3, 1),
) -> IPodLibrary:
    """Four Tracks, two distinct Albums, deliberately interleaved type-4 indexes."""
    document = parse_iTunesDB(library(mirrored=True).serialize().itunes)
    template = document.find_chunks(MhitHeader)[0].chunk
    tracks = tuple(
        replace(
            template,
            header=replace(
                template.header,
                track_id=i,
                db_track_id=100 + i,
                album_id=(10 if i < 3 else 20) if native else 0,
                track_number=(i - 1) % 2 + 1,
                disc_number=1,
            ),
            children=(
                new_string_mhod(MhodType.TITLE, f"Song {(i - 1) % 2 + 1}"),
                new_string_mhod(MhodType.ALBUM, albums[(i - 1) // 2]),
                new_string_mhod(MhodType.ARTIST, "Artist A" if i < 3 else "Artist B"),
                new_string_mhod(
                    MhodType.ALBUM_ARTIST, "Artist A" if i < 3 else "Artist B"
                ),
                *(
                    (
                        new_string_mhod(MhodType.SORT_ALBUM, albums[(i - 1) // 2]),
                        new_string_mhod(
                            MhodType.SORT_ARTIST, "Artist A" if i < 3 else "Artist B"
                        ),
                        new_string_mhod(
                            MhodType.SORT_ALBUM_ARTIST,
                            "Artist A" if i < 3 else "Artist B",
                        ),
                    )
                    if explicit
                    else ()
                ),
            ),
        )
        for i in (1, 2, 3, 4)
    )
    dataset = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 1
    )
    document = document.replace_chunk(
        dataset,
        replace(
            dataset.chunk,
            children=(replace(dataset.chunk.children[0], children=tracks),),
        ),
    )
    if native:
        document = document.append_child(
            new_itunes_chunk(
                MHSD,
                MhsdHeader(dataset_type=4),
                children=(
                    new_itunes_chunk(
                        MHLA,
                        EmptyChunkHeader(),
                        children=tuple(
                            new_itunes_chunk(
                                MHIA,
                                MhiaHeader(
                                    album_id=identity,
                                    sql_id=identity,
                                    album_track_db_id=representative,
                                ),
                                children=(
                                    new_string_mhod(MhodType.ALBUM_ITEM_ALBUM, album),
                                    new_string_mhod(MhodType.ALBUM_ITEM_ARTIST, artist),
                                ),
                            )
                            for identity, representative, album, artist in (
                                (10, 101, albums[0], "Artist A"),
                                (20, 103, albums[1], "Artist B"),
                            )
                        ),
                    ),
                ),
            )
        )
    for master in document.find_chunks(MhypHeader):
        if not master.chunk.header.master_flag:
            continue
        document = document.replace_chunk(
            master,
            replace(
                master.chunk,
                children=(
                    master.chunk.children[0],
                    new_itunes_chunk(
                        MHOD,
                        MhodHeader(mhod_type=52),
                        prefix=MhodLibraryIndexPrefix(sort_type=4),
                        payload=MhodLibraryIndexPayload(
                            tuple(master_order.index(i) for i in (1, 3, 2, 4)),
                            b"index-tail",
                        ),
                    ),
                    *(
                        (
                            new_itunes_chunk(
                                MHOD,
                                MhodHeader(mhod_type=53),
                                prefix=MhodLibraryJumpTablePrefix(sort_type=4),
                                payload=MhodLibraryJumpTablePayload(
                                    (
                                        MhodLibraryJumpTableEntry(
                                            letter_code=ord("N"),
                                            start_index=0,
                                            entry_count=4,
                                        ),
                                    ),
                                    b"jump-tail",
                                ),
                            ),
                        )
                        if jump_tables
                        else ()
                    ),
                    *(
                        new_itunes_chunk(MHIP, MhipHeader(track_id=i))
                        for i in master_order
                    ),
                ),
            ),
        )
    return IPodLibrary(write_iTunesDB(document))


def album_orders(data: bytes) -> dict[int, tuple[int, ...]]:
    result: dict[int, tuple[int, ...]] = {}
    for dataset in parse_iTunesDB(data).find_chunks(MhsdHeader):
        for master in dataset.find_chunks(MhypHeader):
            if not master.chunk.header.master_flag:
                continue
            ids = tuple(
                c.header.track_id
                for c in master.chunk.children
                if isinstance(c.header, MhipHeader)
            )
            for child in master.chunk.children:
                if (
                    isinstance(child.prefix, MhodLibraryIndexPrefix)
                    and child.prefix.sort_type == 4
                ):
                    assert isinstance(child.payload, MhodLibraryIndexPayload)
                    result[dataset.chunk.header.dataset_type] = tuple(
                        ids[i] for i in child.payload.indices
                    )
    return result


def chunk_bytes(chunk: ParsedChunk[ChunkHeader], data: bytes) -> bytes:
    return data[
        chunk.offset : chunk.offset + chunk.generic_header.length_or_child_count
    ]


@pytest.mark.parametrize(
    "albums",
    [
        ("Catalyst", "The Catalyst"),
        ("Nexus", "The Nexus"),
        ("f.e.a.r.", "F.E.A.R."),
        ("Greatest Hits", "Greatest Hits"),
    ],
)
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("native", [False, True])
def test_album_collisions_stay_grouped_after_metadata_edit(
    albums: tuple[str, str], explicit: bool, native: bool
) -> None:
    source = album_source(albums, explicit=explicit, native=native)
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, title=t.title + " edited") for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert album_orders(result.prepared.itunes) == {2: (1, 2, 3, 4), 3: (1, 2, 3, 4)}


@pytest.mark.parametrize("jump_tables", [False, True])
def test_explicit_rebuild_repairs_without_changing_tracks_or_master_occurrences(
    jump_tables: bool,
) -> None:
    source = album_source(jump_tables=jump_tables)
    original = source.serialize().itunes
    noop = source.prepare(source.analyze(source.begin_draft()))
    assert noop.prepared is not None and noop.prepared.itunes == original
    draft = source.begin_draft(rebuild_album_indexes=True)
    plan = source.analyze(draft)
    assert plan.changes_itunes and not plan.required_media
    result = source.prepare(plan)
    assert result.prepared is not None, result.issues
    assert album_orders(result.prepared.itunes) == {2: (1, 2, 3, 4), 3: (1, 2, 3, 4)}
    assert result.prepared.snapshot == source.snapshot
    before, after = parse_iTunesDB(original), parse_iTunesDB(result.prepared.itunes)
    assert sum(
        s.chunk.header.mhod_type == 53 for s in after.find_chunks(MhodHeader)
    ) == (2 if jump_tables else 0)
    for header in (MhitHeader, MhiaHeader, MhipHeader):
        assert [chunk_bytes(s.chunk, original) for s in before.find_chunks(header)] == [
            chunk_bytes(s.chunk, result.prepared.itunes)
            for s in after.find_chunks(header)
        ]
    assert {
        s.chunk.header.dataset_type: chunk_bytes(s.chunk, original)
        for s in before.find_chunks(MhsdHeader)
        if s.chunk.header.dataset_type not in (2, 3)
    } == {
        s.chunk.header.dataset_type: chunk_bytes(s.chunk, result.prepared.itunes)
        for s in after.find_chunks(MhsdHeader)
        if s.chunk.header.dataset_type not in (2, 3)
    }
    for selection in after.find_chunks(MhodHeader):
        if isinstance(selection.chunk.payload, MhodLibraryIndexPayload):
            assert selection.chunk.payload.trailing_data == b"index-tail"
        if isinstance(selection.chunk.payload, MhodLibraryJumpTablePayload):
            assert selection.chunk.payload.trailing_data == b"jump-tail"
    assert source.serialize().itunes == original
    loaded = IPodLibrary(result.prepared.itunes)
    again = loaded.prepare(
        loaded.analyze(loaded.begin_draft(rebuild_album_indexes=True))
    )
    assert (
        again.prepared is not None and again.prepared.itunes == result.prepared.itunes
    )


@pytest.mark.parametrize("jump_tables", [False, True])
def test_rebuild_verification_rejects_retained_bad_index(
    monkeypatch: pytest.MonkeyPatch,
    jump_tables: bool,
) -> None:
    source = album_source(jump_tables=jump_tables)
    original = source.serialize().itunes

    def corrupt(_document: DatabaseDocument[MhbdHeader]) -> bytes:
        return original

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(
        source.analyze(source.begin_draft(rebuild_album_indexes=True))
    )
    assert result.prepared is None
    assert any(i.code == "verification.playlist_index" for i in result.issues), (
        result.issues
    )


def test_rebuild_requires_the_normal_signing_identity() -> None:
    source = album_source()
    plan = source.analyze(
        source.begin_draft(rebuild_album_indexes=True),
        WriteTarget(checksum=WriteChecksum.HASH58),
    )
    assert plan.blocked
    assert any(i.code == "target.missing_guid" for i in plan.issues)


def test_compilation_members_keep_together_despite_per_track_sort_overrides() -> None:
    source = album_source()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(
                t,
                album_artist="Various Artists",
                artist=f"Performer {t.track_id}",
                metadata=replace(
                    t.metadata,
                    compilation=True,
                    sort_album="ZZZ" if t.track_id == 2 else "",
                ),
            )
            if t.track_id in (1, 2)
            else t
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert album_orders(result.prepared.itunes) == {2: (3, 4, 1, 2), 3: (3, 4, 1, 2)}


def test_member_ties_keep_master_occurrence_order() -> None:
    source = album_source()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, title="Tied", track_number=1) if t.track_id in (1, 2) else t
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert album_orders(result.prepared.itunes) == {2: (2, 1, 3, 4), 3: (2, 1, 3, 4)}


def test_album_artist_edit_invalidates_album_order() -> None:
    source = album_source()
    first = source.prepare(
        source.analyze(source.begin_draft(rebuild_album_indexes=True))
    )
    assert first.prepared is not None
    source = IPodLibrary(first.prepared.itunes)
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, sort_album_artist="ZZZ"))
            if t.track_id in (1, 2)
            else t
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert album_orders(result.prepared.itunes) == {2: (3, 4, 1, 2), 3: (3, 4, 1, 2)}


@pytest.mark.parametrize(
    ("albums", "expected"),
    [
        (("Nexus", "The Nexus"), (1, 2, 3, 4)),
        (("f.e.a.r.", "F.E.A.R."), (3, 4, 1, 2)),
    ],
)
def test_exact_album_identity_breaks_ties_with_the_same_artist(
    albums: tuple[str, str], expected: tuple[int, ...]
) -> None:
    source = album_source(albums)
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, artist="Shared Artist", album_artist="Shared Artist")
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert album_orders(result.prepared.itunes) == {2: expected, 3: expected}


def test_sort_artist_is_the_fallback_when_album_artist_is_absent() -> None:
    source = album_source()
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(
                t,
                album_artist="",
                metadata=replace(
                    t.metadata, sort_artist="ZZZ" if t.track_id < 3 else "AAA"
                ),
            )
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert album_orders(result.prepared.itunes) == {2: (3, 4, 1, 2), 3: (3, 4, 1, 2)}


def test_sort_edit_rebuilds_when_a_different_master_member_supplies_group_values() -> (
    None
):
    document = parse_iTunesDB(album_source().serialize().itunes)
    for selection in document.find_chunks(MhitHeader):
        if selection.chunk.header.track_id == 2:
            document = document.replace_chunk(
                selection,
                replace(
                    selection.chunk,
                    header=replace(selection.chunk.header, track_number=1),
                ),
            )
    source = IPodLibrary(write_iTunesDB(document))
    # Tracks 1 and 2 tie on disc/number. Track-table order chooses 1, but the
    # retained Master occurrence order chooses 2 as the Album representative.
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(t, metadata=replace(t.metadata, sort_album="Zulu"))
            if t.track_id == 2
            else t
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert album_orders(result.prepared.itunes) == {2: (3, 4, 1, 2), 3: (3, 4, 1, 2)}


def test_rebuild_regenerates_jump_ranges_for_distinct_letters() -> None:
    source = album_source(("Nexus", "Zebra"))
    result = source.prepare(
        source.analyze(source.begin_draft(rebuild_album_indexes=True))
    )
    assert result.prepared is not None, result.issues
    jumps = [
        s.chunk.payload
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhodHeader)
        if isinstance(s.chunk.payload, MhodLibraryJumpTablePayload)
    ]
    assert len(jumps) == 2
    assert all(
        jump.entries
        == (
            MhodLibraryJumpTableEntry(
                letter_code=ord("N"), start_index=0, entry_count=2
            ),
            MhodLibraryJumpTableEntry(
                letter_code=ord("Z"), start_index=2, entry_count=2
            ),
        )
        for jump in jumps
    )


@pytest.mark.parametrize(
    ("jump_tables", "malformation"),
    [
        (False, "missing_member"),
        (True, "missing_member"),
        (False, "duplicate_member"),
        (True, "duplicate_member"),
        (False, "duplicate_index"),
        (True, "duplicate_index"),
        (True, "duplicate_jump"),
        (True, "missing_index"),
    ],
)
def test_rebuild_rejects_ambiguous_native_structures(
    jump_tables: bool,
    malformation: str,
) -> None:
    document = parse_iTunesDB(album_source(jump_tables=jump_tables).serialize().itunes)
    master = next(
        s for s in document.find_chunks(MhypHeader) if s.chunk.header.master_flag
    )
    children = list(master.chunk.children)
    if malformation == "missing_member":
        children.pop()
    elif malformation == "duplicate_member":
        children.append(children[-1])
    elif malformation == "duplicate_index":
        children.insert(1, children[1])
    elif malformation == "duplicate_jump":
        children.insert(2, children[2])
    else:
        children.pop(1)
    document = document.replace_chunk(
        master, replace(master.chunk, children=tuple(children))
    )
    source = IPodLibrary(write_iTunesDB(document))
    original = source.serialize().itunes
    result = source.prepare(
        source.analyze(source.begin_draft(rebuild_album_indexes=True))
    )
    assert result.prepared is None
    issues = [i for i in result.issues if i.code == "library.album_rebuild_ambiguous"]
    assert len(issues) == 1
    assert issues[0].message == (
        "Album index rebuilding requires complete, unambiguous Master Playlist membership."
        if malformation in ("missing_member", "duplicate_member")
        else "Album index rebuilding requires exactly one Album index and at most one jump table."
    )
    assert source.serialize().itunes == original


@pytest.mark.parametrize(
    ("jump_tables", "corruption"),
    [
        (False, "missing_index"),
        (True, "missing_index"),
        (False, "duplicate_position"),
        (True, "duplicate_position"),
        (True, "jump_ranges"),
        (True, "missing_jump"),
        (False, "added_jump"),
    ],
)
def test_rebuild_verifier_checks_index_presence_and_jump_ranges(
    monkeypatch: pytest.MonkeyPatch, jump_tables: bool, corruption: str
) -> None:
    source = album_source(jump_tables=jump_tables)
    writer = write_iTunesDB

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        for selection in document.find_chunks(MhypHeader):
            if not selection.chunk.header.master_flag:
                continue
            if corruption == "missing_index":
                children = tuple(
                    c
                    for c in selection.chunk.children
                    if not isinstance(c.payload, MhodLibraryIndexPayload)
                )
            elif corruption == "missing_jump":
                children = tuple(
                    c
                    for c in selection.chunk.children
                    if not isinstance(c.payload, MhodLibraryJumpTablePayload)
                )
            elif corruption == "added_jump":
                jump = new_itunes_chunk(
                    MHOD,
                    MhodHeader(mhod_type=53),
                    prefix=MhodLibraryJumpTablePrefix(sort_type=4),
                    payload=MhodLibraryJumpTablePayload(
                        (
                            MhodLibraryJumpTableEntry(
                                letter_code=ord("N"),
                                start_index=0,
                                entry_count=4,
                            ),
                        ),
                        b"",
                    ),
                )
                children = selection.chunk.children
                if not any(
                    isinstance(c.payload, MhodLibraryJumpTablePayload) for c in children
                ):
                    children = (jump, *children)
            elif corruption == "duplicate_position":
                children = tuple(
                    replace(c, payload=replace(c.payload, indices=(0, 0, 2, 3)))
                    if isinstance(c.payload, MhodLibraryIndexPayload)
                    else c
                    for c in selection.chunk.children
                )
            else:
                children = tuple(
                    replace(c, payload=replace(c.payload, entries=()))
                    if isinstance(c.payload, MhodLibraryJumpTablePayload)
                    else c
                    for c in selection.chunk.children
                )
            document = document.replace_chunk(
                selection, replace(selection.chunk, children=children)
            )
        return writer(document)

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(
        source.analyze(source.begin_draft(rebuild_album_indexes=True))
    )
    assert result.prepared is None
    assert any(i.code == "verification.playlist_index" for i in result.issues), (
        result.issues
    )


def test_structural_rebuild_creates_missing_jump_tables() -> None:
    source = album_source(jump_tables=False)
    desired = replace(source.snapshot, tracks=tuple(reversed(source.snapshot.tracks)))
    result = source.prepare(
        source.analyze(source.begin_draft(desired, rebuild_album_indexes=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    assert album_orders(result.prepared.itunes) == {2: (1, 2, 3, 4), 3: (1, 2, 3, 4)}
    assert (
        sum(
            s.chunk.header.mhod_type == 53
            for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhodHeader)
        )
        == 10
    )


@pytest.mark.parametrize("structural", [False, True])
def test_rebuild_without_retained_indexes_preserves_or_creates_as_required(
    structural: bool,
) -> None:
    document = parse_iTunesDB(album_source().serialize().itunes)
    for selection in document.find_chunks(MhypHeader):
        if selection.chunk.header.master_flag:
            document = document.replace_chunk(
                selection,
                replace(
                    selection.chunk,
                    children=tuple(
                        c
                        for c in selection.chunk.children
                        if not isinstance(
                            c.prefix,
                            MhodLibraryIndexPrefix | MhodLibraryJumpTablePrefix,
                        )
                    ),
                ),
            )
    source = IPodLibrary(write_iTunesDB(document))
    original = source.serialize().itunes
    desired = source.snapshot
    if structural:
        desired = replace(desired, tracks=tuple(reversed(desired.tracks)))
    plan = source.analyze(source.begin_draft(desired, rebuild_album_indexes=True))
    assert plan.changes_itunes is structural
    result = source.prepare(
        plan,
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    if structural:
        assert album_orders(result.prepared.itunes) == {
            2: (1, 2, 3, 4),
            3: (1, 2, 3, 4),
        }
    else:
        assert result.prepared.itunes == original


@pytest.mark.parametrize("sort", [3, 36, 999])
def test_rebuild_preserves_other_indexes_byte_for_byte(sort: int) -> None:
    document = parse_iTunesDB(album_source().serialize().itunes)
    for selection in document.find_chunks(MhypHeader):
        if not selection.chunk.header.master_flag:
            continue
        other = new_itunes_chunk(
            MHOD,
            MhodHeader(mhod_type=52),
            prefix=MhodLibraryIndexPrefix(sort_type=sort),
            payload=MhodLibraryIndexPayload((3, 2, 1, 0), b"retained-index"),
        )
        document = document.replace_chunk(
            selection,
            replace(selection.chunk, children=(other, *selection.chunk.children)),
        )
    original = write_iTunesDB(document)
    source = IPodLibrary(original)
    result = source.prepare(
        source.analyze(source.begin_draft(rebuild_album_indexes=True))
    )
    assert result.prepared is not None, result.issues
    assert album_orders(result.prepared.itunes) == {2: (1, 2, 3, 4), 3: (1, 2, 3, 4)}
    before, after = parse_iTunesDB(original), parse_iTunesDB(result.prepared.itunes)
    assert [
        chunk_bytes(s.chunk, original)
        for s in before.find_chunks(MhodHeader)
        if isinstance(s.chunk.prefix, MhodLibraryIndexPrefix)
        and s.chunk.prefix.sort_type == sort
    ] == [
        chunk_bytes(s.chunk, result.prepared.itunes)
        for s in after.find_chunks(MhodHeader)
        if isinstance(s.chunk.prefix, MhodLibraryIndexPrefix)
        and s.chunk.prefix.sort_type == sort
    ]
