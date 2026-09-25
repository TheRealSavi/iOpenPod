"""Privilege-minimising Linux iPod identity discovery.

The USB descriptor serial exposed by sysfs and ordinary udev properties is an
iPod's FireWire GUID, not the Apple product serial used for exact model
lookup.  This module keeps those identities separate and prefers sources that
do not require opening a raw block device:

1. the kernel-cached SCSI VPD page 0x80 sysfs attribute, when available;
2. ``ID_IOPENPOD_PRODUCT_SERIAL``, populated by iOpenPod's udev rule;
3. the rule's mount-anchored ``/dev/disk/by-id/ipod-*`` link;
4. ordinary udev/sysfs USB properties for the FireWire GUID and USB PID.

Raw SG_IO remains a later fallback in :mod:`iopenpod.device.vpd_linux`.
"""

from __future__ import annotations

import json
import logging
import os
import posixpath
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

from .models import IPOD_USB_PIDS, USB_PID_TO_MODEL

logger = logging.getLogger(__name__)

_EMPTY_VALUES = (None, "", b"")
_BY_ID_DIRECTORY = Path("/dev/disk/by-id")
_UDEV_DATA_DIRECTORY = Path("/run/udev/data")
_SERIAL_SETUP_WARNED: set[str] = set()


def whole_disk_device(device: str) -> str:
    """Return the whole-disk node for a partition or device symlink."""

    real = os.path.realpath(device) if os.name == "posix" else device
    base = posixpath.basename(real)
    dirname = posixpath.dirname(real)

    if re.fullmatch(r"sd[a-z]+\d+", base):
        base = re.sub(r"\d+$", "", base)
    elif re.fullmatch(r"(?:mmcblk|nvme).+p\d+", base):
        base = re.sub(r"p\d+$", "", base)

    return posixpath.join(dirname, base)


def _normalise_mount_source(value: str) -> str:
    """Remove findmnt's bind-mount root suffix from a device source."""

    source = value.strip()
    if source.startswith("/dev/") and source.endswith("]"):
        source = source.partition("[")[0]
    return source


