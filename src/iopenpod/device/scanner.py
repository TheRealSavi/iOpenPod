"""
iPod device scanner — discovers connected iPods by scanning mounted drives.

Uses a unified "gather everything, synthesize once" pipeline that combines
ALL available data sources and picks the best value for each field.

Detection pipeline:

  **Phase 1 — Hardware probing** (pure Win32, no file I/O, no subprocess):
    1a. IOCTL_STORAGE_QUERY_PROPERTY → vendor, product, firmware, Apple serial
    1b. PnP device tree walk (SetupAPI/cfgmgr32) → FireWire GUID, USB PID
    1c. If both fail: silent fallback to WMI (PowerShell + registry)

  **Phase 2 — Filesystem probing** (file reads on iPod):
    2a. SysInfo / SysInfoExtended → ModelNumStr, FireWire GUID, serial
    2b. iTunesDB header → hashing_scheme (generation class)

  **Phase 3 — Model resolution** (pure computation, per-field priority):
    - model_number:  SysInfo ModelNumStr → IPOD_MODELS  >  serial suffix → IPOD_MODELS
    - firewire_guid: device tree  >  SysInfoExtended  >  SysInfo  >  USB serial (always 16 hex chars on iPods)
    - serial:        SysInfo pszSerialNumber (Apple serial)  >  IOCTL (only if non-GUID)
    - firmware:      IOCTL revision  >  SysInfo visibleBuildID
    - usb_pid:       device tree USB parent  >  WMI fallback
    - model_family:  IPOD_MODELS  >  USB PID table (with disk-size sanity check)  >  hashing_scheme

  **Phase 4 — Inline VPD** (macOS only, for incomplete identification):
    If model_number is still unknown after Phase 3, query the iPod's
    firmware via IOKit SCSI VPD (~1 s, no root, disk stays mounted)
    to get the Apple serial. Serial-suffix lookup resolves the exact model
    (family, generation, capacity, color).  Writes SysInfo to the iPod
    so that subsequent scans never need VPD again.
"""

import ctypes
import logging
import os
import struct
import subprocess
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

if sys.platform == "win32":
    import ctypes.wintypes as wt
elif TYPE_CHECKING:
    import ctypes.wintypes as wt  # type-checker only

from .diagnostic_log import (
    CAPABILITY_FIELDS,
    IDENTITY_FIELDS,
    SOURCE_FIELDS,
    format_conflicts,
    format_fields,
    format_sources,
)
from .filesystem import (
    ITUNESDB_PLATFORM_MAC,
    detect_filesystem_type,
    filesystem_itunesdb_platform,
)
from .filesystem_profile import inspect_filesystem_profile
from .info import DeviceInfo
from .models import USB_PID_TO_MODEL
from .write_readiness import volume_lock_key

logger = logging.getLogger(__name__)

_PROBE_META_FIELDS: tuple[tuple[str, str], ...] = (
    ("_sysinfo_present", "sysinfo"),
    ("_sysinfo_keys", "sysinfo_keys"),
    ("_sysinfo_extended_present", "sie"),
    ("_sysinfo_extended_keys", "sie_keys"),
    ("_sysinfo_extended_regex_fallback", "sie_regex"),
    ("hashing_scheme", "hash_scheme"),
    ("filesystem_type", "fs_type"),
    ("volume_identity_key", "volume_identity"),
)

# Prevents console windows from flashing on Windows during subprocess calls
_SP_KWARGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)


def _extract_guid_from_instance_id(instance_id: str) -> str:
    """
    Extract the FireWire GUID (16-char hex string) from a USBSTOR or USB
    instance ID.

    The instance ID format depends on whether the USB device reports
    ``UniqueID=TRUE`` or ``FALSE``:

      - **UniqueID=TRUE** (simple USB, e.g. Nano 2G):
        ``000A270018A1F847&0``
        → GUID is the first ``&``-separated segment.

      - **UniqueID=FALSE** (composite USB, e.g. Classic):
        ``8&2F161EF4&0&000A2700138A422D&0``
        → PnP prepends a scope-hash prefix.  The GUID is still present
          as a 16-char hex segment, just not the first one.

    This helper scans ALL ``&``-separated segments and returns the first
    that is exactly 16 hex characters.  Returns empty string if not found.
    """
    for segment in instance_id.split("&"):
        segment = segment.strip()
        if len(segment) == 16:
            try:
                bytes.fromhex(segment)
                return segment.upper()
            except ValueError:
                pass
    return ""


def _get_drive_letters() -> list[str]:
    """Get all available drive letters on Windows."""
    if sys.platform != "win32":
        return []

    import ctypes
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    letters = []
    for i in range(26):
        if bitmask & (1 << i):
            letter = chr(65 + i)
            letters.append(letter)
    return letters


def _has_ipod_control(drive_path: str) -> bool:
    """Check if a drive has iPod_Control at its root."""
    ipod_control = os.path.join(drive_path, "iPod_Control")
    return os.path.isdir(ipod_control)


def _get_disk_info(drive_path: str) -> tuple[float, float]:
    """Get disk size and free space in GB."""
    try:
        import shutil
        usage = shutil.disk_usage(drive_path)
        return usage.total / (1024**3), usage.free / (1024**3)
    except OSError:
        return 0.0, 0.0


def _canonical_mount_path(path: str) -> str:
    """Return a stable path identity for mount alias detection."""
    try:
        return os.path.realpath(path)
    except OSError:
        return os.path.abspath(path)


def _find_ipod_volumes() -> list[tuple[str, str]]:
    """
    Find mounted volumes that contain an iPod_Control directory.

    Returns a list of (mount_path, display_name) tuples.
    Cross-platform: Windows drive letters, macOS /Volumes, Linux common mount dirs.
    """
    candidates: list[tuple[str, str]] = []

    if sys.platform == "win32":
        for letter in _get_drive_letters():
            drive_path = f"{letter}:\\"
            try:
                if _has_ipod_control(drive_path):
                    candidates.append((drive_path, f"{letter}:"))
            except PermissionError:
                continue

    elif sys.platform == "darwin":
        # macOS: iPods mount under /Volumes/
        volumes_dir = "/Volumes"
        if os.path.isdir(volumes_dir):
            for name in os.listdir(volumes_dir):
                vol_path = os.path.join(volumes_dir, name)
                if os.path.isdir(vol_path):
                    try:
                        if _has_ipod_control(vol_path):
                            candidates.append((vol_path, name))
                    except PermissionError:
                        continue

    else:
        # Linux: check common mount locations
        import getpass
        user = getpass.getuser()
        search_dirs = [
            f"/run/media/{user}",
            f"/media/{user}",
            "/mnt",
        ]
        # Also check /media/* for distros that mount directly under /media
        if os.path.isdir("/media"):
            try:
                for entry in os.listdir("/media"):
                    d = os.path.join("/media", entry)
                    if os.path.isdir(d) and d not in search_dirs:
                        search_dirs.append(d)
            except PermissionError:
                pass

        seen: set[str] = set()
        for search_dir in search_dirs:
            if not os.path.isdir(search_dir):
                continue
            try:
                entries = os.listdir(search_dir)
            except PermissionError:
                continue
            for name in entries:
                vol_path = os.path.join(search_dir, name)
                canonical_path = _canonical_mount_path(vol_path)
                if canonical_path in seen or not os.path.isdir(vol_path):
                    continue
                seen.add(canonical_path)
                try:
                    if _has_ipod_control(vol_path):
                        candidates.append((vol_path, name))
                except PermissionError:
                    continue

    logger.debug(
        "iPod volume discovery: platform=%s count=%d mounts=%s",
        sys.platform,
        len(candidates),
        ", ".join(display for _path, display in candidates) or "none",
    )
    return candidates


def _identity_dedup_key(ipod: DeviceInfo) -> tuple[str, str] | None:
    """Return a strong duplicate key for one physical device, if available."""
    try:
        from .sysinfo import normalize_guid
    except Exception:
        normalize_guid = None

    for field in ("firewire_guid", "usb_serial"):
        value = getattr(ipod, field, "")
        normalized = (
            normalize_guid(value)
            if normalize_guid is not None
            else str(value or "").strip().upper()
        )
        if normalized:
            return "guid", normalized

    serial = str(getattr(ipod, "serial", "") or "").strip().upper()
    if serial:
        return "serial", serial

    path = str(getattr(ipod, "path", "") or "")
    if path:
        return "path", _canonical_mount_path(path)

    return None


def _deduplicate_ipods(ipods: list[DeviceInfo]) -> list[DeviceInfo]:
    """Collapse duplicate mount aliases that identify as the same iPod."""
    deduped: list[DeviceInfo] = []
    seen: dict[tuple[str, str], DeviceInfo] = {}
    for ipod in ipods:
        key = _identity_dedup_key(ipod)
        if key is None:
            deduped.append(ipod)
            continue

        existing = seen.get(key)
        if existing is not None:
            logger.debug(
                "Skipping duplicate iPod mount alias: kept=%s skipped=%s key=%s:%s",
                existing.path,
                ipod.path,
                key[0],
                key[1],
            )
            continue

        seen[key] = ipod
        deduped.append(ipod)
    return deduped


# ── macOS: BSD name → USB serial mapping via ioreg text parsing ────────
#
# ioreg's plist (-a) format does NOT include "BSD Name" on child IOMedia
# nodes, but the text format does.  We parse the text output to build a
# mapping from BSD whole-disk name (e.g. "disk4") to the owning USB
# device's serial number.  A second (plist) query then gives us the
# full device properties keyed by serial.
#
# Cache is built once per scan cycle and cleared at the end of
# scan_for_ipods().

_macos_bsd_to_serial: dict[str, str] | None = None
_macos_serial_to_dev: dict[str, dict] | None = None
_macos_cache_lock = threading.Lock()


def _clear_macos_usb_cache() -> None:
    """Clear cached macOS USB maps between scan/identify cycles."""
    global _macos_bsd_to_serial, _macos_serial_to_dev
    with _macos_cache_lock:
        _macos_bsd_to_serial = None
        _macos_serial_to_dev = None


def _parse_macos_ioreg_bsd_serials(text: str) -> dict[str, str]:
    """Pair iPod BSD whole-disk names with their owning USB serial numbers.

    The text ioreg output for iPod nodes looks like::

        +-o iPod@01130000  <class IOUSBHostDevice, ...>
          |   "USB Serial Number" = "000A270018A1F847"
          |   "idProduct" = 4704
          ...
          +-o Apple iPod Media  <class IOMedia, ...>
          |   "BSD Name" = "disk4"

    We track the most recent ``"USB Serial Number"`` seen.  When we hit an
    ``"Apple iPod Media"`` entry followed by a ``"BSD Name"``, we pair the
    disk with the remembered serial — the iPod media node is a descendant
    of its owning USB device, so the iPod's serial is the latest one seen.

    Only iPod media disks are paired; serials of unrelated Apple devices
    (keyboards, AirPods receivers, iPhones, hubs) are ignored.
    """
    import re as _re

    bsd_map: dict[str, str] = {}
    current_serial: str = ""
    pending_serial: str = ""
    for line in text.splitlines():
        m_serial = _re.search(r'"USB Serial Number"\s*=\s*"([^"]+)"', line)
        if m_serial:
            current_serial = (
                m_serial.group(1).replace(" ", "").strip().upper()
            )
            continue
        if "Apple iPod Media" in line:
            pending_serial = current_serial
            continue
        # BSD Name on IOMedia child
        m = _re.search(r'"BSD Name"\s*=\s*"(disk\d+)"', line)
        if m and pending_serial:
            bsd_map[m.group(1)] = pending_serial
            pending_serial = ""
    return bsd_map


