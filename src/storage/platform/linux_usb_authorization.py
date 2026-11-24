"""Request a Linux USB descriptor through the desktop's polkit agent."""

from __future__ import annotations

import array
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from storage.platform import linux_usb_access
from storage.usb_control import UsbControlAuthorizationError, UsbControlError


def receive_descriptor(connection: socket.socket) -> int:
    """Accept one descriptor from the authorized helper, closing malformed replies."""
    if linux_usb_access.peer_uid(connection) != 0:
        raise UsbControlAuthorizationError(
            "The USB authorization helper has an unexpected identity"
        )
    handles = array.array("i")
    unix_connection: Any = connection
    message, ancillary, flags, _address = unix_connection.recvmsg(
        4096, vars(socket)["CMSG_SPACE"](handles.itemsize * 4)
    )
    for level, kind, data in ancillary:
        if (level, kind) == (socket.SOL_SOCKET, vars(socket)["SCM_RIGHTS"]):
            handles.frombytes(data[: len(data) - len(data) % handles.itemsize])
    if message != b"ok" or len(handles) != 1 or flags:
        for descriptor in handles:
            os.close(descriptor)
        raise UsbControlError(
            message.decode("utf-8", errors="replace") or "USB authorization failed"
        )
    descriptor = handles[0]
    try:
        os.set_inheritable(descriptor, False)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def authorized_open(path: str, instance: str, *, scsi: bool = False) -> int:
    """Keep the app unprivileged and pass only the selected device's open handle."""
    pkexec = shutil.which("pkexec")
    if pkexec is None:
        raise UsbControlAuthorizationError(
            "USB access was denied and this desktop has no polkit authorization service (pkexec)."
        )
    if getattr(sys, "frozen", False):
        command = [
            sys.executable,
            "--storage-scsi-access" if scsi else "--storage-usb-access",
        ]
    else:
        command = [
            sys.executable,
            "-I",
            "-S",
            str(Path(linux_usb_access.__file__).resolve()),
        ]
        if scsi:
            command.append("--scsi")
    with tempfile.TemporaryDirectory(prefix="iopenpod-usb-", dir="/tmp") as directory:
        socket_path = str(Path(directory) / "access")
        with socket.socket(vars(socket)["AF_UNIX"], socket.SOCK_STREAM) as server:
            server.bind(socket_path)
            server.listen(1)
            server.settimeout(0.2)
            with subprocess.Popen(
                [
                    pkexec,
                    "--disable-internal-agent",
                    *command,
                    path,
                    instance,
                    socket_path,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ) as process:
                try:
                    deadline = time.monotonic() + 120
                    while time.monotonic() < deadline:
                        try:
                            connection, _address = server.accept()
                        except TimeoutError:
                            if process.poll() is not None:
                                raise UsbControlAuthorizationError(
                                    "USB access was not authorized"
                                ) from None
                            continue
                        with connection:
                            connection.settimeout(10)
                            return receive_descriptor(connection)
                    raise UsbControlAuthorizationError("USB authorization timed out")
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