def find_block_device(mount_path: str) -> str | None:
    """Resolve a mounted path to its backing Linux block-device node."""

    try:
        completed = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", "--target", mount_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if completed.returncode == 0:
            device = _normalise_mount_source(
                completed.stdout.strip().splitlines()[0]
            )
            if device.startswith("/dev/"):
                return device
    except (FileNotFoundError, IndexError, subprocess.TimeoutExpired):
        pass

    def decode_mount_field(value: str) -> str:
        return re.sub(
            r"\\([0-7]{3})",
            lambda match: chr(int(match.group(1), 8)),
            value,
        )

    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as mounts:
            for line in mounts:
                fields = line.split()
                if len(fields) < 2:
                    continue
                if decode_mount_field(fields[1]) != mount_path:
                    continue
                if fields[0].startswith("/dev/"):
                    return fields[0]
    except OSError:
        pass

    try:
        completed = subprocess.run(
            ["lsblk", "--json", "--output", "NAME,MOUNTPOINT"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if completed.returncode == 0:
            payload = json.loads(completed.stdout)
            pending = list(payload.get("blockdevices", []))
            while pending:
                entry = pending.pop()
                pending.extend(entry.get("children") or [])
                if entry.get("mountpoint") != mount_path:
                    continue
                name = str(entry.get("name") or "")
                if name:
                    return f"/dev/{name}"
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    return None


def parse_vpd_page_80(data: bytes) -> str:
    """Decode a complete SCSI VPD page 0x80 response into its serial."""

    if len(data) < 4 or data[1] != 0x80:
        return ""

    payload_length = int.from_bytes(data[2:4], "big")
    if payload_length <= 0 or len(data) < 4 + payload_length:
        return ""
    payload = data[4 : 4 + payload_length]
    try:
        serial = payload.split(b"\x00", 1)[0].decode("ascii").strip()
    except UnicodeDecodeError:
        return ""
    if not serial or any(ord(char) < 0x20 for char in serial):
        return ""
    return serial


def _cached_product_serial(base_disk: str) -> str:
    device_path = Path("/sys/block") / base_disk / "device"
    try:
        serial = _clean_product_serial(
            (device_path / "serial").read_text(encoding="ascii")
        )
    except OSError:
        serial = ""
    if serial:
        return serial

    try:
        return parse_vpd_page_80((device_path / "vpd_pg80").read_bytes())
    except OSError:
        return ""


def _model_fields(usb_pid: int) -> dict[str, object]:
    model = USB_PID_TO_MODEL.get(usb_pid)
    if not model:
        return {}
    return {
        "model_family": model[0],
        "generation": model[1],
    }


def _is_ipod_usb_identity(
    usb_pid: int | None,
    product_name: str,
) -> bool:
    """Return whether USB identity evidence specifically identifies an iPod."""

    normalised_name = product_name.replace("_", " ").strip().casefold()
    return usb_pid in IPOD_USB_PIDS or normalised_name == "ipod"


def _is_ipod_scsi_device(base_disk: str) -> bool:
    """Validate the SCSI vendor/model before trusting cached page 0x80."""

    device_path = Path("/sys/block") / base_disk / "device"
    try:
        vendor = (device_path / "vendor").read_text(encoding="ascii").strip()
        model = (device_path / "model").read_text(encoding="ascii").strip()
    except OSError:
        return False
    return vendor.casefold().startswith("apple") and model.casefold().startswith(
        "ipod"
    )


def _parse_hex_guid(value: str) -> str:
    candidate = value.replace(" ", "").strip()
    if len(candidate) != 16:
        return ""
    try:
        bytes.fromhex(candidate)
    except ValueError:
        return ""
    return candidate.upper()


def _clean_product_serial(value: str) -> str:
    serial = value.replace("\x00", "").strip()
    if not serial:
        return ""
    try:
        serial.encode("ascii")
    except UnicodeEncodeError:
        return ""
    if any(ord(char) < 0x20 for char in serial):
        return ""
    return serial


def _udev_database_key(device: str) -> str:
    """Return the mount-anchored udev database key for a block-device node."""

    try:
        device_stat = os.stat(device)
    except OSError:
        return ""
    if not stat.S_ISBLK(device_stat.st_mode):
        return ""
    # ``os.major``/``os.minor`` and ``stat_result.st_rdev`` are POSIX-only.
    # Access them dynamically so Windows type stubs (and therefore Pylance)
    # can analyse this cross-platform module too.
    major = getattr(os, "major", None)
    minor = getattr(os, "minor", None)
    device_number = getattr(device_stat, "st_rdev", None)
    if not callable(major) or not callable(minor) or not isinstance(device_number, int):
        return ""

    try:
        return f"b{major(device_number)}:{minor(device_number)}"
    except (OSError, TypeError, ValueError):
        return ""


def _properties_from_udev_database(device: str) -> dict[str, str]:
    """Read root-published properties directly when ``udevadm`` is sandboxed."""

    key = _udev_database_key(device)
    if not key:
        return {}
    try:
        data = (_UDEV_DATA_DIRECTORY / key).read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return {}

    properties: dict[str, str] = {}
    for line in data.splitlines():
        if not line.startswith("E:"):
            continue
        name, separator, value = line[2:].partition("=")
        if separator:
            properties[name.strip()] = value.strip()
    return properties


def _identity_from_udev(device: str) -> dict[str, Any]:
    """Read non-privileged identity properties cached by udev."""

    result: dict[str, Any] = {}
    sources: dict[str, str] = {}
    properties: dict[str, str] = {}
    try:
        completed = subprocess.run(
            ["udevadm", "info", "--query=property", "--name", device],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        completed = None

    if completed is not None and completed.returncode == 0:
        for line in completed.stdout.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                properties[key.strip()] = value.strip()
    for key, value in _properties_from_udev_database(device).items():
        properties.setdefault(key, value)

    product_serial = _clean_product_serial(
        properties.get("ID_IOPENPOD_PRODUCT_SERIAL", "")
    )
    if product_serial:
        result["serial"] = product_serial
        sources["serial"] = "udev_scsi_id"
    elif properties.get("ID_IOPENPOD_RULE_VERSION"):
        logger.info(
            "Linux identity rule version %s ran for %s but did not publish "
            "an Apple product serial",
            properties["ID_IOPENPOD_RULE_VERSION"],
            device,
        )

    product_id = properties.get("ID_MODEL_ID", "")
    try:
        usb_pid = int(product_id, 16)
    except ValueError:
        usb_pid = None

    if (
        properties.get("ID_VENDOR_ID", "").lower() != "05ac"
        or not _is_ipod_usb_identity(
            usb_pid,
            properties.get("ID_MODEL", ""),
        )
    ):
        if sources:
            result["_sources"] = sources
        return result

    firewire_guid = _parse_hex_guid(properties.get("ID_SERIAL_SHORT", ""))
    if firewire_guid:
        result["firewire_guid"] = firewire_guid
        sources["firewire_guid"] = "udev"

    if usb_pid is not None:
        result["usb_pid"] = usb_pid
        result.update(_model_fields(usb_pid))
        sources["usb_pid"] = "udev"

    if sources:
        result["_sources"] = sources
    return result


def _identity_from_sysfs(base_disk: str) -> dict[str, Any]:
    """Walk from a SCSI disk to its owning USB device in sysfs."""

    result: dict[str, Any] = {}
    sources: dict[str, str] = {}
    is_ipod = _is_ipod_scsi_device(base_disk)

    current = os.path.realpath(f"/sys/block/{base_disk}/device")
    if not os.path.exists(current):
        if is_ipod:
            product_serial = _cached_product_serial(base_disk)
            if product_serial:
                result["serial"] = product_serial
                sources["serial"] = "sysfs_vpd"
        if sources:
            result["_sources"] = sources
        return result

    for _ in range(12):
        vendor_path = os.path.join(current, "idVendor")
        try:
            vendor = Path(vendor_path).read_text(encoding="ascii").strip()
        except OSError:
            vendor = ""

        if vendor.lower() == "05ac":
            try:
                product = (
                    Path(current, "idProduct").read_text(encoding="ascii").strip()
                )
                usb_pid = int(product, 16)
            except (OSError, ValueError):
                usb_pid = None

            try:
                product_name = (
                    Path(current, "product").read_text(encoding="utf-8").strip()
                )
            except OSError:
                product_name = ""

            if not _is_ipod_usb_identity(usb_pid, product_name):
                break

            is_ipod = True
            if usb_pid is not None:
                result["usb_pid"] = usb_pid
                result.update(_model_fields(usb_pid))
                sources["usb_pid"] = "sysfs"

            try:
                usb_serial = (
                    Path(current, "serial").read_text(encoding="ascii").strip()
                )
            except OSError:
                usb_serial = ""
            firewire_guid = _parse_hex_guid(usb_serial)
            if firewire_guid:
                result["firewire_guid"] = firewire_guid
                sources["firewire_guid"] = "sysfs"
            break

        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    if is_ipod:
        product_serial = _cached_product_serial(base_disk)
        if product_serial:
            result["serial"] = product_serial
            sources["serial"] = "sysfs_vpd"

    if sources:
        result["_sources"] = sources
    return result


def _identity_from_usb_bus(base_disk: str) -> dict[str, Any]:
    """Find the owning Apple USB node when the direct sysfs walk is sparse."""

    result: dict[str, Any] = {}
    sources: dict[str, str] = {}
    block_path = f"/sys/block/{base_disk}"
    if not os.path.exists(block_path):
        return result

    block_real = os.path.realpath(block_path)
    usb_root = Path("/sys/bus/usb/devices")
    try:
        entries = list(usb_root.iterdir())
    except OSError:
        return result

    for entry in entries:
        try:
            vendor = (entry / "idVendor").read_text(encoding="ascii").strip()
        except OSError:
            continue
        if vendor.lower() != "05ac":
            continue
        if not block_real.startswith(os.path.realpath(entry) + os.sep):
            continue

        try:
            usb_pid = int(
                (entry / "idProduct").read_text(encoding="ascii").strip(),
                16,
            )
        except (OSError, ValueError):
            usb_pid = None
        try:
            product_name = (entry / "product").read_text(
                encoding="utf-8"
            ).strip()
        except OSError:
            product_name = ""
        if not _is_ipod_usb_identity(usb_pid, product_name):
            continue

        if usb_pid is not None:
            result["usb_pid"] = usb_pid
            result.update(_model_fields(usb_pid))
            sources["usb_pid"] = "sysfs"

        try:
            usb_serial = (entry / "serial").read_text(encoding="ascii").strip()
        except OSError:
            usb_serial = ""
        firewire_guid = _parse_hex_guid(usb_serial)
        if firewire_guid:
            result["firewire_guid"] = firewire_guid
            sources["firewire_guid"] = "sysfs"
        break

    if sources:
        result["_sources"] = sources
    return result


def _identity_from_by_id(whole_disk: str) -> dict[str, Any]:
    """Read the root-owned iPod serial link for this exact mounted disk."""

    target = os.path.realpath(whole_disk)
    try:
        candidates = list(_BY_ID_DIRECTORY.glob("ipod-*"))
    except OSError:
        return {}

    for candidate in candidates:
        if os.path.realpath(str(candidate)) != target:
            continue
        serial = _clean_product_serial(candidate.name.removeprefix("ipod-"))
        if not re.fullmatch(r"[A-Za-z0-9]{8,16}", serial):
            continue
        return {
            "serial": serial,
            "_sources": {"serial": "udev_scsi_id"},
        }
    return {}


def _merge_identity(target: dict[str, Any], candidate: dict[str, Any]) -> None:
    candidate_sources = candidate.get("_sources") or {}
    target_sources = target.setdefault("_sources", {})

    for field, value in candidate.items():
        if field == "_sources" or value in _EMPTY_VALUES:
            continue
        if target.get(field) not in _EMPTY_VALUES:
            continue
        target[field] = value
        source = candidate_sources.get(field)
        if source:
            target_sources[field] = source

    if not target_sources:
        target.pop("_sources", None)


def probe_linux_identity(mount_path: str) -> dict[str, Any]:
    """Return safe, mount-anchored Linux identity evidence for one iPod."""

    partition = find_block_device(mount_path)
    if not partition:
        logger.debug("Linux identity: no block device for %s", mount_path)
        return {}

    whole_disk = whole_disk_device(partition)
    base_disk = os.path.basename(whole_disk)
    result: dict[str, Any] = {}

    _merge_identity(result, _identity_from_sysfs(base_disk))
    _merge_identity(result, _identity_from_udev(partition))
    if whole_disk != partition:
        _merge_identity(result, _identity_from_udev(whole_disk))
    _merge_identity(result, _identity_from_by_id(whole_disk))
    _merge_identity(result, _identity_from_usb_bus(base_disk))

    if result:
        logger.debug("Linux identity evidence: %s", result)
    if result.get("serial"):
        _SERIAL_SETUP_WARNED.discard(mount_path)
    elif (
        result.get("usb_pid") or result.get("firewire_guid")
    ) and mount_path not in _SERIAL_SETUP_WARNED:
        _SERIAL_SETUP_WARNED.add(mount_path)
        logger.warning(
            "Linux Apple product serial is unavailable for %s. Complete the "
            "Linux identity setup prompt, or pass "
            "--linux-identity-status %r to the same iOpenPod launcher.",
            mount_path,
            mount_path,
        )
    return result