def _build_macos_usb_cache() -> None:
    """Build both caches from ioreg in one shot.

    Caller must hold ``_macos_cache_lock``.
    """
    global _macos_bsd_to_serial, _macos_serial_to_dev

    import plistlib
    import subprocess

    bsd_map: dict[str, str] = {}
    dev_map: dict[str, dict] = {}

    def _collect_usb_devices(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                _collect_usb_devices(item)
            return
        if not isinstance(node, dict):
            return

        if node.get("idVendor", 0) == 0x05AC:
            serial = (
                node.get("USB Serial Number", "")
                or node.get("kUSBSerialNumberString", "")
            )
            key = str(serial).replace(" ", "").strip().upper()
            if key:
                dev_map[key] = node

        for child in node.get("IORegistryEntryChildren") or []:
            _collect_usb_devices(child)

    # ── 1. Text parse: map BSD whole-disk → USB serial ─────────────────
    try:
        proc = subprocess.run(
            ["ioreg", "-r", "-c", "IOMedia"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=8,
        )
        if proc.returncode == 0 and proc.stdout:
            bsd_map = _parse_macos_ioreg_bsd_serials(proc.stdout)
    except subprocess.TimeoutExpired:
        logger.warning("macOS: ioreg text parse timed out")
    except Exception as e:
        logger.debug("macOS: ioreg text parse failed: %s", e)

    # ── 2. Plist query: full device properties keyed by serial ─────────
    try:
        proc = subprocess.run(
            ["ioreg", "-a", "-r", "-c", "IOUSBHostDevice"],
            capture_output=True, timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            parsed = plistlib.loads(proc.stdout)
            _collect_usb_devices(parsed)
    except Exception as e:
        logger.debug("ioreg plist query failed: %s", e)

    if bsd_map:
        logger.debug("macOS: BSD→serial map: %s", bsd_map)

    _macos_bsd_to_serial = bsd_map
    _macos_serial_to_dev = dev_map


def _probe_hardware_macos(mount_path: str) -> dict:
    """
    macOS hardware probing via ioreg + diskutil.

    **Matching strategy**: ``diskutil info`` gives the BSD whole-disk name
    for each volume.  A text-format ``ioreg`` query maps BSD names to USB
    serial numbers (because the text format exposes "BSD Name" on IOMedia
    children, while the plist format does not).  A second plist query gives
    full device properties (PID, serial, firmware) keyed by serial.

    This correctly associates each volume with its own USB device even when
    multiple iPods are connected, without relying on SysInfo files.
    """
    import plistlib
    import subprocess

    result: dict = {}

    # ── Step 1: Confirm USB bus and get BSD whole-disk via diskutil ─────
    bsd_whole_disk: str | None = None
    try:
        proc = subprocess.run(
            ["diskutil", "info", "-plist", mount_path],
            capture_output=True, timeout=10,
        )
        if proc.returncode == 0:
            disk_info = plistlib.loads(proc.stdout)
            if disk_info.get("BusProtocol") != "USB":
                logger.debug(
                    "macOS probe: %s is not on USB (protocol=%s)",
                    mount_path, disk_info.get("BusProtocol"),
                )
                return result
            bsd_whole_disk = disk_info.get("ParentWholeDisk")
    except Exception as e:
        logger.debug("diskutil info failed for %s: %s", mount_path, e)

    # ── Step 2: Ensure the ioreg caches are built ──────────────────────
    with _macos_cache_lock:
        if _macos_bsd_to_serial is None or _macos_serial_to_dev is None:
            _build_macos_usb_cache()
        bsd_map = _macos_bsd_to_serial or {}
        dev_map = _macos_serial_to_dev or {}

    if not dev_map:
        logger.debug("macOS probe: no Apple USB devices found in ioreg")
        return result

    # ── Step 3: Match this volume's BSD name → USB serial → device ─────
    target_dev: dict | None = None

    if bsd_whole_disk and bsd_whole_disk in bsd_map:
        serial_key = bsd_map[bsd_whole_disk]
        target_dev = dev_map.get(serial_key)
        if target_dev:
            logger.debug(
                "macOS probe: %s → %s → FW GUID %s → PID 0x%04X",
                mount_path, bsd_whole_disk, serial_key,
                target_dev.get("idProduct", 0),
            )

    # Fallback: if only one USB device, use it directly
    if not target_dev and len(dev_map) == 1:
        target_dev = next(iter(dev_map.values()))

    if not target_dev:
        logger.debug(
            "macOS probe: could not match %s (bsd=%s) to any Apple "
            "USB device", mount_path, bsd_whole_disk or "unknown",
        )
        return result

    # ── Step 4: Extract device info ────────────────────────────────────
    pid = target_dev.get("idProduct", 0)
    if pid:
        result["usb_pid"] = pid
        model_info = USB_PID_TO_MODEL.get(pid)
        if model_info:
            result["model_family"] = model_info[0]
            result["generation"] = model_info[1]

    # The USB serial number for iPods is the FireWire GUID (16 hex
    # chars), NOT the Apple serial number.  Store it only as
    # firewire_guid — the real Apple serial comes from SysInfo.
    usb_serial = (target_dev.get("USB Serial Number", "") or target_dev.get("kUSBSerialNumberString", ""))
    if usb_serial:
        clean = usb_serial.replace(" ", "").strip()
        if len(clean) == 16:
            try:
                bytes.fromhex(clean)
                result["firewire_guid"] = clean.upper()
                logger.debug("macOS probe: USB serial is FW GUID: %s", clean.upper())
            except ValueError:
                pass

    bcd = target_dev.get("bcdDevice", 0)
    if bcd:
        major = (bcd >> 8) & 0xFF
        minor = bcd & 0xFF
        result["firmware"] = f"{major}.{minor:02d}"

    return result


def _linux_find_block_device(mount_path: str) -> str | None:
    """Resolve a mount path to its block device (e.g. ``/dev/sdb1``).

    Tries three strategies in order:

    1. ``findmnt`` — present on all modern distros (util-linux), handles
       paths with spaces, special characters, and bind mounts correctly.
    2. ``/proc/mounts`` with octal-escape decoding — the kernel escapes
       spaces as ``\\040``, tabs as ``\\011``, etc.  Previous code compared
       the raw escaped field to the unescaped *mount_path*, which failed for
       mount points containing spaces
    3. ``lsblk --json`` — robust JSON output, handles spaces in mount points.
    """
    import re as _re

    # ── Strategy 1: findmnt (best, handles all edge cases) ─────────
    try:
        cp = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", "--target", mount_path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=5,
        )
        if cp.returncode == 0:
            dev = cp.stdout.strip().split("\n")[0].strip()
            if dev.startswith("/dev/"):
                logger.debug("Linux block device via findmnt: %s", dev)
                return dev
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # ── Strategy 2: /proc/mounts with octal-escape decode ──────────
    def _decode_mount_octal(field: str) -> str:
        """Decode octal escapes (\\040 → space, \\011 → tab, etc.)."""
        return _re.sub(
            r"\\([0-7]{3})",
            lambda m: chr(int(m.group(1), 8)),
            field,
        )

    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    decoded_mount = _decode_mount_octal(parts[1])
                    if decoded_mount == mount_path:
                        dev = parts[0]
                        if dev.startswith("/dev/"):
                            logger.debug("Linux block device via /proc/mounts: %s", dev)
                            return dev
    except OSError:
        pass

    # ── Strategy 3: lsblk JSON ─────────────────────────────────────
    try:
        import json as _json
        cp = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,MOUNTPOINT"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=5,
        )
        if cp.returncode == 0:
            data = _json.loads(cp.stdout)
            for dev_entry in data.get("blockdevices", []):
                for child in dev_entry.get("children", []):
                    mp = child.get("mountpoint") or ""
                    if mp == mount_path:
                        name = child.get("name", "")
                        if name:
                            logger.debug("Linux block device via lsblk: /dev/%s", name)
                            return f"/dev/{name}"
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    return None


def _linux_usb_info_from_udevadm(device: str) -> dict:
    """Extract USB identity fields via ``udevadm info``.

    Returns a dict that may contain *usb_pid*, *firewire_guid*,
    *model_family*, and *generation*.  Non-destructive — does not detach
    drivers or require root.
    """
    result: dict = {}
    try:
        cp = subprocess.run(
            ["udevadm", "info", "--query=property", "--name", device],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=5,
        )
        if cp.returncode != 0:
            return result

        props: dict[str, str] = {}
        for line in cp.stdout.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                props[k.strip()] = v.strip()

        # Vendor check — only proceed for Apple devices
        id_vendor = props.get("ID_VENDOR_ID", "")
        if id_vendor != "05ac":
            logger.debug("Linux udevadm %s: not Apple (vendor=%s)", device, id_vendor or "missing")
            return result

        # USB PID
        id_model = props.get("ID_MODEL_ID", "")
        if id_model:
            try:
                pid = int(id_model, 16)
                result["usb_pid"] = pid
                model_info = USB_PID_TO_MODEL.get(pid)
                if model_info:
                    result["model_family"] = model_info[0]
                    result["generation"] = model_info[1]
            except ValueError:
                pass

        # USB serial — on iPods this is the 16-hex-char FireWire GUID
        usb_serial = props.get("ID_SERIAL_SHORT", "")
        if usb_serial:
            clean = usb_serial.replace(" ", "")
            if len(clean) == 16:
                try:
                    bytes.fromhex(clean)
                    result["firewire_guid"] = clean.upper()
                except ValueError:
                    pass

        if result:
            logger.debug("Linux udevadm info: %s", result)

    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return result


def _linux_usb_info_from_sysfs(base_disk: str) -> dict:
    """Walk sysfs from a block device up to the USB ancestor.

    Returns a dict that may contain *usb_pid*, *firewire_guid*,
    *model_family*, and *generation*.
    """
    result: dict = {}

    sysfs_path = f"/sys/block/{base_disk}/device"
    if not os.path.exists(sysfs_path):
        return result

    current = os.path.realpath(sysfs_path)
    for _ in range(8):
        vendor_file = os.path.join(current, "idVendor")
        if os.path.exists(vendor_file):
            with open(vendor_file) as vf:
                vendor = vf.read().strip()
            if vendor == "05ac":  # Apple
                # Read product ID
                product_file = os.path.join(current, "idProduct")
                if os.path.exists(product_file):
                    with open(product_file) as pf:
                        product = pf.read().strip()
                    try:
                        pid = int(product, 16)
                        result["usb_pid"] = pid
                        model_info = USB_PID_TO_MODEL.get(pid)
                        if model_info:
                            result["model_family"] = model_info[0]
                            result["generation"] = model_info[1]
                    except ValueError:
                        pass

                # Read USB serial — on iPods this is the FireWire
                # GUID (16 hex chars), not the Apple serial number.
                serial_file = os.path.join(current, "serial")
                if os.path.exists(serial_file):
                    with open(serial_file) as sf:
                        usb_serial = sf.read().strip()
                    if usb_serial:
                        clean = usb_serial.replace(" ", "")
                        if len(clean) == 16:
                            try:
                                bytes.fromhex(clean)
                                result["firewire_guid"] = clean.upper()
                                logger.debug("Linux sysfs: USB serial is FW GUID: %s", clean.upper())
                            except ValueError:
                                pass
                break

        current = os.path.dirname(current)

    return result


def _linux_usb_info_from_bus_scan(base_disk: str) -> dict:
    """Scan ``/sys/bus/usb/devices/`` for an Apple device matching *base_disk*.

    This is a last-resort fallback when neither udevadm nor the sysfs device
    walk finds USB identity fields.  It works by:

      1. Following ``/sys/block/{base_disk}`` real path to find which USB bus
         address the block device lives under (e.g. ``usb2/2-1``).
      2. Scanning ``/sys/bus/usb/devices/`` for an entry whose ``idVendor``
         is ``05ac`` (Apple) and whose real path is an ancestor of the block
         device's real path.
      3. Reading ``idProduct`` and ``serial`` from that USB device.

    Returns a dict that may contain *usb_pid*, *firewire_guid*,
    *model_family*, and *generation*.
    """
    result: dict = {}

    block_link = f"/sys/block/{base_disk}"
    if not os.path.exists(block_link):
        return result

    block_real = os.path.realpath(block_link)

    usb_devices_dir = "/sys/bus/usb/devices"
    if not os.path.isdir(usb_devices_dir):
        return result

    try:
        entries = os.listdir(usb_devices_dir)
    except OSError:
        return result

    for entry in entries:
        entry_path = os.path.join(usb_devices_dir, entry)
        vendor_file = os.path.join(entry_path, "idVendor")
        if not os.path.exists(vendor_file):
            continue
        try:
            with open(vendor_file) as vf:
                vendor = vf.read().strip()
        except OSError:
            continue
        if vendor != "05ac":
            continue

        # Check if this USB device is an ancestor of the block device
        usb_real = os.path.realpath(entry_path)
        if not block_real.startswith(usb_real + "/"):
            continue

        # Found the Apple USB device that owns this disk
        product_file = os.path.join(entry_path, "idProduct")
        if os.path.exists(product_file):
            try:
                with open(product_file) as pf:
                    product = pf.read().strip()
                pid = int(product, 16)
                result["usb_pid"] = pid
                model_info = USB_PID_TO_MODEL.get(pid)
                if model_info:
                    result["model_family"] = model_info[0]
                    result["generation"] = model_info[1]
            except (ValueError, OSError):
                pass

        serial_file = os.path.join(entry_path, "serial")
        if os.path.exists(serial_file):
            try:
                with open(serial_file) as sf:
                    usb_serial = sf.read().strip().replace(" ", "")
                if len(usb_serial) == 16:
                    bytes.fromhex(usb_serial)
                    result["firewire_guid"] = usb_serial.upper()
                    logger.debug("Linux USB bus scan: FW GUID: %s", usb_serial.upper())
            except (ValueError, OSError):
                pass

        if result:
            logger.debug("Linux USB bus scan: %s", result)
        break

    return result


def _probe_hardware_linux(mount_path: str) -> dict:
    """
    Linux hardware probing via sysfs / udevadm / findmnt.

    Traces the mount point → block device → USB device through multiple
    strategies to extract the USB PID, serial number, and FireWire GUID.

    Strategies (tried in order for each sub-task):

    Block device lookup:
      1. ``findmnt`` — handles paths with spaces and bind mounts
      2. ``/proc/mounts`` with octal-escape decoding
      3. ``lsblk --json``

    USB identity extraction:
      1. ``udevadm info`` on the partition device
      2. ``udevadm info`` on the parent disk device (Arch/CachyOS may not
         propagate USB properties to partition devices)
      3. sysfs walk — manual traversal from block device to USB ancestor
      4. USB bus scan — walk ``/sys/bus/usb/devices/`` for Apple devices
         matching this block device
    """
    import re as _re

    result: dict = {}

    try:
        device = _linux_find_block_device(mount_path)
        if not device:
            logger.debug("Linux probe: could not resolve block device for %s", mount_path)
            return result

        # Get the base disk name (e.g., sdb from /dev/sdb1)
        dev_name = os.path.basename(device)
        base_disk = _re.sub(r"\d+$", "", dev_name)  # sdb1 → sdb

        # ── Strategy 1: udevadm info on partition ─────────────────
        result = _linux_usb_info_from_udevadm(device)

        # ── Strategy 2: udevadm info on parent disk ──────────────
        #   On Arch-based distros (CachyOS, Manjaro, EndeavourOS), udev
        #   rules may not propagate USB identity properties (ID_VENDOR_ID,
        #   ID_MODEL_ID, ID_SERIAL_SHORT) from the USB device to its
        #   partition children.  Querying the parent disk directly works.
        if not result and base_disk != dev_name:
            result = _linux_usb_info_from_udevadm(f"/dev/{base_disk}")

        # ── Strategy 3: sysfs walk ────────────────────────────────
        if not result:
            result = _linux_usb_info_from_sysfs(base_disk)

        # ── Strategy 4: USB bus scan (last resort) ────────────────
        if not result:
            result = _linux_usb_info_from_bus_scan(base_disk)

    except Exception as e:
        logger.debug("Linux hardware probe failed: %s", e)

    return result


def _identify_via_usb_for_drive(drive_letter: str) -> dict | None:
    """
    Identify the iPod connected at a specific drive letter via WMI + USB registry.

    Uses WMI to trace:  drive letter → Win32_DiskDrive → PNPDeviceID
    then cross-references the USBSTOR instance ID to the parent USB device
    to get the actual PID for THIS specific device (not stale registry entries).

    Returns dict with keys: firewire_guid, serial, firmware, usb_pid,
                             model_family, generation
    """
    if sys.platform != "win32":
        return None

    import subprocess

    result: dict = {}

    # ── Step 1: Use WMI to get the disk PNPDeviceID for this drive letter ──
    try:
        # Query WMI to find the disk drive associated with this drive letter.
        # Chain: LogicalDisk → Partition → DiskDrive
        ps_cmd = (
            f"$logdisk = Get-WmiObject Win32_LogicalDisk | "
            f"Where-Object {{ $_.DeviceID -eq '{drive_letter}:' }}; "
            f"if ($logdisk) {{ "
            f"  $part = Get-WmiObject -Query \"ASSOCIATORS OF "
            f"{{Win32_LogicalDisk.DeviceID='$($logdisk.DeviceID)'}} "
            f"WHERE AssocClass=Win32_LogicalDiskToPartition\"; "
            f"  if ($part) {{ "
            f"    $disk = Get-WmiObject -Query \"ASSOCIATORS OF "
            f"{{Win32_DiskPartition.DeviceID='$($part.DeviceID)'}} "
            f"WHERE AssocClass=Win32_DiskDriveToDiskPartition\"; "
            f"    if ($disk) {{ "
            f"      Write-Output \"PNP:$($disk.PNPDeviceID)\"; "
            f"      Write-Output \"SERIAL:$($disk.SerialNumber.Trim())\"; "
            f"      Write-Output \"MODEL:$($disk.Model)\" "
            f"    }} "
            f"  }} "
            f"}}"
        )
        wmi_result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
            **_SP_KWARGS,
        )
        pnp_id = ""
        for line in wmi_result.stdout.strip().splitlines():
            line = line.strip()
            if line.startswith("PNP:"):
                pnp_id = line[4:]
            elif line.startswith("SERIAL:"):
                wmi_serial = line[7:].strip()
                if wmi_serial:
                    # WMI disk serial for iPods is the FireWire GUID
                    # (16 hex chars), not the Apple serial.
                    wmi_clean = wmi_serial.replace(" ", "")
                    if len(wmi_clean) == 16:
                        try:
                            bytes.fromhex(wmi_clean)
                            result.setdefault("firewire_guid", wmi_clean.upper())
                            logger.debug("WMI: serial is FW GUID: %s", wmi_clean.upper())
                        except ValueError:
                            result["serial"] = wmi_serial
                            logger.debug("WMI: non-hex serial (Apple?): %s", wmi_serial)
                else:
                    result["serial"] = wmi_serial
                    logger.debug("WMI: non-GUID serial (Apple?): %s", wmi_serial)
            elif line.startswith("MODEL:"):
                pass  # Just confirms it's an iPod

        if not pnp_id:
            logger.debug("Drive %s: no WMI disk drive found", drive_letter)
            return result if result else None

    except Exception as e:
        logger.debug("WMI query failed for drive %s: %s", drive_letter, e)
        return None

    # ── Step 2: Extract info from the USBSTOR PNPDeviceID ──
    # Format varies:
    #   Simple:    USBSTOR\DISK&VEN_APPLE&PROD_IPOD&REV_1.62\000A270018A1F847&0
    #   Composite: USBSTOR\DISK&VEN_APPLE&PROD_IPOD&REV_1.62\8&2F161EF4&0&000A2700138A422D&0
    if "USBSTOR" in pnp_id.upper():
        parts = pnp_id.split("\\")
        if len(parts) >= 2:
            device_desc = parts[1] if len(parts) > 1 else ""
            instance_id = parts[2] if len(parts) > 2 else ""

            # Extract firmware revision from "REV_x.xx"
            if "REV_" in device_desc.upper():
                rev_part = device_desc.upper().split("REV_")[-1]
                result["firmware"] = rev_part

            # Extract FireWire GUID from instance ID
            guid = _extract_guid_from_instance_id(instance_id)
            if guid:
                result["firewire_guid"] = guid
                logger.debug("WMI USBSTOR: FW GUID from instance ID: %s", guid)

    # ── Step 3: Find the USB PID for THIS specific device ──
    # Cross-reference the USBSTOR instance to its parent USB device.
    # We use the extracted GUID (which is the USB iSerialNumber) to find
    # the matching USB\VID_05AC&PID_xxxx\<guid> entry in the registry.
    try:
        import winreg

        # Use the GUID as the cross-reference key (it appears as the USB
        # device instance ID).  Falls back to scanning all segments.
        guid_for_match = result.get("firewire_guid", "")
        if not guid_for_match and "\\" in pnp_id:
            guid_for_match = _extract_guid_from_instance_id(
                pnp_id.split("\\")[-1]
            )

        if guid_for_match:
            usb_key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Enum\USB"
            )
            try:
                k = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(usb_key, k)
                        k += 1
                    except OSError:
                        break

                    upper = subkey_name.upper()
                    if "VID_05AC" not in upper or "PID_" not in upper:
                        continue
                    # Skip composite interface sub-devices (MI_xx)
                    if "MI_" in upper:
                        continue

                    # Check if THIS USB device has our USBSTOR instance ID
                    try:
                        pid_key = winreg.OpenKey(usb_key, subkey_name)
                    except OSError:
                        continue

                    try:
                        m = 0
                        while True:
                            try:
                                usb_instance = winreg.EnumKey(pid_key, m)
                                m += 1
                            except OSError:
                                break

                            # Match the USBSTOR GUID to the USB instance
                            if guid_for_match.upper() in usb_instance.upper():
                                pid_str = upper.split("PID_")[1][:4]
                                try:
                                    pid = int(pid_str, 16)
                                    result["usb_pid"] = pid
                                    model_info = USB_PID_TO_MODEL.get(pid)
                                    if model_info:
                                        result["model_family"] = model_info[0]
                                        result["generation"] = model_info[1]
                                    logger.debug(
                                        "Drive %s: matched USB PID 0x%04X via "
                                        "GUID %s",
                                        drive_letter, pid, guid_for_match,
                                    )
                                except ValueError:
                                    pass
                                break  # Found our device
                    finally:
                        winreg.CloseKey(pid_key)

                    # Stop scanning once we found our match
                    if "usb_pid" in result:
                        break

            finally:
                winreg.CloseKey(usb_key)

    except OSError:
        pass

    return result if result else None


