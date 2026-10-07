"""Mixed F1061 rasters retain their own extents during artwork preparation."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_artwork_format_repair import prepare_cover
from tests.iPodDB.library.test_write_artwork import BLUE, COVER, RED, TARGET
from tests.iPodDB.library.test_writing import library

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import (
    FileDependency,
    IPodLibrary,
    SourceFile,
    WriteResources,
    WriteTarget,
    content_sha256,
    read_content,
)


def mixed_source(
    mhif_size: int, *, allocation: int = 6160, offset: int = 6272
) -> tuple[IPodLibrary, WriteTarget, WriteResources]:
    source = library()
    cover = replace(COVER, format_id=1061, width=56, height=56, row_bytes=112)
    target = replace(TARGET, cover_formats=(cover,))
    first, second = source.snapshot.tracks
    desired = replace(
        source.snapshot,
        tracks=(
            replace(first, artwork_id=RED.artwork_id),
            replace(second, artwork_id=BLUE.artwork_id),
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        WriteResources(artwork=(RED, BLUE), file_inventory=()),
    )
    assert result.prepared is not None and result.prepared.artwork is not None
    document = parse_ArtworkDB(result.prepared.artwork)
    selection = document.find_chunks(MhiiHeader)[1]
    row = selection.chunk
    container = row.children[0]
    assert isinstance(container.payload, MhodContainerPayload)
    location = container.payload.child
    location = replace(
        location,
        header=replace(
            location.header,
            image_height=55,
            image_size=6160,
            image_size_2=allocation,
            ithmb_offset=offset,
        ),
    )
    document = document.replace_chunk(
        selection,
        replace(
            row,
            children=(
                replace(container, payload=replace(container.payload, child=location)),
                *row.children[1:],
            ),
        ),
    )
    entry = document.find_chunks(MhifHeader)[0]
    document = document.replace_chunk(
        entry,
        replace(entry.chunk, header=replace(entry.chunk.header, image_size=mhif_size)),
    )
    file = result.prepared.artwork_files[0]
    data = read_content(file.data, 0, 6272 + allocation)
    dependency = FileDependency(file.relative_path, len(data), content_sha256(data))
    return (
        IPodLibrary(result.prepared.itunes).with_artwork(write_ArtworkDB(document)),
        target,
        WriteResources(
            artwork=(BLUE,),
            files=(SourceFile(dependency, data),),
            file_inventory=(dependency,),
        ),
    )


@pytest.mark.parametrize(
    "mhif_size, expected_size", [(6160, 6160), (6272, 6272), (99, 6272)]
)
@pytest.mark.parametrize("allocation", [6160, 6272])
def test_mixed_f1061_prepares_and_preserves_retained_artwork(
    mhif_size: int, expected_size: int, allocation: int
) -> None:
    source, target, resources = mixed_source(mhif_size, allocation=allocation)
    original = source.serialize()
    result = prepare_cover(source, target, resources)
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork is not None and original.artwork is not None
    before = parse_ArtworkDB(original.artwork).find_chunks(MhiiHeader)[1].chunk
    document = parse_ArtworkDB(result.prepared.artwork)
    after = next(
        s.chunk
        for s in document.find_chunks(MhiiHeader)
        if s.chunk.header.image_id == before.header.image_id
    )
    assert after == before
    assert document.find_chunks(MhifHeader)[0].chunk.header.image_size == expected_size
    output = result.prepared.artwork_files[0]
    assert (
        read_content(output.data, 0, len(resources.files[0].data))
        == resources.files[0].data
    )
    updated = IPodLibrary(result.prepared.itunes).with_artwork(result.prepared.artwork)
    read = updated.artwork_read(
        updated.snapshot.tracks[0].artwork_id, target.cover_formats, 56
    )
    assert read is not None and read.length == expected_size
    pixels = read.decode(read_content(output.data, read.offset, read.length))
    assert (pixels.width, pixels.height) == (56, expected_size // 112)
    assert source.serialize() == original


@pytest.mark.parametrize("offset", [0, 6271, 6273])
@pytest.mark.parametrize("allocation", [6160, 6272])
def test_mixed_f1061_invalid_ranges_still_block(offset: int, allocation: int) -> None:
    source, target, resources = mixed_source(6272, offset=offset, allocation=allocation)
    result = prepare_cover(source, target, resources)
    assert result.prepared is None
    assert any("overlap" in i.message or "outside" in i.message for i in result.issues)


def test_mixed_f1061_unrelated_edit_is_lossless() -> None:
    source, target, _ = mixed_source(99)
    original = source.serialize()
    desired = replace(source.snapshot, device_name="Renamed")
    result = source.prepare(source.analyze(source.begin_draft(desired), target))
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork == original.artwork
    assert not result.prepared.artwork_files


def test_mixed_f1061_majority_selects_layout_when_mhif_is_unrecognized() -> None:
    source, target, resources = mixed_source(99)
    original = source.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    row = document.find_chunks(MhiiHeader)[1].chunk
    shared = replace(
        row,
        header=replace(row.header, image_id=row.header.image_id + 1, db_track_id_ref=0),
    )
    dataset = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 1
    )
    document = document.replace_chunk(
        dataset,
        replace(
            dataset.chunk, children=(dataset.chunk.children[0].append_child(shared),)
        ),
    )
    source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    result = prepare_cover(source, target, resources)
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork is not None
    assert (
        parse_ArtworkDB(result.prepared.artwork)
        .find_chunks(MhifHeader)[0]
        .chunk.header.image_size
        == 6160
    )


def test_mixed_f1061_full_shard_requires_only_captured_inventory() -> None:
    source, target, resources = mixed_source(6272)
    result = prepare_cover(
        source,
        replace(target, max_artwork_file_bytes=len(resources.files[0].data)),
        replace(resources, files=()),
    )
    assert result.prepared is not None, result.issues
    assert [f.relative_path for f in result.prepared.artwork_files] == [
        "iPod_Control/Artwork/F1061_2.ithmb"
    ]
