from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from iopenpod.device import create_virtual_ipod
from iopenpod.device.filesystem_profile import FilesystemProfile
from iopenpod.device.write_guard import DeviceWriteGuard, DeviceWriteSafetyError
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.sync import _db_io


def test_write_database_raises_original_writer_error_when_requested(
    monkeypatch,
    tmp_path,
) -> None:
    from iopenpod import itunesdb_writer

    class WriterError(RuntimeError):
        pass

    def fake_write_itunesdb(*_args, **_kwargs):
        raise WriterError("Artwork image exceeds Pillow safety limit. Offending image: /music/Album/cover.tif")

    monkeypatch.setattr(itunesdb_writer, "write_itunesdb", fake_write_itunesdb)

    with pytest.raises(WriterError, match="Offending image: /music/Album/cover.tif"):
        _db_io.write_database(tmp_path, [], raise_on_error=True)


def test_write_database_rejects_track_whose_committed_media_file_is_missing(
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MA005")
    track = TrackInfo(
        title="Missing",
        location=":iPod_Control:Music:F00:MISSING.mp3",
    )

    assert _db_io.write_database(tmp_path, [track]) is False


def test_write_database_rejects_duplicate_committed_media_locations(
    tmp_path: Path,
) -> None:
    create_virtual_ipod(tmp_path, "MA005")
    media_path = tmp_path / "iPod_Control" / "Music" / "F00" / "SONG.mp3"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"audio")
    location = ":iPod_Control:Music:F00:SONG.mp3"

    assert _db_io.write_database(
        tmp_path,
        [
            TrackInfo(title="First", location=location),
            TrackInfo(title="Duplicate", location=location),
        ],
    ) is False


def test_verify_written_database_requires_a_committed_database(
    tmp_path: Path,
) -> None:
    with pytest.raises(_db_io.DatabaseVerificationError, match="could not be reparsed"):
        _db_io.verify_written_database(tmp_path, expected_track_count=0)


def test_verify_written_database_rejects_media_outside_ipod(
    monkeypatch,
    tmp_path: Path,
) -> None:
    outside_media = tmp_path.parent / "outside.mp3"
    outside_media.write_bytes(b"audio")
    monkeypatch.setattr(
        _db_io,
        "read_existing_database",
        lambda *_args, **_kwargs: {
            "tracks": [{"Title": "Escape", "Location": str(outside_media)}],
        },
    )

    with pytest.raises(_db_io.DatabaseVerificationError, match="outside the iPod"):
        _db_io.verify_written_database(tmp_path, expected_track_count=1)


def test_database_media_path_keys_preserve_case_on_hfsx() -> None:
    upper = _db_io._database_media_path_key(
        Path("/iPod_Control/Music/Song.mp3"),
        case_sensitive=True,
    )
    lower = _db_io._database_media_path_key(
        Path("/iPod_Control/Music/song.mp3"),
        case_sensitive=True,
    )

    assert upper != lower
    assert _db_io._database_media_path_key(
        Path("/iPod_Control/Music/Song.mp3"),
        case_sensitive=False,
    ) == _db_io._database_media_path_key(
        Path("/iPod_Control/Music/song.mp3"),
        case_sensitive=False,
    )


def test_playcount_commit_checks_write_readiness_before_reading_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from iopenpod.itunesdb_parser import playcounts

    reads: list[Path] = []
    monkeypatch.setattr(
        playcounts,
        "parse_playcounts",
        lambda _path: [SimpleNamespace(has_data=True)],
    )
    monkeypatch.setattr(
        _db_io,
        "inspect_device_write_readiness",
        lambda _path: (_ for _ in ()).throw(
            DeviceWriteSafetyError("volume identity unavailable")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        _db_io,
        "read_existing_database",
        lambda path: reads.append(path) or {},
    )

    with pytest.raises(DeviceWriteSafetyError, match="identity unavailable"):
        _db_io.commit_playcounts_if_needed(tmp_path)

    assert reads == []


def test_playcount_cleanup_removes_only_contained_known_state_files(
    tmp_path: Path,
) -> None:
    itunes_dir = tmp_path / "iPod_Control" / "iTunes"
    itunes_dir.mkdir(parents=True)
    cleanup_names = (
        "Play Counts",
        "iTunesStats",
        "PlayCounts.plist",
        "OTGPlaylistInfo",
    )
    for name in cleanup_names:
        (itunes_dir / name).write_bytes(b"state")
    numbered_otg = itunes_dir / "OTGPlaylistInfo_1"
    numbered_otg.write_bytes(b"firmware-owned")

    revalidations: list[str] = []
    _db_io.delete_playcounts_files(
        tmp_path,
        before_device_mutation=lambda: revalidations.append("checked"),
    )

    assert all(not (itunes_dir / name).exists() for name in cleanup_names)
    assert numbered_otg.read_bytes() == b"firmware-owned"
    assert revalidations == ["checked"] * len(cleanup_names)


@pytest.mark.parametrize("filename", ["Play Counts", "OTGPlaylistInfo"])
def test_playcount_cleanup_failure_is_a_device_safety_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    filename: str,
) -> None:
    itunes_dir = tmp_path / "iPod_Control" / "iTunes"
    itunes_dir.mkdir(parents=True)
    state_file = itunes_dir / filename
    state_file.write_bytes(b"state")
    original_unlink = _db_io.durable_unlink

    def fail_selected_file(path: Path, *, missing_ok: bool = False) -> None:
        if path.name == filename:
            raise OSError("device rejected cleanup")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(_db_io, "durable_unlink", fail_selected_file)

    with pytest.raises(
        DeviceWriteSafetyError,
        match=rf"could not be cleared \({filename}\): device rejected cleanup",
    ):
        _db_io.delete_playcounts_files(tmp_path)

    assert state_file.read_bytes() == b"state"


def test_guarded_playcount_commit_does_not_hide_cleanup_safety_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from iopenpod.sync import _playlist_builder, _track_conversion, database_commit

    monkeypatch.setattr(
        _db_io,
        "read_existing_database",
        lambda _path: {"tracks": [{}]},
    )
    monkeypatch.setattr(
        _track_conversion,
        "track_dict_to_info",
        lambda _track: SimpleNamespace(),
    )
    monkeypatch.setattr(
        _playlist_builder,
        "build_and_evaluate_playlists",
        lambda *_args: ("iPod", 1, [], "Podcasts", 2, [], []),
    )
    monkeypatch.setattr(
        database_commit,
        "write_database_commit",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        _db_io,
        "delete_playcounts_files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DeviceWriteSafetyError("cleanup not durable")
        ),
    )

    with pytest.raises(DeviceWriteSafetyError, match="cleanup not durable"):
        _db_io._commit_playcounts_guarded(
            tmp_path,
            filesystem_profile=cast(FilesystemProfile, SimpleNamespace()),
            write_guard=cast(DeviceWriteGuard, SimpleNamespace()),
        )
