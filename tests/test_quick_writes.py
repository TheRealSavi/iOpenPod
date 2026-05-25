from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from iTunesDB_Writer.mhit_writer import TrackInfo
from SyncEngine import quick_writes
from SyncEngine._playlist_builder import build_and_evaluate_playlists


@dataclass
class FakePlaylistInfo:
    playlist_id: int
    track_ids: list[int]


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
        return ("iPod", [FakePlaylistInfo(1, [100]), FakePlaylistInfo(2, [100])], [])

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
    assert captured["evaluate"]["playlists_raw"] == playlists_data
    assert captured["evaluate"]["smart_raw"] == []
    assert captured["write"]["master_playlist_name"] == "iPod"


def test_write_cached_itunesdb_uses_master_name_from_cache(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    all_tracks = [SimpleNamespace(artist="", album="", album_artist="")]

    monkeypatch.setattr(quick_writes, "_tracks_to_infos", lambda *_args, **_kwargs: all_tracks)

    def fake_evaluate(**kwargs):
        captured["evaluate"] = kwargs
        return ("Renamed iPod", [FakePlaylistInfo(1, [100])], [])

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


def test_write_cached_itunesdb_splits_smart_playlists(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    all_tracks = [SimpleNamespace(artist="", album="", album_artist="")]

    monkeypatch.setattr(quick_writes, "_tracks_to_infos", lambda *_args, **_kwargs: all_tracks)

    def fake_evaluate(**kwargs):
        captured.update(kwargs)
        return ("iPod", [FakePlaylistInfo(1, [100])], [FakePlaylistInfo(2, [100])])

    monkeypatch.setattr(quick_writes, "_evaluate_tracks_and_playlists", fake_evaluate)
    monkeypatch.setattr(quick_writes, "_write_evaluated_database", lambda *args, **kwargs: True)

    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[{"track_id": 10, "db_track_id": 100}],
        playlists_data=[
            {"playlist_id": 1, "Title": "Regular", "_source": "regular"},
            {"playlist_id": 2, "Title": "Smart", "_source": "smart"},
        ],
    )

    assert result.success
    assert captured["playlists_raw"] == [
        {"playlist_id": 1, "Title": "Regular", "_source": "regular"}
    ]
    assert captured["smart_raw"] == [
        {"playlist_id": 2, "Title": "Smart", "_source": "smart"}
    ]


def test_write_cached_itunesdb_reports_missing_tracks() -> None:
    result = quick_writes.write_cached_itunesdb(
        "I:/",
        tracks_data=[],
        playlists_data=[],
    )

    assert not result.success
    assert result.error == "No cached tracks available to write."


def test_write_cached_itunesdb_passes_artwork_sources(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    all_tracks = [SimpleNamespace(artist="", album="", album_artist="")]

    monkeypatch.setattr(quick_writes, "_tracks_to_infos", lambda *_args, **_kwargs: all_tracks)
    monkeypatch.setattr(
        quick_writes,
        "_evaluate_tracks_and_playlists",
        lambda **_kwargs: ("iPod", [FakePlaylistInfo(1, [100])], []),
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
        lambda **_kwargs: ("iPod", [FakePlaylistInfo(1, [100])], []),
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

    _master_name, playlists, _smart_playlists = build_and_evaluate_playlists(
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
        [track],
        [],
    )

    imported = next(playlist for playlist in playlists if playlist.playlist_id == 2)
    assert imported.track_ids == [100]