# ── Direct IOCTL detection (no WMI / PowerShell) ──────────────────────────

# Windows constants for CreateFileW / DeviceIoControl
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x01
_FILE_SHARE_WRITE = 0x02
_OPEN_EXISTING = 3
_IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400


def _identify_via_direct_ioctl(drive_letter: str) -> dict | None:
    """
    Query the USB storage device directly via IOCTL_STORAGE_QUERY_PROPERTY.

    Opens the drive handle (``\\\\.\\X:``) and sends a STORAGE_PROPERTY_QUERY
    for StorageDeviceProperty.  Under the hood Windows issues a SCSI INQUIRY
    to the device and returns the parsed result in a STORAGE_DEVICE_DESCRIPTOR.

    This bypasses WMI, PowerShell, and the USB registry entirely — the
    response comes straight from the device firmware.

    Returns a dict with: vendor, product, serial, firmware, bus_type,
                          model_family, generation (if PID can be inferred).

    Only works on Windows (requires kernel32 / DeviceIoControl).
    """
    if sys.platform != "win32":
        return None

    _setup_win32_prototypes()

    result: dict = {}
    path = f"\\\\.\\{drive_letter}:"

    handle = ctypes.windll.kernel32.CreateFileW(  # type: ignore[attr-defined]
        path,
        _GENERIC_READ,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        _OPEN_EXISTING,
        0,
        None,
    )
    INVALID = ctypes.c_void_p(-1).value
    if handle == INVALID:
        logger.debug("Direct IOCTL: cannot open %s (access denied?)", path)
        return None

    try:
        # STORAGE_PROPERTY_QUERY:
        #   PropertyId  = 0  (StorageDeviceProperty)
        #   QueryType   = 0  (PropertyStandardQuery)
        #   AdditionalParameters[1] = 0
        query = struct.pack("<III", 0, 0, 0)  # 12 bytes

        buf_size = 1024
        out_buf = (ctypes.c_ubyte * buf_size)()
        returned = wt.DWORD(0)

        ok = ctypes.windll.kernel32.DeviceIoControl(  # type: ignore[attr-defined]
            handle,
            _IOCTL_STORAGE_QUERY_PROPERTY,
            query,
            len(query),
            out_buf,
            buf_size,
            ctypes.byref(returned),
            None,
        )

        if not ok:
            err = ctypes.get_last_error()
            logger.debug("Direct IOCTL: DeviceIoControl failed on %s (err=%d)",
                         path, err)
            return None

        data = bytes(out_buf[: returned.value])
        if len(data) < 36:
            logger.debug("Direct IOCTL: response too short (%d bytes)", len(data))
            return None

        # Parse STORAGE_DEVICE_DESCRIPTOR
        #  0: Version        (DWORD)
        #  4: Size           (DWORD)
        #  8: DeviceType     (BYTE)
        #  9: DeviceTypeMod  (BYTE)
        # 10: RemovableMedia (BOOLEAN)
        # 11: CommandQueueing (BOOLEAN)
        # 12: VendorIdOffset (DWORD)
        # 16: ProductIdOffset(DWORD)
        # 20: ProductRevisionOffset (DWORD)
        # 24: SerialNumberOffset    (DWORD)
        # 28: BusType        (DWORD) — STORAGE_BUS_TYPE enum
        # 32: RawPropertiesLength (DWORD)
        # 36: RawDeviceProperties[1] (variable)

        def _read_str(offset_pos: int) -> str:
            if offset_pos + 4 > len(data):
                return ""
            off = struct.unpack_from("<I", data, offset_pos)[0]
            if off == 0 or off >= len(data):
                return ""
            # Find null terminator
            end = off
            while end < len(data) and data[end] != 0:
                end += 1
            return data[off:end].decode("ascii", errors="replace").strip()

        vendor = _read_str(12)
        product = _read_str(16)
        revision = _read_str(20)
        serial = _read_str(24)
        bus_type = struct.unpack_from("<I", data, 28)[0] if len(data) >= 32 else -1
        removable = bool(data[10]) if len(data) > 10 else False

        logger.debug(
            "Direct IOCTL %s: vendor=%r product=%r revision=%r serial=%r "
            "bus_type=%d removable=%s",
            drive_letter, vendor, product, revision, serial, bus_type, removable,
        )

        # Validate it's actually an Apple iPod
        if vendor.lower() not in ("apple", "apple inc.", "apple inc"):
            logger.debug("Direct IOCTL: vendor is %r, not Apple — skipping",
                         vendor)
            return None

        result["vendor"] = vendor
        result["product"] = product
        result["bus_type"] = bus_type

        if revision:
            result["firmware"] = revision

        if serial:
            # The IOCTL serial for iPods is typically the FireWire GUID
            # (16 hex chars), NOT the Apple serial number.  Store as
            # firewire_guid only — the real Apple serial comes from SysInfo.
            clean = serial.replace(" ", "").strip()
            if len(clean) == 16:
                try:
                    bytes.fromhex(clean)
                    result["firewire_guid"] = clean.upper()
                    logger.debug("Direct IOCTL: serial is FW GUID: %s", clean.upper())
                except ValueError:
                    # Not a hex string — might be a real Apple serial
                    result["serial"] = serial
                    logger.debug("Direct IOCTL: non-hex serial (Apple?): %s", serial)
            else:
                # Non-16-char serial — could be an actual Apple serial
                result["serial"] = serial
                logger.debug("Direct IOCTL: non-GUID serial (Apple?): %s", serial)

    finally:
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]

    # ── Walk the PnP device tree to get FireWire GUID and USB PID ──
    # The SCSI layer gives us vendor/product/serial/firmware, but the
    # FireWire GUID (needed for hash generation) and the USB PID live
    # in the PnP device tree above the SCSI device.
    tree_info = _walk_device_tree(drive_letter)
    if tree_info:
        for key in (
            "usb_vid",
            "usbstor_instance_id",
            "usb_parent_instance_id",
            "usb_grandparent_instance_id",
        ):
            if tree_info.get(key):
                result[key] = tree_info[key]
        if tree_info.get("firewire_guid"):
            result["firewire_guid"] = tree_info["firewire_guid"]
            logger.debug(
                "Drive %s: FW GUID from device tree: %s",
                drive_letter, tree_info["firewire_guid"],
            )
        if tree_info.get("usb_pid"):
            result["usb_pid"] = tree_info["usb_pid"]
        if tree_info.get("model_family"):
            result.setdefault("model_family", tree_info["model_family"])
        if tree_info.get("generation"):
            result.setdefault("generation", tree_info["generation"])

    return result if result else None


