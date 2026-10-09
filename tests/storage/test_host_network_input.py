"""Network media uses the same observed, read-only Host input boundary."""

import ctypes
import os
import stat
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from storage import ConcurrentModificationError, HostPath, UnsafeFilesystemPathError
from storage.host_directory import (
    LocalHostDirectory,
    pin_host_directory,
    resolve_host_entry,
)
from storage.host_input import (
    LocalHostFile,
    resolve_host_selection,
    resolve_local_file_reference,
    validate_host_path_spelling,
)
from storage.host_installation import require_plain_path

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows network paths")


@pytest.fixture
def remote_drive(monkeypatch: pytest.MonkeyPatch) -> Mock:
    if sys.platform != "win32":
        pytest.skip("Windows drive classification")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    drive_type = Mock(return_value=4)  # DRIVE_REMOTE
    monkeypatch.setattr(kernel, "GetDriveTypeW", drive_type)

    def load_kernel(*args: object, **kwargs: object) -> ctypes.CDLL:
        return kernel

    monkeypatch.setattr(ctypes, "WinDLL", load_kernel)
    return drive_type


def test_mapped_network_selection_can_enumerate_and_read_media(
    tmp_path: Path, remote_drive: Mock
) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")
    selected = resolve_host_selection(HostPath(tmp_path))
    entries = LocalHostDirectory.observe(selected).list_entries(checkpoint=lambda: None)
    assert len(entries) == 1 and entries[0].path == HostPath(source)
    observed = entries[0].file
    assert observed is not None
    assert observed.read_bytes(max_bytes=5, checkpoint=lambda: None) == b"audio"
    with observed.capture(checkpoint=lambda: None) as captured:
        assert Path(captured).read_bytes() == b"audio"


def test_unc_selection_reaches_regular_file_observation(
    tmp_path: Path, remote_drive: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")
    root = Path(r"\\nas\music")
    selected = root / source.name
    native_lstat = Path.lstat

    def lstat(path: Path) -> os.stat_result:
        return native_lstat(tmp_path / path.relative_to(root))

    monkeypatch.setattr(Path, "lstat", lstat)
    entry = resolve_host_entry(HostPath(selected))
    assert entry.path == HostPath(selected)
    assert entry.file == LocalHostFile.observe(HostPath(selected))
    assert LocalHostDirectory.observe(HostPath(root)).path == HostPath(root)


@pytest.mark.parametrize(
    "reference",
    [
        "Artist/Song #1.mp3",
        r"\\nas\music\Artist\Song #1.mp3",
        "//nas/music/Artist/Song #1.mp3",
        "file://nas/music/Artist/Song%20%231.mp3",
        "file:////nas/music/Artist/Song%20%231.mp3",
        "file://localhost/%2fnas/music/Artist/Song%20%231.mp3",
    ],
)
def test_network_playlist_paths_resolve_without_filesystem_access(
    reference: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Resolving a Playlist reference must not access its target")

    monkeypatch.setattr(Path, "stat", unexpected)
    monkeypatch.setattr(Path, "lstat", unexpected)
    assert resolve_local_file_reference(
        reference, HostPath(r"\\nas\music\Mix.m3u")
    ) == HostPath(r"\\nas\music\Artist\Song #1.mp3")


@pytest.mark.parametrize(
    "spelling",
    [
        "//?/UNC/nas/music/song.mp3",
        "//./pipe/song.mp3",
        "/??/UNC/nas/music/song.mp3",
        "//??/UNC/nas/music/song.mp3",
        "//nas",
        "//nas/",
        "///nas/music/song.mp3",
        "//nas/../song.mp3",
        "//nas/./song.mp3",
        "//nas/music/song.mp3:stream",
        "//nas/music/NUL.mp3",
        "//nas/music/song.mp3.",
    ],
)
def test_network_media_still_rejects_device_and_ambiguous_paths(spelling: str) -> None:
    with pytest.raises(ValueError):
        validate_host_path_spelling(spelling, allow_network=True)


def test_native_unc_symbolic_link_target_is_canonicalized(
    tmp_path: Path, remote_drive: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")
    alias = tmp_path / "alias.mp3"
    target = Path(r"\\nas\music\song.mp3")
    native_lstat = Path.lstat

    def lstat(path: Path) -> os.stat_result:
        if path == alias:
            return os.stat_result((stat.S_IFLNK, 0, 0, 1, 0, 0, 0, 0, 0, 0))
        return native_lstat(source if path == target else path)

    def readlink(path: Path) -> Path:
        return Path(r"\\?\UNC\nas\music\song.mp3")

    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "readlink", readlink)
    assert resolve_host_selection(HostPath(alias)) == HostPath(target)


def test_network_source_replacement_and_disappearance_are_still_rejected(
    tmp_path: Path, remote_drive: Mock
) -> None:
    source = tmp_path / "song.mp3"
    source.write_bytes(b"audio")
    observed = LocalHostFile.observe(HostPath(source))
    replacement = tmp_path / "replacement.mp3"
    replacement.write_bytes(b"other")
    os.utime(replacement, ns=(observed.modified_ns, observed.modified_ns))
    replacement.replace(source)
    with pytest.raises(ConcurrentModificationError):
        observed.read_bytes(max_bytes=5, checkpoint=lambda: None)
    source.unlink()
    with pytest.raises(FileNotFoundError):
        observed.read_bytes(max_bytes=5, checkpoint=lambda: None)


@pytest.mark.parametrize("drive_type", [0, 1])
def test_unavailable_drives_remain_rejected(
    tmp_path: Path, remote_drive: Mock, drive_type: int
) -> None:
    remote_drive.return_value = drive_type
    with pytest.raises(UnsafeFilesystemPathError, match="available filesystem"):
        resolve_host_selection(HostPath(tmp_path))


def test_installation_paths_retain_local_drive_policy(
    tmp_path: Path, remote_drive: Mock
) -> None:
    with pytest.raises(ValueError):
        require_plain_path(Path(r"\\nas\music\app.exe"))
    with (
        pytest.raises(UnsafeFilesystemPathError, match="local drive"),
        pin_host_directory(tmp_path),
    ):
        pytest.fail("Installation directory pinning must not permit remote drives")
