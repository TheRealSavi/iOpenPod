"""Binary Alarm browser vectors from the native imported-array investigation."""

import pytest
from tests.iPodDB.alarm_fixtures import (
    named_playlist_chunk,
    playlist_chunk,
    playlist_dataset,
    playlist_library,
    track_dataset,
)

from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library import AlarmPlaylistLayout

LAYOUTS = (
    AlarmPlaylistLayout.CLASSIC,
    AlarmPlaylistLayout.CLASSIC_LATE,
    AlarmPlaylistLayout.NANO_4,
)


@pytest.mark.parametrize("layout", LAYOUTS)
def test_native_name_order_and_import_order_ties(layout: AlarmPlaylistLayout) -> None:
    library = playlist_library(
        track_dataset(),
        playlist_dataset(
            3,
            (
                named_playlist_chunk(100, "Library", master=True),
                named_playlist_chunk(900, "zebra"),
                named_playlist_chunk(400, "  Alpha"),
                named_playlist_chunk(300, "Alpha"),
                named_playlist_chunk(200, "alpha"),
            ),
        ),
    )
    result = library.alarm_playlists(layout)
    assert result.complete, result.issues
    assert [row.playlist_id for row in result.playlists] == [100, 400, 300, 200, 900]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_smart_parent_child_links_are_import_ordered(
    layout: AlarmPlaylistLayout,
) -> None:
    library = playlist_library(
        track_dataset(),
        playlist_dataset(
            2,
            (
                named_playlist_chunk(100, "Library", master=True),
                named_playlist_chunk(200, "Earlier parent"),
                named_playlist_chunk(201, "Child", smart=False, parent=200),
                named_playlist_chunk(301, "Later child", smart=False, parent=300),
                named_playlist_chunk(300, "Later parent"),
            ),
        ),
    )
    result = library.alarm_playlists(layout)
    assert result.complete, result.issues
    assert [row.playlist_id for row in result.playlists] == [100, 300]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_late_classic_media_width_and_distinguished_exclusions(
    layout: AlarmPlaylistLayout,
) -> None:
    library = playlist_library(
        track_dataset(MhitHeader(track_id=1, media_type=0x200000)),
        playlist_dataset(
            2,
            (
                named_playlist_chunk(100, "Library", master=True),
                playlist_chunk(200, items=(MhipHeader(track_id=1),)),
                named_playlist_chunk(300, "Internal 32", kind=32),
                named_playlist_chunk(400, "Internal 34", kind=34),
                named_playlist_chunk(500, "Ordinary"),
            ),
        ),
    )
    result = library.alarm_playlists(layout)
    assert result.complete, result.issues
    assert [row.playlist_id for row in result.playlists] == (
        [100, 200, 500]
        if layout is AlarmPlaylistLayout.CLASSIC_LATE
        else [100, 300, 400, 500]
    )