# ── PnP device tree walk via SetupAPI + cfgmgr32 ──────────────────────────

# These constants / structs are scoped to Windows-only. The functions that
# use them already guard with ``sys.platform != "win32"``.

_IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
_DIGCF_PRESENT = 0x02
_DIGCF_DEVICEINTERFACE = 0x10
_CR_SUCCESS = 0


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("InterfaceClassGuid", _GUID),
        ("Flags", ctypes.c_ulong),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("ClassGuid", _GUID),
        ("DevInst", ctypes.c_ulong),
        ("Reserved", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _STORAGE_DEVICE_NUMBER(ctypes.Structure):
    _fields_ = [
        ("DeviceType", ctypes.c_ulong),
        ("DeviceNumber", ctypes.c_ulong),
        ("PartitionNumber", ctypes.c_ulong),
    ]


# {53F56307-B6BF-11D0-94F2-00A0C91EFB8B}
_GUID_DEVINTERFACE_DISK = _GUID(
    0x53F56307, 0xB6BF, 0x11D0,
    (ctypes.c_ubyte * 8)(0x94, 0xF2, 0x00, 0xA0, 0xC9, 0x1E, 0xFB, 0x8B),
)


def _setup_win32_prototypes() -> None:
    """
    Declare proper argtypes/restype for Win32 functions used by the direct
    backend.  Without this, ctypes defaults to ``c_int`` return values which
    **truncate 64-bit handles** on 64-bit Windows — a silent, fatal bug.

    Called once on first use; subsequent calls are no-ops.
    """
    if getattr(_setup_win32_prototypes, "_done", False):
        return
    _setup_win32_prototypes._done = True  # type: ignore[attr-defined]

    k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    sa = ctypes.windll.setupapi  # type: ignore[attr-defined]
    cm = ctypes.windll.cfgmgr32  # type: ignore[attr-defined]

    # ── kernel32 ───────────────────────────────────────────────────────
    k32.CreateFileW.argtypes = [
        wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
        wt.DWORD, wt.DWORD, wt.HANDLE,
    ]
    k32.CreateFileW.restype = ctypes.c_void_p  # HANDLE (pointer-width)

    k32.DeviceIoControl.argtypes = [
        ctypes.c_void_p, wt.DWORD,
        ctypes.c_void_p, wt.DWORD,
        ctypes.c_void_p, wt.DWORD,
        ctypes.POINTER(wt.DWORD), ctypes.c_void_p,
    ]
    k32.DeviceIoControl.restype = wt.BOOL

    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.restype = wt.BOOL

    # ── setupapi ───────────────────────────────────────────────────────
    sa.SetupDiGetClassDevsW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, wt.HWND, wt.DWORD,
    ]
    sa.SetupDiGetClassDevsW.restype = ctypes.c_void_p  # HDEVINFO

    sa.SetupDiEnumDeviceInterfaces.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, wt.DWORD,
        ctypes.c_void_p,
    ]
    sa.SetupDiEnumDeviceInterfaces.restype = wt.BOOL

    sa.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, wt.DWORD,
        ctypes.POINTER(wt.DWORD), ctypes.c_void_p,
    ]
    sa.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL

    sa.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    sa.SetupDiDestroyDeviceInfoList.restype = wt.BOOL

    # ── cfgmgr32 ──────────────────────────────────────────────────────
    cm.CM_Get_Device_ID_Size.argtypes = [
        ctypes.POINTER(ctypes.c_ulong), ctypes.c_ulong, ctypes.c_ulong,
    ]
    cm.CM_Get_Device_ID_Size.restype = ctypes.c_ulong

    cm.CM_Get_Device_IDW.argtypes = [
        ctypes.c_ulong, ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
    ]
    cm.CM_Get_Device_IDW.restype = ctypes.c_ulong

    cm.CM_Get_Parent.argtypes = [
        ctypes.POINTER(ctypes.c_ulong), ctypes.c_ulong, ctypes.c_ulong,
    ]
    cm.CM_Get_Parent.restype = ctypes.c_ulong


