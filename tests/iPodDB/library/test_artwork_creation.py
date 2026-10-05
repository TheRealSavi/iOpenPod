"""Fresh ArtworkDB layouts, retained variants, and older Track relationships."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_write_artwork import RED, TARGET
from tests.iPodDB.library.test_writing import library

from device_registry import DEFAULT_DEVICE_REGISTRY, ArtworkFormat
from iPodDB.ArtworkDB.builder.build_ArtworkDB import new_ArtworkDB
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import build_artwork_index
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import CoverFormat, CoverPixelFormat, IPodLibrary, WriteResources

COVER_SETS = tuple(
    dict.fromkeys(
        p.capabilities.artwork.cover_formats
        for p in DEFAULT_DEVICE_REGISTRY.profiles
        if p.capabilities.artwork.supports_cover_art
    )
)


@pytest.mark.parametrize("formats", COVER_SETS)
def test_first_database_contains_every_profile_cover_layout(
    formats: tuple[ArtworkFormat, ...],
) -> None:
    source = library()
    target = replace(
        TARGET,
        cover_formats=tuple(
            CoverFormat(
                f.format_id,
                f.width,
                f.height,
                f.row_bytes,
                CoverPixelFormat(f.pixel_format.value),
            )
            for f in formats
        ),
    )
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-1) for t in source.snapshot.tracks),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert result.prepared and result.prepared.artwork, result.issues
    document = parse_ArtworkDB(result.prepared.artwork)
    assert [s.chunk.header.dataset_type for s in document.find_chunks(MhsdHeader)] == [
        1,
        2,
        3,
    ]
    sizes = {
        s.chunk.header.format_id: s.chunk.header.image_size
        for s in document.find_chunks(MhifHeader)
    }
    index = build_artwork_index(document)
    assert len(index.items) == 1
    locations = {location.format_id: location for location in index.items[0].locations}
    for f in formats:
        assert sizes[f.format_id] == f.row_bytes * f.height
        location = locations[f.format_id]
        assert (
            location.width,
            location.height,
            location.offset,
            location.byte_length,
        ) == (f.width, f.height, 0, sizes[f.format_id])
    assert write_ArtworkDB(document) == result.prepared.artwork


@pytest.mark.parametrize("root_value", [1, 2, 6, 77])
def test_existing_root_variant_is_preserved(root_value: int) -> None:
    source = library().with_artwork(
        write_ArtworkDB(new_ArtworkDB(next_mhii_id=300, unk_mhfd_0x10=root_value))
    )
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=-1),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired), replace(TARGET, artwork_root_value=6)
        ),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert result.prepared and result.prepared.artwork, result.issues
    document = parse_ArtworkDB(result.prepared.artwork)
    assert document.header.unk_mhfd_0x10 == root_value
    assert document.header.next_mhii_id == 301


@pytest.mark.parametrize("shared", [False, True])
def test_older_track_headers_use_distinct_reverse_artwork_links(shared: bool) -> None:
    document = parse_iTunesDB(library().serialize().itunes)
    for selection in reversed(document.find_chunks(MhitHeader)):
        document = document.replace_chunk(
            selection,
            replace(selection.chunk, raw_header=selection.chunk.raw_header[:0x148]),
        )
    source = IPodLibrary(write_iTunesDB(document))
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(track, artwork_id=-1) if shared or track.track_id == 1 else track
            for track in source.snapshot.tracks
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert result.prepared and result.prepared.artwork, result.issues
    artwork = parse_ArtworkDB(result.prepared.artwork)
    rows = artwork.find_chunks(MhiiHeader)
    assert len(rows) == (2 if shared else 1)
    owners = {s.chunk.header.db_track_id_ref for s in rows}
    assert owners == ({101, 102} if shared else {101})
    assert all(
        s.chunk.generic_header.header_length == 0x148
        for s in parse_iTunesDB(result.prepared.itunes).find_chunks(MhitHeader)
    )
    assert all(
        t.artwork_id > 0
        for t in result.prepared.snapshot.tracks
        if shared or t.track_id == 1
    )


@pytest.mark.parametrize(
    "problem", ["missing_images", "missing_formats", "duplicate_formats"]
)
def test_ambiguous_or_incompatible_existing_layout_blocks_additions(
    problem: str,
) -> None:
    from tests.iPodDB.library.test_write_artwork import (
        BLUE,
        resources_for,
        with_shared_artwork,
    )

    source, file = with_shared_artwork()
    document = parse_ArtworkDB(source.serialize().artwork or b"")
    if problem in ("missing_images", "missing_formats"):
        kind = 1 if problem == "missing_images" else 3
        document = replace(
            document,
            children=tuple(
                c
                for c in document.children
                if not isinstance(c.header, MhsdHeader) or c.header.dataset_type != kind
            ),
        )
    else:
        selection = next(
            s
            for s in document.find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 3
        )
        container = selection.chunk.children[0]
        info = container.children[0]
        assert isinstance(info.header, MhifHeader)
        children = (info, info)
        document = document.replace_chunk(
            selection,
            replace(selection.chunk, children=(replace(container, children=children),)),
        )
    source = IPodLibrary(source.serialize().itunes).with_artwork(
        write_ArtworkDB(document)
    )
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=BLUE.artwork_id),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET), resources_for(file)
    )
    assert result.prepared is None
    assert any(i.severity.value == "error" for i in result.issues)


def test_orphan_thumbnail_prefix_is_preserved_and_next_frame_is_aligned() -> None:
    import hashlib

    from iPodDB.library import FileDependency, SourceFile

    source = library()
    prefix = b"existing orphan bytes"
    dependency = FileDependency(
        "iPod_Control/Artwork/F1055_1.ithmb",
        len(prefix),
        hashlib.sha256(prefix).hexdigest(),
    )
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=-1),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET),
        WriteResources(
            artwork=(RED,),
            files=(SourceFile(dependency, prefix),),
            file_inventory=(dependency,),
        ),
    )
    assert result.prepared and result.prepared.artwork, result.issues
    data = result.prepared.artwork_files[0].data
    assert isinstance(data, bytes)
    assert data.startswith(prefix)
    item = build_artwork_index(parse_ArtworkDB(result.prepared.artwork)).items[0]
    assert item.locations[0].offset == 32
    assert data[len(prefix) : 32] == bytes(32 - len(prefix))


def test_additional_cover_format_precedes_retained_auxiliary_body() -> None:
    from tests.iPodDB.library.test_write_artwork import (
        BLUE,
        COVER,
        resources_for,
        with_shared_artwork,
    )

    source, file = with_shared_artwork()
    target = replace(TARGET, cover_formats=(COVER, replace(COVER, format_id=1060)))
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=BLUE.artwork_id),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target), resources_for(file)
    )
    assert result.prepared and result.prepared.artwork, result.issues
    row = parse_ArtworkDB(result.prepared.artwork).find_chunks(MhiiHeader)[-1].chunk
    assert [
        c.header.mhod_type for c in row.children if isinstance(c.header, MhodHeader)
    ] == [2, 2, 6]


def test_profile_without_sparse_artwork_gets_distinct_track_owners() -> None:
    source = library()
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-1) for t in source.snapshot.tracks),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired), replace(TARGET, supports_sparse_artwork=False)
        ),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert result.prepared and result.prepared.artwork, result.issues
    rows = parse_ArtworkDB(result.prepared.artwork).find_chunks(MhiiHeader)
    assert {s.chunk.header.db_track_id_ref for s in rows} == {101, 102}
    assert len({t.artwork_id for t in result.prepared.snapshot.tracks}) == 2
    assert len(result.prepared.artwork_files) == 1
    assert len(result.prepared.artwork_files[0].data) == 32


@pytest.mark.parametrize("empty_database", [False, True])
def test_missing_images_do_not_let_new_artwork_capture_unrelated_track_references(
    empty_database: bool,
) -> None:
    document = parse_iTunesDB(library().serialize().itunes)
    second = document.find_chunks(MhitHeader)[1]
    document = document.replace_chunk(
        second,
        replace(second.chunk, header=replace(second.chunk.header, artwork_id_ref=100)),
    )
    source = IPodLibrary(write_iTunesDB(document))
    if empty_database:
        source = source.with_artwork(
            write_ArtworkDB(new_ArtworkDB(next_mhii_id=100, unk_mhfd_0x10=6))
        )
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=-1),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert result.prepared and result.prepared.artwork, result.issues
    assert result.prepared.snapshot.tracks[0].artwork_id == 101
    assert result.prepared.snapshot.tracks[1].artwork_id == 0
    # An unavailable display association does not authorize rewriting its source field.
    assert (
        parse_iTunesDB(result.prepared.itunes)
        .find_chunks(MhitHeader)[1]
        .chunk.header.artwork_id_ref
        == 100
    )
