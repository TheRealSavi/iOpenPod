from __future__ import annotations

import struct
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from iopenpod.device.write_guard import DatabaseGeneration
from iopenpod.itunesdb_shared.constants import MEDIA_TYPE_PODCAST
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhyp_writer import write_mhyp
from iopenpod.sync import quick_writes
from iopenpod.sync._playlist_builder import build_and_evaluate_playlists
from iopenpod.sync._track_conversion import track_dict_to_info


@dataclass
class FakePlaylistInfo:
    playlist_id: int
    track_ids: list[int]


@pytest.fixture(autouse=True)
def _safe_filesystem_profile(monkeypatch):
    profile = SimpleNamespace(case_sensitive=False)
    monkeypatch.setattr(
        quick_writes,
        "inspect_device_write_readiness",
        lambda _path, **_kwargs: profile,
    )
    monkeypatch.setattr(
        quick_writes,
        "revalidate_device_write_readiness",
        lambda retained, **_kwargs: retained,
    )
    monkeypatch.setattr(quick_writes, "volume_lock_key", lambda _profile: "test-volume")
    return profile


def test_quick_write_keeps_numbered_album_artist_placeholder_group(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        quick_writes,
        "_evaluate_tracks_and_playlists",
        lambda **_kwargs: (
            "iPod",
            None,
            [FakePlaylistInfo(1, [100])],
            "iPod",
            None,
            [],
            [],
        ),
    )

    def fake_write(*_args, **kwargs) -> bool:
        captured["track"] = kwargs["all_tracks"][0]
        return True

    monkeypatch.setattr(quick_writes, "_write_evaluated_database", fake_write)

    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[
            {
                "track_id": 10,
                "db_track_id": 100,
                "Title": "Video",
                "Location": ":iPod_Control:Music:F00:VIDEO.m4v",
                "Artist": "Unknown Artist 194",
                "Album": "Unknown Album 175",
                "Album Artist": "Unknown Artist 194",
            }
        ],
        playlists_data=[
            {"playlist_id": 1, "Title": "iPod", "master_flag": 1}
        ],
    )

    track = captured["track"]
    assert result.success
    assert (track.artist, track.album, track.album_artist) == (
        "Unknown Artist 194",
        "Unknown Album 194",
        "Unknown Artist 194",
    )


def test_write_cached_itunesdb_dumps_tracks_and_playlists_once(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    tracks_data = [{"track_id": 10, "db_track_id": 100, "Title": "Edited"}]
    playlists_data = [
        {"playlist_id": 1, "Title": "iPod", "master_flag": 1},
        {"playlist_id": 2, "Title": "Pending", "_isNew": True},
    ]
    all_tracks = [SimpleNamespace(artist="", album="", album_artist="")]

    monkeypatch.setattr(quick_writes, "_tracks_to_infos", lambda *_args, **_kwargs: all_tracks)

    def fake_evaluate(**kwargs):
        captured["evaluate"] = kwargs
        return (
            "iPod",
            None,
            [FakePlaylistInfo(1, [100]), FakePlaylistInfo(2, [100])],
            "iPod",
            None,
            [],
            [],
        )

    def fake_write(*args, **kwargs):
        captured["write_args"] = args
        captured["write"] = kwargs
        return True

    monkeypatch.setattr(quick_writes, "_evaluate_tracks_and_playlists", fake_evaluate)
    monkeypatch.setattr(quick_writes, "_write_evaluated_database", fake_write)

    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=tracks_data,
        playlists_data=playlists_data,
    )

    assert result.success
    assert result.track_count == 1
    assert result.playlist_counts == {1: 1, 2: 1}
    assert captured["evaluate"]["tracks_data"] == tracks_data
    assert captured["evaluate"]["dataset2_playlist_rows"] == [
        {
            "playlist_id": 1,
            "Title": "iPod",
            "master_flag": 1,
            "_mhsd_dataset_type": 2,
            "_mhsd_result_key": "mhlp",
        },
        {
            "playlist_id": 2,
            "Title": "Pending",
            "_isNew": True,
            "_mhsd_dataset_type": 2,
            "_mhsd_result_key": "mhlp",
        },
    ]
    assert captured["evaluate"]["dataset3_playlist_rows"] == []
    assert captured["evaluate"]["dataset5_playlist_rows"] == []
    assert captured["write"]["master_playlist_name"] == "iPod"