def _walk_device_tree(drive_letter: str) -> dict:
    """
    Walk the Windows PnP device tree from a volume to its USB ancestor.

    Uses only Win32 APIs (SetupAPI + cfgmgr32) — no WMI, no PowerShell:

        Volume (``\\\\.\\D:``)
          → ``IOCTL_STORAGE_GET_DEVICE_NUMBER`` → DeviceNumber N
          → Enumerate ``GUID_DEVINTERFACE_DISK`` interfaces
          → Match by DeviceNumber → get ``DevInst``
          → ``CM_Get_Device_ID`` → USBSTOR instance ID (contains **FireWire GUID**)
          → ``CM_Get_Parent``   → USB device ID (contains **PID**)

    Returns dict with any of: ``firewire_guid``, ``usb_pid``,
    ``model_family``, ``generation``.
    """
    if sys.platform != "win32":
        return {}

    _setup_win32_prototypes()

    result: dict = {}
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    setupapi = ctypes.windll.setupapi  # type: ignore[attr-defined]
    cfgmgr32 = ctypes.windll.cfgmgr32  # type: ignore[attr-defined]

    INVALID = ctypes.c_void_p(-1).value  # 0xFFFFFFFFFFFFFFFF on 64-bit

    # ── Step 1: Get the physical device number for this volume ──────────
    vol_path = f"\\\\.\\{drive_letter}:"
    vol_handle = kernel32.CreateFileW(
        vol_path, _GENERIC_READ, _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None, _OPEN_EXISTING, 0, None,
    )
    if vol_handle == INVALID:
        return result

    try:
        sdn = _STORAGE_DEVICE_NUMBER()
        returned = wt.DWORD()
        ok = kernel32.DeviceIoControl(
            vol_handle, _IOCTL_STORAGE_GET_DEVICE_NUMBER,
            None, 0, ctypes.byref(sdn), ctypes.sizeof(sdn),
            ctypes.byref(returned), None,
        )
        if not ok:
            return result
        target_dev_num = sdn.DeviceNumber
    finally:
        kernel32.CloseHandle(vol_handle)

    logger.debug("Drive %s: physical device number = %d",
                 drive_letter, target_dev_num)

    # ── Step 2: Enumerate present disk interfaces, find matching one ───
    hDevInfo = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(_GUID_DEVINTERFACE_DISK), None, None,
        _DIGCF_PRESENT | _DIGCF_DEVICEINTERFACE,
    )
    if hDevInfo == INVALID:
        return result

    target_devinst = 0

    try:
        idx = 0
        while True:
            iface = _SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(_SP_DEVICE_INTERFACE_DATA)

            if not setupapi.SetupDiEnumDeviceInterfaces(
                hDevInfo, None, ctypes.byref(_GUID_DEVINTERFACE_DISK),
                idx, ctypes.byref(iface),
            ):
                break
            idx += 1

            # First call: get required buffer size (expected to fail with
            # ERROR_INSUFFICIENT_BUFFER — that's fine, we just need the size)
            required = wt.DWORD()
            devinfo = _SP_DEVINFO_DATA()
            devinfo.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                hDevInfo, ctypes.byref(iface), None, 0,
                ctypes.byref(required), ctypes.byref(devinfo),
            )
            if required.value == 0:
                continue

            # Allocate and fill SP_DEVICE_INTERFACE_DETAIL_DATA_W.
            # The struct has a DWORD cbSize followed by a WCHAR[] path.
            # cbSize must be set to 8 on 64-bit Windows, 6 on 32-bit.
            buf_size = required.value
            detail_buf = (ctypes.c_byte * buf_size)()
            cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            struct.pack_into("<I", detail_buf, 0, cb_size)

            devinfo2 = _SP_DEVINFO_DATA()
            devinfo2.cbSize = ctypes.sizeof(_SP_DEVINFO_DATA)
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                hDevInfo, ctypes.byref(iface), detail_buf, buf_size,
                None, ctypes.byref(devinfo2),
            ):
                continue

            # Device path is a null-terminated wide string at offset 4
            device_path = ctypes.wstring_at(
                ctypes.addressof(detail_buf) + 4,
            )

            # Open the disk device and compare its device number
            dev_handle = kernel32.CreateFileW(
                device_path, 0, _FILE_SHARE_READ | _FILE_SHARE_WRITE,
                None, _OPEN_EXISTING, 0, None,
            )
            if dev_handle == INVALID:
                continue

            try:
                sdn2 = _STORAGE_DEVICE_NUMBER()
                returned2 = wt.DWORD()
                ok2 = kernel32.DeviceIoControl(
                    dev_handle, _IOCTL_STORAGE_GET_DEVICE_NUMBER,
                    None, 0, ctypes.byref(sdn2), ctypes.sizeof(sdn2),
                    ctypes.byref(returned2), None,
                )
            finally:
                kernel32.CloseHandle(dev_handle)

            if ok2 and sdn2.DeviceNumber == target_dev_num:
                target_devinst = devinfo2.DevInst
                break
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hDevInfo)

    if not target_devinst:
        logger.debug("Drive %s: no matching disk in device tree",
                     drive_letter)
        return result

    # ── Step 3: Get USBSTOR instance ID → extract FireWire GUID ────────
    # e.g. "USBSTOR\DISK&VEN_APPLE&PROD_IPOD&REV_1.62\000A270018A1F847&0"
    id_len = ctypes.c_ulong()
    if cfgmgr32.CM_Get_Device_ID_Size(
        ctypes.byref(id_len), target_devinst, 0,
    ) != _CR_SUCCESS:
        return result

    dev_id_buf = ctypes.create_unicode_buffer(id_len.value + 1)
    if cfgmgr32.CM_Get_Device_IDW(
        target_devinst, dev_id_buf, id_len.value + 1, 0,
    ) != _CR_SUCCESS:
        return result

    usbstor_id = dev_id_buf.value
    result["usbstor_instance_id"] = usbstor_id
    logger.debug("Drive %s: USBSTOR instance = %s", drive_letter, usbstor_id)

    if "USBSTOR" in usbstor_id.upper():
        parts = usbstor_id.split("\\")
        if len(parts) >= 3:
            guid = _extract_guid_from_instance_id(parts[2])
            if guid:
                result["firewire_guid"] = guid
                logger.debug(
                    "Drive %s: FW GUID from USBSTOR instance: %s",
                    drive_letter, guid,
                )

    # ── Step 4: Walk up to USB parent → extract PID ────────────────────
    # For simple USB devices the parent is the USB device node:
    #   USB\VID_05AC&PID_1260\000A270018A1F847
    # For composite USB devices the immediate parent is an interface node:
    #   USB\VID_05AC&PID_1261&MI_00\7&2551D7E5&0
    # In both cases we get the PID.  For composite devices, walk up one
    # more level to reach the actual USB device node if we still need
    # the GUID (fallback if USBSTOR extraction didn't yield it).
    parent = ctypes.c_ulong()
    if cfgmgr32.CM_Get_Parent(
        ctypes.byref(parent), target_devinst, 0,
    ) == _CR_SUCCESS:
        id_len2 = ctypes.c_ulong()
        if cfgmgr32.CM_Get_Device_ID_Size(
            ctypes.byref(id_len2), parent.value, 0,
        ) == _CR_SUCCESS:
            parent_buf = ctypes.create_unicode_buffer(id_len2.value + 1)
            if cfgmgr32.CM_Get_Device_IDW(
                parent.value, parent_buf, id_len2.value + 1, 0,
            ) == _CR_SUCCESS:
                usb_id = parent_buf.value
                result["usb_parent_instance_id"] = usb_id
                logger.debug("Drive %s: USB parent = %s",
                             drive_letter, usb_id)

                upper_id = usb_id.upper()
                if "VID_" in upper_id:
                    vid_str = upper_id.split("VID_")[1][:4]
                    try:
                        result["usb_vid"] = int(vid_str, 16)
                    except ValueError:
                        pass
                if "PID_" in upper_id:
                    pid_str = upper_id.split("PID_")[1][:4]
                    try:
                        pid = int(pid_str, 16)
                        result["usb_pid"] = pid
                        model_info = USB_PID_TO_MODEL.get(pid)
                        if model_info:
                            result["model_family"] = model_info[0]
                            result["generation"] = model_info[1]
                    except ValueError:
                        pass

                # Composite device: parent is USB\...&MI_xx\... (interface)
                # Walk up one more level to the real USB device node.
                # Its instance ID will have the GUID as a simple segment.
                if "MI_" in upper_id and not result.get("firewire_guid"):
                    grandparent = ctypes.c_ulong()
                    if cfgmgr32.CM_Get_Parent(
                        ctypes.byref(grandparent), parent.value, 0,
                    ) == _CR_SUCCESS:
                        gp_len = ctypes.c_ulong()
                        if cfgmgr32.CM_Get_Device_ID_Size(
                            ctypes.byref(gp_len), grandparent.value, 0,
                        ) == _CR_SUCCESS:
                            gp_buf = ctypes.create_unicode_buffer(
                                gp_len.value + 1
                            )
                            if cfgmgr32.CM_Get_Device_IDW(
                                grandparent.value, gp_buf,
                                gp_len.value + 1, 0,
                            ) == _CR_SUCCESS:
                                gp_id = gp_buf.value
                                result["usb_grandparent_instance_id"] = gp_id
                                logger.debug(
                                    "Drive %s: USB grandparent = %s",
                                    drive_letter, gp_id,
                                )
                                gp_parts = gp_id.split("\\")
                                if len(gp_parts) >= 3:
                                    gp_guid = _extract_guid_from_instance_id(
                                        gp_parts[2]
                                    )
                                    if gp_guid:
                                        result["firewire_guid"] = gp_guid
                                        logger.debug(
                                            "Drive %s: FW GUID from USB "
                                            "grandparent: %s",
                                            drive_letter, gp_guid,
                                        )

    return result


# ── Unified probing functions ──────────────────────────────────────────────


def _probe_hardware(mount_path: str, mount_name: str) -> dict:
    """
    Phase 1: Hardware probing — query the USB device for identification.

    Platform-specific:
      - **Windows**: Direct IOCTL + device tree walk, with WMI fallback.
      - **macOS**: system_profiler SPUSBDataType to find the Apple USB device.
      - **Linux**: sysfs traversal from block device to USB device.

    Returns a dict that may contain any of:
        vendor, product, serial, firmware, bus_type, firewire_guid,
        usb_pid, model_family, generation, _sources
    """
    result: dict = {}
    _hw_method = ""
    logger.debug(
        "Hardware probe start: mount=%s display=%s platform=%s",
        mount_path,
        mount_name,
        sys.platform,
    )

    if sys.platform == "win32":
        # On Windows, mount_name is "D:" — extract the drive letter
        drive_letter = mount_name[0] if mount_name and mount_name[0].isalpha() else ""
        if not drive_letter:
            logger.debug("Hardware probe result: mount=%s no drive letter", mount_path)
            return result

        # ── Primary: Direct IOCTL + device tree (fast, no subprocess) ──
        ioctl_info = _identify_via_direct_ioctl(drive_letter)
        if ioctl_info:
            result.update(ioctl_info)
            _hw_method = "ioctl"
            logger.debug("Hardware probe (direct): %s", result)

        # ── Fallback: WMI (only if direct gave us nothing useful) ──────
        if not result:
            logger.debug(
                "Direct probe failed for drive %s, falling back to WMI",
                drive_letter,
            )
            wmi_info = _identify_via_usb_for_drive(drive_letter)
            if wmi_info:
                result.update(wmi_info)
                _hw_method = "wmi"
                logger.debug("Hardware probe (WMI fallback): %s", result)

    elif sys.platform == "darwin":
        result = _probe_hardware_macos(mount_path)
        _hw_method = "ioreg"
        if result:
            logger.debug("Hardware probe (macOS): %s", result)

    else:
        result = _probe_hardware_linux(mount_path)
        _hw_method = "sysfs"
        if result:
            logger.debug("Hardware probe (Linux): %s", result)

    # Annotate per-field data sources for authority tracking
    if result and _hw_method:
        sources = result.setdefault("_sources", {})
        if result.get("firewire_guid"):
            # On Windows, FW GUID comes from device tree walk specifically
            sources["firewire_guid"] = (
                "device_tree" if _hw_method in ("ioctl", "wmi") else _hw_method
            )
        if result.get("serial"):
            sources["serial"] = _hw_method
        if result.get("firmware"):
            sources["firmware"] = _hw_method
        if result.get("usb_pid"):
            sources["usb_pid"] = (
                "device_tree" if _hw_method in ("ioctl", "wmi") else _hw_method
            )

    logger.debug(
        "Hardware probe result: mount=%s method=%s identity=[%s] sources=[%s]",
        mount_path,
        _hw_method or "none",
        format_fields(result, IDENTITY_FIELDS),
        format_sources(result.get("_sources", {}), SOURCE_FIELDS),
    )
    return result


