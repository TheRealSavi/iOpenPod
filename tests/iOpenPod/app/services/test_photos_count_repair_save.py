"""Photo count repair uses ordinary recoverable Storage publication."""

from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device

from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhsd import MhsdHeader


@pytest.mark.parametrize("concurrent_change", [False, True])
def test_photo_count_repair_save_and_restore(
    tmp_path: Path, concurrent_change: bool
) -> None:
    device = build_device(tmp_path, photos=True)
    try:
        relative = "Photos/Photo Database"
        path = device.root / relative
        valid = path.read_bytes()
        expected_photos = device.active.library.photos
        image_list = parse_PhotosDB(valid).find_chunks(MhsdHeader)[0].chunk.children[0]
        offset = image_list.offset + 8
        damaged = valid[:offset] + bytes(4) + valid[offset + 4 :]
        device.coordinator.close()
        path.write_bytes(damaged)
        device.original[relative] = damaged
        device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        assert device.active.library.photos == expected_photos
        assert device.active.photos_repairs_pending
        review = device.prepare(device.active.library)
        assert review.result.prepared is not None, review.result.issues
        assert review.result.prepared.photos == valid
        device.assert_original()
        if concurrent_change:
            path.write_bytes(damaged + b"concurrent change")
        result = device.save(review)
        if concurrent_change:
            assert result.active is None
            assert path.read_bytes() == damaged + b"concurrent change"
        else:
            assert result.active is not None, result.issues
            assert not result.active.photos_repairs_pending
            assert path.read_bytes() == valid
            device.restore(result.recovery_path)
    finally:
        device.coordinator.close()
