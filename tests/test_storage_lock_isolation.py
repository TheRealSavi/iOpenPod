"""Parallel tests isolate synthetic identities without disabling writer leases."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from storage._writer_lock import HostResourceLease, VolumeWriterLease

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("lease_type", [HostResourceLease, VolumeWriterLease])
def test_default_writer_leases_use_the_pytest_process_namespace(
    tmp_path_factory: pytest.TempPathFactory,
    lease_type: type[HostResourceLease] | type[VolumeWriterLease],
) -> None:
    with lease_type("test-default-lease-namespace") as lease:
        assert lease._path.is_relative_to(  # pyright: ignore[reportPrivateUsage]
            tmp_path_factory.getbasetemp()
        )


@pytest.mark.parametrize("lease_type", [HostResourceLease, VolumeWriterLease])
def test_explicit_writer_lease_directories_are_not_replaced(
    tmp_path: Path, lease_type: type[HostResourceLease] | type[VolumeWriterLease]
) -> None:
    directory = tmp_path / "explicit-locks"
    with lease_type("test-explicit-lease-namespace", directory) as lease:
        assert lease._path.parent == directory  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("lease_type", [HostResourceLease, VolumeWriterLease])
def test_isolated_default_lease_still_excludes_another_process(
    lease_type: type[HostResourceLease] | type[VolumeWriterLease],
) -> None:
    script = """
import sys
from pathlib import Path
from storage._writer_lock import HostResourceLease, VolumeWriterLease
from storage.errors import DeviceBusyError
lease_type = {"HostResourceLease": HostResourceLease, "VolumeWriterLease": VolumeWriterLease}[sys.argv[1]]
try:
    with lease_type(sys.argv[2], Path(sys.argv[3])):
        raise SystemExit("A second process unexpectedly acquired the writer lease.")
except DeviceBusyError:
    print("busy")
"""
    identity = "test-cross-process-lease-exclusion"
    with lease_type(identity) as lease:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                lease_type.__name__,
                identity,
                str(lease._path.parent),  # pyright: ignore[reportPrivateUsage]
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "busy"
