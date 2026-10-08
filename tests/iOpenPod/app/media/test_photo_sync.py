"""Photo Sync preserves originals and publishes verified, independent viewing copies."""

import struct
import zlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

import pytest
from PIL import Image
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.library.test_writing import library

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.media.photo_sync import photo_library_with_asset, prepare_sync_photo
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.library import (
    IPodLibrary,
    PhotoFileFormat,
    PhotoPixelFormat,
    PhotoRepresentationKind,
    PhotoThumbnailFormat,
    PreparedPhoto,
    WriteResources,
    WriteTarget,
    content_sha256,
    select_photo_thumbnail,
)
from iPodDB.library._document_edit import rebuild
from iPodDB.PhotosDB.builder.build_PhotosDB import new_photos_chunk
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhba import MhbaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhia import DEFINITION as MHIA_DEFINITION
from iPodDB.PhotosDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB

if TYPE_CHECKING:
    from iPodDB.shared.chunk import ChunkHeader, ParsedChunk

FORMATS = (
    PhotoThumbnailFormat(1024, 8, 4, 16, PhotoPixelFormat.RGB565_LE),
    PhotoThumbnailFormat(1025, 8, 8, 16, PhotoPixelFormat.RGB565_LE),
)


def large_photo_png(width: int, height: int) -> bytes:
    """Encode a large 1-bit raster without allocating its full decoded image."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    compressor = zlib.compressobj()
    row = b"\x00" + b"\xff" * ((width + 7) // 8)
    payload = b"".join(compressor.compress(row) for _ in range(height))
    payload += compressor.flush()
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0))
        + chunk(b"IDAT", payload)
        + chunk(b"IEND", b"")
    )


@pytest.mark.parametrize("size", [(6016, 6016), (15360, 8640), (32768, 512)])
def test_large_photos_prepare_and_verify_without_rejecting_source_dimensions(
    size: tuple[int, int],
) -> None:
    data = large_photo_png(*size)
    asset = prepare_sync_photo(
        data,
        photo_id=101,
        original_relative_path="Photos/Full Resolution/iOpenPod/large.png",
        thumbnail_shard=1,
        formats=FORMATS,
    )
    assert asset.files[0].data == data
    assert (
        asset.photo.representations[0].width,
        asset.photo.representations[0].height,
    ) == size
    source = library()
    plan = source.analyze(
        source.begin_draft(
            replace(source.snapshot, photos=photo_library_with_asset(None, asset))
        ),
        WriteTarget(photo_formats=FORMATS, photos_root_value=6),
    )
    result = source.prepare(plan, WriteResources(photos=(asset,)))
    assert result.prepared is not None, result.issues


def test_photo_preparation_keeps_pillows_own_pixel_limit() -> None:
    pixel_limit = Image.MAX_IMAGE_PIXELS
    with pytest.raises(ValueError, match="could not be decoded"):
        prepare_sync_photo(
            large_photo_png(16384, 16384),
            photo_id=101,
            original_relative_path="Photos/Full Resolution/iOpenPod/large.png",
            thumbnail_shard=1,
            formats=FORMATS,
        )
    assert pixel_limit == Image.MAX_IMAGE_PIXELS


def test_reduced_panorama_keeps_enough_detail_for_cropped_thumbnails() -> None:
    with Image.new("RGB", (4096, 64), "red") as image:
        image.paste("blue", (0, 32, 4096, 64))
        output = BytesIO()
        image.save(output, format="PNG")
    asset = prepare_sync_photo(
        output.getvalue(),
        photo_id=101,
        original_relative_path="Photos/Full Resolution/iOpenPod/panorama.png",
        thumbnail_shard=1,
        formats=FORMATS,
        crop_format_ids=(1024,),
    )
    read = select_photo_thumbnail(asset.photo, FORMATS, 8, format_id=1024)
    assert read is not None
    assert isinstance(asset.files[1].data, bytes)
    pixels = read.decode(asset.files[1].data)
    assert pixels.rgb888[0] > 200 and pixels.rgb888[2] < 50
    assert pixels.rgb888[-3] < 50 and pixels.rgb888[-1] > 200


def _image() -> bytes:
    image = Image.new("RGB", (20, 40), "red")
    image.paste(Image.new("RGB", (20, 20), "blue"), (0, 20))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _wide_image() -> bytes:
    image = Image.new("RGB", (40, 20), "red")
    image.paste(Image.new("RGB", (20, 20), "blue"), (20, 0))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _asset(
    *, photo_id: int = 101, shard: int = 1, fit: bool = False, rotate: bool = False
) -> PreparedPhoto:
    return prepare_sync_photo(
        _image(),
        photo_id=photo_id,
        original_relative_path=f"Photos/Full Resolution/iOpenPod/{shard}.png",
        thumbnail_shard=shard,
        formats=FORMATS,
        fit_thumbnails=fit,
        crop_format_ids=(1024,),
        rotate_tall_photos=rotate,
    )


def test_photo_fit_and_rotation_change_only_verified_viewing_copies() -> None:
    cropped, fitted, rotated = _asset(), _asset(fit=True), _asset(fit=True, rotate=True)
    assert (
        cropped.files[0].data
        == fitted.files[0].data
        == rotated.files[0].data
        == _image()
    )
    assert cropped.files[1].data != fitted.files[1].data != rotated.files[1].data
    cropped_low = cropped.photo.representations[1]
    assert (
        cropped_low.width,
        cropped_low.height,
        cropped_low.horizontal_padding,
        cropped_low.vertical_padding,
    ) == (8, 4, 0, 0)
    high_resolution = cropped.photo.representations[2]
    assert (
        high_resolution.width,
        high_resolution.height,
        high_resolution.horizontal_padding,
        high_resolution.vertical_padding,
    ) == (6, 8, 2, 0)
    high_read = select_photo_thumbnail(cropped.photo, FORMATS, 8, format_id=1025)
    assert high_read is not None
    assert isinstance(cropped.files[2].data, bytes)
    high_pixels = high_read.decode(cropped.files[2].data)
    assert high_pixels.rgb888[:3] == b"\xff\x00\x00"
    assert high_pixels.rgb888[-3:] == b"\x00\x00\xff"
    assert (high_pixels.width, high_pixels.height) == (4, 8)
    representation = fitted.photo.representations[1]
    assert (
        representation.width,
        representation.height,
        representation.horizontal_padding,
        representation.vertical_padding,
    ) == (5, 4, 3, 0)
    read = select_photo_thumbnail(fitted.photo, FORMATS, 8, format_id=1024)
    assert read is not None
    assert isinstance(fitted.files[1].data, bytes)
    pixels = read.decode(fitted.files[1].data)
    assert pixels.rgb888[:3] == b"\xff\x00\x00"
    assert pixels.rgb888[-3:] == b"\x00\x00\xff"
    assert (pixels.width, pixels.height) == (2, 4)


def test_photo_fit_records_vertical_padding_for_a_wide_source() -> None:
    image_format = PhotoThumbnailFormat(1026, 4, 8, 8, PhotoPixelFormat.RGB565_LE)
    asset = prepare_sync_photo(
        _wide_image(),
        photo_id=101,
        original_relative_path="Photos/Full Resolution/iOpenPod/1.png",
        thumbnail_shard=1,
        formats=(image_format,),
    )

    representation = asset.photo.representations[1]
    assert (
        representation.width,
        representation.height,
        representation.horizontal_padding,
        representation.vertical_padding,
    ) == (4, 5, 0, 3)
    read = select_photo_thumbnail(asset.photo, (image_format,), 8)
    assert read is not None
    assert isinstance(asset.files[1].data, bytes)
    pixels = read.decode(asset.files[1].data)
    assert pixels.rgb888[:3] == b"\xff\x00\x00"
    assert pixels.rgb888[-3:] == b"\x00\x00\xff"
    assert (pixels.width, pixels.height) == (4, 2)


def test_first_photosdb_creation_and_explicit_photo_replacement_round_trip() -> None:
    source = library()
    asset = _asset()
    photos = photo_library_with_asset(None, asset)
    target = WriteTarget(photo_formats=FORMATS, photos_root_value=6)
    plan = source.analyze(
        source.begin_draft(replace(source.snapshot, photos=photos)), target
    )
    assert not plan.blocked, plan.issues
    assert plan.required_photos == (101,)
    result = source.prepare(plan, WriteResources(photos=(asset,)))
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == source.serialize().itunes
    assert result.prepared.photos is not None
    assert result.prepared.snapshot.photos == photos
    document = parse_PhotosDB(result.prepared.photos)
    assert document.header.unk_mhfd_0x10 == 6
    assert document.find_chunks(MhiiHeader)[0].chunk.header.image_id == 101
    assert write_PhotosDB(document) == result.prepared.photos
    loaded = IPodLibrary.parse(result.prepared.itunes).with_photos(
        result.prepared.photos
    )
    newer = _asset(shard=2, rotate=True)
    desired = replace(loaded.snapshot, photos=photo_library_with_asset(photos, newer))
    assert loaded.analyze(loaded.begin_draft(desired), target).blocked
    replacement = loaded.analyze(
        loaded.begin_draft(desired, replace_photos=(101,)), target
    )
    updated = loaded.prepare(replacement, WriteResources(photos=(newer,)))
    assert updated.prepared is not None, updated.issues
    assert updated.prepared.snapshot.photos == desired.photos
    assert updated.prepared.snapshot.photos is not None
    assert updated.prepared.snapshot.photos.albums == photos.albums


def test_photo_resources_accept_verified_batch_larger_than_512_mib() -> None:
    class PaddedPhoto:
        """A valid PNG with trailing bytes, without retaining a huge batch."""

        def __init__(self) -> None:
            self.png = _image()
            self.sha256 = content_sha256(self)

        def __len__(self) -> int:
            return 60 * 1024 * 1024

        def read_at(self, offset: int, length: int) -> bytes:
            prefix = self.png[offset : offset + length]
            return prefix + bytes(length - len(prefix))

    source = library()
    data = PaddedPhoto()
    assets: list[PreparedPhoto] = []
    photos = None
    for number in range(1, 10):
        asset = prepare_sync_photo(
            data.png,
            photo_id=100 + number,
            original_relative_path=f"Photos/Full Resolution/iOpenPod/{number}.png",
            thumbnail_shard=number,
            formats=FORMATS,
        )
        original = asset.files[0]
        asset = replace(
            asset,
            photo=replace(
                asset.photo,
                source_size_bytes=len(data),
                representations=(
                    replace(asset.photo.representations[0], size_bytes=len(data)),
                    *asset.photo.representations[1:],
                ),
            ),
            files=(
                replace(
                    original,
                    dependency=replace(
                        original.dependency, size=len(data), sha256=data.sha256
                    ),
                    data=data,
                ),
                *asset.files[1:],
            ),
        )
        assets.append(asset)
        photos = photo_library_with_asset(photos, asset)
    assert (
        sum(len(file.data) for asset in assets for file in asset.files)
        > 512 * 1024 * 1024
    )
    plan = source.analyze(
        source.begin_draft(replace(source.snapshot, photos=photos)),
        WriteTarget(photo_formats=FORMATS, photos_root_value=6),
    )
    result = source.prepare(plan, WriteResources(photos=tuple(assets)))
    assert result.prepared is not None, result.issues
    assert result.prepared.snapshot.photos == photos


def test_photo_preparation_rejects_missing_or_changed_asset_evidence() -> None:
    source = library()
    asset = _asset()
    desired = replace(source.snapshot, photos=photo_library_with_asset(None, asset))
    assert source.analyze(source.begin_draft(desired)).blocked
    plan = source.analyze(
        source.begin_draft(desired),
        WriteTarget(photo_formats=FORMATS, photos_root_value=6),
    )
    assert source.prepare(plan).prepared is None
    changed = replace(
        asset, files=(replace(asset.files[0], data=b"changed"), *asset.files[1:])
    )
    result = source.prepare(plan, WriteResources(photos=(changed,)))
    assert result.prepared is None
    assert any(issue.code == "resources.invalid_photo" for issue in result.issues)
    with pytest.raises(ValueError, match="inside Photos"):
        prepare_sync_photo(
            _image(),
            photo_id=1,
            original_relative_path="outside.png",
            thumbnail_shard=1,
            formats=FORMATS,
        )


def test_photo_format_size_mismatch_reports_format_and_sizes() -> None:
    source = library()
    format_1013 = PhotoThumbnailFormat(
        1013, 220, 176, 440, PhotoPixelFormat.RGB565_BE_90
    )
    asset = prepare_sync_photo(
        _image(),
        photo_id=101,
        original_relative_path="Photos/Full Resolution/iOpenPod/1.png",
        thumbnail_shard=1,
        formats=(format_1013,),
        rotate_tall_photos=True,
    )
    desired_photos = replace(
        photo_library_with_asset(None, asset),
        formats=(PhotoFileFormat(1013, 77_440),),
    )
    plan = source.analyze(
        source.begin_draft(replace(source.snapshot, photos=desired_photos)),
        WriteTarget(photo_formats=(format_1013,), photos_root_value=6),
    )

    result = source.prepare(plan, WriteResources(photos=(asset,)))

    issue = next(
        issue for issue in result.issues if issue.code == "resources.invalid_photo"
    )
    assert issue.message == (
        "Photo format 1013 declares 77440 bytes, "
        "but the prepared representation contains 96800 bytes."
    )


def test_f1067_photo_thumbnail_matches_its_two_byte_record_size() -> None:
    source = library()
    format_1067 = PhotoThumbnailFormat(1067, 720, 480, 1080, PhotoPixelFormat.I420_LE)
    asset = prepare_sync_photo(
        _image(),
        photo_id=101,
        original_relative_path="Photos/Full Resolution/iOpenPod/1.png",
        thumbnail_shard=1,
        formats=(format_1067,),
        rotate_tall_photos=True,
    )
    desired_photos = replace(
        photo_library_with_asset(None, asset),
        formats=(PhotoFileFormat(1067, 691_200),),
    )
    plan = source.analyze(
        source.begin_draft(replace(source.snapshot, photos=desired_photos)),
        WriteTarget(photo_formats=(format_1067,), photos_root_value=6),
    )

    result = source.prepare(plan, WriteResources(photos=(asset,)))

    assert result.prepared is not None, result.issues
    assert asset.photo.representations[1].size_bytes == 691_200


def test_photo_transaction_publishes_assets_before_database_and_reclaims_replacement(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        formats = tuple(
            PhotoThumbnailFormat(
                f.format_id,
                f.width,
                f.height,
                f.row_bytes,
                PhotoPixelFormat(f.pixel_format.value),
            )
            for f in device.active.profile.capabilities.artwork.photo_formats
        )
        asset = prepare_sync_photo(
            _image(),
            photo_id=101,
            original_relative_path="Photos/Full Resolution/iOpenPod/first.png",
            thumbnail_shard=1,
            formats=formats,
            fit_thumbnails=True,
        )
        photos = photo_library_with_asset(None, asset)
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                replace(device.active.library, photos=photos),
                device.active,
                1,
                1,
                photos=(asset,),
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        paths = tuple(
            change.path for change in review.file_changes if change.action == "write"
        )
        assert paths[-1] == "Photos/Photo Database"
        assert set(paths[:-1]) == {
            file.dependency.relative_path for file in asset.files
        }
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        replacement = prepare_sync_photo(
            _image(),
            photo_id=101,
            original_relative_path="Photos/Full Resolution/iOpenPod/second.png",
            thumbnail_shard=2,
            formats=formats,
            original=asset.photo,
        )
        desired = photo_library_with_asset(photos, replacement)
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                replace(device.active.library, photos=desired),
                device.active,
                1,
                2,
                photos=(replacement,),
                replace_photos=(101,),
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        removals = {
            change.path for change in review.file_changes if change.action == "remove"
        }
        assert removals == {file.dependency.relative_path for file in asset.files}
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        for representation in asset.photo.representations:
            assert not (device.root / representation.relative_path).exists()
        assert all(
            (device.root / file.dependency.relative_path).read_bytes() == file.data
            for file in replacement.files
        )
        assert saved.active.library.photos is not None
        assert len(saved.active.library.photos.photos) == 1
        assert next(
            rep
            for rep in saved.active.library.photos.photos[0].representations
            if rep.kind is PhotoRepresentationKind.FULL_RESOLUTION
        ).relative_path.endswith("second.png")
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "corruption", ["dimensions", "offset", "missing-thumbnail", "master-membership"]
)
def test_photo_source_dimensions_ranges_and_master_membership_are_verified(
    corruption: str,
) -> None:
    source = library()
    asset = _asset()
    representations = asset.photo.representations
    if corruption == "dimensions":
        asset = replace(
            asset,
            photo=replace(
                asset.photo,
                representations=(
                    replace(representations[0], width=1),
                    *representations[1:],
                ),
            ),
        )
    elif corruption == "offset":
        asset = replace(
            asset,
            photo=replace(
                asset.photo,
                representations=(
                    representations[0],
                    replace(representations[1], offset=1),
                ),
            ),
        )
    elif corruption == "missing-thumbnail":
        asset = replace(asset, files=asset.files[:1])
    desired_photos = photo_library_with_asset(None, asset)
    if corruption == "master-membership":
        desired_photos = replace(
            desired_photos, albums=(replace(desired_photos.albums[0], photo_ids=()),)
        )
    plan = source.analyze(
        source.begin_draft(replace(source.snapshot, photos=desired_photos)),
        WriteTarget(photo_formats=FORMATS, photos_root_value=6),
    )
    result = source.prepare(plan, WriteResources(photos=(asset,)))
    assert result.prepared is None
    assert result.issues


def test_photo_removal_preserves_files_shared_with_retained_photo(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path, photos=True)
    device.coordinator.close()
    photo_path = device.root / "Photos/Photo Database"
    document = parse_PhotosDB(photo_path.read_bytes())
    image_dataset = next(
        item.chunk
        for item in document.find_chunks(MhsdHeader)
        if item.chunk.header.dataset_type == 1
    )
    first = document.find_chunks(MhiiHeader)[0].chunk
    second = replace(first, header=replace(first.header, image_id=999))
    edits: dict[int, ParsedChunk[ChunkHeader] | None] = {
        id(image_dataset): replace(
            image_dataset, children=(image_dataset.children[0].append_child(second),)
        )
    }
    for album in document.find_chunks(MhbaHeader):
        edits[id(album.chunk)] = album.chunk.append_child(
            new_photos_chunk(MHIA_DEFINITION, MhiaHeader(image_id=999))
        )
    photo_path.write_bytes(write_PhotosDB(rebuild(document, edits)))
    thumbnails = device.root / "Photos/Thumbs"
    thumbnails.mkdir()
    (thumbnails / "F1017_1.ithmb").write_bytes(b"shared packed image bytes")
    (thumbnails / "F1023_1.ithmb").write_bytes(b"other shared packed image bytes")
    coordinator = DeviceCoordinator(device.storage)
    coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    device = replace(device, coordinator=coordinator)
    try:
        photos = device.active.library.photos
        assert photos is not None
        desired = replace(
            photos,
            photos=(photos.photos[1],),
            albums=tuple(replace(album, photo_ids=(999,)) for album in photos.albums),
        )
        review = device.prepare(
            replace(device.active.library, photos=desired), delete=True
        )
        assert review.result.prepared is not None, review.result.issues
        assert not any(change.action == "remove" for change in review.file_changes)
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert (
            thumbnails / "F1017_1.ithmb"
        ).read_bytes() == b"shared packed image bytes"
        assert (device.root / "Photos/Full Resolution/iOpenPod/Sunrise.jpg").exists()
    finally:
        coordinator.close()
