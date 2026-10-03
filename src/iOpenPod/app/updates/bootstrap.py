"""Hold application use leases and commit health before enabling device work."""

from __future__ import annotations

import atexit
import time
from pathlib import Path
from typing import TYPE_CHECKING

from storage.host_installation import file_identity
from storage.host_usage import HostInstallationLease

from .installation import running_installation
from .portable import Operation, lease_target, read_operation

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QApplication, QWidget

_lease: HostInstallationLease | None = None
_operation: Operation | None = None


def prepare_launch(health: list[str] | None) -> None:
    global _lease, _operation
    installation = running_installation()
    if installation is None or installation.target.startswith("macos"):
        if health:
            raise ValueError(
                "This installation does not support a helper health launch"
            )
        return
    if health:
        operation = read_operation(Path(health[0]), installation.public_keys)
        expected = (
            operation.target
            if operation.asset.target.startswith("windows")
            else operation.candidate
        )
        if (
            health[1] != operation.nonce
            or installation.executable != expected
            or installation.version != operation.asset.version
            or not operation.matches("authorized", operation.nonce)
            or file_identity(expected) != operation.incoming
        ):
            raise ValueError("Invalid application update health launch")
        _operation = operation
        return
    try:
        target = lease_target(installation)
    except ValueError:
        # An unpackaged Linux build can still launch and offer manual updates.
        return
    _lease = HostInstallationLease(target)
    atexit.register(_lease.close)


def awaiting_health() -> bool:
    return _operation is not None


def start_health_handshake(
    application: QApplication, window: QWidget, ready: Callable[[], None]
) -> None:
    """A responsive Qt event turn confirms actual GUI startup; device work waits."""
    from PySide6.QtCore import QTimer

    operation = _operation
    if operation is None:
        ready()
        return
    window.setEnabled(False)
    deadline = time.monotonic() + 90
    timer = QTimer(window)
    timer.setInterval(100)

    def poll() -> None:
        global _lease, _operation
        if operation.matches("committed", operation.nonce):
            key = (
                operation.target
                if operation.asset.target.startswith("windows")
                else operation.root
            )
            try:
                _lease = HostInstallationLease(key)
            except OSError:
                # The helper flushes the commit before releasing its exclusive lock.
                if time.monotonic() < deadline:
                    return
            else:
                atexit.register(_lease.close)
                _operation = None
                timer.stop()
                window.setEnabled(True)
                ready()
                return
        if time.monotonic() >= deadline:
            timer.stop()
            application.exit(1)

    def healthy() -> None:
        operation.write("healthy", operation.nonce)
        timer.start()

    timer.timeout.connect(poll)
    QTimer.singleShot(0, healthy)