def test_quick_write_holds_writer_guard_from_build_through_commit(
    monkeypatch,
) -> None:
    events: list[str] = []
    cached_generation = DatabaseGeneration("iTunesDB", True, digest="cached")
    committed_generation = DatabaseGeneration("iTunesDB", True, digest="committed")
    guard_arguments: dict[str, Any] = {}

    class FakeGuard:
        def __init__(self, _ipod_path, **kwargs) -> None:
            guard_arguments.update(kwargs)

        @property
        def starting_database_generation(self):
            return committed_generation

        def __enter__(self):
            events.append("guard-enter")
            return self

        def __exit__(self, *_args) -> None:
            events.append("guard-exit")

    monkeypatch.setattr(quick_writes, "DeviceWriteGuard", FakeGuard, raising=False)

    def fake_tracks_to_infos(*_args):
        events.append("build")
        return [SimpleNamespace(artist="", album="", album_artist="")]

    monkeypatch.setattr(
        quick_writes,
        "_tracks_to_infos",
        fake_tracks_to_infos,
    )
    monkeypatch.setattr(
        quick_writes,
        "_evaluate_tracks_and_playlists",
        lambda **_kwargs: (
            "iPod",
            None,
            [],
            "iPod",
            None,
            [],
            [],
        ),
    )

    def fake_write(*_args, **kwargs) -> bool:
        assert isinstance(kwargs["write_guard"], FakeGuard)
        events.append("commit")
        return True

    monkeypatch.setattr(quick_writes, "_write_evaluated_database", fake_write)

    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[{"track_id": 1, "Title": "Song"}],
        playlists_data=[],
        expected_database_generation=cached_generation,
    )

    assert result.success is True
    assert result.database_generation == committed_generation
    assert guard_arguments["expected_database_generation"] == cached_generation
    assert events == ["guard-enter", "build", "commit", "guard-exit"]


def test_quick_write_refuses_replaced_scan_time_volume(monkeypatch) -> None:
    guard_entered = False

    class FakeGuard:
        def __init__(self, *_args, **_kwargs) -> None:
            nonlocal guard_entered
            guard_entered = True

    monkeypatch.setattr(quick_writes, "DeviceWriteGuard", FakeGuard)

    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[{"track_id": 1, "Title": "Song"}],
        playlists_data=[],
        expected_volume_identity_key="scan-volume",
    )

    assert result.success is False
    assert result.errors[0][0] == "filesystem_safety"
    assert "different volume" in result.error.lower()
    assert guard_entered is False


def test_write_cached_itunesdb_uses_master_name_from_cache(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    all_tracks = [SimpleNamespace(artist="", album="", album_artist="")]

    monkeypatch.setattr(quick_writes, "_tracks_to_infos", lambda *_args, **_kwargs: all_tracks)

    def fake_evaluate(**kwargs):
        captured["evaluate"] = kwargs
        return ("Renamed iPod", 1, [FakePlaylistInfo(1, [100])], "Renamed iPod", None, [], [])

    def fake_write(*args, **kwargs):
        captured["write"] = kwargs
        return True

    monkeypatch.setattr(quick_writes, "_evaluate_tracks_and_playlists", fake_evaluate)
    monkeypatch.setattr(quick_writes, "_write_evaluated_database", fake_write)

    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[{"track_id": 10, "db_track_id": 100}],
        playlists_data=[
            {"playlist_id": 1, "Title": "Renamed iPod", "master_flag": 1}
        ],
    )

    assert result.success
    assert result.master_playlist_name == "Renamed iPod"
    assert captured["write"]["master_playlist_name"] == "Renamed iPod"


