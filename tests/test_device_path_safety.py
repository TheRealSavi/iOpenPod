import os
import subprocess
from pathlib import Path

import pytest

from iopenpod.device.path_safety import UnsafeDevicePathError, resolve_device_path


def _create_directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
        return
    except OSError as symlink_error:
        if os.name != "nt":
            pytest.skip(f"directory symlinks are unavailable: {symlink_error}")

    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"directory links are unavailable: {completed.stderr.strip()}")


def test_device_path_resolves_relative_path_inside_allowed_subtree(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"

    resolved = resolve_device_path(
        ipod_root,
        "iPod_Control/Music/F00/Song.mp3",
        allowed_subtree="iPod_Control/Music",
    )

    assert resolved == ipod_root / "iPod_Control" / "Music" / "F00" / "Song.mp3"


@pytest.mark.parametrize(
    "untrusted_path",
    [
        "/etc/passwd",
        r"C:\Users\Someone\Music\Song.mp3",
        r"C:Music\Song.mp3",
        r"\\server\share\Song.mp3",
        "iPod_Control/Music/../../outside.mp3",
        "iPod_Control/Music/Song.mp3\x00.jpg",
    ],
)
def test_device_path_rejects_non_relative_or_traversing_paths(
    tmp_path: Path,
    untrusted_path: str,
) -> None:
    with pytest.raises(UnsafeDevicePathError):
        resolve_device_path(
            tmp_path / "ipod",
            untrusted_path,
            allowed_subtree="iPod_Control/Music",
        )


def test_device_path_rejects_path_outside_allowed_subtree(tmp_path: Path) -> None:
    with pytest.raises(UnsafeDevicePathError):
        resolve_device_path(
            tmp_path / "ipod",
            "Photos/Full Resolution/photo.jpg",
            allowed_subtree="iPod_Control/Music",
        )


def test_device_path_rejects_symlink_escape(tmp_path: Path) -> None:
    ipod_root = tmp_path / "ipod"
    music_root = ipod_root / "iPod_Control" / "Music"
    outside = tmp_path / "outside"
    music_root.mkdir(parents=True)
    outside.mkdir()
    _create_directory_link(music_root / "F00", outside)

    with pytest.raises(UnsafeDevicePathError):
        resolve_device_path(
            ipod_root,
            "iPod_Control/Music/F00/Song.mp3",
            allowed_subtree="iPod_Control/Music",
        )


def test_device_path_rejects_directory_link_within_allowed_subtree(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    music_root = ipod_root / "iPod_Control" / "Music"
    target = music_root / "F01"
    target.mkdir(parents=True)
    _create_directory_link(music_root / "F00", target)

    with pytest.raises(UnsafeDevicePathError, match="link|reparse"):
        resolve_device_path(
            ipod_root,
            "iPod_Control/Music/F00/Song.mp3",
            allowed_subtree="iPod_Control/Music",
        )


def test_device_path_rejects_final_file_symlink_within_allowed_subtree(
    tmp_path: Path,
) -> None:
    ipod_root = tmp_path / "ipod"
    music_root = ipod_root / "iPod_Control" / "Music" / "F00"
    music_root.mkdir(parents=True)
    target = music_root / "Live.mp3"
    target.write_bytes(b"live")
    link = music_root / "Stale.mp3"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    with pytest.raises(UnsafeDevicePathError, match="link|reparse"):
        resolve_device_path(
            ipod_root,
            "iPod_Control/Music/F00/Stale.mp3",
            allowed_subtree="iPod_Control/Music",
        )
