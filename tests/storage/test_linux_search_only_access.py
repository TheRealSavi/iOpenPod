"""Native Linux permission tests for pinned access through search-only ancestors."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, cast

import pytest

from storage import (
    ConcurrentModificationError,
    DevicePath,
    HostPath,
    Storage,
    UnsafeFilesystemPathError,
)
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


@pytest.mark.parametrize("denied", ["ancestor_search", "file_read", "directory_read"])
def test_search_only_access_does_not_bypass_required_permissions(
    search_only: Path, denied: str
) -> None:
    source = search_only / "known.bin"
    if denied == "directory_read":
        observed_directory = LocalHostDirectory.observe(HostPath(search_only))
        search_only.chmod(0o100)
        try:
            with pytest.raises(PermissionError):
                observed_directory.list_entries(checkpoint=lambda: None)
        finally:
            search_only.chmod(0o700)
        return
    observed_file = LocalHostFile.observe(HostPath(source))
    denied_path = search_only.parent if denied == "ancestor_search" else source
    denied_path.chmod(0)
    try:
        with pytest.raises(PermissionError):
            source.read_bytes()
        with pytest.raises(PermissionError), observed_file.open_read():
            pytest.fail("A required permission was bypassed")
    finally:
        denied_path.chmod(0o100 if denied == "ancestor_search" else 0o600)


@pytest.mark.parametrize("operation", ["file", "directory"])
@pytest.mark.parametrize("timing", ["before_pin", "after_pin"])
def test_search_only_ancestor_swap_never_redirects_access(
    search_only: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    timing: str,
) -> None:
    observed_file = LocalHostFile.observe(HostPath(search_only / "known.bin"))
    observed_directory = LocalHostDirectory.observe(HostPath(search_only))
    ancestor = search_only.parent
    moved = tmp_path / "pinned-original"
    outside = tmp_path / "outside"
    (outside / "readable").mkdir(parents=True)
    (outside / "readable/known.bin").write_bytes(b"unapproved bytes")
    (outside / "readable/private.bin").write_bytes(b"private")
    native_open = os.open
    swapped = False

    def swap() -> None:
        nonlocal swapped
        ancestor.rename(moved)
        ancestor.symlink_to(outside, target_is_directory=True)
        swapped = True

    def open_with_swap(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        trigger = os.fspath(path) == ancestor.name and not swapped
        if trigger and timing == "before_pin":
            swap()
        descriptor = native_open(path, flags, mode, dir_fd=dir_fd)
        if trigger and timing == "after_pin":
            swap()
        return descriptor

    monkeypatch.setattr(os, "open", open_with_swap)
    seen: list[str] = []
    try:
        with pytest.raises(
            (OSError, UnsafeFilesystemPathError, ConcurrentModificationError)
        ):
            if operation == "file":
                with observed_file.open_read() as stream:
                    assert stream.read() == b"approved bytes"
                    seen.append("known.bin")
            else:
                observed_directory.list_entries(
                    checkpoint=lambda: None,
                    on_entry=lambda entry: seen.append(entry.path.path.name),
                )
        assert swapped
        assert seen == (["known.bin"] if timing == "after_pin" else [])
    finally:
        if swapped:
            ancestor.unlink()
            moved.rename(ancestor)


@pytest.mark.parametrize("cancel", [False, True])
def test_search_only_directory_pins_close_after_read_or_cancellation(
    search_only: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    native_open = os.open
    descriptors: list[int] = []

    def record_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = native_open(path, flags, mode, dir_fd=dir_fd)
        descriptors.append(descriptor)
        return descriptor

    monkeypatch.setattr(os, "open", record_open)
    observed = LocalHostFile.observe(HostPath(search_only / "known.bin"))
    if cancel:
        with (
            pytest.raises(InterruptedError, match="cancelled"),
            observed.open_read() as stream,
        ):
            assert stream.read(1) == b"a"
            raise InterruptedError("cancelled")
    else:
        with observed.open_read() as stream:
            assert stream.read() == b"approved bytes"
    assert descriptors
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
