"""Obsolete shared Photo files are handled independently of owner iteration order."""

from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_sync_execution import (
    _AvailableTools,  # pyright: ignore[reportPrivateUsage]
    _Executor,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_photo_sharding import photo_host

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.media.photo_sync import photo_library_with_asset, prepare_sync_photo
from iOpenPod.app.sync_execution import SyncExecutionStatus
from iPodDB.library import PhotoPixelFormat, PhotoThumbnailFormat
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB
from storage import (
    DevicePath,
    FileFingerprint,
    FilesystemSession,
    StorageOperationError,
)

if TYPE_CHECKING:
    from iPodDB.shared.chunk import ChunkHeader, ParsedChunk


@pytest.mark.parametrize("replacement_index", [0, 1])
@pytest.mark.parametrize("damage", ["unreadable", "malformed"])
def test_shared_obsolete_photo_file_is_preserved_when_any_owner_is_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_index: int,
    damage: str,
) -> None:
    device = build_device(tmp_path)
    try:
        first = _Executor(device.coordinator, transcoder=_AvailableTools()).execute(
            _request(device, photo_host(tmp_path / "host", ("red", "blue"))),
            lambda _: None,
            Event(),
        )
        assert first.status is SyncExecutionStatus.SUCCESS, first.issues
        assert first.active is not None and first.active.library.photos is not None
        library = first.active.library.photos
        shared = library.photos[0].representations[1].relative_path
        original_bytes = (device.root / shared).read_bytes()
        assert library.photos[1].representations[1].relative_path == shared

        if damage == "malformed":
            database_path = device.root / "Photos/Photo Database"
            document = parse_PhotosDB(database_path.read_bytes())
            stored_path = ":" + shared.removeprefix("Photos/").replace("/", ":")
            malformed = "Photos/Thumbs/unrecognized-photo-file.bin"
            changed = 0
            for selection in document.find_chunks(MhodHeader):
                payload = selection.chunk.payload
                if not isinstance(payload, MhodContainerPayload):
                    continue
                names: list[ParsedChunk[ChunkHeader]] = []
                matched = False
                for child in payload.child.children:
                    if (
                        isinstance(child.payload, MhodStringPayload)
                        and child.payload.value == stored_path
                    ):
                        child = replace(
                            child,
                            payload=replace(
                                child.payload,
                                value=":Thumbs:unrecognized-photo-file.bin",
                            ),
                        )
                        changed += 1
                        matched = True
                    names.append(child)
                if matched:
                    document = document.replace_chunk(
                        selection,
                        replace(
                            selection.chunk,
                            payload=replace(
                                payload,
                                child=replace(payload.child, children=tuple(names)),
                            ),
                        ),
                    )
            assert changed == 2
            device.coordinator.close()
            database_path.write_bytes(write_PhotosDB(document))
            (device.root / malformed).write_bytes(original_bytes)
            device.coordinator.select_device(
                device.coordinator.discover_devices().candidates[0].id
            )
            assert device.active.library.photos is not None
            library = device.active.library.photos
            shared = malformed
        else:
            fingerprint = FilesystemSession.fingerprint

            def unreadable(
                session: FilesystemSession, path: DevicePath
            ) -> FileFingerprint:
                if str(path) == shared:
                    raise StorageOperationError("Unreadable shared old Photo shard")
                return fingerprint(session, path)

            monkeypatch.setattr(FilesystemSession, "fingerprint", unreadable)

        updated = library.photos[replacement_index]
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
        asset = prepare_sync_photo(
            (tmp_path / "host/blue.png").read_bytes(),
            photo_id=updated.photo_id,
            original_relative_path="Photos/Full Resolution/replacement.png",
            thumbnail_shard=99,
            formats=formats,
            original=updated,
        )
        retained = replace(
            library,
            photos=(updated,),
            albums=tuple(
                replace(album, photo_ids=(updated.photo_id,))
                for album in library.albums
            ),
        )
        desired = photo_library_with_asset(retained, asset)
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                replace(device.active.library, photos=desired),
                device.active,
                1,
                2,
                photos=(asset,),
                replace_photos=(updated.photo_id,),
                delete_omissions=True,
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        assert any(
            issue.code
            == (
                "photos.unreadable_source_regeneration"
                if damage == "unreadable"
                else "photos.unrecognized_source_regeneration"
            )
            for issue in review.result.issues
        )
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        saved_photos = saved.active.library.photos
        assert saved_photos is not None
        assert saved_photos == desired
        assert (device.root / shared).read_bytes() == original_bytes
        assert all(
            representation.relative_path != shared
            for photo in saved_photos.photos
            for representation in photo.representations
        )
    finally:
        device.coordinator.close()
