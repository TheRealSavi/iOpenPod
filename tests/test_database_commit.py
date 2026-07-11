from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from iTunesDB_Writer.mhit_writer import TrackInfo
from iTunesDB_Writer.mhyp_writer import PlaylistInfo
from SyncEngine import _db_io, database_commit, itunes_prefs
from SyncEngine.database_commit import (
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
    assert calls[1] == (
        "protect",
        (tmp_path, [track], {"include_photo_totals": False, "photo_db": None}),
    )


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


def test_apply_itunes_protections_can_include_photo_totals(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    photo_db = SimpleNamespace(photos={1: object(), 2: object()}, file_sizes={1: 10, 2: 20})

    monkeypatch.setattr(
        database_commit,
        "_current_device_supports",
        lambda: (True, False),
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
