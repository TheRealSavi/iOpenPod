"""Track EQ belongs to Library edits, not Host metadata replacement."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device

from iOpenPod.app.library_tag_updates import with_rockbox_edits
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.sync_track_details import (
    apply_track_tags,
    track_tag_sha256,
    track_tag_values,
)
from iPodDB.library import IPodLibrary, Track, TrackMetadata


@pytest.mark.parametrize("raw", ["", "#!#116#!#", "Unknown\u00e9 curve"])
@pytest.mark.parametrize("host_raw", ["", "#!#100#!#"])
def test_host_metadata_cannot_replace_an_ipod_eq_assignment(
    raw: str, host_raw: str
) -> None:
    retained = Track(
        1, "Before", "Artist", "Album", 1000, metadata=TrackMetadata(equalizer=raw)
    )
    host = replace(retained, title="After", metadata=TrackMetadata(equalizer=host_raw))
    merged = apply_track_tags(retained, host)
    assert merged.title == "After"
    assert merged.metadata.equalizer == raw
    assert track_tag_values(merged) == track_tag_values(host)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", "d81289dd66c3544507ec13c4726aa81bc7581e8e0dda93774af7a7b490a118f1"),
        (
            "#!#116#!#",
            "a08005c6ba0a7b3dafdd442540d503d50ff4fd10662a9b621a619ea95eb94693",
        ),
        ("Custom", "99cb020d8f7b3bec4e8cf67ec98bcd64601279110876b3c5f428b86e2e2b28d2"),
    ],
)
def test_existing_v1_sync_digests_keep_their_original_meaning(
    raw: str, expected: str
) -> None:
    # Golden values captured from the pre-EQ implementation, including its slot
    # for the retained EQ text. Comparison/merge ownership changes, not storage.
    track = Track(
        1, "Song", "Artist", "Album", 1000, metadata=TrackMetadata(equalizer=raw)
    )
    assert track_tag_sha256(track) == expected


@pytest.mark.parametrize("title_changed", [False, True])
def test_eq_only_edit_does_not_schedule_embedded_media_tag_work(
    tmp_path: Path, title_changed: bool
) -> None:
    device = build_device(tmp_path)
    try:
        original = device.active.library
        track = original.tracks[0]
        changed = replace(
            track,
            title="Updated" if title_changed else track.title,
            metadata=replace(track.metadata, equalizer="#!#116#!#"),
        )
        request = LibraryPreparationRequest(
            replace(original, tracks=(changed, *original.tracks[1:])),
            device.active,
            1,
            1,
            rockbox_metadata=True,
        )
        source = IPodLibrary(
            (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
        )
        updated = with_rockbox_edits(request, source)
        assert tuple(item.track_id for item in updated.rockbox_media) == (
            (track.track_id,) if title_changed else ()
        )
    finally:
        device.coordinator.close()
