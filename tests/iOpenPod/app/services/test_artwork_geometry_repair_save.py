"""Automatic native-raster repair is published only by a verified transaction."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.artwork_index import thumbnail_payload
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import MhifHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB


def install_legacy_geometry(device: Device) -> None:
    """Install a synthetic legacy raster while no device session is open."""
    device.coordinator.close()
    path = "iPod_Control/Artwork/ArtworkDB"
    document = parse_ArtworkDB((device.root / path).read_bytes())
    for selection in document.find_chunks(MhiiHeader):
        row = selection.chunk
        children = []
        for child in row.children:
            payload = thumbnail_payload(child)
            if payload is not None:
                location = payload.child
                child = replace(
                    child,
                    payload=replace(
                        payload,
                        child=replace(
                            location,
                            header=replace(
                                location.header,
                                format_id=1061,
                                image_width=56,
                                image_height=56,
                                image_size=6272,
                                image_size_2=6272,
                                ithmb_offset=0,
                            ),
                        ),
                    ),
                )
            children.append(child)
        document = document.replace_chunk(
            selection, replace(row, children=tuple(children))
        )
    for format_selection in document.find_chunks(MhifHeader):
        document = document.replace_chunk(
            format_selection,
            replace(
                format_selection.chunk,
                header=replace(
                    format_selection.chunk.header,
                    format_id=1061,
                    image_size=6272,
                ),
            ),
        )
    changed = {
        path: write_ArtworkDB(document),
        "iPod_Control/Artwork/F1055_1.ithmb": b"\x00\xf8" * (56 * 56),
    }
    for relative, data in changed.items():
        (device.root / relative).write_bytes(data)
        device.original[relative] = data
    device.coordinator.select_device(
        device.coordinator.discover_devices().candidates[0].id
    )


@pytest.mark.parametrize("concurrent_change", [False, True])
def test_automatic_geometry_save_preserves_files_and_supports_rollback(
    tmp_path: Path,
    concurrent_change: bool,
) -> None:
    device = build_device(tmp_path)
    try:
        install_legacy_geometry(device)
        assert device.active.artwork_repairs_pending
        device.assert_original()
        review = device.prepare(device.active.library)
        assert review.result.prepared is not None, review.result.issues
        created = review.result.prepared.artwork_files
        assert created
        device.assert_original()
        thumbnail = device.root / "iPod_Control/Artwork/F1055_1.ithmb"
        if concurrent_change:
            thumbnail.write_bytes(b"\xff" + thumbnail.read_bytes()[1:])
        result = device.save(review)
        if concurrent_change:
            assert result.active is None
            assert (
                device.root / "iPod_Control/Artwork/ArtworkDB"
            ).read_bytes() == device.original["iPod_Control/Artwork/ArtworkDB"]
            assert all(not (device.root / f.relative_path).exists() for f in created)
        else:
            assert result.active is not None, result.issues
            assert not result.active.artwork_repairs_pending
            assert (
                thumbnail.read_bytes()
                == device.original["iPod_Control/Artwork/F1055_1.ithmb"]
            )
            device.restore(result.recovery_path)
            assert all(not (device.root / f.relative_path).exists() for f in created)
    finally:
        device.coordinator.close()
