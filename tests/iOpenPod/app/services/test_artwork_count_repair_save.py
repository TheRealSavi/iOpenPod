"""Count recovery is read-only until a verified, recoverable Storage publication."""

from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import MhsdHeader


@pytest.mark.parametrize("recorded_count", [0, 2])
@pytest.mark.parametrize("concurrent_change", [False, True])
def test_count_repair_save_checks_source_and_can_restore_original(
    tmp_path: Path, recorded_count: int, concurrent_change: bool
) -> None:
    device = build_device(tmp_path)
    try:
        expected_tracks = device.active.library.tracks
        relative = "iPod_Control/Artwork/ArtworkDB"
        path = device.root / relative
        valid = path.read_bytes()
        image_list = parse_ArtworkDB(valid).find_chunks(MhsdHeader)[0].chunk.children[0]
        offset = image_list.offset + 8
        damaged = (
            valid[:offset] + recorded_count.to_bytes(4, "little") + valid[offset + 4 :]
        )
        device.coordinator.close()
        path.write_bytes(damaged)
        device.original[relative] = damaged
        device.coordinator.select_device(
            device.coordinator.discover_devices().candidates[0].id
        )
        assert device.active.library.tracks == expected_tracks
        device.assert_original()
        review = device.prepare(device.active.library)
        assert review.result.prepared is not None, review.result.issues
        assert review.result.prepared.artwork == valid
        assert not review.result.prepared.artwork_files
        device.assert_original()
        if concurrent_change:
            path.write_bytes(damaged + b"concurrent edit")

        result = device.save(review)

        if concurrent_change:
            assert result.active is None
            assert path.read_bytes() == damaged + b"concurrent edit"
        else:
            assert result.active is not None, result.issues
            assert path.read_bytes() == valid
            for retained in (
                "iPod_Control/iTunes/iTunesDB",
                "iPod_Control/Artwork/F1055_1.ithmb",
            ):
                assert (device.root / retained).read_bytes() == device.original[
                    retained
                ]
            device.restore(result.recovery_path)
    finally:
        device.coordinator.close()
