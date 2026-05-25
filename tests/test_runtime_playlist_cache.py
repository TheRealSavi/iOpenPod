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


def test_rename_master_playlist_updates_live_cache(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )

    cache = runtime.iTunesDBCache()
    cache.set_data(
        {
            "mhlt": [],
            "mhlp": [{"playlist_id": 1, "Title": "Old", "master_flag": 1}],
            "mhlp_podcast": [],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    assert cache.rename_master_playlist("New") is True
    assert cache.get_playlists()[0]["Title"] == "New"


def test_remove_user_playlist_removes_live_playlist(monkeypatch) -> None:
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
                {"playlist_id": 1, "Title": "Keep"},
                {"playlist_id": 2, "Title": "Remove"},
            ],
            "mhlp_podcast": [],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    assert cache.remove_user_playlist(2) is True
    assert [playlist["playlist_id"] for playlist in cache.get_playlists()] == [1]


def test_remove_user_playlist_rejects_master_playlist(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )

    cache = runtime.iTunesDBCache()
    cache.set_data(
        {
            "mhlt": [],
            "mhlp": [{"playlist_id": 1, "Title": "iPod", "master_flag": 1}],
            "mhlp_podcast": [],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    assert cache.remove_user_playlist(1) is False
    assert cache.get_playlists()[0]["master_flag"] == 1


def test_get_playlists_distinguishes_dataset5_smart_playlists_from_categories(
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
            "mhlp": [],
            "mhlp_podcast": [],
            "mhlp_smart": [
                {
                    "playlist_id": 2,
                    "Title": "Recently Added",
                    "mhsd5_type": 0,
                    "smart_playlist_data": {"live_update": True},
                },
                {
                    "playlist_id": 3,
                    "Title": "Music",
                    "mhsd5_type": 1,
                    "smart_playlist_data": {"live_update": True},
                },
                {
                    "playlist_id": 4,
                    "Title": "String Zero Smart",
                    "mhsd5_type": "0",
                    "smart_playlist_data": {"live_update": True},
                },
            ],
        },
        "/fake/ipod",
    )

    playlists = {
        playlist["playlist_id"]: playlist
        for playlist in cache.get_playlists()
    }

    assert playlists[2]["_source"] == "smart"
    assert playlists[2]["master_flag"] == 0
    assert playlists[3]["_source"] == "category"
    assert playlists[3]["master_flag"] == 0
    assert playlists[4]["_source"] == "smart"


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


def test_update_track_artwork_records_pending_artwork(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )

    artwork_path = tmp_path / "iopenpod-artwork-test.png"
    artwork_path.write_bytes(b"png")
    track = {"db_track_id": 123, "Title": "Song", "artwork_count": 0}
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

    cache.update_track_artwork([track], str(artwork_path))

    assert track["artwork_count"] == 0
    assert "has_artwork" not in track
    assert track["_iop_pending_artwork_path"] == str(artwork_path)
    assert cache.has_pending_track_edits()
    assert cache.pop_track_artwork_edits() == {123: str(artwork_path)}
    assert not cache.has_pending_track_edits()


def test_discard_quick_write_state_preserves_photo_edits(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )

    track = {"db_track_id": 123, "Title": "Song", "checked_flag": 0}
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

    cache.update_track_flags([track], {"checked_flag": 1})
    cache.save_user_playlist(
        {
            "playlist_id": 2,
            "Title": "Pending",
            "_source": "regular",
            "items": [],
        }
    )
    cache.stage_photo_import("/tmp/photo.jpg", "Album")
    cache.update_track_artwork([track], "/tmp/iopenpod-artwork-test.png")

    cache.discard_quick_write_state()

    assert not cache.has_pending_track_edits()
    assert not cache.has_pending_playlists()
    assert cache.pop_track_artwork_edits() == {}
    assert cache.has_pending_photo_edits()


def test_reload_after_itunesdb_write_clears_quick_state_and_starts_load(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )

    load_calls = 0
    track = {"db_track_id": 123, "Title": "Song", "checked_flag": 0}
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
    cache.update_track_flags([track], {"checked_flag": 1})
    cache.stage_photo_import("/tmp/photo.jpg", "Album")

    def fake_start_loading() -> None:
        nonlocal load_calls
        load_calls += 1

    monkeypatch.setattr(cache, "start_loading", fake_start_loading)

    cache.reload_after_itunesdb_write()

    assert load_calls == 1
    assert cache.get_data() is None
    assert not cache.has_pending_track_edits()
    assert cache.has_pending_photo_edits()
