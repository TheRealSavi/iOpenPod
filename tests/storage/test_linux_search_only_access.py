"""Native Linux permission tests for pinned access through search-only ancestors."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, cast

import pytest

from storage import DevicePath, HostPath, Storage
from storage.host_directory import LocalHostDirectory
from storage.host_input import LocalHostFile
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Linux permission semantics"
)


@pytest.fixture
def search_only(tmp_path: Path) -> Generator[Path]:
    if cast("Callable[[], int]", vars(os)["geteuid"])() == 0:
        pytest.skip("Permission checks require an unprivileged process")
    ancestor = tmp_path / "search-only"
    directory = ancestor / "readable"
    directory.mkdir(parents=True)
    (directory / "known.bin").write_bytes(b"approved bytes")
    ancestor.chmod(0o100)
    try:
        # Establish that this filesystem enforces search without directory read.
        with pytest.raises(PermissionError):
            list(ancestor.iterdir())
        assert (directory / "known.bin").read_bytes() == b"approved bytes"
        yield directory
    finally:
        ancestor.chmod(0o700)


def test_known_host_file_below_search_only_ancestor_is_readable(
    search_only: Path,
) -> None:
    observed = LocalHostFile.observe(HostPath(search_only / "known.bin"))
    with observed.open_read() as stream:
        assert stream.read() == b"approved bytes"
        assert stream.seek(0) == 0
        assert stream.read(8) == b"approved"


@pytest.mark.parametrize("operation", ["read", "fingerprint"])
def test_device_reads_below_search_only_mount_ancestor(
    search_only: Path, tmp_path: Path, operation: str
) -> None:
    platform = VirtualStoragePlatform()
    platform.add_volume(search_only)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    with storage.open_session(storage.discover().volumes[0]) as session:
        if operation == "read":
            assert session.read(DevicePath("known.bin")) == b"approved bytes"
        else:
            assert session.fingerprint(DevicePath("known.bin")).size == 14


def test_readable_directory_below_search_only_ancestor_can_be_listed(
    search_only: Path,
) -> None:
    observed = LocalHostDirectory.observe(HostPath(search_only))
    entries = observed.list_entries(checkpoint=lambda: None)
    assert [entry.path.path.name for entry in entries] == ["known.bin"]