def test_write_cached_itunesdb_splits_categories_from_visible_playlists(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    all_tracks = [SimpleNamespace(artist="", album="", album_artist="")]

    monkeypatch.setattr(quick_writes, "_tracks_to_infos", lambda *_args, **_kwargs: all_tracks)

    def fake_evaluate(**kwargs):
        captured.update(kwargs)
        return ("iPod", None, [FakePlaylistInfo(1, [100])], "iPod", None, [], [FakePlaylistInfo(2, [100])])

    monkeypatch.setattr(quick_writes, "_evaluate_tracks_and_playlists", fake_evaluate)
    monkeypatch.setattr(quick_writes, "_write_evaluated_database", lambda *args, **kwargs: True)

    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[{"track_id": 10, "db_track_id": 100}],
        playlists_data=[
            {"playlist_id": 1, "Title": "Regular", "_source": "regular"},
            {
                "playlist_id": 2,
                "Title": "Smart",
                "_source": "smart",
                "smart_playlist_data": {"live_update": True},
            },
            {
                "playlist_id": 3,
                "Title": "Music",
                "_source": "category",
                "smart_playlist_data": {"live_update": True},
            },
            {
                "playlist_id": 4,
                "Title": "Movies",
                "_source": "smart",
                "mhsd5_type": 2,
            },
        ],
    )

    assert result.success
    assert captured["dataset2_playlist_rows"] == [
        {
            "playlist_id": 1,
            "Title": "Regular",
            "_source": "regular",
            "_mhsd_dataset_type": 2,
            "_mhsd_result_key": "mhlp",
        },
        {
            "playlist_id": 2,
            "Title": "Smart",
            "_source": "smart",
            "smart_playlist_data": {"live_update": True},
            "_mhsd_dataset_type": 2,
            "_mhsd_result_key": "mhlp",
        },
    ]
    assert captured["dataset3_playlist_rows"] == []
    assert captured["dataset5_playlist_rows"] == [
        {
            "playlist_id": 3,
            "Title": "Music",
            "_source": "category",
            "smart_playlist_data": {"live_update": True},
        },
        {
            "playlist_id": 4,
            "Title": "Movies",
            "_source": "smart",
            "mhsd5_type": 2,
        },
    ]


def test_write_cached_itunesdb_mirrors_regular_playlist_when_dataset3_exists(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}
    all_tracks = [SimpleNamespace(artist="", album="", album_artist="")]

    monkeypatch.setattr(quick_writes, "_tracks_to_infos", lambda *_args, **_kwargs: all_tracks)

    def fake_evaluate(**kwargs):
        captured.update(kwargs)
        return (
            "iPod",
            1,
            [FakePlaylistInfo(2, [100])],
            "iPod",
            10,
            [FakePlaylistInfo(2, [100])],
            [],
        )

    monkeypatch.setattr(quick_writes, "_evaluate_tracks_and_playlists", fake_evaluate)
    monkeypatch.setattr(quick_writes, "_write_evaluated_database", lambda *args, **kwargs: True)

    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[{"track_id": 10, "db_track_id": 100}],
        playlists_data=[
            {
                "playlist_id": 10,
                "Title": "iPod",
                "master_flag": 1,
                "_mhsd_dataset_type": 3,
            },
            {
                "playlist_id": 2,
                "Title": "New Mix",
                "_source": "regular",
                "items": [{"track_id": 10}],
            },
        ],
    )

    assert result.success
    assert captured["dataset2_playlist_rows"] == [
        {
            "playlist_id": 2,
            "Title": "New Mix",
            "_source": "regular",
            "items": [{"track_id": 10}],
            "mhip_child_count": 1,
            "_mhsd_dataset_type": 2,
            "_mhsd_result_key": "mhlp",
        }
    ]
    assert captured["dataset3_playlist_rows"] == [
        {
            "playlist_id": 10,
            "Title": "iPod",
            "master_flag": 1,
            "_mhsd_dataset_type": 3,
        },
        {
            "playlist_id": 2,
            "Title": "New Mix",
            "_source": "regular",
            "items": [{"track_id": 10}],
            "mhip_child_count": 1,
            "_mhsd_dataset_type": 3,
            "_mhsd_result_key": "mhlp_podcast",
        },
    ]


def test_write_cached_itunesdb_reports_missing_tracks() -> None:
    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[],
        playlists_data=[],
    )

    assert not result.success
    assert result.error == "No cached tracks available to write."


