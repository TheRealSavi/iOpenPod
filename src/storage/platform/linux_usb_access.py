"""Open one connection-bound Linux USB node after native authorization.

This module also runs as an isolated, standard-library-only pkexec helper. It
passes an already-open descriptor to the calling user without changing device
permissions, installing rules, or executing USB requests as root.
"""

from __future__ import annotations

import array
import os
import re
import socket
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

USB_DEVICES = Path("/sys/bus/usb/devices")
USB_NODES = Path("/dev/bus/usb")
SYS_BLOCK = Path("/sys/class/block")


@dataclass(frozen=True)
class LinuxUsbDevice:
    path: str
    instance: str
    vendor: int
    product: int


def devices() -> tuple[LinuxUsbDevice, ...]:
    """Capture the sysfs generation as well as the reusable USB address."""
    result: list[LinuxUsbDevice] = []
    for entry in USB_DEVICES.iterdir():
        if ":" in entry.name:
            continue
        try:
            bus = int((entry / "busnum").read_text())
            address = int((entry / "devnum").read_text())
            vendor = int((entry / "idVendor").read_text(), 16)
            product = int((entry / "idProduct").read_text(), 16)
            if not (1 <= bus <= 999 and 1 <= address <= 127):
                continue
            node = USB_NODES / f"{bus:03d}" / f"{address:03d}"
            instance = f"{entry.resolve()}:{entry.stat().st_ino}:{bus}:{address}"
            result.append(LinuxUsbDevice(str(node), instance, vendor, product))
        except (OSError, ValueError):
            continue  # A device may disappear during enumeration.
    return tuple(result)


def require_device(path: str, instance: str) -> LinuxUsbDevice:
    matches = [d for d in devices() if (d.path, d.instance) == (path, instance)]
    if len(matches) != 1:
        raise OSError(
            "The selected USB connection changed; reconnect and select it again"
        )
    return matches[0]


def open_device(path: str, instance: str) -> int:
    """Open only a current kernel USB node, and qualify the held descriptor."""
    expected = require_device(path, instance)
    before = os.stat(path, follow_symlinks=False)
    before_device = int(getattr(before, "st_rdev", 0))
    if not stat.S_ISCHR(before.st_mode) or vars(os)["major"](before_device) != 189:
        raise OSError("The selected path is not a Linux USB device")
    descriptor = os.open(
        path, os.O_RDWR | vars(os)["O_CLOEXEC"] | vars(os)["O_NOFOLLOW"]
    )
    try:
        held = os.fstat(descriptor)
        if (held.st_dev, held.st_ino, getattr(held, "st_rdev", 0)) != (
            before.st_dev,
            before.st_ino,
            before_device,
        ) or require_device(path, instance) != expected:
            raise OSError("The selected USB device changed while opening it")
        # usbfs exposes cached device descriptors in host byte order.
        data = os.read(descriptor, 18)
        if (
            len(data) != 18
            or data[:2] != b"\x12\x01"
            or int.from_bytes(data[8:10], sys.byteorder) != expected.vendor
            or int.from_bytes(data[10:12], sys.byteorder) != expected.product
        ):
            raise OSError("The held USB descriptor does not match the selected device")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@dataclass(frozen=True)
class LinuxScsiTarget:
    partition: str
    partition_number: str
    disk: str
    disk_number: str
    sg_node: str
    sg_number: str
    diskseq: str


def scsi_target(partition: str) -> LinuxScsiTarget:
    """Resolve a partition to its kernel SCSI device and one USB disk generation."""
    if not re.fullmatch(r"sd[a-z]+[1-9][0-9]*", partition):
        raise OSError("Expected a Linux SCSI disk partition")
    part = (SYS_BLOCK / partition).resolve(strict=True)
    disk = part.parent
    if (
        not (part / "partition").is_file()
        or not re.fullmatch(r"sd[a-z]+", disk.name)
        or not any(
            (node / "idVendor").is_file()
            and (node / "idProduct").is_file()
            and (node / "subsystem").resolve().name == "usb"
            for node in disk.parents
        )
    ):
        raise OSError("The selected partition does not belong to a USB disk")
    scsi = (disk / "device").resolve(strict=True)
    nodes = tuple((scsi / "scsi_generic").glob("sg[0-9]*"))
    if len(nodes) != 1 or not re.fullmatch(r"sg[0-9]+", nodes[0].name):
        raise OSError("The selected USB disk has no unique Linux SCSI interface")
    seq = (disk / "diskseq").read_text("ascii").strip()
    if not seq.isdecimal() or int(seq) == 0:
        raise OSError("The kernel did not identify this disk connection")
    return LinuxScsiTarget(
        partition,
        (part / "dev").read_text("ascii").strip(),
        disk.name,
        (disk / "dev").read_text("ascii").strip(),
        nodes[0].name,
        (nodes[0] / "dev").read_text("ascii").strip(),
        seq,
    )


def check_device_number(descriptor: int, expected: str, *, block: bool) -> None:
    held = os.fstat(descriptor)
    expected_kind = stat.S_ISBLK if block else stat.S_ISCHR
    number = int(getattr(held, "st_rdev", 0))
    major = int(vars(os)["major"](number))
    minor = int(vars(os)["minor"](number))
    if not expected_kind(held.st_mode) or f"{major}:{minor}" != expected:
        raise OSError("The open handle belongs to a different device")


def open_scsi_device(partition: str, diskseq: str) -> int:
    target = scsi_target(partition)
    if target.diskseq != diskseq:
        raise OSError("The selected USB disk connection changed")
    descriptor = os.open(
        "/dev/" + target.sg_node,
        os.O_RDWR
        | os.O_EXCL
        | vars(os)["O_NOFOLLOW"]
        | vars(os)["O_NONBLOCK"]
        | vars(os)["O_CLOEXEC"],
    )
    try:
        check_device_number(descriptor, target.sg_number, block=False)
        if target != scsi_target(partition):
            raise OSError("The USB disk changed while opening its SCSI interface")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def peer_uid(connection: socket.socket) -> int:
    credentials = connection.getsockopt(
        socket.SOL_SOCKET, vars(socket)["SO_PEERCRED"], struct.calcsize("=iII")
    )
    return int(struct.unpack("=iII", credentials)[1])


def main(arguments: list[str], *, scsi: bool = False) -> int:
    """Authorize only a descriptor handoff to the original calling user."""
    if sys.platform != "linux" or len(arguments) != 3:
        return 2
    path, instance, socket_path = arguments
    caller_text = os.environ.get("PKEXEC_UID", "")
    if not caller_text.isdecimal():
        return 2
    caller = int(caller_text)
    if caller <= 0 or os.geteuid() != 0:
        return 2
    target = os.lstat(socket_path)
    if not stat.S_ISSOCK(target.st_mode) or target.st_uid != caller:
        return 2
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect(socket_path)
        if peer_uid(connection) != caller:
            return 2
        try:
            descriptor = (
                open_scsi_device(path, instance)
                if scsi
                else open_device(path, instance)
            )
        except OSError as error:
            connection.sendall(str(error).encode("utf-8")[:4096])
            return 1
        try:
            connection.sendmsg(
                [b"ok"],
                [
                    (
                        socket.SOL_SOCKET,
                        socket.SCM_RIGHTS,
                        array.array("i", [descriptor]),
                    )
                ],
            )
        finally:
            os.close(descriptor)
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--scsi"]:
        raise SystemExit(main(sys.argv[2:], scsi=True))
    raise SystemExit(main(sys.argv[1:]))
