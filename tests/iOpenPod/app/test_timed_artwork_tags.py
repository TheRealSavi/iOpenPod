"""Timed display edits distinguish the embedded cover from later images."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device

from iOpenPod.app.library_tag_updates import with_rockbox_edits
from iOpenPod.app.library_write import LibraryPreparationRequest
from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.container_mhod import (
    MhodContainerPayload,
)
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB
from iPodDB.library import (
    ArtworkGroupReference,
    ArtworkPixels,
    IPodLibrary,
    TimedArtworkAsset,
    TimedArtworkFrame,
)

BLUE = ArtworkPixels(1, 1, b"\0\0\xff")


@pytest.mark.parametrize("metadata_changed", [False, True])
def test_retained_zero_cover_does_not_rewrite_embedded_artwork(
    tmp_path: Path,
    metadata_changed: bool,
) -> None:
    device = build_device(tmp_path)
    try:
        first, second = device.active.library.tracks
        source = IPodLibrary(
            device.original["iPod_Control/iTunes/iTunesDB"]
        ).with_artwork(device.original["iPod_Control/Artwork/ArtworkDB"])
        asset = TimedArtworkAsset(
            -1,
            (
                TimedArtworkFrame(0, ArtworkGroupReference(first.artwork_id, 0)),
                TimedArtworkFrame(10_000, BLUE),
            ),
        )
        desired = replace(
            device.active.library,
            tracks=(
                replace(
                    first,
                    artwork_id=-1,
                    title="Edited" if metadata_changed else first.title,
                ),
                second,
            ),
        )
        request = LibraryPreparationRequest(
            desired, device.active, 1, 1, artwork=(asset,), rockbox_metadata=True
        )

        result = with_rockbox_edits(request, source)

        if metadata_changed:
            assert len(result.rockbox_media) == 1
            update = result.rockbox_media[0]
            assert update.track_id == first.track_id
            assert update.preserve_artwork
            assert update.artwork is None and update.artwork_read is None
        else:
            assert not result.rockbox_media
    finally:
        device.coordinator.close()


def test_new_zero_pixels_are_embedded_instead_of_a_later_frame(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        first, second = device.active.library.tracks
        source = IPodLibrary(
            device.original["iPod_Control/iTunes/iTunesDB"]
        ).with_artwork(device.original["iPod_Control/Artwork/ArtworkDB"])
        asset = TimedArtworkAsset(
            -1,
            (
                TimedArtworkFrame(10_000, ArtworkPixels(1, 1, b"\xff\0\0")),
                TimedArtworkFrame(0, BLUE),
            ),
        )
        request = LibraryPreparationRequest(
            replace(
                device.active.library, tracks=(replace(first, artwork_id=-1), second)
            ),
            device.active,
            1,
            1,
            artwork=(asset,),
            rockbox_metadata=True,
        )

        result = with_rockbox_edits(request, source)

        assert len(result.rockbox_media) == 1
        update = result.rockbox_media[0]
        assert update.artwork == BLUE
        assert update.artwork_read is None and not update.preserve_artwork
    finally:
        device.coordinator.close()


def test_moving_a_retained_frame_to_zero_embeds_its_exact_source_group(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    try:
        first, second = device.active.library.tracks
        document = parse_ArtworkDB(device.original["iPod_Control/Artwork/ArtworkDB"])
        selected = document.find_chunks(MhiiHeader)[0]
        wrapper = selected.chunk.children[0]
        assert isinstance(wrapper.payload, MhodContainerPayload)
        location = wrapper.payload.child
        offset = location.header.ithmb_offset + location.header.image_size
        later = replace(
            wrapper,
            payload=replace(
                wrapper.payload,
                child=replace(
                    location,
                    header=replace(
                        location.header, image_time_key=10_000, ithmb_offset=offset
                    ),
                ),
            ),
        )
        document = document.replace_chunk(
            selected,
            replace(selected.chunk, children=(*selected.chunk.children, later)),
        )
        source = IPodLibrary(
            device.original["iPod_Control/iTunes/iTunesDB"]
        ).with_artwork(write_ArtworkDB(document))
        asset = TimedArtworkAsset(
            -1, (TimedArtworkFrame(0, ArtworkGroupReference(first.artwork_id, 10_000)),)
        )
        request = LibraryPreparationRequest(
            replace(
                device.active.library, tracks=(replace(first, artwork_id=-1), second)
            ),
            device.active,
            1,
            1,
            artwork=(asset,),
            rockbox_metadata=True,
        )

        result = with_rockbox_edits(request, source)

        update = result.rockbox_media[0]
        assert update.artwork is None and not update.preserve_artwork
        assert update.artwork_read is not None
        assert update.artwork_read.offset == offset
        assert update.artwork_read.length == location.header.image_size
    finally:
        device.coordinator.close()
