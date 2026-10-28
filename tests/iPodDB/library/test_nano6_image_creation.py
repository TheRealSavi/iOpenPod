"""Nano 6 image-record structure follows the executed Original 1.x writer."""

import base64
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from tests.iPodDB.library.test_writing import library

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.media.photo_sync import photo_library_with_asset, prepare_sync_photo
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import (
    ArtworkAsset,
    ArtworkPixels,
    CoverFormat,
    CoverPixelFormat,
    FileDependency,
    IPodLibrary,
    PhotoPixelFormat,
    PhotoThumbnailFormat,
    PreparedPhoto,
    SourceFile,
    WriteResources,
    WriteTarget,
    content_sha256,
)
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB

FIXTURES = Path(__file__).parents[2] / "fixtures"
RED = ArtworkAsset(-1, ArtworkPixels(80, 80, bytes((255, 0, 0)) * 80 * 80))


def _original(artifact: str) -> bytes:
    # Emitted by origin/1.x a20242428b93b672d14b37230772dbad75139c69;
    # frozen evidence, with no Original source/runtime dependency.
    return base64.b64decode(
        "".join(
            (FIXTURES / artifact / "nano6-original-1x.b64")
            .read_text(encoding="ascii")
            .splitlines()
        ),
        validate=True,
    )


def _target() -> WriteTarget:
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MC688")
    assert profile is not None
    artwork = profile.capabilities.artwork
    return WriteTarget(
        artwork_root_value=artwork.artwork_root_value,
        include_auxiliary_image_records=artwork.include_auxiliary_image_records,
        photos_root_value=artwork.photos_root_value,
        cover_formats=tuple(
            CoverFormat(
                f.format_id,
                f.width,
                f.height,
                f.row_bytes,
                CoverPixelFormat(f.pixel_format.value),
            )
            for f in artwork.cover_formats
        ),
        photo_formats=tuple(
            PhotoThumbnailFormat(
                f.format_id,
                f.width,
                f.height,
                f.row_bytes,
                PhotoPixelFormat(f.pixel_format.value),
            )
            for f in artwork.photo_formats
        ),
    )


def _photo(photo_id: int = 100, shard: int = 1) -> PreparedPhoto:
    stream = BytesIO()
    Image.new("RGB", (80, 80), "red").save(stream, format="PNG")
    return prepare_sync_photo(
        stream.getvalue(),
        photo_id=photo_id,
        original_relative_path=f"Photos/Full Resolution/iOpenPod/{photo_id}.png",
        thumbnail_shard=shard,
        formats=_target().photo_formats,
        crop_format_ids=(1092,),
    )


