"""Real filesystem tests of exact-file updater operations and ownership."""

import ctypes
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from storage.host_installation import (
    file_identity,
    move_owned_file,
    private_directory,
    remove_owned_file,
)
from storage.platform import host_install_windows


def test_private_directory_retries_collisions_and_preserves_native_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    advapi = Mock()
    kernel = Mock()
    kernel.CreateDirectoryW.return_value = 0
    loader = Mock(return_value=advapi)
    error = OSError(5, "Access is denied")
    win_error = Mock(return_value=error)
    last_error = Mock(side_effect=[183, 5])  # Already exists, then access denied.
    monkeypatch.setattr(ctypes, "WinDLL", loader, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", last_error, raising=False)
    monkeypatch.setattr(ctypes, "WinError", win_error, raising=False)
    monkeypatch.setattr(
        host_install_windows, "installation_kernel", Mock(return_value=kernel)
    )

    with pytest.raises(OSError) as raised:
        host_install_windows.create_private_directory(tmp_path, ".test-update-")
    assert raised.value is error
    loader.assert_called_once_with("advapi32", use_last_error=True)
    assert kernel.CreateDirectoryW.call_count == 2
    assert last_error.call_count == 2
    win_error.assert_called_once_with(5)
    kernel.LocalFree.assert_called_once()


def test_private_staging_is_new_and_does_not_claim_adjacent_files(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "family photographs.txt"
    sentinel.write_bytes(b"precious")
    first = private_directory(tmp_path, ".test-update-")
    second = private_directory(tmp_path, ".test-update-")
    assert first != second
    (first / "record").write_bytes(b"owned")
    identity = file_identity(first / "record")
    remove_owned_file(first / "record", identity)
    assert not (first / "record").exists()
    assert sentinel.read_bytes() == b"precious"


def test_cleanup_rejects_changed_content_and_hardlinks(tmp_path: Path) -> None:
    owned = tmp_path / "owned"
    owned.write_bytes(b"old")
    identity = file_identity(owned)
    owned.write_bytes(b"new")
    with pytest.raises(ValueError):
        remove_owned_file(owned, identity)
    os.link(owned, tmp_path / "alias")
    with pytest.raises(ValueError):
        file_identity(owned)
    assert owned.read_bytes() == b"new"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native rename")
def test_native_rename_preserves_sentinels_and_refuses_existing_destinations(
    tmp_path: Path,
) -> None:
    old = tmp_path / "renamed app !%.exe"
    old.write_bytes(b"old application")
    new = tmp_path / "incoming.exe"
    new.write_bytes(b"new application")
    backup = tmp_path / "previous.exe"
    sentinel = tmp_path / "photos.txt"
    sentinel.write_bytes(b"user")
    old_id, new_id = file_identity(old), file_identity(new)
    with pytest.raises(OSError):
        move_owned_file(new, old, new_id)
    assert old.read_bytes() == b"old application"
    move_owned_file(old, backup, old_id)
    move_owned_file(new, old, new_id)
    assert old.read_bytes() == b"new application"
    assert backup.read_bytes() == b"old application"
    assert sentinel.read_bytes() == b"user"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native rename")
def test_native_rename_rejects_target_replaced_after_analysis(tmp_path: Path) -> None:
    old = tmp_path / "app.exe"
    old.write_bytes(b"original")
    identity = file_identity(old)
    old.unlink()
    old.write_bytes(b"user replaced this")
    with pytest.raises(ValueError):
        move_owned_file(old, tmp_path / "backup.exe", identity)
    assert old.read_bytes() == b"user replaced this"
