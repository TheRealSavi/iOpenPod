from __future__ import annotations

import logging
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


def test_commit_user_playlists_keeps_user_smart_playlists_visible(
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
                    "Title": "Old Smart Bucket Copy",
                    "_source": "smart",
                    "smart_playlist_data": {"live_update": True},
                    "smart_playlist_rules": {"rules": []},
                }
            ],
        },
        "/fake/ipod",
    )

    cache.save_user_playlist(
        {
            "playlist_id": 2,
            "Title": "Recently Played",
            "_source": "smart",
            "smart_playlist_data": {"live_update": True},
            "smart_playlist_rules": {"rules": []},
        }
    )

    cache.commit_user_playlists()

    data = cache.get_data()
    assert data is not None
    assert [playlist["playlist_id"] for playlist in data["mhlp"]] == [2]
    assert data["mhlp"][0]["Title"] == "Recently Played"
    assert data["mhlp_smart"] == []


def test_commit_user_playlists_keeps_categories_in_smart_bucket(
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
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    cache.save_user_playlist(
        {
            "playlist_id": 3,
            "Title": "Music",
            "_source": "category",
            "mhsd5_type": 4,
            "smart_playlist_data": {"live_update": True},
        }
    )

    cache.commit_user_playlists()

    data = cache.get_data()
    assert data is not None
    assert data["mhlp"] == []
    assert [playlist["playlist_id"] for playlist in data["mhlp_smart"]] == [3]


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


def test_remove_user_playlist_can_target_same_id_by_dataset(monkeypatch) -> None:
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
                {"playlist_id": 2, "Title": "Dataset 2", "_mhsd_dataset_type": 2}
            ],
            "mhlp_podcast": [
                {"playlist_id": 2, "Title": "Dataset 3", "_mhsd_dataset_type": 3}
            ],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    assert cache.remove_user_playlist(2, 3) is True
    assert [(p["Title"], p["_mhsd_dataset_type"]) for p in cache.get_playlists()] == [
        ("Dataset 2", 2)
    ]


def test_display_playlists_merge_duplicate_dataset2_and_dataset3_rows(
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
                    "playlist_id": 2,
                    "Title": "Favorites",
                    "_mhsd_dataset_type": 2,
                    "items": [{"track_id": 10}, {"track_id": 11}],
                    "mhip_child_count": 2,
                }
            ],
            "mhlp_podcast": [
                {
                    "playlist_id": 2,
                    "Title": "Favorites",
                    "_mhsd_dataset_type": 3,
                    "items": [{"track_id": 10}, {"track_id": 11}],
                    "mhip_child_count": 2,
                }
            ],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    raw_playlists = cache.get_playlists()
    display_playlists = runtime.display_playlists_from_rows(raw_playlists)

    assert len(raw_playlists) == 2
    assert len(display_playlists) == 1
    assert display_playlists[0]["_mhsd_display_merged"] is True
    assert display_playlists[0]["_mhsd_display_types"] == [2, 3]
    assert display_playlists[0]["_mhsd_display_label"] == "MHSD type 2 + MHSD type 3"


def test_display_playlists_keep_type3_only_playlist_as_single_regular_row(
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
            "mhlp_podcast": [
                {
                    "playlist_id": 3,
                    "Title": "Type 3 Only",
                    "_mhsd_dataset_type": 3,
                    "items": [],
                }
            ],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    display_playlists = runtime.display_playlists_from_rows(cache.get_playlists())

    assert len(display_playlists) == 1
    assert display_playlists[0]["_source"] == "regular"
    assert display_playlists[0]["_mhsd_display_merged"] is False
    assert display_playlists[0]["_mhsd_display_types"] == [3]


def test_display_playlists_surface_dataset5_rows_even_without_mhsd5_marker(
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
                    "playlist_id": 5,
                    "Title": "Browse Row",
                    "mhsd5_type": 0,
                    "smart_playlist_data": {"live_update": True},
                }
            ],
        },
        "/fake/ipod",
    )

    display_playlists = runtime.display_playlists_from_rows(cache.get_playlists())

    assert len(display_playlists) == 1
    assert display_playlists[0]["Title"] == "Browse Row"
    assert display_playlists[0]["_mhsd_dataset_type"] == 5
    assert display_playlists[0]["_mhsd_display_types"] == [5]


def test_saving_display_merged_playlist_updates_all_duplicate_origins(
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
                    "playlist_id": 2,
                    "Title": "Old",
                    "_mhsd_dataset_type": 2,
                    "items": [{"track_id": 10}],
                }
            ],
            "mhlp_podcast": [
                {
                    "playlist_id": 2,
                    "Title": "Old",
                    "_mhsd_dataset_type": 3,
                    "items": [{"track_id": 10}],
                }
            ],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )
    merged = runtime.display_playlists_from_rows(cache.get_playlists())[0]
    merged["Title"] = "New"
    merged["items"] = [{"track_id": 10}, {"track_id": 11}]

    cache.save_user_playlist(merged)
    pending = sorted(
        cache.get_user_playlists(),
        key=lambda playlist: playlist["_mhsd_dataset_type"],
    )

    assert [(row["Title"], row["_mhsd_dataset_type"]) for row in pending] == [
        ("New", 2),
        ("New", 3),
    ]
    assert pending[0]["items"] == [{"track_id": 10}, {"track_id": 11}]
    assert pending[1]["items"] == [{"track_id": 10}, {"track_id": 11}]

    cache.commit_user_playlists()
    data = cache.get_data()
    assert data is not None
    assert data["mhlp"][0]["Title"] == "New"
    assert data["mhlp_podcast"][0]["Title"] == "New"
    assert data["mhlp"][0]["items"] == [{"track_id": 10}, {"track_id": 11}]
    assert data["mhlp_podcast"][0]["items"] == [{"track_id": 10}, {"track_id": 11}]


def test_removing_display_merged_playlist_deletes_all_duplicate_origins(
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
                {"playlist_id": 2, "Title": "Duplicate", "_mhsd_dataset_type": 2}
            ],
            "mhlp_podcast": [
                {"playlist_id": 2, "Title": "Duplicate", "_mhsd_dataset_type": 3}
            ],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    assert cache.remove_user_playlist(2, None) is True
    data = cache.get_data()
    assert data is not None
    assert data["mhlp"] == []
    assert data["mhlp_podcast"] == []


def test_save_user_playlist_refuses_ambiguous_originless_existing_edit(
    monkeypatch,
    caplog,
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
                {"playlist_id": 2, "Title": "Dataset 2", "_mhsd_dataset_type": 2}
            ],
            "mhlp_podcast": [
                {"playlist_id": 2, "Title": "Dataset 3", "_mhsd_dataset_type": 3}
            ],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    with caplog.at_level(logging.ERROR):
        cache.save_user_playlist(
            {
                "playlist_id": 2,
                "Title": "Edited",
                "_isNew": False,
                "_source": "regular",
                "playlist_description": "must not create a duplicate",
            }
        )

    assert "Refusing playlist edit without MHSD origin" in caplog.text
    assert cache.has_pending_playlists() is False
    data = cache.get_data()
    assert data is not None
    assert data["mhlp"][0]["Title"] == "Dataset 2"
    assert data["mhlp_podcast"][0]["Title"] == "Dataset 3"


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
                    "mhsd5_type": 4,
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
    assert "master_flag" not in playlists[2]
    assert playlists[3]["_source"] == "category"
    assert "master_flag" not in playlists[3]
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
