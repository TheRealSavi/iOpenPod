"""Host-side resource lease behavior."""

from __future__ import annotations

import errno
from io import BytesIO
from typing import TYPE_CHECKING

import pytest

from storage import (
    DeviceBusyError,
    HostResourceLease,
    StorageOperationError,
    _writer_lock,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_host_resource_lease_rejects_reentrant_access(tmp_path: Path) -> None:
    lock_directory = tmp_path / "locks"

    with (
        HostResourceLease("backup-repository:test", lock_directory),
        pytest.raises(DeviceBusyError, match="Host resource"),
        HostResourceLease("backup-repository:test", lock_directory),
    ):
        pytest.fail("A second lease unexpectedly acquired the same resource")


def test_host_resource_leases_are_scoped_by_identity(tmp_path: Path) -> None:
    lock_directory = tmp_path / "locks"

    with (
        HostResourceLease("backup-repository:first", lock_directory),
        HostResourceLease("backup-repository:second", lock_directory),
    ):
        pass


@pytest.mark.parametrize("number", (errno.EMFILE, errno.EIO, errno.ENOSPC))
def test_lock_resource_errors_are_not_reported_as_another_process(
    monkeypatch: pytest.MonkeyPatch, number: int
) -> None:
    error = OSError(number, "resource unavailable")

    def fail(*_args: object) -> None:
        raise error

    monkeypatch.setattr(_writer_lock, "_windows_locking", fail)
    monkeypatch.setattr(_writer_lock, "_posix_flock", fail)
    with pytest.raises(StorageOperationError, match="resource unavailable") as raised:
        _writer_lock._lock_file(BytesIO(), "Host staging cleanup")  # pyright: ignore[reportPrivateUsage]
    assert not isinstance(raised.value, DeviceBusyError)
    assert raised.value.__cause__ is error
