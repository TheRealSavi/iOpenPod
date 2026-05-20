from __future__ import annotations

from types import SimpleNamespace

from app_core import runtime


def test_commit_user_playlists_hydrates_pending_playlist_into_live_cache(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )

    cache = runtime.iTunesDBCache()
    cache.set_data(
        {
            "mhlt": [],
            "mhlp": [
                {
                    "playlist_id": 1,
                    "Title": "Existing",
                    "items": [{"track_id": 7}],
                    "mhip_child_count": 1,
                }
            ],
            "mhlp_podcast": [],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    cache.save_user_playlist(
        {
            "playlist_id": 2,
            "Title": "New Playlist",
            "_source": "regular",
            "items": [{"track_id": 10}, {"track_id": 20}],
        }
    )

    cache.commit_user_playlists()

    assert cache.has_pending_playlists() is False

    playlists = sorted(
        cache.get_playlists(),
        key=lambda playlist: int(playlist.get("playlist_id", 0) or 0),
    )

    assert [playlist["playlist_id"] for playlist in playlists] == [1, 2]
    assert playlists[1]["Title"] == "New Playlist"
    assert playlists[1]["items"] == [{"track_id": 10}, {"track_id": 20}]
    assert playlists[1]["mhip_child_count"] == 2


def test_album_grid_ignores_movie_only_album_entries(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )

    cache = runtime.iTunesDBCache()
    cache.set_data(
        {
            "mhlt": [
                {
                    "track_id": 1,
                    "album_id": 100,
                    "Album": "Movie Collection",
                    "Artist": "Director",
                    "Album Artist": "Director",
                    "media_type": 0x02,
                    "length": 90_000,
                },
                {
                    "track_id": 2,
                    "album_id": 200,
                    "Album": "Music Album",
                    "Artist": "Band",
                    "Album Artist": "Band",
                    "media_type": 0x01,
                    "length": 180_000,
                },
            ],
            "mhla": [
                {
                    "album_id": 100,
                    "Album (Used by Album Item)": "Movie Collection",
                    "Artist (Used by Album Item)": "Director",
                },
                {
                    "album_id": 200,
                    "Album (Used by Album Item)": "Music Album",
                    "Artist (Used by Album Item)": "Band",
                },
            ],
            "mhlp": [],
            "mhlp_podcast": [],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    albums = runtime.build_album_list(cache)

    assert [album["title"] for album in albums] == ["Music Album"]
    assert albums[0]["track_count"] == 1


def test_update_track_flags_records_canonical_track_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )

    track = {
        "db_track_id": 123,
        "Title": "Song",
        "checked_flag": 0,
        "compilation_flag": 0,
        "eq_setting": "",
    }
    cache = runtime.iTunesDBCache()
    cache.set_data(
        {
            "mhlt": [track],
            "mhlp": [],
            "mhlp_podcast": [],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    cache.update_track_flags(
        [track],
        {
            "checked_flag": 1,
            "compilation_flag": 1,
            "eq_setting": "Bass Booster",
        },
    )

    assert track["checked_flag"] == 1
    assert track["compilation_flag"] == 1
    assert track["eq_setting"] == "Bass Booster"
    assert cache.get_track_edits() == {
        123: {
            "checked_flag": (0, 1),
            "compilation_flag": (0, 1),
            "eq_setting": ("", "Bass Booster"),
        }
    }