def _probe_filesystem(ipod_path: str) -> dict:
    """
    Phase 2: Filesystem probing — read on-device files for identification.

    Reads SysInfo/SysInfoExtended and the iTunesDB header.  All file reads
    are independent and their results are merged.

    Returns a dict that may contain any of:
        model_number, model_family, generation, capacity, color,
        serial, firewire_guid, firmware, hashing_scheme
    """
    result: dict = {}

    filesystem_type = detect_filesystem_type(ipod_path)
    try:
        filesystem_profile = inspect_filesystem_profile(ipod_path)
    except Exception as exc:
        filesystem_profile = None
        logger.warning(
            "Could not capture scan-time iPod volume identity: mount=%s error=%s",
            ipod_path,
            exc,
        )
    if filesystem_profile is not None:
        filesystem_type = filesystem_type or filesystem_profile.filesystem_type
        if filesystem_profile.identity.is_complete:
            result["volume_identity_key"] = volume_lock_key(filesystem_profile)
            result.setdefault("_sources", {})["volume_identity_key"] = (
                "mounted_volume_identity"
            )
            logger.info(
                "iPod mounted volume identity captured: mount=%s identity=%s",
                ipod_path,
                result["volume_identity_key"],
            )
    if filesystem_type:
        logger.info(
            "iPod mounted filesystem detected: mount=%s filesystem=%s",
            ipod_path,
            filesystem_type,
        )
        if (
            sys.platform.startswith("linux")
            and filesystem_itunesdb_platform(filesystem_type) == ITUNESDB_PLATFORM_MAC
        ):
            logger.warning(
                "Mac-formatted iPod filesystem detected on Linux: "
                "mount=%s filesystem=%s. Linux may mount journaled HFS+ "
                "read-only; verify write support before syncing.",
                ipod_path,
                filesystem_type,
            )

    # ── SysInfo / SysInfoExtended ──────────────────────────────────────
    sysinfo = _identify_via_sysinfo(ipod_path)
    if sysinfo:
        result.update(sysinfo)

    # ── iTunesDB header (hashing_scheme) ───────────────────────────────
    hash_info = _identify_via_hashing_scheme(ipod_path)
    if hash_info:
        # Only take hashing_scheme; model_family from this source is low-confidence
        result["hashing_scheme"] = hash_info.get("hashing_scheme", -1)
        result.setdefault("_sources", {}).setdefault("hashing_scheme", "itunes")
        # Store the hash-inferred family/gen separately so Phase 3 can use
        # them as a last resort without overriding higher-confidence sources.
        if hash_info.get("model_family"):
            result["hash_model_family"] = hash_info["model_family"]
            result["hash_generation"] = hash_info.get("generation", "")

    if filesystem_type:
        result["filesystem_type"] = filesystem_type
        result.setdefault("_sources", {})["filesystem_type"] = "mounted_filesystem"

    logger.debug(
        "Filesystem probe result: mount=%s meta=[%s] identity=[%s] caps=[%s] "
        "sources=[%s]",
        ipod_path,
        format_fields(result, _PROBE_META_FIELDS, include_false=True),
        format_fields(result, IDENTITY_FIELDS),
        format_fields(result, CAPABILITY_FIELDS, include_false=True),
        format_sources(result.get("_sources", {}), SOURCE_FIELDS),
    )
    return result


def _log_model_resolution(resolved: dict, disk_size_gb: float) -> None:
    logger.debug(
        "Model resolution result: method=%s disk=%.1fGB identity=[%s] "
        "sources=[%s] conflicts=[%s]",
        resolved.get("identification_method", "unknown"),
        disk_size_gb,
        format_fields(resolved, IDENTITY_FIELDS),
        format_sources(resolved.get("_sources", {}), SOURCE_FIELDS),
        format_conflicts(resolved.get("_conflicts", [])),
    )


def _resolve_model(
    hw: dict,
    fs: dict,
    disk_size_gb: float,
) -> dict:
    """
    Phase 3: Model resolution — synthesise a final identification from all
    collected data with clear per-field priority.

    Returns the resolved fields: model_number, model_family, generation,
    capacity, color, firewire_guid, serial, firmware, usb_pid, hashing_scheme,
    identification_method, _sources.
    """
    from .lookup import get_model_info, usb_pid_identity_conflicts

    resolved: dict = {}
    hw_sources = hw.get("_sources", {})
    fs_sources = fs.get("_sources", {})
    sources: dict[str, str] = {}
    resolved["_sources"] = sources  # reference — mutations visible in resolved
    conflicts: list[dict] = []
    resolved["_conflicts"] = conflicts

    extra_fields = (
        "family_id",
        "updater_family_id",
        "product_type",
        "usb_vid",
        "usb_serial",
        "usbstor_instance_id",
        "usb_parent_instance_id",
        "usb_grandparent_instance_id",
        "scsi_vendor",
        "scsi_product",
        "scsi_revision",
        "connected_bus",
        "reported_volume_format",
        "filesystem_type",
        "volume_identity_key",
        "db_version",
        "shadow_db_version",
        "uses_sqlite_db",
        "supports_sparse_artwork",
        "max_tracks",
        "max_file_size_gb",
        "max_transfer_speed",
        "podcasts_supported",
        "voice_memos_supported",
        "audio_codecs",
        "power_information",
        "apple_drm_version",
        "artwork_formats",
        "photo_formats",
        "chapter_image_formats",
    )
    for field in extra_fields:
        hw_value = hw.get(field)
        fs_value = fs.get(field)
        if hw_value not in (None, "", b"", {}, []):
            resolved[field] = hw_value
            sources[field] = hw_sources.get(field, "hardware")
        if fs_value not in (None, "", b"", {}, []) and field not in resolved:
            resolved[field] = fs_value
            sources[field] = fs_sources.get(field, "sysinfo_extended")

    # ── FireWire GUID ──────────────────────────────────────────────────
    # Priority: device tree > SysInfoExtended/SysInfo > IOCTL serial
    # (The device tree USBSTOR instance is the most authoritative because
    # it's guaranteed to be for the currently-connected device at this
    # specific drive letter.  SysInfo can be stale or missing.)
    if hw.get("firewire_guid"):
        resolved["firewire_guid"] = hw["firewire_guid"]
        sources["firewire_guid"] = hw_sources.get("firewire_guid", "hardware")
    elif fs.get("firewire_guid"):
        resolved["firewire_guid"] = fs["firewire_guid"]
        sources["firewire_guid"] = fs_sources.get("firewire_guid", "sysinfo")
    else:
        resolved["firewire_guid"] = ""

    # ── Serial (Apple serial number, NOT the USB/FireWire GUID) ────────
    # Only the filesystem layer (SysInfo pszSerialNumber) provides the real
    # Apple serial.  Hardware probing returns the USB serial which is always
    # the FireWire GUID on iPods — that's stored in firewire_guid above.
    fs_serial = fs.get("serial", "")
    hw_serial = hw.get("serial", "")  # rare: non-GUID serial from IOCTL
    if fs_serial and not fs_serial.startswith("RAND"):
        resolved["serial"] = fs_serial
        sources["serial"] = fs_sources.get("serial", "sysinfo")
    elif hw_serial and not hw_serial.startswith("RAND"):
        resolved["serial"] = hw_serial
        sources["serial"] = hw_sources.get("serial", "hardware")
    else:
        resolved["serial"] = ""

    # ── Firmware ───────────────────────────────────────────────────────
    # Priority: IOCTL revision > SysInfo visibleBuildID
    if hw.get("firmware"):
        resolved["firmware"] = hw["firmware"]
        sources["firmware"] = hw_sources.get("firmware", "hardware")
    elif fs.get("firmware"):
        resolved["firmware"] = fs["firmware"]
        sources["firmware"] = fs_sources.get("firmware", "sysinfo")
    else:
        resolved["firmware"] = ""

    # ── USB PID ────────────────────────────────────────────────────────
    resolved["usb_pid"] = hw.get("usb_pid", 0)
    if resolved["usb_pid"]:
        sources.setdefault("usb_pid", hw_sources.get("usb_pid", "hardware"))

    # ── Hashing scheme ─────────────────────────────────────────────────
    resolved["hashing_scheme"] = fs.get("hashing_scheme", -1)

    # ── Model identification (layered, highest-confidence wins) ────────
    #
    # Layers 1 and 2 are evaluated together so they can cross-check each
    # other.  When they agree the SysInfo result is used (preserving its
    # provenance). When they DISAGREE the serial suffix wins: it is a
    # is a manufacturer-encoded identifier that is much harder to corrupt
    # than the NVRAM-stored ModelNumStr, which can be wrong after a botched
    # restore, firmware flash, or logic-board swap (e.g. a device whose
    # NVRAM reports M9787/4th-Gen but whose serial encodes MA452/5th-Gen).
    #
    # Layer 1: SysInfo ModelNumStr → IPOD_MODELS
    sysinfo_model = fs.get("model_number", "")
    sysinfo_mi: tuple | None = None
    if sysinfo_model:
        sysinfo_mi = get_model_info(sysinfo_model)

    # Layer 2: Longest matching serial suffix → IPOD_MODELS
    serial = resolved["serial"]
    serial_info: dict | None = None
    if serial:
        serial_info = _identify_via_serial_lookup(serial)

    pid_family = hw.get("model_family", "")
    pid_gen = hw.get("generation", "")
    if sysinfo_mi and pid_family and usb_pid_identity_conflicts(
        sysinfo_mi[0],
        sysinfo_mi[1],
        pid_family,
        pid_gen,
    ):
        logger.warning(
            "_resolve_model: SysInfo ModelNumStr %s (%s %s) conflicts "
            "with live USB PID identity %s %s; ignoring cached model",
            sysinfo_model,
            sysinfo_mi[0],
            sysinfo_mi[1],
            pid_family,
            pid_gen or "(generation unknown)",
        )
        conflicts.append({
            "field": "model_number",
            "winner": "usb_pid",
            "rejected_source": fs_sources.get("model_number", "sysinfo"),
            "rejected_value": sysinfo_model,
            "reason": "model conflicts with live USB PID identity",
        })
        sysinfo_model = ""
        sysinfo_mi = None

    if serial_info and pid_family and usb_pid_identity_conflicts(
        serial_info.get("model_family", ""),
        serial_info.get("generation", ""),
        pid_family,
        pid_gen,
    ):
        logger.warning(
            "_resolve_model: serial suffix '%s' resolves to %s %s, "
            "which conflicts with live USB PID identity %s %s; ignoring "
            "cached serial-derived model",
            serial_info.get("serial_suffix", "?"),
            serial_info.get("model_family", "?"),
            serial_info.get("generation", "?"),
            pid_family,
            pid_gen or "(generation unknown)",
        )
        conflicts.append({
            "field": "model_number",
            "winner": "usb_pid",
            "rejected_source": sources.get("serial", "serial_lookup"),
            "rejected_value": serial_info.get("model_number", ""),
            "reason": "serial-derived model conflicts with live USB PID identity",
        })
        serial_info = None

    # Cross-check: if both resolved and they disagree, serial wins.
    _use_serial = False
    if sysinfo_mi and serial_info:
        sr_model = serial_info.get("model_number", "")
        if sr_model and sr_model != sysinfo_model:
            logger.warning(
                "_resolve_model: SysInfo ModelNumStr %s (%s %s) conflicts "
                "with serial suffix '%s' → %s (%s %s); preferring serial "
                "(USB PID family: %s)",
                sysinfo_model, sysinfo_mi[0], sysinfo_mi[1],
                serial_info.get("serial_suffix", "?"), sr_model,
                serial_info.get("model_family", "?"),
                serial_info.get("generation", "?"),
                hw.get("model_family", "unknown"),
            )
            conflicts.append({
                "field": "model_number",
                "winner": sources.get("serial", "serial_lookup"),
                "rejected_source": fs_sources.get("model_number", "sysinfo"),
                "rejected_value": sysinfo_model,
                "reason": "SysInfo model conflicts with Apple serial suffix",
            })
            _use_serial = True
    elif serial_info and not sysinfo_mi:
        _use_serial = True

    if sysinfo_mi and not _use_serial:
        resolved["model_number"] = sysinfo_model
        resolved["model_family"] = sysinfo_mi[0]
        resolved["generation"] = sysinfo_mi[1]
        resolved["capacity"] = sysinfo_mi[2]
        resolved["color"] = sysinfo_mi[3]
        resolved["identification_method"] = "sysinfo"
        _mn_src = fs_sources.get("model_number", "sysinfo")
        sources["model_number"] = _mn_src
        sources.setdefault("model_family", _mn_src)
        sources.setdefault("generation", _mn_src)
        sources.setdefault("capacity", _mn_src)
        sources.setdefault("color", _mn_src)
        _log_model_resolution(resolved, disk_size_gb)
        return resolved

    if _use_serial:
        serial_info = serial_info or {}
        resolved["serial"] = serial
        resolved["model_number"] = serial_info.get("model_number", "")
        resolved["model_family"] = serial_info.get("model_family", "iPod")
        resolved["generation"] = serial_info.get("generation", "")
        resolved["capacity"] = serial_info.get("capacity", "")
        resolved["color"] = serial_info.get("color", "")
        resolved["identification_method"] = "serial"
        # Derived fields inherit the serial's authority source.
        _serial_src = sources.get("serial", "serial_lookup")
        sources["model_number"] = "serial_lookup"
        sources.setdefault("model_family", _serial_src)
        sources.setdefault("generation", _serial_src)
        sources.setdefault("capacity", _serial_src)
        sources.setdefault("color", _serial_src)
        _log_model_resolution(resolved, disk_size_gb)
        return resolved

    # Layer 3: USB PID → family/generation (coarse)
    # No disk-size rejection — modded iPods often have non-stock storage.
    pid = resolved["usb_pid"]
    pid_family = hw.get("model_family", "")
    pid_gen = hw.get("generation", "")
    if pid and pid_family:
        resolved["model_family"] = pid_family
        resolved["generation"] = pid_gen
        resolved["identification_method"] = "usb_pid"
        sources.setdefault("model_family", "usb_pid")
        if pid_gen:
            sources.setdefault("generation", "usb_pid")

    # Layer 4: Hashing scheme → generation class (coarsest)
    if resolved.get("model_family", "iPod") == "iPod":
        hash_family = fs.get("hash_model_family")
        if hash_family and hash_family != "iPod":
            resolved.setdefault("model_family", hash_family)
            resolved.setdefault("generation", fs.get("hash_generation", ""))
            resolved["identification_method"] = "hashing"

    # Defaults for anything not yet resolved
    resolved.setdefault("model_number", sysinfo_model or "")
    resolved.setdefault("model_family", "iPod")
    resolved.setdefault("generation", "")
    resolved.setdefault("capacity", "")
    resolved.setdefault("color", "")
    resolved.setdefault("identification_method", "filesystem")

    _log_model_resolution(resolved, disk_size_gb)
    return resolved


