"""Automatic MHIF corrections use the existing publication and recovery path."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.library.test_write_artwork import BLUE

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader


@pytest.mark.parametrize("changed_thumbnail", [False, True])
def test_automatic_repair_is_transactional_and_checks_retained_files(
    tmp_path: Path, changed_thumbnail: bool
) -> None:
    device = build_device(tmp_path, artwork_size_multiplier=760)
    try:
        first, second = device.active.library.tracks
        review = device.prepare(
            replace(
                device.active.library,
                tracks=(replace(first, artwork_id=BLUE.artwork_id), second),
            ),
            cover=True,
        )
        assert review.result.prepared is not None, review.result.issues
        device.assert_original()
        thumbnail = device.root / "iPod_Control/Artwork/F1055_1.ithmb"
        if changed_thumbnail:
            thumbnail.write_bytes(
                bytes([thumbnail.read_bytes()[0] ^ 255]) + thumbnail.read_bytes()[1:]
            )
        saved = device.save(review)
        database_path = device.root / "iPod_Control/Artwork/ArtworkDB"
        if changed_thumbnail:
            assert saved.active is None
            assert (
                database_path.read_bytes()
                == device.original["iPod_Control/Artwork/ArtworkDB"]
            )
        else:
            assert saved.active is not None, saved.issues
            sizes = {
                s.chunk.header.format_id: s.chunk.header.image_size
                for s in parse_ArtworkDB(database_path.read_bytes()).find_chunks(
                    MhifHeader
                )
            }
            assert sizes[1055] == 128 * 128 * 2
            assert thumbnail.read_bytes().startswith(
                device.original["iPod_Control/Artwork/F1055_1.ithmb"]
            )
            device.restore(saved.recovery_path)
    finally:
        device.coordinator.close()
