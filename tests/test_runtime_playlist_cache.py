from __future__ import annotations

import logging
from types import SimpleNamespace

from iopenpod.application import runtime
from iopenpod.device.write_guard import DatabaseGeneration


def test_cache_emits_load_failed_after_partial_device_load(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )

    cache = runtime.iTunesDBCache()
    errors: list[str] = []
    cache.load_failed.connect(errors.append)

    cache._on_load_complete(
        (
            {"mhlt": [], "mhlp": [], "mhlp_podcast": [], "mhlp_smart": []},
            "/fake/ipod",
            ["Could not load iTunesDB: [Errno 13] Permission denied"],
        )
    )

    assert errors == ["Could not load iTunesDB: [Errno 13] Permission denied"]


def test_quick_write_snapshot_carries_database_generation(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )
    generation = DatabaseGeneration("iTunesDB", True, digest="loaded")
    committed_generation = DatabaseGeneration("iTunesDB", True, digest="committed")
    cache = runtime.iTunesDBCache()
    cache.set_data(
        {"mhlt": [], "mhlp": [], "mhlp_podcast": [], "mhlp_smart": []},
        "/fake/ipod",
        generation,
    )

    snapshot = cache.capture_quick_write_state()

    assert snapshot.database_generation == generation
    assert cache.commit_quick_write_state_with_generation(
        snapshot.revision,
        committed_generation,
    )
    assert cache.get_database_generation() == committed_generation


def test_cache_rejects_database_changed_while_it_was_parsed(monkeypatch) -> None:
    from iopenpod.itunesdb_parser import ipod_library
    from iopenpod.sync import _db_io, photos

    generations = iter(
        (
            DatabaseGeneration("iTunesDB", True, digest="before"),
            DatabaseGeneration("iTunesDB", True, digest="after"),
        )
    )
    monkeypatch.setattr(
        runtime,
        "capture_database_generation",
        lambda _path: next(generations),
    )
    monkeypatch.setattr(_db_io, "commit_playcounts_if_needed", lambda _path: False)
    monkeypatch.setattr(
        ipod_library,
        "load_ipod_library",
        lambda *_args, **_kwargs: {"mhlt": []},
    )
    monkeypatch.setattr(photos, "read_photo_db", lambda _path: photos.PhotoDB())

    _data, _device_path, errors, generation = runtime.iTunesDBCache()._load_data(
        "/fake/ipod",
        "/fake/ipod/iPod_Control/iTunes/iTunesDB",
    )

    assert generation is None
    assert any("changed while iOpenPod was loading it" in error for error in errors)


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
            "mhlp_podcast": [
                {"playlist_id": 2, "Title": "Old Podcast", "master_flag": 1}
            ],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    assert cache.rename_master_playlist("New") is True
    playlists = cache.get_playlists()
    assert playlists[0]["Title"] == "New"
    assert playlists[1]["Title"] == "New"


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


def test_new_regular_playlist_creates_dataset2_and_dataset3_rows(
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
                {"playlist_id": 1, "Title": "iPod", "master_flag": 1}
            ],
            "mhlp_podcast": [
                {
                    "playlist_id": 10,
                    "Title": "iPod",
                    "master_flag": 1,
                    "_mhsd_dataset_type": 3,
                }
            ],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    cache.save_user_playlist(
        {
            "Title": "New Mix",
            "_isNew": True,
            "_source": "regular",
            "items": [{"track_id": 10}],
        }
    )
    pending = sorted(
        cache.get_user_playlists(),
        key=lambda playlist: playlist["_mhsd_dataset_type"],
    )

    assert [(row["Title"], row["_mhsd_dataset_type"]) for row in pending] == [
        ("New Mix", 2),
        ("New Mix", 3),
    ]

    cache.commit_user_playlists()
    data = cache.get_data()
    assert data is not None
    assert [row["Title"] for row in data["mhlp"] if not row.get("master_flag")] == [
        "New Mix"
    ]
    assert [
        row["Title"]
        for row in data["mhlp_podcast"]
        if not row.get("master_flag")
    ] == ["New Mix"]


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


def test_album_grid_does_not_duplicate_music_album_for_matching_podcast_album_entry(monkeypatch) -> None:
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
                    "Album": "Shared Album",
                    "Artist": "Band",
                    "Album Artist": "Band",
                    "media_type": 0x04,
                    "length": 90_000,
                },
                {
                    "track_id": 2,
                    "album_id": 200,
                    "Album": "Shared Album",
                    "Artist": "Band",
                    "Album Artist": "Band",
                    "media_type": 0x01,
                    "length": 180_000,
                },
            ],
            "mhla": [
                {
                    "album_id": 100,
                    "Album (Used by Album Item)": "Shared Album",
                    "Artist (Used by Album Item)": "Band",
                },
                {
                    "album_id": 200,
                    "Album (Used by Album Item)": "Shared Album",
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

    assert [album["title"] for album in albums] == ["Shared Album"]
    assert albums[0]["filter_key"] == "album_id"
    assert albums[0]["filter_value"] == 200


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


def test_commit_quick_write_state_preserves_live_data_and_photo_edits(
    monkeypatch,
) -> None:
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

    revision = cache.get_quick_write_revision()
    assert cache.commit_quick_write_state(revision) is True

    assert cache.get_data() is not None
    assert cache.is_ready()
    assert track["checked_flag"] == 1
    assert [playlist["Title"] for playlist in cache.get_playlists()] == ["Pending"]
    assert not cache.has_pending_track_edits()
    assert not cache.has_pending_playlists()
    assert cache.has_pending_photo_edits()


def test_commit_quick_write_state_keeps_edits_staged_after_snapshot(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )

    track = {"db_track_id": 123, "Title": "Song", "rating": 20}
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
    cache.update_track_flags([track], {"rating": 40})
    written_revision = cache.get_quick_write_revision()

    cache.update_track_flags([track], {"rating": 80})

    assert cache.commit_quick_write_state(written_revision) is False
    assert cache.has_pending_track_edits()
    assert cache.get_track_edits()[123]["rating"] == (20, 80)


def test_playlist_remove_and_master_rename_advance_quick_write_revision(
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
                {"playlist_id": 1, "Title": "iPod", "master_flag": 1},
                {"playlist_id": 2, "Title": "Mix"},
            ],
            "mhlp_podcast": [],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )

    before_remove = cache.get_quick_write_revision()
    assert cache.remove_user_playlist(2) is True
    after_remove = cache.get_quick_write_revision()
    assert after_remove > before_remove

    assert cache.rename_master_playlist("RoadPod") is True
    assert cache.get_quick_write_revision() > after_remove


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
