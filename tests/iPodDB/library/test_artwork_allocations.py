"""Retained raster length and optional allocation length describe different facts."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_artwork_format_repair import (
    prepare_cover,
    retained_source,
    with_wrong_sizes,
)
from tests.iPodDB.library.test_write_artwork import (
    BLUE,
    COVER,
    TARGET,
    resources_for,
    with_shared_artwork,
)
from tests.iPodDB.library.test_writing import library

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import (
    IPodLibrary,
    TimedArtworkAsset,
    TimedArtworkFrame,
    WriteResources,
    content_sha256,
    read_content,
)


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


@pytest.mark.parametrize("counter", [0, 1, 99, 100])
def test_artwork_allocation_repairs_a_stale_counter_without_reusing_an_image(
    counter: int,
) -> None:
    healthy, file = with_shared_artwork()
    original = healthy.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    document = replace(document, header=replace(document.header, next_mhii_id=counter))
    source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    retained = source.serialize()
    first, second = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, artwork_id=-2), second))

    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET), resources_for(file)
    )

    assert result.prepared is not None and result.prepared.artwork is not None, (
        result.issues
    )
    output = parse_ArtworkDB(result.prepared.artwork)
    identities = [
        selection.chunk.header.image_id for selection in output.find_chunks(MhiiHeader)
    ]
    assert identities == [100, 101]
    assert output.header.next_mhii_id == 102
    assert result.prepared.snapshot.tracks[1].artwork_id == 100
    assert source.serialize() == retained


@pytest.mark.parametrize("counter", [0xFFFFFFFE, 0xFFFFFFFF])
def test_artwork_identity_counter_never_wraps_to_zero(counter: int) -> None:
    healthy, file = with_shared_artwork()
    original = healthy.serialize()
    assert original.artwork is not None
    document = parse_ArtworkDB(original.artwork)
    document = replace(document, header=replace(document.header, next_mhii_id=counter))
    source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    retained = source.serialize()
    first, second = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, artwork_id=-2), second))

    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET), resources_for(file)
    )

    if counter == 0xFFFFFFFF:
        assert result.prepared is None
        assert any(
            "identities are exhausted" in issue.message for issue in result.issues
        )
    else:
        assert result.prepared is not None and result.prepared.artwork is not None, (
            result.issues
        )
        assert result.prepared.snapshot.tracks[0].artwork_id == 0xFFFFFFFE
        assert (
            parse_ArtworkDB(result.prepared.artwork).header.next_mhii_id == 0xFFFFFFFF
        )
    assert source.serialize() == retained


def test_thumbnail_count_includes_all_formats_before_pixel_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = library()
    first, second = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, artwork_id=-2), second))
    # 32,768 source images fit MHIT's u16 count; two representations per image
    # would wrap the firmware's separate u16 thumbnail count to zero.
    asset = TimedArtworkAsset(
        -2, tuple(TimedArtworkFrame(time, BLUE.pixels) for time in range(32768))
    )
    target = replace(TARGET, cover_formats=(COVER, replace(COVER, format_id=1060)))

    def reject_encoding(*_args: object, **_kwargs: object) -> bytes:
        pytest.fail("Thumbnail overflow must be rejected before encoding pixels")

    monkeypatch.setattr("iPodDB.library._artwork_writing.encode_ithmb", reject_encoding)
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        WriteResources(artwork=(asset,), file_inventory=()),
    )
    assert result.prepared is None
    assert any(
        "native thumbnail count limit" in issue.message for issue in result.issues
    )