def test_write_cached_itunesdb_allows_empty_device_master_playlist(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    monkeypatch.setattr(quick_writes, "_tracks_to_infos", lambda *_args, **_kwargs: [])

    def fake_evaluate(**kwargs):
        captured["evaluate"] = kwargs
        return ("Dreamy", 1, [FakePlaylistInfo(1, [])], "Dreamy", None, [], [])

    def fake_write(*args, **kwargs):
        captured["write"] = kwargs
        return True

    monkeypatch.setattr(quick_writes, "_evaluate_tracks_and_playlists", fake_evaluate)
    monkeypatch.setattr(quick_writes, "_write_evaluated_database", fake_write)

    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[],
        playlists_data=[{"playlist_id": 1, "Title": "Dreamy", "master_flag": 1}],
    )

    assert result.success
    assert result.track_count == 0
    assert result.master_playlist_name == "Dreamy"
    assert captured["evaluate"]["tracks_data"] == []
    assert captured["write"]["all_tracks"] == []
    assert captured["write"]["master_playlist_name"] == "Dreamy"


def test_write_cached_itunesdb_passes_artwork_sources(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    all_tracks = [SimpleNamespace(artist="", album="", album_artist="")]

    monkeypatch.setattr(quick_writes, "_tracks_to_infos", lambda *_args, **_kwargs: all_tracks)
    monkeypatch.setattr(
        quick_writes,
        "_evaluate_tracks_and_playlists",
        lambda **_kwargs: ("iPod", None, [FakePlaylistInfo(1, [100])], "iPod", None, [], []),
    )

    def fake_write(*args, **kwargs):
        captured["write"] = kwargs
        return True

    monkeypatch.setattr(quick_writes, "_write_evaluated_database", fake_write)

    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[{"track_id": 10, "db_track_id": 100}],
        playlists_data=[{"playlist_id": 1, "Title": "iPod", "master_flag": 1}],
        artwork_sources={100: "/tmp/iopenpod-artwork-test.png"},
    )

    assert result.success
    assert captured["write"]["pc_file_paths"] == {100: "/tmp/iopenpod-artwork-test.png"}


def test_write_cached_itunesdb_empty_artwork_sources_skip_artwork_writer(
    monkeypatch,
) -> None:
    captured: dict[str, Any] = {}
    all_tracks = [SimpleNamespace(artist="", album="", album_artist="")]

    monkeypatch.setattr(quick_writes, "_tracks_to_infos", lambda *_args, **_kwargs: all_tracks)
    monkeypatch.setattr(
        quick_writes,
        "_evaluate_tracks_and_playlists",
        lambda **_kwargs: ("iPod", None, [FakePlaylistInfo(1, [100])], "iPod", None, [], []),
    )

    def fake_write(*args, **kwargs):
        captured["write"] = kwargs
        return True

    monkeypatch.setattr(quick_writes, "_write_evaluated_database", fake_write)

    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[{"track_id": 10, "db_track_id": 100}],
        playlists_data=[{"playlist_id": 1, "Title": "iPod", "master_flag": 1}],
        artwork_sources={},
    )

    assert result.success
    assert captured["write"]["pc_file_paths"] is None


def test_cached_playlist_items_can_reference_db_track_ids() -> None:
    track = TrackInfo(
        title="Imported",
        location=":iPod_Control:Music:F00:IMPT.mp3",
        track_id=10,
        db_track_id=100,
    )

    _master_name, _master_id, playlists, _podcast_master, _podcast_master_id, _podcast_playlists, _smart_playlists = build_and_evaluate_playlists(
        [{"track_id": 10, "db_track_id": 100}],
        [
            {"playlist_id": 1, "Title": "iPod", "master_flag": 1},
            {
                "playlist_id": 2,
                "Title": "Imported",
                "items": [{"db_track_id": 100}],
            },
        ],
        [],
        [],
        [track],
    )

    imported = next(playlist for playlist in playlists if playlist.playlist_id == 2)
    assert imported.track_ids == [100]


