"""Artwork ownership, append-only assets, and independent packed color vectors."""

import base64
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.library.test_writing import library

from iPodDB.ArtworkDB.ithmb import (
    DecodedImage,
    IthmbLayout,
    IthmbPixelFormat,
    decode_ithmb,
)
from iPodDB.ArtworkDB.ithmb_writer import encode_ithmb
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import ArtworkPixels, CoverFormat, IPodLibrary
from iPodDB.library.writing import (
    ArtworkAsset,
    FileDependency,
    PreparedFile,
    SourceFile,
    WriteResources,
    WriteTarget,
)

COVER = CoverFormat(1055, 4, 4, 8, IthmbPixelFormat.RGB565_LE)
TARGET = WriteTarget(cover_formats=(COVER,), artwork_root_value=2)
RED = ArtworkAsset(-1, ArtworkPixels(4, 4, bytes((255, 0, 0)) * 16))
BLUE = ArtworkAsset(-2, ArtworkPixels(4, 4, bytes((0, 0, 255)) * 16))


def with_shared_artwork(
    *, target: WriteTarget = TARGET
) -> tuple[IPodLibrary, PreparedFile]:
    source = library()
    desired = replace(
        source.snapshot,
        tracks=tuple(replace(t, artwork_id=-1) for t in source.snapshot.tracks),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert result.prepared is not None and result.prepared.artwork is not None, (
        result.issues
    )
    assert len(result.prepared.artwork_files) == 1
    return IPodLibrary(result.prepared.itunes).with_artwork(
        result.prepared.artwork
    ), result.prepared.artwork_files[0]


def resources_for(file: PreparedFile) -> WriteResources:
    dependency = FileDependency(
        file.relative_path, len(file.data), hashlib.sha256(file.data).hexdigest()
    )
    return WriteResources(
        artwork=(BLUE,),
        files=(SourceFile(dependency, file.data),),
        file_inventory=(dependency,),
    )


def test_shared_artwork_replacement_does_not_change_other_track_or_source_prefix() -> (
    None
):
    source, file = with_shared_artwork()
    first, second = source.snapshot.tracks
    desired = replace(source.snapshot, tracks=(replace(first, artwork_id=-2), second))
    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET), resources_for(file)
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.tracks[1] == second
    assert result.prepared.snapshot.tracks[0].artwork_id != second.artwork_id
    assert result.prepared.artwork_files[0].data[: len(file.data)] == file.data
    assert result.prepared.retained_artwork
    read = (
        IPodLibrary(result.prepared.itunes)
        .with_artwork(result.prepared.artwork or b"")
        .artwork_read(result.prepared.snapshot.tracks[0].artwork_id, (COVER,), 4)
    )
    assert read is not None
    image = read.decode(
        result.prepared.artwork_files[0].data[read.offset : read.offset + read.length]
    )
    assert image.rgb888[2] > 240


def test_clear_removes_every_reverse_owner_link_and_keeps_shared_direct_owner() -> None:
    source, _ = with_shared_artwork()
    original = source.serialize()
    document = parse_ArtworkDB(original.artwork or b"")
    item = document.find_chunks(MhiiHeader)[0]
    first, second = source.snapshot.tracks
    assert first.ipod
    row = replace(
        item.chunk,
        header=replace(item.chunk.header, db_track_id_ref=first.ipod.db_track_id),
    )
    document = document.replace_chunk(item, row)
    container = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 1
    )
    extra = replace(row, header=replace(row.header, image_id=99))
    document = document.replace_chunk(
        container,
        replace(
            container.chunk, children=(container.chunk.children[0].append_child(extra),)
        ),
    )
    source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=0),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired), TARGET))
    assert result.prepared is not None and result.prepared.artwork is not None, (
        result.issues
    )
    reread = parse_ArtworkDB(result.prepared.artwork)
    assert all(
        s.chunk.header.db_track_id_ref == 0 for s in reread.find_chunks(MhiiHeader)
    )
    assert reread.header.next_mhii_id == document.header.next_mhii_id
    assert result.prepared.snapshot.tracks[1].artwork_id == second.artwork_id
    assert result.prepared.snapshot.tracks[0].artwork_id == 0
    assert not result.prepared.artwork_files


@pytest.mark.parametrize(
    "failure",
    ["missing_prefix", "wrong_bytes", "collision", "range", "missing_inventory"],
)
def test_invalid_artwork_resources_cannot_produce_output(failure: str) -> None:
    source, file = with_shared_artwork()
    resources = resources_for(file)
    if failure == "missing_prefix":
        resources = replace(resources, files=())
    elif failure == "wrong_bytes":
        resources = replace(
            resources, files=(replace(resources.files[0], data=b"wrong"),)
        )
    elif failure == "collision":
        resources = replace(
            resources,
            file_inventory=(
                resources.files[0].dependency,
                replace(
                    resources.files[0].dependency,
                    relative_path=file.relative_path.upper(),
                ),
            ),
        )
    elif failure == "missing_inventory":
        resources = replace(resources, file_inventory=None)
    else:
        original = source.serialize()
        document = parse_ArtworkDB(original.artwork or b"")
        row = document.find_chunks(MhiiHeader)[0]
        container = row.chunk.children[0]
        assert isinstance(container.payload, MhodContainerPayload)
        location = container.payload.child
        container = replace(
            container,
            payload=replace(
                container.payload,
                child=replace(
                    location, header=replace(location.header, ithmb_offset=100000)
                ),
            ),
        )
        document = document.replace_chunk(
            row, replace(row.chunk, children=(container,))
        )
        source = IPodLibrary(original.itunes).with_artwork(write_ArtworkDB(document))
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=-2),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), TARGET), resources
    )
    assert result.prepared is None and result.issues