def _identify_via_sysinfo(ipod_path: str) -> dict | None:
    """Try to identify via SysInfo / SysInfoExtended files."""

    result: dict = {}
    result["_sources"] = {}

    # Try SysInfoExtended first
    sie_path = os.path.join(ipod_path, "iPod_Control", "Device", "SysInfoExtended")
    result["_sysinfo_extended_present"] = os.path.exists(sie_path)
    if os.path.exists(sie_path):
        try:
            from .sysinfo import (
                identity_from_sysinfo_extended,
                parse_sysinfo_extended,
            )

            parsed = parse_sysinfo_extended(
                Path(sie_path).read_bytes(),
                source="sysinfo_extended",
            )
            result["_sysinfo_extended_keys"] = len(parsed.plist)
            result["_sysinfo_extended_regex_fallback"] = parsed.used_regex_fallback
            identity = identity_from_sysinfo_extended(parsed, "sysinfo_extended")
            sources = identity.get("_sources", {})
            for key, value in identity.items():
                if key.startswith("_") or key in {
                    "model_raw",
                    "sysinfo_extended_raw_xml",
                }:
                    continue
                result[key] = value
                if key in sources:
                    result["_sources"][key] = sources[key]
            if identity.get("serial"):
                logger.debug("SysInfoExtended: Apple serial: %s", identity["serial"])
            if identity.get("firewire_guid"):
                logger.debug("SysInfoExtended: FW GUID: %s", identity["firewire_guid"])
        except Exception as exc:
            logger.info("SysInfoExtended parse failed for %s: %s", ipod_path, exc)

    # Try SysInfo
    sysinfo_path = os.path.join(ipod_path, "iPod_Control", "Device", "SysInfo")
    result["_sysinfo_present"] = os.path.exists(sysinfo_path)
    if os.path.exists(sysinfo_path):
        try:
            from .sysinfo import identity_from_sysinfo, parse_sysinfo_text

            sysinfo = parse_sysinfo_text(Path(sysinfo_path).read_text(errors="replace"))
            result["_sysinfo_keys"] = len(sysinfo)
            identity = identity_from_sysinfo(sysinfo, "sysinfo")
            sources = identity.get("_sources", {})
            for key, value in identity.items():
                if key.startswith("_"):
                    continue
                if key in result and result[key] not in (None, ""):
                    continue
                result[key] = value
                if key in sources:
                    result["_sources"].setdefault(key, sources[key])
            if identity.get("model_number"):
                from .lookup import get_model_info

                mi = get_model_info(identity["model_number"])
                if mi:
                    result.setdefault("model_family", mi[0])
                    result.setdefault("generation", mi[1])
                    result.setdefault("capacity", mi[2])
                    result.setdefault("color", mi[3])
            if identity.get("serial"):
                logger.debug("SysInfo: Apple serial: %s", identity["serial"])
            if identity.get("firewire_guid"):
                logger.debug("SysInfo: FW GUID: %s", identity["firewire_guid"])
        except Exception as exc:
            logger.info("SysInfo parse failed for %s: %s", ipod_path, exc)

    return result if any(k != "_sources" for k in result) else None


def _extract_ipod_name(ipod_path: str) -> str:
    """
    Lightweight extraction of the iPod's user-assigned name from the master
    playlist title in the iTunesDB binary.  Uses buffered positional reads
    so only a few KB are transferred over USB — never reads the whole file.

    For iTunesCDB files (Nano 5G+), the entire file must be read and
    decompressed first — but these are typically small (< 200 KB compressed).

    Returns the name string, or empty string if extraction fails.
    """
    from .info import resolve_itdb_path
    itdb_path = resolve_itdb_path(ipod_path)
    if not itdb_path:
        return ""
    try:
        # For iTunesCDB, we need to decompress the whole file first.
        # Check if it's a CDB by reading the header.
        with open(itdb_path, "rb") as f:
            peek = f.read(16)
            if len(peek) < 16 or peek[:4] != b"mhbd":
                return ""
            unk_0x0c = struct.unpack("<I", peek[12:16])[0]

        if unk_0x0c == 2:
            # Compressed CDB — read and decompress the full file, then
            # use the parser's decompression to get the full data.
            from iopenpod.itunesdb_parser.parser import decompress_itunescdb
            with open(itdb_path, "rb") as f:
                raw = f.read()
            data = decompress_itunescdb(raw)
            if len(data) < 24 or data[:4] != b"mhbd":
                return ""
            return _ipod_name_from_data(data)
        else:
            # Standard iTunesDB — use positional reads
            with open(itdb_path, "rb") as f:
                return _ipod_name_from_stream(f)

    except (EOFError, OSError, struct.error) as e:
        logger.debug("iPod name extraction failed: %s", e)
    return ""


def _ipod_name_from_data(data: bytes) -> str:
    """Extract iPod name from a fully in-memory (decompressed) database."""
    import io
    return _ipod_name_from_stream(io.BytesIO(data))


def _ipod_name_from_stream(f) -> str:
    """Extract iPod name from an open file-like object (positional reads)."""
    def _read(n: int) -> bytes:
        buf = f.read(n)
        if len(buf) < n:
            raise EOFError("Unexpected end of iTunesDB")
        return buf

    try:
        hdr = _read(24)
        if hdr[:4] != b"mhbd":
            return ""

        mhbd_header_len = struct.unpack("<I", hdr[4:8])[0]
        mhbd_children = struct.unpack("<I", hdr[20:24])[0]

        def _name_from_mhsd(mhsd_pos: int, mhsd_hdr_len: int) -> str:
            """Try to read iPod name from the master playlist in an mhsd."""
            mhlp_pos = mhsd_pos + mhsd_hdr_len
            f.seek(mhlp_pos)
            mhlp_hdr = _read(12)
            if mhlp_hdr[:4] != b"mhlp":
                return ""
            mhlp_hdr_len = struct.unpack("<I", mhlp_hdr[4:8])[0]
            pl_count = struct.unpack("<I", mhlp_hdr[8:12])[0]
            if pl_count == 0:
                return ""

            # Walk playlists looking for the master (type=1)
            mhyp_pos = mhlp_pos + mhlp_hdr_len
            for _ in range(min(pl_count, 16)):
                f.seek(mhyp_pos)
                mhyp_hdr = _read(24)
                if mhyp_hdr[:4] != b"mhyp":
                    return ""
                mhyp_hdr_len = struct.unpack("<I", mhyp_hdr[4:8])[0]
                mhyp_total = struct.unpack("<I", mhyp_hdr[8:12])[0]
                mhod_count = struct.unpack("<I", mhyp_hdr[12:16])[0]
                pl_type = mhyp_hdr[20]  # 1 = master playlist

                if pl_type == 1:
                    # Walk child MHODs to find type 1 (title)
                    mhod_pos = mhyp_pos + mhyp_hdr_len
                    for _ in range(min(mhod_count, 64)):
                        f.seek(mhod_pos)
                        mhod_hdr = _read(40)
                        if mhod_hdr[:4] != b"mhod":
                            break
                        mhod_total = struct.unpack("<I", mhod_hdr[8:12])[0]
                        mhod_type = struct.unpack("<I", mhod_hdr[12:16])[0]

                        if mhod_type == 1:
                            enc = struct.unpack("<I", mhod_hdr[24:28])[0]
                            slen = struct.unpack("<I", mhod_hdr[28:32])[0]
                            if slen > 1024:
                                break
                            sdata = _read(slen)
                            if enc == 2:
                                return sdata.decode("utf-8", errors="replace")
                            else:
                                return sdata.decode("utf-16-le", errors="replace")

                        mhod_pos += mhod_total
                    return ""  # Had the master but couldn't read name

                mhyp_pos += mhyp_total
            return ""

        # Walk mhsd children — try type 2 first (classic), fall back to
        # type 3 (Nano 5G+ / newer iTunes omit type 2 entirely and put
        # the master playlist in type 3 instead).
        type3_pos: int | None = None
        type3_hdr_len: int = 0
        pos = mhbd_header_len
        for _ in range(mhbd_children):
            f.seek(pos)
            mhsd_hdr = _read(16)
            if mhsd_hdr[:4] != b"mhsd":
                break
            mhsd_hdr_len = struct.unpack("<I", mhsd_hdr[4:8])[0]
            mhsd_total_len = struct.unpack("<I", mhsd_hdr[8:12])[0]
            ds_type = struct.unpack("<I", mhsd_hdr[12:16])[0]

            if ds_type == 2:
                name = _name_from_mhsd(pos, mhsd_hdr_len)
                if name:
                    return name
                break  # type 2 existed but couldn't extract — don't fallback
            elif ds_type == 3 and type3_pos is None:
                type3_pos = pos
                type3_hdr_len = mhsd_hdr_len

            pos += mhsd_total_len

        # Type 2 wasn't found — try type 3
        if type3_pos is not None:
            name = _name_from_mhsd(type3_pos, type3_hdr_len)
            if name:
                return name

    except (EOFError, OSError, struct.error) as e:
        logger.debug("Could not extract iPod name: %s", e)
    except Exception as e:
        logger.debug("Could not extract iPod name (unexpected): %s", e)
    return ""


def _identify_via_hashing_scheme(ipod_path: str) -> dict | None:
    """
    Identify generation class from iTunesDB hashing_scheme field.

    This is a fallback — it tells us the generation class but not the exact model.
    """
    from .info import resolve_itdb_path
    itdb_path = resolve_itdb_path(ipod_path)
    if not itdb_path:
        return None

    try:
        with open(itdb_path, "rb") as f:
            header = f.read(0x72)
        if len(header) < 0x32 or header[:4] != b"mhbd":
            return None

        scheme = struct.unpack("<H", header[0x30:0x32])[0]

        result: dict = {"hashing_scheme": scheme}

        # Map raw mhbd hashing_scheme to ChecksumType via canonical table
        from .checksum import MHBD_SCHEME_TO_CHECKSUM, ChecksumType
        cs_type = MHBD_SCHEME_TO_CHECKSUM.get(scheme)

        if cs_type == ChecksumType.NONE or cs_type is None:
            result["model_family"] = "iPod"
            result["generation"] = "(pre-2007)"
        elif cs_type == ChecksumType.HASH58:
            result["model_family"] = "iPod"
            result["generation"] = "(Classic or Nano 3G/4G)"
        elif cs_type == ChecksumType.HASH72:
            result["model_family"] = "iPod Nano"
            result["generation"] = "(5th gen)"
        elif cs_type == ChecksumType.HASHAB:
            result["model_family"] = "iPod Nano"
            result["generation"] = "(6th/7th gen)"

        return result
    except Exception:
        return None