def test_cached_playlist_items_can_reference_source_paths(tmp_path) -> None:
    source = tmp_path / "Imported.mp3"
    source.write_bytes(b"audio")
    track = TrackInfo(
        title="Imported",
        location=":iPod_Control:Music:F00:IMPT.mp3",
        db_track_id=100,
        source_path=str(source),
    )

    _master_name, _master_id, playlists, _podcast_master, _podcast_master_id, _podcast_playlists, _smart_playlists = build_and_evaluate_playlists(
        [],
        [
            {"playlist_id": 1, "Title": "iPod", "master_flag": 1},
            {
                "playlist_id": 2,
                "Title": "Imported",
                "items": [{"source_path": str(source)}],
            },
        ],
        [],
        [],
        [track],
        {str(source): 100},
    )

    imported = next(playlist for playlist in playlists if playlist.playlist_id == 2)
    assert imported.track_ids == [100]


def test_user_smart_playlist_in_visible_bucket_is_evaluated() -> None:
    track = TrackInfo(
        title="Song",
        location=":iPod_Control:Music:F00:SONG.mp3",
        track_id=10,
        db_track_id=100,
    )

    _master_name, _master_id, playlists, _podcast_master, _podcast_master_id, _podcast_playlists, smart_playlists = build_and_evaluate_playlists(
        [{"track_id": 10, "db_track_id": 100, "Title": "Song"}],
        [
            {"playlist_id": 1, "Title": "iPod", "master_flag": 1},
            {
                "playlist_id": 2,
                "Title": "User Smart",
                "_source": "smart",
                "smart_playlist_data": {
                    "live_update": True,
                    "check_rules": True,
                    "check_limits": False,
                },
                "smart_playlist_rules": {"conjunction": "AND", "rules": []},
            },
        ],
        [],
        [],
        [track],
    )

    user_smart = next(playlist for playlist in playlists if playlist.playlist_id == 2)
    assert user_smart.is_smart
    assert user_smart.track_ids == [100]
    assert smart_playlists == []


def test_dataset2_standard_playlists_win_over_dataset3_podcast_mirror() -> None:
    track = TrackInfo(
        title="Song",
        location=":iPod_Control:Music:F00:SONG.mp3",
        track_id=10,
        db_track_id=100,
    )

    master_name, master_id, playlists, podcast_master_name, podcast_master_id, podcast_playlists, smart_playlists = build_and_evaluate_playlists(
        [{"track_id": 10, "db_track_id": 100, "Title": "Song"}],
        [
            {"playlist_id": 1, "Title": "Dataset 2 Master", "master_flag": 1},
            {"playlist_id": 2, "Title": "Dataset 2 Playlist", "items": [{"db_track_id": 100}]},
        ],
        [
            {"playlist_id": 10, "Title": "Dataset 3 Master", "master_flag": 1},
            {"playlist_id": 11, "Title": "Dataset 3 Playlist", "items": [{"db_track_id": 100}]},
        ],
        [],
        [track],
    )

    assert master_name == "Dataset 2 Master"
    assert master_id == 1
    assert [playlist.name for playlist in playlists] == ["Dataset 2 Playlist"]
    assert podcast_master_name == "Dataset 3 Master"
    assert podcast_master_id == 10
    assert [playlist.name for playlist in podcast_playlists] == ["Dataset 3 Playlist"]
    assert smart_playlists == []


def test_dataset3_podcast_playlist_list_stays_separate_when_dataset2_empty() -> None:
    track = TrackInfo(
        title="Podcast",
        location=":iPod_Control:Music:F00:PODC.mp3",
        track_id=10,
        db_track_id=100,
    )

    master_name, master_id, playlists, podcast_master_name, podcast_master_id, podcast_playlists, smart_playlists = build_and_evaluate_playlists(
        [{"track_id": 10, "db_track_id": 100, "Title": "Podcast"}],
        [],
        [
            {"playlist_id": 10, "Title": "Dataset 3 Master", "master_flag": 1},
            {"playlist_id": 11, "Title": "Dataset 3 Playlist", "items": [{"db_track_id": 100}]},
        ],
        [],
        [track],
    )

    assert master_name == "iPod"
    assert master_id is None
    assert playlists == []
    assert podcast_master_name == "Dataset 3 Master"
    assert podcast_master_id == 10
    assert [playlist.name for playlist in podcast_playlists] == ["Dataset 3 Playlist"]
    assert smart_playlists == []


