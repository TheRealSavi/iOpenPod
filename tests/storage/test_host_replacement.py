"""Host edits stage before replacement and reject changed reviewed files."""

from pathlib import Path
from typing import BinaryIO

import pytest

from storage import HostPath
from storage.errors import ConcurrentModificationError
from storage.host_input import LocalHostFile
from storage.host_replacement import replace_host_file


def test_staged_edit_and_failure_preserve_original(tmp_path: Path) -> None:
    path = tmp_path / "track"
    path.write_bytes(b"original")
    observed = LocalHostFile.observe(HostPath(path))

    def fail(staged: BinaryIO) -> None:
        staged.write(b"partial")
        raise ValueError("verification failed")

    with pytest.raises(ValueError, match="verification failed"):
        replace_host_file(observed, fail)
    assert path.read_bytes() == b"original"
    replaced = replace_host_file(observed, lambda staged: staged.write(b"verified"))
    assert path.read_bytes() == b"verified"
    assert replaced == LocalHostFile.observe(HostPath(path))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["track"]


def test_changed_source_is_never_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "track"
    path.write_bytes(b"original")
    observed = LocalHostFile.observe(HostPath(path))

    def race(staged: BinaryIO) -> None:
        staged.write(b"verified")
        path.write_bytes(b"external edit")

    with pytest.raises(ConcurrentModificationError):
        replace_host_file(observed, race)
    assert path.read_bytes() == b"external edit"


def test_link_swap_cannot_redirect_replacement(tmp_path: Path) -> None:
    from storage.errors import UnsafeFilesystemPathError

    path = tmp_path / "track"
    target = tmp_path / "unrelated"
    path.write_bytes(b"original")
    target.write_bytes(b"untouched")
    observation = LocalHostFile.observe(HostPath(path))

    def swap(staged: BinaryIO) -> None:
        staged.write(b"updated")
        path.unlink()
        path.symlink_to(target)

    with pytest.raises(UnsafeFilesystemPathError):
        replace_host_file(observation, swap)
    assert target.read_bytes() == b"untouched"
    assert path.is_symlink()