def _identify_via_serial_lookup(serial: str) -> dict | None:
    """Look up a model from the serial's longest published suffix."""
    from .lookup import lookup_by_serial, match_serial_suffix

    result = lookup_by_serial(serial)
    if not result:
        return None

    model_num, info = result
    return {
        "model_number": model_num,
        "model_family": info[0],
        "generation": info[1],
        "capacity": info[2],
        "color": info[3],
        "serial_suffix": match_serial_suffix(serial) or "",
    }


def _estimate_capacity_from_disk_size(disk_gb: float) -> str:
    """Estimate marketed capacity from actual disk size.

    .. deprecated:: Use :func:`iopenpod.device.info._estimate_capacity_from_disk_size` directly.
    """
    from .info import _estimate_capacity_from_disk_size as _impl
    return _impl(disk_gb)


def _try_vpd_identification(ipod: DeviceInfo) -> None:
    """Attempt full VPD-based identification for an incompletely resolved iPod.

    Delegates to :func:`iopenpod.device.vpd_libusb.identify_via_vpd` on supported
    non-Windows platforms.

    SysInfo writing is NOT done here — the authority module handles it
    after all identification is complete.
    """
    if sys.platform == "win32":
        logger.debug(
            "Skipping inline VPD identification on Windows: mount=%s",
            ipod.path,
        )
        return

    try:
        from .vpd_libusb import identify_via_vpd
    except ImportError:
        return

    result = identify_via_vpd(
        mount_path=ipod.path,
        usb_pid=ipod.usb_pid,
        firewire_guid=ipod.firewire_guid,
        write_sysinfo_to_device=False,
    )
    if result is None:
        return

    # Apply resolved fields
    if result["model_number"]:
        ipod.model_number = result["model_number"]
        ipod.model_family = result["model_family"]
        ipod.generation = result["generation"]
        ipod.capacity = result["capacity"]
        ipod.color = result["color"]
        ipod.identification_method = "usb_vpd"
        ipod._field_sources["model_number"] = "vpd"

    if not ipod.serial and result["serial"]:
        ipod.serial = result["serial"]
        ipod._field_sources["serial"] = "vpd"
    if not ipod.firewire_guid and result["firewire_guid"]:
        ipod.firewire_guid = result["firewire_guid"]
        ipod._field_sources["firewire_guid"] = "vpd"
    if not ipod.firmware and result["firmware"]:
        ipod.firmware = result["firmware"]
        ipod._field_sources["firmware"] = "vpd"

    # Update mount path in case pyusb caused a remount to a different path
    if result["mount_path"] and result["mount_path"] != ipod.path:
        logger.info("  VPD: mount path changed %s → %s", ipod.path, result["mount_path"])
        ipod.path = result["mount_path"]


def _display_name_for_mount_path(mount_path: str) -> str:
    """Return the same style of display name used by broad volume discovery."""
    if sys.platform == "win32":
        drive, _tail = os.path.splitdrive(os.path.abspath(mount_path))
        if drive:
            return drive
    normalized = os.path.normpath(mount_path)
    return os.path.basename(normalized) or normalized


def identify_ipod_at_path(
    ipod_path: str,
    mount_name: str | None = None,
) -> DeviceInfo | None:
    """Identify one selected iPod root without scanning every mounted volume."""
    if not ipod_path:
        return None

    expanded_path = os.path.expanduser(ipod_path)
    drive, tail = os.path.splitdrive(expanded_path)
    if sys.platform == "win32" and drive and tail in ("", "."):
        mount_path = drive + "\\"
    else:
        mount_path = os.path.abspath(expanded_path)
    virtual = _load_virtual_ipod_mount_if_present(mount_path)
    if virtual is not None:
        return virtual
    if not _has_ipod_control(mount_path):
        logger.info("Selected path is not an iPod root: %s", mount_path)
        return None

    display_name = mount_name or _display_name_for_mount_path(mount_path)
    try:
        return _identify_ipod_mount(mount_path, display_name)
    finally:
        _clear_macos_usb_cache()


def _identify_ipod_mount(mount_path: str, display_name: str) -> DeviceInfo:
    """Run the full identification pipeline for one already-discovered mount."""
    from .info import enrich

    virtual = _load_virtual_ipod_mount_if_present(mount_path)
    if virtual is not None:
        return virtual

    ipod = DeviceInfo(path=mount_path, mount_name=display_name)
    ipod.disk_size_gb, ipod.free_space_gb = _get_disk_info(mount_path)
    logger.info(
        "Identifying iPod: mount=%s display=%s disk=%.1fGB free=%.1fGB",
        mount_path,
        display_name,
        ipod.disk_size_gb,
        ipod.free_space_gb,
    )

    # Phase 1: Hardware probing
    hw = _probe_hardware(mount_path, display_name)

    # Phase 2: Filesystem probing
    fs = _probe_filesystem(mount_path)

    # Phase 3: Model resolution (per-field priority merge)
    resolved = _resolve_model(hw, fs, ipod.disk_size_gb)

    # Apply resolved fields to the DeviceInfo
    ipod.model_number = resolved.get("model_number", "")
    ipod.model_family = resolved.get("model_family", "iPod")
    ipod.generation = resolved.get("generation", "")
    ipod.capacity = resolved.get("capacity", "")
    ipod.color = resolved.get("color", "")
    ipod.firewire_guid = resolved.get("firewire_guid", "")
    ipod.serial = resolved.get("serial", "")
    ipod.firmware = resolved.get("firmware", "")
    ipod.usb_pid = resolved.get("usb_pid", 0)
    ipod.hashing_scheme = resolved.get("hashing_scheme", -1)
    ipod.identification_method = resolved.get("identification_method", "filesystem")
    # `DeviceInfo.raw_identity_evidence` expects lists of evidence dicts;
    # wrap the hw/fs dicts in single-item lists to satisfy the type.
    ipod.raw_identity_evidence = {
        "hardware": [hw] if hw is not None else [],
        "filesystem": [fs] if fs is not None else [],
    }
    ipod.identity_conflicts = list(resolved.get("_conflicts", []))
    for field in (
        "family_id",
        "updater_family_id",
        "product_type",
        "usb_vid",
        "usb_serial",
        "usbstor_instance_id",
        "usb_parent_instance_id",
        "usb_grandparent_instance_id",
        "scsi_vendor",
        "scsi_product",
        "scsi_revision",
        "connected_bus",
        "reported_volume_format",
        "filesystem_type",
        "volume_identity_key",
        "db_version",
        "shadow_db_version",
        "uses_sqlite_db",
        "supports_sparse_artwork",
        "max_tracks",
        "max_file_size_gb",
        "max_transfer_speed",
        "podcasts_supported",
        "voice_memos_supported",
        "audio_codecs",
        "power_information",
        "apple_drm_version",
        "artwork_formats",
        "photo_formats",
        "chapter_image_formats",
    ):
        value = resolved.get(field)
        if value not in (None, "", b"", {}, []):
            setattr(ipod, field, value)

    # Apply per-field provenance from the resolution phase
    resolved_sources = resolved.get("_sources", {})
    if resolved_sources:
        ipod._field_sources.update(resolved_sources)

    # Phase 4: Inline VPD for incomplete identification (non-Windows only)
    if sys.platform != "win32" and not ipod.model_number and ipod.usb_pid:
        _try_vpd_identification(ipod)

    # Extract user-assigned iPod name from master playlist
    ipod.ipod_name = _extract_ipod_name(mount_path)

    # Estimate capacity from disk size if still unknown
    if not ipod.capacity and ipod.disk_size_gb > 0:
        ipod.capacity = _estimate_capacity_from_disk_size(ipod.disk_size_gb)
        if ipod.capacity:
            ipod._field_sources["capacity"] = "disk_size"

    # Phase 5: Enrich (fills checksum, artwork, HashInfo, etc.)
    enrich(ipod)

    ipod_data = ipod.__dict__
    logger.info(
        "iPod identified: mount=%s display=%s filesystem=%s "
        "reported_volume_format=%s identity=[%s] caps=[%s] method=%s "
        "checksum=%s hash_scheme=%s sources=[%s] conflicts=[%s]",
        ipod.path,
        ipod.display_name,
        ipod.filesystem_type or "unknown",
        ipod.reported_volume_format or "unknown",
        format_fields(ipod_data, IDENTITY_FIELDS),
        format_fields(ipod_data, CAPABILITY_FIELDS, include_false=True),
        ipod.identification_method,
        ipod.checksum_type,
        ipod.hashing_scheme,
        format_sources(ipod._field_sources, SOURCE_FIELDS),
        format_conflicts(ipod.identity_conflicts),
    )

    return ipod


def _load_virtual_ipod_mount_if_present(mount_path: str) -> DeviceInfo | None:
    """Load root-level iPodInfo.json metadata when this is a virtual iPod."""

    try:
        from .virtual import (
            ensure_virtual_itunes_database,
            has_virtual_ipod_info,
            load_virtual_ipod_info,
        )

        if not has_virtual_ipod_info(mount_path):
            return None
        ensure_virtual_itunes_database(mount_path)
        return load_virtual_ipod_info(mount_path)
    except Exception as exc:
        logger.warning("Virtual iPod metadata could not be loaded: %s", exc)
        return None


def scan_for_ipods() -> list[DeviceInfo]:
    """
    Scan all mounted volumes for connected iPods.

    Uses a unified four-phase pipeline, then calls ``enrich()`` so each
    returned :class:`DeviceInfo` is fully populated (checksum type, artwork
    formats, HashInfo, disk stats, etc.).

      **Phase 1 — Hardware probing** (platform-specific):
        Windows: Direct IOCTL + device tree walk, with silent WMI fallback.
        macOS: system_profiler SPUSBDataType for USB device identification.
        Linux: sysfs traversal from block device to USB device.

      **Phase 2 — Filesystem probing** (cross-platform file reads):
        SysInfo / SysInfoExtended + iTunesDB header.

      **Phase 3 — Model resolution** (per-field priority merge):
        SysInfo ModelNumStr > serial suffix > USB PID > hashing_scheme.

      **Phase 4 — Inline VPD** (macOS only, for incomplete identification):
        If model_number is still unknown after Phase 3, query the iPod's
        firmware via IOKit SCSI VPD to get the Apple serial, then resolve
        via serial-suffix lookup. Writes SysInfo so this only runs once.

      **Phase 5 — Enrich** (fills derived fields: checksum, artwork, etc.)

    Returns a list of fully-enriched DeviceInfo objects.
    """
    ipods: list[DeviceInfo] = []
    logger.info("iPod scan started")

    candidates: list[tuple[str, str]] = []
    try:
        candidates = _find_ipod_volumes()
        for mount_path, display_name in candidates:
            ipods.append(_identify_ipod_mount(mount_path, display_name))
        deduped_ipods = _deduplicate_ipods(ipods)
        if len(deduped_ipods) != len(ipods):
            logger.info(
                "Deduplicated iPod scan results: before=%d after=%d",
                len(ipods),
                len(deduped_ipods),
            )
        ipods = deduped_ipods
    finally:
        # Clear the macOS ioreg caches so they're fresh on the next rescan.
        _clear_macos_usb_cache()

    mounts = ", ".join(display for _path, display in candidates) or "none"
    logger.info("iPod scan finished: count=%d mounts=%s", len(ipods), mounts)
    return ipods