def test_podcast_playlist_membership_tracks_all_podcast_tracks() -> None:
    existing_podcast = TrackInfo(
        title="Old Episode",
        location=":iPod_Control:Music:F00:OLDP.mp3",
        track_id=10,
        db_track_id=100,
        media_type=MEDIA_TYPE_PODCAST,
        podcast_flag=1,
    )
    new_podcast = TrackInfo(
        title="New Episode",
        location=":iPod_Control:Music:F00:NEWP.mp3",
        track_id=11,
        db_track_id=101,
        media_type=MEDIA_TYPE_PODCAST,
        podcast_flag=1,
    )
    song = TrackInfo(
        title="Song",
        location=":iPod_Control:Music:F00:SONG.mp3",
        track_id=12,
        db_track_id=102,
    )

    _master_name, _master_id, playlists, _podcast_master, _podcast_master_id, podcast_playlists, _smart_playlists = build_and_evaluate_playlists(
        [
            {"track_id": 10, "db_track_id": 100, "Title": "Old Episode"},
            {"track_id": 12, "db_track_id": 102, "Title": "Song"},
        ],
        [
            {"playlist_id": 1, "Title": "iPod", "master_flag": 1},
            {
                "playlist_id": 2,
                "Title": "Podcasts",
                "podcast_flag": 1,
                "items": [{"db_track_id": 100}],
            },
        ],
        [
            {"playlist_id": 10, "Title": "iPod", "master_flag": 1},
            {
                "playlist_id": 2,
                "Title": "Podcasts",
                "podcast_flag": 1,
                "items": [{"db_track_id": 100}],
            },
        ],
        [],
        [existing_podcast, new_podcast, song],
    )

    assert [playlist.track_ids for playlist in playlists if playlist.podcast_flag] == [[100, 101]]
    assert [playlist.track_ids for playlist in podcast_playlists if playlist.podcast_flag] == [[100, 101]]


def test_converted_track_dict_builds_dataset3_podcast_playlist() -> None:
    converted = {
        "track_id": 10,
        "db_track_id": 100,
        "Title": "Converted Episode",
        "Album": "Example Show",
        "Location": ":iPod_Control:Music:F00:CONV.mp3",
        "media_type": MEDIA_TYPE_PODCAST,
        "use_podcast_now_playing_flag": 1,
        "skip_when_shuffling": 1,
        "remember_position": 1,
    }
    track = track_dict_to_info(converted)

    assert track.media_type == MEDIA_TYPE_PODCAST
    assert track.podcast_flag == 1
    assert track.skip_when_shuffling is True
    assert track.remember_position is True

    _master_name, _master_id, _playlists, _podcast_master, _podcast_master_id, podcast_playlists, _smart_playlists = build_and_evaluate_playlists(
        [converted],
        [{"playlist_id": 1, "Title": "iPod", "master_flag": 1}],
        [],
        [],
        [track],
    )

    assert [(playlist.name, playlist.track_ids, playlist.podcast_flag) for playlist in podcast_playlists] == [
        ("Podcasts", [100], 1)
    ]


def test_podcast_playlist_is_created_in_dataset3_when_missing() -> None:
    podcast = TrackInfo(
        title="Episode",
        location=":iPod_Control:Music:F00:PODC.mp3",
        track_id=10,
        db_track_id=100,
        media_type=MEDIA_TYPE_PODCAST,
        podcast_flag=1,
    )

    _master_name, _master_id, playlists, _podcast_master, _podcast_master_id, podcast_playlists, _smart_playlists = build_and_evaluate_playlists(
        [{"track_id": 10, "db_track_id": 100, "Title": "Episode"}],
        [{"playlist_id": 1, "Title": "iPod", "master_flag": 1}],
        [],
        [],
        [podcast],
    )

    assert playlists == []
    assert [(playlist.name, playlist.track_ids, playlist.podcast_flag) for playlist in podcast_playlists] == [
        ("Podcasts", [100], 1)
    ]


