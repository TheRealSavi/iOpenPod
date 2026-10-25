"""Layered Host storage must resolve off-device without weakening recovery."""

from dataclasses import replace
from pathlib import Path

import pytest
from tests.storage.linux_mount_test_support import linux_recovery_layout

from storage import HostPath, HostPathOnPhysicalDeviceError, MountInspectionError


def test_ecryptfs_recovery_uses_the_backing_physical_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = linux_recovery_layout(tmp_path, monkeypatch)
    mounted = layout.storage.discover().volumes[0]
    assert layout.adapter.physical_device_id_for_path(layout.home) == (
        layout.adapter.physical_device_id_for_path(layout.backing)
    )
    layout.storage.require_host_path_off_physical_device(
        HostPath(layout.home / "TransactionRecovery"), mounted
    )
    with layout.storage.open_session(mounted) as session:
        assert session.host_transaction_journals() == ()
    assert not (layout.home / "TransactionRecovery").exists()


@pytest.mark.parametrize("alias", [False, True])
def test_ecryptfs_backing_on_the_ipod_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias: bool
) -> None:
    layout = linux_recovery_layout(tmp_path, monkeypatch, backing_on_device=True)
    if alias:
        link = layout.host / "backing-alias"
        try:
            link.symlink_to(layout.backing, target_is_directory=True)
        except OSError as error:
            pytest.skip(f"Directory symlinks unavailable: {error}")
        layout.records[1] = replace(layout.records[1], source=str(link))
    mounted = layout.storage.discover().volumes[0]
    with (
        layout.storage.open_session(mounted) as session,
        pytest.raises(HostPathOnPhysicalDeviceError, match="Host recovery storage"),
    ):
        session.host_transaction_journals()
    assert not (layout.home / "TransactionRecovery").exists()


@pytest.mark.parametrize("failure", ["relative", "missing", "file", "cycle", "unknown"])
def test_unresolved_layered_recovery_storage_still_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    layout = linux_recovery_layout(tmp_path, monkeypatch)
    backing_file = layout.host / "not-a-directory"
    backing_file.write_bytes(b"fixture")
    changed = {
        "relative": replace(layout.records[1], source="relative-backing"),
        "missing": replace(layout.records[1], source=str(layout.host / "missing")),
        "file": replace(layout.records[1], source=str(backing_file)),
        "cycle": replace(layout.records[1], source=str(layout.home)),
        "unknown": replace(layout.records[1], filesystem_type="unknown-overlay"),
    }[failure]
    layout.records[1] = changed
    mounted = layout.storage.discover().volumes[0]
    with (
        layout.storage.open_session(mounted) as session,
        pytest.raises(MountInspectionError, match="Host recovery storage"),
    ):
        session.host_transaction_journals()
    assert not (layout.home / "TransactionRecovery").exists()
