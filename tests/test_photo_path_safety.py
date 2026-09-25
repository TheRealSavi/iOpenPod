from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from PIL.Image import Image

from iopenpod.device.artwork_presets import ArtworkFormat
from iopenpod.device.filesystem_profile import FilesystemProfile
from iopenpod.device.path_safety import UnsafeDevicePathError
from iopenpod.device.storage_safety import FileSizeLimitError
from iopenpod.sync import photos as photos_module
from iopenpod.sync.photos import (
    PhotoDB,
    PhotoEntry,
    PhotoMetadataSafetyError,
    PhotoSyncItem,
    PhotoSyncPlan,
    PhotoThumbRef,
    _full_res_rel_path_for_entry,
    apply_photo_sync_plan,
    load_photo_preview,
    read_photo_db,
    write_photo_db_metadata_only,
)


def test_generated_full_resolution_filename_is_bounded_for_ipod_filesystems() -> None:
    entry = PhotoEntry(
        image_id=12345,
        display_name=f"{'very-long-photo-name-' * 30}.jpeg",
    )

    filename = Path(_full_res_rel_path_for_entry(entry)).name

    assert len(filename.encode("ascii")) <= 255
    assert filename.endswith("_12345.jpg")


def _removal_plan(entry: PhotoEntry) -> PhotoSyncPlan:
    database = PhotoDB(photos={entry.image_id: entry})
    return PhotoSyncPlan(
        current_db=database,
        photos_to_remove=[
            PhotoSyncItem(
                visual_hash=entry.visual_hash,
                display_name=entry.display_name,
                image_id=entry.image_id,
            ),
        ],
    )


def test_photo_preview_rejects_full_resolution_parent_traversal(tmp_path: Path) -> None:
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"not an image")
    entry = PhotoEntry(
        image_id=100,
        full_res_path="../../../outside.jpg",
    )

    with pytest.raises(UnsafeDevicePathError):
        load_photo_preview(entry, tmp_path / "ipod")


def test_photo_preview_rejects_thumbnail_parent_traversal(tmp_path: Path) -> None:
    outside = tmp_path / "outside.ithmb"
    outside.write_bytes(b"outside payload")
    entry = PhotoEntry(image_id=100)
    entry.thumbs[1017] = PhotoThumbRef(
        format_id=1017,
        offset=0,
        size=len(b"outside payload"),
        width=1,
        height=1,
        filename="../../../outside.ithmb",
    )

    with pytest.raises(UnsafeDevicePathError):
        load_photo_preview(entry, tmp_path / "ipod")


def test_photo_removal_rejects_full_resolution_parent_traversal(tmp_path: Path) -> None:
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"keep")
    entry = PhotoEntry(
        image_id=100,
        visual_hash="photo-hash",
        full_res_path="../../../outside.jpg",
    )

    with pytest.raises(UnsafeDevicePathError):
        apply_photo_sync_plan(tmp_path / "ipod", _removal_plan(entry))

    assert outside.read_bytes() == b"keep"