def test_nano6_first_artwork_matches_original_root_and_image_children() -> None:
    original = parse_ArtworkDB(_original("ArtworkDB"))
    source = library()
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=-1),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(
        source.analyze(source.begin_draft(desired), _target()),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert result.prepared is not None and result.prepared.artwork is not None, (
        result.issues
    )
    written = parse_ArtworkDB(result.prepared.artwork)
    assert written.header.unk_mhfd_0x10 == original.header.unk_mhfd_0x10 == 2
    expected = original.find_chunks(MhiiHeader)[0].chunk
    actual = written.find_chunks(MhiiHeader)[0].chunk
    assert (
        tuple(
            c.header.mhod_type
            for c in actual.children
            if isinstance(c.header, MhodHeader)
        )
        == tuple(
            c.header.mhod_type
            for c in expected.children
            if isinstance(c.header, MhodHeader)
        )
        == (2, 2, 2, 2)
    )


def test_nano6_first_photo_matches_original_root_and_image_children() -> None:
    original = parse_PhotosDB(_original("PhotosDB"))
    target = _target()
    asset = _photo()
    source = library()
    desired = replace(source.snapshot, photos=photo_library_with_asset(None, asset))
    result = source.prepare(
        source.analyze(source.begin_draft(desired), target),
        WriteResources(photos=(asset,)),
    )
    assert result.prepared is not None and result.prepared.photos is not None, (
        result.issues
    )
    written = parse_PhotosDB(result.prepared.photos)
    assert written.header.unk_mhfd_0x10 == original.header.unk_mhfd_0x10 == 6
    expected = original.find_chunks(MhiiHeader)[0].chunk
    actual = written.find_chunks(MhiiHeader)[0].chunk
    assert (
        tuple(
            c.header.mhod_type
            for c in actual.children
            if isinstance(c.header, MhodHeader)
        )
        == tuple(
            c.header.mhod_type
            for c in expected.children
            if isinstance(c.header, MhodHeader)
        )
        == (5, 2, 2)
    )


@pytest.mark.parametrize("root_value", [2, 6])
def test_nano6_replacement_preserves_retained_root_and_auxiliary_data(
    root_value: int,
) -> None:
    source = library()
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=-1),
            source.snapshot.tracks[1],
        ),
    )
    legacy_target = replace(
        _target(), artwork_root_value=root_value, include_auxiliary_image_records=True
    )
    first = source.prepare(
        source.analyze(source.begin_draft(desired), legacy_target),
        WriteResources(artwork=(RED,), file_inventory=()),
    )
    assert first.prepared is not None and first.prepared.artwork is not None, (
        first.issues
    )
    document = parse_ArtworkDB(first.prepared.artwork)
    selection = document.find_chunks(MhiiHeader)[0]
    auxiliary = selection.chunk.children[-1]
    assert isinstance(auxiliary.payload, MhodOpaquePayload)
    retained_body = auxiliary.payload.data[:-4] + b"KEEP"
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk,
            header=replace(selection.chunk.header, image_order_key=0x12345678),
            children=(
                *selection.chunk.children[:-1],
                replace(auxiliary, payload=MhodOpaquePayload(retained_body)),
            ),
        ),
    )
    source = IPodLibrary(first.prepared.itunes).with_artwork(write_ArtworkDB(document))
    desired = replace(
        source.snapshot,
        tracks=(
            replace(source.snapshot.tracks[0], artwork_id=-2),
            source.snapshot.tracks[1],
        ),
    )
    files = tuple(
        SourceFile(
            FileDependency(
                file.relative_path, len(file.data), content_sha256(file.data)
            ),
            file.data,
        )
        for file in first.prepared.artwork_files
    )
    second = source.prepare(
        source.analyze(source.begin_draft(desired), _target()),
        WriteResources(
            artwork=(replace(RED, artwork_id=-2),),
            files=files,
            file_inventory=tuple(file.dependency for file in files),
        ),
    )
    assert second.prepared is not None and second.prepared.artwork is not None, (
        second.issues
    )
    written = parse_ArtworkDB(second.prepared.artwork)
    assert written.header.unk_mhfd_0x10 == root_value
    image_id = second.prepared.snapshot.tracks[0].artwork_id
    image = next(
        s.chunk
        for s in written.find_chunks(MhiiHeader)
        if s.chunk.header.image_id == image_id
    )
    assert image.header.image_order_key == 0x12345678
    assert tuple(
        c.payload.data
        for c in image.children
        if isinstance(c.payload, MhodOpaquePayload)
    ) == (retained_body,)


def test_nano6_photo_addition_retains_existing_auxiliary_and_unknown_data() -> None:
    source = library()
    first_photo = _photo()
    desired = replace(
        source.snapshot, photos=photo_library_with_asset(None, first_photo)
    )
    first = source.prepare(
        source.analyze(
            source.begin_draft(desired),
            replace(_target(), include_auxiliary_image_records=True),
        ),
        WriteResources(photos=(first_photo,)),
    )
    assert first.prepared is not None and first.prepared.photos is not None, (
        first.issues
    )
    document = parse_PhotosDB(first.prepared.photos)
    selection = document.find_chunks(MhiiHeader)[0]
    auxiliary = selection.chunk.children[-1]
    assert isinstance(auxiliary.payload, MhodOpaquePayload)
    retained_body = auxiliary.payload.data[:-4] + b"KEEP"
    document = document.replace_chunk(
        selection,
        replace(
            selection.chunk,
            header=replace(selection.chunk.header, image_order_key=0x12345678),
            children=(
                *selection.chunk.children[:-1],
                replace(auxiliary, payload=MhodOpaquePayload(retained_body)),
            ),
        ),
    )
    source = IPodLibrary(first.prepared.itunes).with_photos(write_PhotosDB(document))
    second_photo = _photo(photo_id=101, shard=2)
    desired = replace(
        source.snapshot,
        photos=photo_library_with_asset(source.snapshot.photos, second_photo),
    )
    second = source.prepare(
        source.analyze(source.begin_draft(desired), _target()),
        WriteResources(photos=(second_photo,)),
    )
    assert second.prepared is not None and second.prepared.photos is not None, (
        second.issues
    )
    written = parse_PhotosDB(second.prepared.photos)
    assert written.header.unk_mhfd_0x10 == 6
    retained, added = (s.chunk for s in written.find_chunks(MhiiHeader))
    assert retained.header.image_order_key == 0x12345678
    assert tuple(
        c.payload.data
        for c in retained.children
        if isinstance(c.payload, MhodOpaquePayload)
    ) == (retained_body,)
    assert tuple(
        c.header.mhod_type for c in added.children if isinstance(c.header, MhodHeader)
    ) == (5, 2, 2)