def test_full_shard_allocation_uses_inventory_without_reading_full_unmodified_file() -> (
    None
):
    source = library()
    full = FileDependency("iPod_Control/Artwork/F1055_1.ithmb", 32, "0" * 64)
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=-1),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(
        source.analyze(
            source.begin_draft(desired), replace(TARGET, max_artwork_file_bytes=32)
        ),
        WriteResources(artwork=(RED,), file_inventory=(full,)),
    )
    assert result.prepared is not None, result.issues
    assert result.prepared.artwork_files[0].relative_path.endswith("F1055_2.ithmb")


def test_artwork_addition_keeps_original_unknown_data_and_photo_dataset() -> None:
    original = base64.b64decode(
        (
            Path(__file__).parents[2]
            / "fixtures/ArtworkDB/original-with-unknown-data.b64"
        ).read_bytes()
    )
    from iPodDB.ArtworkDB.builder.build_ArtworkDB import new_artwork_chunk
    from iPodDB.ArtworkDB.shared.chunk_defs.mhba import DEFINITION as MHBA
    from iPodDB.ArtworkDB.shared.chunk_defs.mhba import MhbaHeader

    document = parse_ArtworkDB(original)
    selection = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 2
    )
    album = new_artwork_chunk(
        MHBA, MhbaHeader(album_id=12, slide_duration=15, repeat=1, show_titles=1)
    )
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk, children=(selection.chunk.children[0].append_child(album),)
        ),
    )
    original = write_ArtworkDB(document)
    source = library().with_artwork(original)
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

    def photos(data: bytes) -> bytes:
        dataset = next(
            s.chunk
            for s in parse_ArtworkDB(data).find_chunks(MhsdHeader)
            if s.chunk.header.dataset_type == 2
        )
        return data[
            dataset.offset : dataset.offset
            + dataset.generic_header.length_or_child_count
        ]

    assert photos(original) == photos(result.prepared.artwork)
    assert b"mhzz" in result.prepared.artwork
    assert (
        parse_ArtworkDB(result.prepared.artwork).raw_source_suffix
        == parse_ArtworkDB(original).raw_source_suffix
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (IthmbPixelFormat.RGB565_LE, "00f8e0071f00"),
        (IthmbPixelFormat.RGB565_BE, "f80007e0001f"),
        (IthmbPixelFormat.RGB555_LE, "007ce0031f00"),
        (IthmbPixelFormat.RGB555_BE, "7c0003e0001f"),
        (IthmbPixelFormat.REC_RGB555_LE, "007ce0031f00"),
    ],
)
def test_packed_primary_colors_match_bitfield_vectors(
    kind: IthmbPixelFormat, expected: str
) -> None:
    colors = DecodedImage(3, 1, bytes((255, 0, 0, 0, 255, 0, 0, 0, 255)))
    assert encode_ithmb(colors, IthmbLayout(3, 1, 8, kind)) == bytes.fromhex(
        expected
    ) + bytes(2)


def test_aspect_ratio_is_retained_with_explicit_black_letterboxing() -> None:
    source = DecodedImage(4, 2, bytes((255, 0, 0)) * 8)
    layout = IthmbLayout(4, 4, 8, IthmbPixelFormat.RGB565_LE)
    decoded = decode_ithmb(encode_ithmb(source, layout), layout)
    assert decoded.pixels[:12] == bytes(12) and decoded.pixels[-12:] == bytes(12)
    assert decoded.pixels[12] > 240


def test_unsupported_layouts_and_unbounded_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        ArtworkPixels(8193, 1, b"")
    for layout in (
        IthmbLayout(2, 4, 4, IthmbPixelFormat.RGB565_BE_90),
        IthmbLayout(3, 1, 6, IthmbPixelFormat.UYVY),
        IthmbLayout(4, 4, 8, IthmbPixelFormat.I420_LE),
        IthmbLayout(4, 4, 8, IthmbPixelFormat.RGB565_LE, horizontal_padding=1),
    ):
        with pytest.raises(ValueError):
            encode_ithmb(DecodedImage(4, 4, RED.pixels.rgb888), layout)


def test_deleting_slideshow_music_blocks_instead_of_damaging_photo_relationships() -> (
    None
):
    from iPodDB.ArtworkDB.builder.build_ArtworkDB import (
        new_artwork_chunk,
        new_ArtworkDB,
    )
    from iPodDB.ArtworkDB.shared.chunk_defs.mhba import DEFINITION as MHBA
    from iPodDB.ArtworkDB.shared.chunk_defs.mhba import MhbaHeader

    document = new_ArtworkDB(next_mhii_id=1, unk_mhfd_0x10=2)
    selection = next(
        s for s in document.find_chunks(MhsdHeader) if s.chunk.header.dataset_type == 2
    )
    album = new_artwork_chunk(
        MHBA, MhbaHeader(album_id=12, play_music=1, db_track_id_ref=101)
    )
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk, children=(selection.chunk.children[0].append_child(album),)
        ),
    )
    source = library().with_artwork(write_ArtworkDB(document))
    playlist = source.snapshot.playlists[0]
    desired = replace(
        source.snapshot,
        tracks=source.snapshot.tracks[1:],
        playlists=(
            replace(
                playlist, entries=tuple(e for e in playlist.entries if e.track_id == 2)
            ),
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired, delete_omissions=True)),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert any(
        i.code == "artwork.photo_music_dependency" and i.record_id == 1
        for i in result.issues
    )
