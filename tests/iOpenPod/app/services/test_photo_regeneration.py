"""Fresh Photo replacement preserves obsolete files that cannot be reclaimed."""

from dataclasses import replace
from io import BytesIO
from pathlib import Path
from threading import Event

import pytest
from PIL import Image
from tests.iOpenPod.app.services.test_library_resources import build_device

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.media.photo_sync import photo_library_with_asset, prepare_sync_photo
from iPodDB.library import PhotoPixelFormat, PhotoThumbnailFormat
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.PhotosDB.shared.constants import PhotosMhodType
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB
from storage import (
    DevicePath,
    FileFingerprint,
    FilesystemSession,
    StorageOperationError,
)


@pytest.mark.parametrize(
    "damage,stored_name,old_path,warning",
    (
        (
            "invalid_namespace",
            ":Other:F1017_1.ithmb",
            "Photos/Other/F1017_1.ithmb",
            "photos.unrecognized_source_regeneration",
        ),
        (
            "noncanonical_name",
            ":Thumbs:legacy-thumbnail.bin",
            "Photos/Thumbs/legacy-thumbnail.bin",
            "photos.unrecognized_source_regeneration",
        ),
        (
            "unreadable",
            ":Thumbs:F1017_1.ithmb",
            "Photos/Thumbs/F1017_1.ithmb",
            "photos.unreadable_source_regeneration",
        ),
    ),
)
def test_complete_photo_replacement_preserves_unreclaimable_old_thumbnail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
    stored_name: str,
    old_path: str,
    warning: str,
) -> None:
    device = build_device(tmp_path, photos=True)
    try:
        device.coordinator.close()
        database_path = device.root / "Photos/Photo Database"
        document = parse_PhotosDB(database_path.read_bytes())
        selection = document.find_chunks(MhiiHeader)[0]
        row = selection.chunk
        thumbnail = next(
            child
            for child in row.children
            if isinstance(child.header, MhodHeader)
            and child.header.mhod_type == PhotosMhodType.THUMBNAIL_IMAGE
        )
        assert isinstance(thumbnail.payload, MhodContainerPayload)
        location = thumbnail.payload.child
        filename = location.children[0]
        assert isinstance(filename.payload, MhodStringPayload)
        changed_location = replace(
            location,
            children=(
                replace(filename, payload=replace(filename.payload, value=stored_name)),
                *location.children[1:],
            ),
        )
        document = document.replace_chunk(
            selection,
            replace(
                row,
                children=tuple(
                    replace(
                        child,
                        payload=replace(thumbnail.payload, child=changed_location),
                    )
                    if child is thumbnail
                    else child
                    for child in row.children
                ),
            ),
        )
        damaged_database = write_PhotosDB(document)
        database_path.write_bytes(damaged_database)
        retained = b"old thumbnail must remain byte exact"
        old_file = device.root / old_path
        old_file.parent.mkdir(parents=True, exist_ok=True)
        old_file.write_bytes(retained)
        device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        photos = device.active.library.photos
        assert photos is not None
        original = photos.photos[0]
        formats = tuple(
            PhotoThumbnailFormat(
                item.format_id,
                item.width,
                item.height,
                item.row_bytes,
                PhotoPixelFormat(item.pixel_format.value),
            )
            for item in device.active.profile.capabilities.artwork.photo_formats
        )
        source = BytesIO()
        with Image.new("RGB", (32, 24), "green") as image:
            image.save(source, format="PNG")
        asset = prepare_sync_photo(
            source.getvalue(),
            photo_id=original.photo_id,
            original_relative_path="Photos/Full Resolution/iOpenPod/replacement.png",
            thumbnail_shard=2,
            formats=formats,
            original=original,
        )
        captured = 0
        native_fingerprint = FilesystemSession.fingerprint

        def fingerprint(self: FilesystemSession, path: DevicePath) -> FileFingerprint:
            nonlocal captured
            if damage == "unreadable" and str(path) == old_path:
                captured += 1
                raise StorageOperationError("old thumbnail read failed")
            return native_fingerprint(self, path)

        monkeypatch.setattr(FilesystemSession, "fingerprint", fingerprint)
        desired_photos = photo_library_with_asset(photos, asset)
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                replace(device.active.library, photos=desired_photos),
                device.active,
                1,
                1,
                photos=(asset,),
                replace_photos=(original.photo_id,),
            ),
            lambda _: None,
            Event(),
        )

        assert review.result.prepared is not None, review.result.issues
        assert any(issue.code == warning for issue in review.result.issues)
        assert not any(change.path == old_path for change in review.file_changes)
        assert old_file.read_bytes() == retained
        assert database_path.read_bytes() == damaged_database
        if damage == "unreadable":
            assert captured > 0

        saved = device.save(review)

        assert saved.active is not None, saved.issues
        assert saved.active.library.photos == desired_photos
        assert old_file.read_bytes() == retained
        assert database_path.read_bytes() == review.result.prepared.photos
        assert all(
            (device.root / file.dependency.relative_path).read_bytes() == file.data
            for file in asset.files
        )
        for unchanged in (
            "iPod_Control/iTunes/iTunesDB",
            "iPod_Control/Artwork/ArtworkDB",
        ):
            assert (device.root / unchanged).read_bytes() == device.original[unchanged]
    finally:
        device.coordinator.close()
