"""Host-side resource lease behavior."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from storage import DeviceBusyError, HostResourceLease

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
