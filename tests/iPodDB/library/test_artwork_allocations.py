"""Retained raster length and optional allocation length describe different facts."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_artwork_format_repair import (
    prepare_cover,
    retained_source,
    with_wrong_sizes,
)
from tests.iPodDB.library.test_write_artwork import COVER

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import IPodLibrary, content_sha256, read_content


@pytest.mark.parametrize("height", [0, 55, 56])
@pytest.mark.parametrize("extra", [0, 128])
def test_omitted_or_padded_allocation_accepts_cover_and_preserves_retained_bytes(
    height: int, extra: int
) -> None:
    cover = (
        replace(COVER, format_id=1061, width=56, height=height, row_bytes=112)
        if height
        else COVER
    )
    source, target, resources = retained_source((cover,))
    original = source.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    selection = document.find_chunks(MhiiHeader)[0]
    row = selection.chunk
    container = row.children[0]
    assert isinstance(container.payload, MhodContainerPayload)
    location = container.payload.child
    allocation = location.header.image_size + extra if extra else 0
    location = replace(
        location, header=replace(location.header, image_size_2=allocation)
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
    source = with_wrong_sizes(
        IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    )
    original = source.serialize()
    file = resources.files[0]
    prefix = read_content(file.data, 0, len(file.data)) + bytes([0xA5]) * extra
    dependency = replace(
        file.dependency, size=len(prefix), sha256=content_sha256(prefix)
    )
    resources = replace(
        resources,
        files=(replace(file, dependency=dependency, data=prefix),),
        file_inventory=(dependency,),
    )

    result = prepare_cover(source, target, resources)

    assert result.prepared is not None, " | ".join(i.message for i in result.issues)
    assert result.prepared.artwork is not None
    retained = (
        parse_ArtworkDB(result.prepared.artwork)
        .find_chunks(MhiiHeader)[0]
        .chunk.children[0]
    )
    assert isinstance(retained.payload, MhodContainerPayload)
    assert retained.payload.child.header == location.header
    assert read_content(result.prepared.artwork_files[0].data, 0, len(prefix)) == prefix
    assert source.serialize() == original


def test_padded_allocation_must_fit_captured_file() -> None:
    source, target, resources = retained_source()
    original = source.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    selection = document.find_chunks(MhiiHeader)[0]
    row = selection.chunk
    container = row.children[0]
    assert isinstance(container.payload, MhodContainerPayload)
    location = container.payload.child
    location = replace(
        location,
        header=replace(location.header, image_size_2=location.header.image_size + 1),
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
    source = with_wrong_sizes(
        IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    )
    result = prepare_cover(source, target, resources)
    assert result.prepared is None
    assert any(
        "outside its captured thumbnail file" in i.message for i in result.issues
    )