def test_photo_removal_rejects_symlink_escape(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    managed_root = ipod_root / "Photos" / "Full Resolution"
    outside = tmp_path / "outside"
    managed_root.mkdir(parents=True)
    outside.mkdir()
    victim = outside / "victim.jpg"
    victim.write_bytes(b"keep")
    try:
        (managed_root / "iOpenPod").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    entry = PhotoEntry(
        image_id=100,
        visual_hash="photo-hash",
        full_res_path="Full Resolution/iOpenPod/victim.jpg",
    )

    with pytest.raises(UnsafeDevicePathError):
        apply_photo_sync_plan(ipod_root, _removal_plan(entry))

    assert victim.read_bytes() == b"keep"


def test_photo_metadata_write_does_not_truncate_predictable_temps(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    photo_dir = ipod_root / "Photos"
    mapping_dir = ipod_root / "iPod_Control" / "iOpenPod"
    photo_dir.mkdir(parents=True)
    mapping_dir.mkdir(parents=True)
    predictable_temps = [
        photo_dir / "Photo Database.tmp",
        mapping_dir / "photo_sync.json.tmp",
    ]
    for predictable in predictable_temps:
        predictable.write_bytes(b"do-not-truncate")

    write_photo_db_metadata_only(ipod_root, PhotoDB())

    assert all(path.read_bytes() == b"do-not-truncate" for path in predictable_temps)
    assert isinstance(read_photo_db(ipod_root), PhotoDB)


def test_incremental_thumb_append_rejects_symlink_leaf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    thumbs_dir = ipod_root / "Photos" / "Thumbs"
    thumbs_dir.mkdir(parents=True)
    outside = tmp_path / "outside.ithmb"
    outside.write_bytes(b"outside-safe")
    thumb_link = thumbs_dir / "F1017_1.ithmb"
    try:
        thumb_link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    monkeypatch.setattr(
        photos_module,
        "_encode_photo_for_formats",
        lambda *_args, **_kwargs: {
            1017: {
                "data": b"new-thumb",
                "size": len(b"new-thumb"),
                "width": 1,
                "height": 1,
                "hpad": 0,
                "vpad": 0,
                "filename": "F1017_1.ithmb",
            }
        },
    )

    with pytest.raises(UnsafeDevicePathError, match="symbolic link|reparse point"):
        photos_module._append_touched_photo_thumbs(
            ipod_root,
            PhotoEntry(image_id=101),
            cast(Image, object()),
            {},
            {1017: 0},
            rotate_tall_photos=False,
            fit_thumbnails=False,
        )

    assert outside.read_bytes() == b"outside-safe"


@pytest.mark.parametrize("payload", [b"mhfd", b"not-a-photo-database"])
def test_existing_malformed_photo_database_fails_closed(
    tmp_path: Path,
    payload: bytes,
) -> None:
    db_path = tmp_path / "ipod" / "Photos" / "Photo Database"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(payload)

    with pytest.raises(PhotoMetadataSafetyError, match="malformed or incomplete"):
        read_photo_db(tmp_path / "ipod")

    assert db_path.read_bytes() == payload


def test_existing_unreadable_photo_database_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ipod" / "Photos" / "Photo Database"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"mhfd" + b"\x00" * 128)
    original_read_bytes = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path == db_path:
            raise PermissionError("device read denied")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    with pytest.raises(PhotoMetadataSafetyError, match="could not be read safely"):
        read_photo_db(tmp_path / "ipod")


def test_existing_malformed_photo_mapping_blocks_metadata_write(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    mapping_path = ipod_root / "iPod_Control" / "iOpenPod" / "photo_sync.json"
    mapping_path.parent.mkdir(parents=True)
    mapping_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(PhotoMetadataSafetyError, match="photo mapping"):
        write_photo_db_metadata_only(ipod_root, PhotoDB())

    assert mapping_path.read_text(encoding="utf-8") == "{not-json"
    assert not (ipod_root / "Photos" / "Photo Database").exists()


def test_photo_ithmb_append_size_is_checked_before_mutation(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    thumb_path = ipod_root / "Photos" / "Thumbs" / "F1017_1.ithmb"
    thumb_path.parent.mkdir(parents=True)
    original = b"existing"
    thumb_path.write_bytes(original)
    fmt = ArtworkFormat(
        1017,
        1,
        1,
        2,
        "RGB565_LE",
        "photo_thumb",
        "test thumbnail",
    )
    payload_size = photos_module._photo_format_payload_size(1017, fmt)
    change_set = photos_module._PhotoSyncChangeSet(
        removed_ids=set(),
        updated_ids=set(),
        new_ids={101},
        touch_ids=[101],
    )
    database = PhotoDB(file_sizes={1017: len(original)})

    with pytest.raises(FileSizeLimitError, match="F1017_1.ithmb"):
        photos_module._preflight_photo_ithmb_sizes(
            ipod_root,
            database,
            change_set,
            {1017: fmt},
            cast(
                FilesystemProfile,
                SimpleNamespace(
                    max_file_size_bytes=len(original) + payload_size - 1,
                ),
            ),
        )

    assert thumb_path.read_bytes() == original
    photos_module._preflight_photo_ithmb_sizes(
        ipod_root,
        database,
        change_set,
        {1017: fmt},
        cast(
            FilesystemProfile,
            SimpleNamespace(max_file_size_bytes=len(original) + payload_size),
        ),
    )
