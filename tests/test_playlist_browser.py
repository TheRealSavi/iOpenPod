from __future__ import annotations

from GUI.widgets.playlistBrowser import (
    _is_ipod_category_playlist,
    _is_user_smart_playlist,
)


def test_dataset5_smart_playlist_is_not_treated_as_ipod_category() -> None:
    playlist = {
        "Title": "Recently Added",
        "_source": "smart",
        "mhsd5_type": 0,
        "smart_playlist_data": {"live_update": True},
    }

    assert not _is_ipod_category_playlist(playlist)
    assert _is_user_smart_playlist(playlist)


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