def test_smart_playlist_playlist_rules_use_referenced_playlist_ids() -> None:
    mucha_id = 0x3F132AAFF590919A
    horchata_id = 0xCF653C0FFD7D66C4
    tracks = [
        TrackInfo(
            title="Mucha Episode",
            location=":iPod_Control:Music:F00:MUCH.mp3",
            track_id=10,
            db_track_id=100,
        ),
        TrackInfo(
            title="Horchata Episode",
            location=":iPod_Control:Music:F00:HORC.mp3",
            track_id=11,
            db_track_id=101,
        ),
        TrackInfo(
            title="Other Episode",
            location=":iPod_Control:Music:F00:OTHR.mp3",
            track_id=12,
            db_track_id=102,
        ),
    ]

    _master_name, _master_id, playlists, _podcast_master, _podcast_master_id, _podcast_playlists, _smart_playlists = build_and_evaluate_playlists(
        [
            {"track_id": 10, "db_track_id": 100, "Title": "Mucha Episode"},
            {"track_id": 11, "db_track_id": 101, "Title": "Horchata Episode"},
            {"track_id": 12, "db_track_id": 102, "Title": "Other Episode"},
        ],
        [
            {"playlist_id": 1, "Title": "iPod", "master_flag": 1},
            {
                "playlist_id": mucha_id,
                "Title": "Mucha Gracias",
                "items": [{"track_id": 10}],
            },
            {
                "playlist_id": horchata_id,
                "Title": "Horchata",
                "items": [{"track_id": 11}],
            },
            {
                "playlist_id": 0x74F0AFDEDA69A018,
                "Title": "Smart PL Rule",
                "smart_playlist_data": {
                    "live_update": True,
                    "check_rules": True,
                    "check_limits": False,
                },
                "smart_playlist_rules": {
                    "conjunction": "OR",
                    "rules": [
                        {
                            "field_id": 0x28,
                            "action_id": 0x00000001,
                            "from_value": mucha_id,
                            "to_value": mucha_id,
                            "from_units": 1,
                            "to_units": 1,
                        },
                        {
                            "field_id": 0x28,
                            "action_id": 0x00000001,
                            "from_value": horchata_id,
                            "to_value": horchata_id,
                            "from_units": 1,
                            "to_units": 1,
                        },
                    ],
                },
            },
        ],
        [],
        [],
        tracks,
    )

    smart = next(playlist for playlist in playlists if playlist.name == "Smart PL Rule")
    assert smart.track_ids == [100, 101]


def test_existing_dataset5_user_smart_playlist_stays_in_dataset5_bucket() -> None:
    track = TrackInfo(
        title="Song",
        location=":iPod_Control:Music:F00:SONG.mp3",
        track_id=10,
        db_track_id=100,
    )

    _master_name, _master_id, playlists, _podcast_master, _podcast_master_id, _podcast_playlists, smart_playlists = build_and_evaluate_playlists(
        [{"track_id": 10, "db_track_id": 100, "Title": "Song"}],
        [{"playlist_id": 1, "Title": "iPod", "master_flag": 1}],
        [],
        [
            {
                "playlist_id": 2,
                "Title": "Old Smart Bucket Copy",
                "mhsd5_type": 0,
                "smart_playlist_data": {
                    "live_update": True,
                    "check_rules": True,
                    "check_limits": False,
                },
                "smart_playlist_rules": {"conjunction": "AND", "rules": []},
            }
        ],
        [track],
    )

    assert playlists == []
    dataset5_smart = next(
        playlist for playlist in smart_playlists if playlist.playlist_id == 2
    )
    assert dataset5_smart.is_smart
    assert dataset5_smart.track_ids == [100]


