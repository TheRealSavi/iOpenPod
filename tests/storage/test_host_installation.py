"""Real filesystem tests of exact-file updater operations and ownership."""

import os
import sys
from pathlib import Path

import pytest

from storage.host_installation import (
    file_identity,
    move_owned_file,
    private_directory,
    remove_owned_file,
)


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
