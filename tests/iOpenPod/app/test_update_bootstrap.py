"""GUI and device startup remain suspended until the installer releases ownership."""

from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from tests.iOpenPod.app.test_portable_updates import operation

from iOpenPod.app.updates import bootstrap
from iOpenPod.app.updates.installation import Installation
from iOpenPod.app.updates.portable import Operation
from storage.host_installation import file_identity
from storage.host_usage import HostInstallationLease

APPLICATION = QApplication.instance() or QApplication([])


def test_health_waits_for_commit_and_exclusive_lease_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert isinstance(APPLICATION, QApplication)
    op = operation(tmp_path)
    monkeypatch.setattr(bootstrap, "_operation", op)
    monkeypatch.setattr(bootstrap, "_lease", None)
    leases: list[HostInstallationLease] = []

    def acquire_lease(
        installation: Path, *, exclusive: bool = False
    ) -> HostInstallationLease:
        lease = HostInstallationLease(installation, exclusive=exclusive)
        leases.append(lease)
        return lease

    monkeypatch.setattr(bootstrap, "HostInstallationLease", acquire_lease)
    window = QWidget()
    ready: list[bool] = []
    try:
        with HostInstallationLease(op.target, exclusive=True):
            bootstrap.start_health_handshake(
                APPLICATION, window, lambda: ready.append(True)
            )
            QTest.qWait(150)
            assert op.matches("healthy", op.nonce)
            assert not window.isEnabled() and not ready
            op.write("committed", op.nonce)
            QTest.qWait(150)
            assert not window.isEnabled() and not ready
        QTest.qWait(150)
        assert window.isEnabled() and ready == [True]
        assert not bootstrap.awaiting_health()
        with pytest.raises(OSError), HostInstallationLease(op.target, exclusive=True):
            pytest.fail("The new app did not acquire its use lease")
    finally:
        for lease in leases:
            lease.close()
        window.close()


def test_health_launch_requires_authorization_and_exact_incoming_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    op = operation(tmp_path)
    # Represent the state after publication without using platform-specific rename.
    op.target.write_bytes(b"new")
    from dataclasses import replace

    op = replace(op, incoming=file_identity(op.target))
    installation = Installation(
        "2.0.2", "windows-x86_64", "windows-onefile-v1", (), op.target, tmp_path
    )
    monkeypatch.setattr(bootstrap, "running_installation", lambda: installation)

    def read_operation(_directory: Path, _keys: tuple[str, ...]) -> Operation:
        return op

    monkeypatch.setattr(bootstrap, "read_operation", read_operation)
    monkeypatch.setattr(bootstrap, "_operation", None)
    with pytest.raises(ValueError, match="Invalid"):
        bootstrap.prepare_launch([str(op.directory), op.nonce])
    op.write("authorized", op.nonce)
    with pytest.raises(ValueError, match="Invalid"):
        bootstrap.prepare_launch([str(op.directory), "wrong-nonce"])
    bootstrap.prepare_launch([str(op.directory), op.nonce])
    assert bootstrap.awaiting_health()
    op.target.write_bytes(b"unexpected contents")
    with pytest.raises(ValueError, match="Invalid"):
        bootstrap.prepare_launch([str(op.directory), op.nonce])