def test_dataset5_category_keeps_firmware_marker_from_ui_cache() -> None:
    track = TrackInfo(
        title="Song",
        location=":iPod_Control:Music:F00:SONG.mp3",
        track_id=10,
        db_track_id=100,
    )

    _master_name, _master_id, _playlists, _podcast_master, _podcast_master_id, _podcast_playlists, smart_playlists = build_and_evaluate_playlists(
        [{"track_id": 10, "db_track_id": 100, "Title": "Song"}],
        [{"playlist_id": 1, "Title": "iPod", "master_flag": 1}],
        [],
        [
            {
                "playlist_id": 3,
                "Title": "Music",
                "_source": "category",
                "master_flag": 0,
                "mhsd5_type": "4",
                "smart_playlist_data": {
                    "live_update": True,
                    "check_rules": True,
                    "check_limits": False,
                },
                "smart_playlist_rules": {"conjunction": "AND", "rules": []},
            }
        ],
        [track],
    )

    assert len(smart_playlists) == 1
    assert smart_playlists[0].master is False
    assert smart_playlists[0].mhsd5_type == 4


def test_dataset5_category_preserves_parsed_membership_and_item_metadata() -> None:
    tracks = [
        TrackInfo(
            title="Included",
            location=":iPod_Control:Music:F00:INCL.mp3",
            track_id=10,
            db_track_id=100,
        ),
        TrackInfo(
            title="Rule Match If Evaluated",
            location=":iPod_Control:Music:F00:RULE.mp3",
            track_id=20,
            db_track_id=200,
        ),
    ]

    (
        _master_name,
        _master_id,
        _playlists,
        _podcast_master,
        _podcast_master_id,
        _podcast_playlists,
        smart_playlists,
    ) = build_and_evaluate_playlists(
        [
            {"track_id": 10, "db_track_id": 100, "Title": "Included"},
            {"track_id": 20, "db_track_id": 200, "Title": "Rule Match If Evaluated"},
        ],
        [{"playlist_id": 1, "Title": "iPod", "master_flag": 1}],
        [],
        [
            {
                "playlist_id": 3,
                "Title": "Music",
                "_source": "category",
                "master_flag": 1,
                "mhsd5_type": 4,
                "items": [
                    {
                        "track_id": 10,
                        "podcast_group_flag": 0,
                        "group_id": 55,
                        "group_id_ref": 0,
                        "track_persistent_id": 100,
                        "mhip_persistent_id": 999,
                    }
                ],
                "smart_playlist_data": {
                    "live_update": True,
                    "check_rules": True,
                    "check_limits": False,
                },
                "smart_playlist_rules": {"conjunction": "AND", "rules": []},
            }
        ],
        tracks,
    )

    assert smart_playlists[0].track_ids == [100]
    assert smart_playlists[0].item_metadata is not None
    assert smart_playlists[0].item_metadata[0].group_id == 55
    assert smart_playlists[0].item_metadata[0].mhip_persistent_id == 999


def test_mhsd5_ringtones_and_rentals_special_flag_matches_libgpod() -> None:
    data = write_mhyp("Rentals", [], playlist_id=7, master=True, mhsd5_type=7)

    assert struct.unpack_from("<H", data, 0x50)[0] == 7
    assert struct.unpack_from("<H", data, 0x52)[0] == 7
    assert struct.unpack_from("<I", data, 0x54)[0] == 1


def test_dataset5_marker_in_dataset2_bucket_is_preserved_without_repair() -> None:
    track = TrackInfo(
        title="Movie",
        location=":iPod_Control:Music:F00:MOVI.m4v",
        track_id=10,
        db_track_id=100,
    )

    _master, _master_id, playlists, _podcast_master, _podcast_master_id, _podcast_playlists, _smart = (
        build_and_evaluate_playlists(
            [{"track_id": 10, "db_track_id": 100, "Title": "Movie"}],
            [
                {"playlist_id": 1, "Title": "iPod", "master_flag": 1},
                {
                    "playlist_id": 7,
                    "Title": "Rentals",
                    "_source": "category",
                    "mhsd5_type": 7,
                    "smart_playlist_data": {
                        "live_update": True,
                        "check_rules": True,
                        "check_limits": False,
                    },
                    "smart_playlist_rules": {"conjunction": "AND", "rules": []},
                },
            ],
            [],
            [],
            [track],
        )
    )

    assert len(playlists) == 1
    assert playlists[0].name == "Rentals"
    assert playlists[0].mhsd5_type == 7
