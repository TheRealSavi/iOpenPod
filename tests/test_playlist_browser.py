from __future__ import annotations

from PyQt6.QtWidgets import QLabel

from iopenpod.gui.widgets.playlistBrowser import (
    PlaylistListPanel,
    _is_ipod_category_playlist,
    _is_regular_track_playlist,
    _is_user_smart_playlist,
    _podcast_grouping_summary,
)
from iopenpod.itunesdb_shared.extraction import extract_playlist_item_extras


def test_dataset5_smart_playlist_is_not_treated_as_ipod_category() -> None:
    playlist = {
        "Title": "Recently Added",
        "_source": "smart",
        "mhsd5_type": 0,
        "smart_playlist_data": {"live_update": True},
    }

    assert not _is_ipod_category_playlist(playlist)
    assert _is_user_smart_playlist(playlist)


def test_dataset5_origin_is_internal_browsing_category_even_without_marker() -> None:
    playlist = {
        "Title": "Recently Added",
        "_source": "smart",
        "_mhsd_dataset_type": 5,
        "mhsd5_type": 0,
        "smart_playlist_data": {"live_update": True},
    }

    assert _is_ipod_category_playlist(playlist)
    assert not _is_user_smart_playlist(playlist)


def test_dataset5_browsing_category_is_not_treated_as_user_smart_playlist() -> None:
    playlist = {
        "Title": "Music",
        "_source": "category",
        "mhsd5_type": 4,
        "smart_playlist_data": {"live_update": True},
    }

    assert _is_ipod_category_playlist(playlist)
    assert not _is_user_smart_playlist(playlist)


def test_string_zero_mhsd5_type_stays_a_smart_playlist() -> None:
    playlist = {
        "Title": "Smart",
        "_source": "smart",
        "mhsd5_type": "0",
        "smart_playlist_data": {"live_update": True},
    }

    assert not _is_ipod_category_playlist(playlist)
    assert _is_user_smart_playlist(playlist)


def test_regular_track_playlist_excludes_generated_playlist_types() -> None:
    assert _is_regular_track_playlist({"Title": "Manual", "_source": "regular"})
    assert _is_regular_track_playlist({"Title": "Parsed Manual"})
    assert not _is_regular_track_playlist({"Title": "Library", "master_flag": 1})
    assert not _is_regular_track_playlist({"Title": "Music", "_source": "category", "mhsd5_type": 4})
    assert not _is_regular_track_playlist({"Title": "Smart", "smart_playlist_data": {"live_update": True}})
    assert _is_regular_track_playlist({
        "Title": "Type 3 Manual",
        "_source": "regular",
        "_mhsd_dataset_type": 3,
    })
    assert not _is_regular_track_playlist({"Title": "Podcasts", "podcast_flag": 1})
    assert not _is_regular_track_playlist({"Title": "Synced", "_source": "sync_playlist_file"})


def test_category_playlist_requires_dataset5_location() -> None:
    assert _is_ipod_category_playlist({
        "Title": "Music",
        "_source": "category",
        "_mhsd_dataset_type": 5,
        "mhsd5_type": 4,
    })
    assert not _is_ipod_category_playlist({
        "Title": "Suspicious Type 2",
        "_source": "regular",
        "_mhsd_dataset_type": 2,
        "mhsd5_type": 4,
    })


def test_playlist_item_extras_preserve_dataset3_group_title() -> None:
    assert extract_playlist_item_extras(
        [{"data": {"mhod_type": 1, "string": "The Show"}}]
    ) == {"podcast_group_title": "The Show"}


def test_dataset3_podcast_grouping_summary_uses_group_headers() -> None:
    playlist = {
        "_mhsd_dataset_type": 3,
        "Title": "Podcasts",
        "podcast_flag": 1,
        "items": [
            {
                "podcast_group_flag": 256,
                "group_id": 44,
                "track_id": 0,
                "podcast_group_title": "The Show",
            },
            {"track_id": 10, "group_id_ref": 44},
            {"track_id": 11, "group_id_ref": 44},
        ],
    }

    assert _podcast_grouping_summary(
        playlist,
        {
            10: {"Title": "Episode One"},
            11: {"Title": "Episode Two"},
        },
    ) == [
        {
            "group_id": 44,
            "title": "The Show",
            "count": 2,
            "preview_titles": ["Episode One", "Episode Two"],
        }
    ]


def test_podcast_flag_playlist_gets_podcast_section_even_when_display_merged(qtbot) -> None:
    panel = PlaylistListPanel()
    qtbot.addWidget(panel)

    panel.loadPlaylists([
        {
            "Title": "Manual",
            "playlist_id": 1,
            "_mhsd_dataset_type": 2,
            "_mhsd_display_types": [2],
        },
        {
            "Title": "Podcasts",
            "playlist_id": 2,
            "podcast_flag": 1,
            "_mhsd_dataset_type": 3,
            "_mhsd_display_merged": True,
            "_mhsd_display_types": [2, 3],
        },
    ])

    section_labels = [
        child.text()
        for child in panel.findChildren(QLabel)
        if child.text().endswith("PLAYLISTS")
    ]

    assert "REGULAR PLAYLISTS" in section_labels
    assert "PODCAST PLAYLISTS" in section_labels
