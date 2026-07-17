from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo
from iopenpod.sync import _db_io, database_commit, itunes_prefs
from iopenpod.sync.database_commit import (
    DatabaseCommitPayload,
    apply_itunes_protections_from_tracks,
    write_database_commit,
)


def _track(*, media_type: int = 0, size: int = 1234, length: int = 3000) -> TrackInfo:
    track = TrackInfo(title="Song", location=":iPod_Control:Music:F00:ABCD.mp3")
    track.media_type = media_type
    track.size = size
    track.length = length
    return track


@pytest.fixture(autouse=True)
def _safe_device_profile(monkeypatch):
    profile = SimpleNamespace(case_sensitive=False)
    monkeypatch.setattr(
        database_commit,
        "inspect_device_write_readiness",
        lambda _path: profile,
    )
    monkeypatch.setattr(
        database_commit,
        "revalidate_device_write_readiness",
        lambda retained, **_kwargs: retained,
    )
    monkeypatch.setattr(database_commit, "volume_lock_key", lambda _profile: "test-volume")
    return profile


def test_write_database_commit_writes_payload_and_protects_after_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, Any]] = []
    track = _track()
    playlist = PlaylistInfo(name="RoadPod", playlist_id=1)

    def fake_write_database(ipod_path, tracks, **kwargs):
        calls.append(("write", (ipod_path, tracks, kwargs)))
        return True

    def fake_protect(ipod_path, tracks, **kwargs):
        calls.append(("protect", (ipod_path, tracks, kwargs)))

    monkeypatch.setattr(_db_io, "write_database", fake_write_database)
    monkeypatch.setattr(
        database_commit,
        "apply_itunes_protections_from_tracks",
        fake_protect,
    )
    monkeypatch.setattr(
        database_commit,
        "flush_filesystem",
        lambda path: (calls.append(("flush", path)) or True, "flushed"),
        raising=False,
    )

    result = write_database_commit(
        tmp_path,
        DatabaseCommitPayload(
            all_tracks=[track],
            pc_file_paths={10: "C:/Music/Song.mp3"},
            playlists=[playlist],
            master_playlist_name="RoadPod",
            master_playlist_id=10,
        ),
        progress_callback=lambda _message: None,
        raise_on_error=True,
        protect_itunes=True,
    )

    assert result is True
    assert calls[0][0] == "write"
    assert calls[0][1][0] == tmp_path
    assert calls[0][1][1] == [track]
    assert calls[0][1][2]["pc_file_paths"] == {10: "C:/Music/Song.mp3"}
    assert calls[0][1][2]["playlists"] == [playlist]
    assert calls[0][1][2]["master_playlist_name"] == "RoadPod"
    assert calls[0][1][2]["master_playlist_id"] == 10
    assert calls[0][1][2]["progress_callback"] is not None
    assert calls[0][1][2]["raise_on_error"] is True
    assert calls[1][0] == "protect"
    assert calls[1][1][0] == tmp_path
    assert calls[1][1][1] == [track]
    assert calls[1][1][2]["include_photo_totals"] is False
    assert calls[1][1][2]["photo_db"] is None
    assert callable(calls[1][1][2]["before_device_mutation"])
    assert calls[2] == ("flush", tmp_path)


def test_write_database_commit_skips_protection_when_write_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    protected: list[bool] = []

    monkeypatch.setattr(_db_io, "write_database", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        database_commit,
        "apply_itunes_protections_from_tracks",
        lambda *_args, **_kwargs: protected.append(True),
    )

    result = write_database_commit(
        tmp_path,
        DatabaseCommitPayload(all_tracks=[_track()]),
        protect_itunes=True,
    )

    assert result is False
    assert protected == []


def test_write_database_commit_fails_when_durability_barrier_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(_db_io, "write_database", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        database_commit,
        "flush_filesystem",
        lambda _path: (False, "FlushFileBuffers failed"),
        raising=False,
    )

    result = write_database_commit(
        tmp_path,
        DatabaseCommitPayload(all_tracks=[_track()]),
    )

    assert result is False


def test_write_database_commit_can_defer_flush_to_sync_session(
    monkeypatch,
    tmp_path: Path,
) -> None:
    flushes: list[Path] = []
    monkeypatch.setattr(_db_io, "write_database", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        database_commit,
        "flush_filesystem",
        lambda path: (flushes.append(Path(path)) or True, "flushed"),
        raising=False,
    )

    result = write_database_commit(
        tmp_path,
        DatabaseCommitPayload(all_tracks=[_track()]),
        flush_after_write=False,
    )

    assert result is True
    assert flushes == []


def test_write_database_commit_checks_and_refreshes_supplied_writer_generation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    guard = SimpleNamespace(
        assert_database_unchanged=lambda: events.append("generation-check"),
        refresh_database_generation=lambda: events.append("generation-refresh"),
    )
    def fake_write_database(*_args, **kwargs) -> bool:
        events.append("write-start")
        kwargs["before_database_replace"]()
        events.append("write-replace")
        return True

    monkeypatch.setattr(_db_io, "write_database", fake_write_database)
    monkeypatch.setattr(
        database_commit,
        "flush_filesystem",
        lambda _path: (events.append("flush") or True, "flushed"),
    )

    result = write_database_commit(
        tmp_path,
        DatabaseCommitPayload(all_tracks=[_track()]),
        write_guard=guard,
    )

    assert result is True
    assert events == [
        "generation-check",
        "write-start",
        "generation-check",
        "write-replace",
        "generation-refresh",
        "flush",
    ]


def test_apply_itunes_protections_can_include_photo_totals(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    photo_db = SimpleNamespace(photos={1: object(), 2: object()}, file_sizes={1: 10, 2: 20})

    monkeypatch.setattr(
        database_commit,
        "_current_device_supports",
        lambda _ipod_path: (True, False),
    )
    monkeypatch.setattr(
        itunes_prefs,
        "protect_from_itunes",
        lambda ipod_path, **kwargs: captured.update({"ipod_path": ipod_path, **kwargs}),
    )

    apply_itunes_protections_from_tracks(
        tmp_path,
        [_track(size=100, length=2000)],
        photo_db=photo_db,
        include_photo_totals=True,
    )

    assert captured["ipod_path"] == tmp_path
    assert captured["track_count"] == 1
    assert captured["total_music_bytes"] == 100
    assert captured["total_music_seconds"] == 2
    assert captured["total_photos"] == 2
    assert captured["total_photo_bytes"] == 30
    assert captured["supports_photos"] is True
    assert captured["supports_videos"] is False
