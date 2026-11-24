"""The permission helper hands off only a current device's descriptor."""

import array
import os
import socket
import struct
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from storage import UsbControlError
from storage.platform import linux_usb_access as access
from storage.platform import linux_usb_authorization as authorization


def test_missing_polkit_fails_locally_without_a_terminal_or_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_executable(_name: str) -> None:
        return None

    monkeypatch.setattr(
        "storage.platform.linux_usb_authorization.shutil.which", missing_executable
    )
    with pytest.raises(UsbControlError, match="polkit"):
        authorization.authorized_open("unused", "unused")


def test_helper_rejects_an_ordinary_or_nonlinux_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PKEXEC_UID", raising=False)
    assert access.main(["unused", "unused", "unused"]) == 2


def test_changed_sysfs_generation_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    device = access.LinuxUsbDevice("/dev/bus/usb/001/002", "old-generation", 1, 2)
    monkeypatch.setattr(
        access, "devices", lambda: (replace(device, instance="new-generation"),)
    )
    with pytest.raises(OSError, match="connection changed"):
        access.require_device(device.path, device.instance)


def test_peer_credentials_preserve_unsigned_linux_user_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        vars(socket), "SO_PEERCRED", vars(socket).get("SO_PEERCRED", 17)
    )
    connection = MagicMock(spec=socket.socket)
    connection.getsockopt.return_value = struct.pack("=iII", 123, 4_000_000_000, 1000)
    assert access.peer_uid(connection) == 4_000_000_000


@pytest.mark.skipif(sys.platform != "linux", reason="Unix descriptor passing")
@pytest.mark.parametrize("count", [1, 2])
def test_descriptor_handoff_and_malformed_reply_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    path = tmp_path / "handle"
    path.touch()
    original = os.open(path, os.O_RDWR)

    def root_peer(_connection: socket.socket) -> int:
        return 0

    monkeypatch.setattr(access, "peer_uid", root_peer)
    left, right = socket.socketpair()
    try:
        rights = array.array("i", [original] * count)
        native: Any = right
        # Use the real kernel transfer, including duplicated descriptor ownership.
        native.sendmsg(
            [b"ok"], [(socket.SOL_SOCKET, vars(socket)["SCM_RIGHTS"], rights)]
        )
        if count == 1:
            received = authorization.receive_descriptor(left)
            try:
                assert not os.get_inheritable(received)
                assert os.fstat(received).st_ino == os.fstat(original).st_ino
            finally:
                os.close(received)
        else:
            with pytest.raises(UsbControlError):
                authorization.receive_descriptor(left)
    finally:
        left.close()
        right.close()
        os.close(original)
