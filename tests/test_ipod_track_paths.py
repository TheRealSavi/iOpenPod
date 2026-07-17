from pathlib import Path

import pytest

from iopenpod.device.path_safety import UnsafeDevicePathError
from iopenpod.sync.ipod_track_paths import (
    existing_ipod_track_file_path,
    expected_ipod_track_file_path,
    ipod_location_from_file_path,
)


def test_expected_path_resolves_missing_colon_location(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"

    assert expected_ipod_track_file_path(
        ipod_root,
        ":iPod_Control:Music:F00:GONE.mp3",
    ) == ipod_root / "iPod_Control" / "Music" / "F00" / "GONE.mp3"


def test_expected_path_resolves_missing_windows_device_location(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"

    assert expected_ipod_track_file_path(
        ipod_root,
        r"X:\iPod_Control\Music\F01\GONE.m4a",
    ) == ipod_root / "iPod_Control" / "Music" / "F01" / "GONE.m4a"


def test_expected_path_skips_external_windows_location_without_ipod_marker(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"

    assert expected_ipod_track_file_path(
        ipod_root,
        r"C:\Users\Someone\Music\Song.mp3",
    ) is None


def test_expected_path_rejects_parent_traversal(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"

    assert expected_ipod_track_file_path(
        ipod_root,
        ":iPod_Control:Music:F00:..:..:outside.mp3",
    ) is None


def test_expected_path_rejects_existing_absolute_host_file(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    outside = tmp_path / "Song.mp3"
    outside.write_bytes(b"audio")

    assert expected_ipod_track_file_path(ipod_root, outside) is None


def test_expected_path_rejects_nul_in_location(tmp_path: Path) -> None:
    assert expected_ipod_track_file_path(
        tmp_path / "ipod",
        ":iPod_Control:Music:F00:Song.mp3\x00../../outside.mp3",
    ) is None


def test_expected_path_rejects_music_symlink_escape(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    music_root = ipod_root / "iPod_Control" / "Music"
    outside = tmp_path / "outside"
    music_root.mkdir(parents=True)
    outside.mkdir()
    try:
        (music_root / "F00").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        import pytest

        pytest.skip(f"directory symlinks are unavailable: {exc}")

    assert expected_ipod_track_file_path(
        ipod_root,
        ":iPod_Control:Music:F00:Song.mp3",
    ) is None


def test_existing_path_resolves_common_location_forms(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    track_path = ipod_root / "iPod_Control" / "Music" / "F00" / "Song.mp3"
    track_path.parent.mkdir(parents=True)
    track_path.write_bytes(b"audio")

    assert existing_ipod_track_file_path(
        ipod_root,
        {"Location": ":iPod_Control:Music:F00:Song.mp3"},
    ) == track_path
    assert existing_ipod_track_file_path(
        ipod_root,
        {"Location": r"E:\iPod_Control\Music\F00\Song.mp3"},
    ) == track_path
    assert existing_ipod_track_file_path(
        ipod_root,
        {"Location": str(track_path)},
    ) == track_path


def test_existing_path_resolves_file_uri_with_ipod_marker(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    track_path = ipod_root / "iPod_Control" / "Music" / "F00" / "Song.mp3"
    track_path.parent.mkdir(parents=True)
    track_path.write_bytes(b"audio")

    uri = f"file:///Volumes/IPOD/iPod_Control/Music/F00/{track_path.name}"

    assert existing_ipod_track_file_path(ipod_root, uri) == track_path


def test_existing_path_can_fallback_to_music_filename(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    track_path = ipod_root / "iPod_Control" / "Music" / "F37" / "REALNAME.m4a"
    track_path.parent.mkdir(parents=True)
    track_path.write_bytes(b"audio")

    assert existing_ipod_track_file_path(
        ipod_root,
        {"Location": ":iPod_Control:Music:F00:REALNAME.mp3"},
        allow_music_filename_fallback=True,
    ) == track_path


def test_ipod_location_from_file_path_formats_colon_location(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    track_path = ipod_root / "iPod_Control" / "Music" / "F00" / "Song.mp3"

    assert (
        ipod_location_from_file_path(ipod_root, track_path)
        == ":iPod_Control:Music:F00:Song.mp3"
    )


def test_ipod_location_from_file_path_rejects_path_outside_music(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    outside = tmp_path / "host-song.mp3"

    with pytest.raises(UnsafeDevicePathError, match="outside the iPod music"):
        ipod_location_from_file_path(ipod_root, outside)
