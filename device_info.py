"""
Centralised device information store for iOpenPod.

When an iPod is selected, every knowable detail about it is gathered **once**
by the device scanner / loader and stored here.  Every other module — GUI,
writer, sync engine — accesses device info exclusively through this store.
**No consumer should ever probe hardware, read SysInfo, or query the registry
on its own.**  If the store is empty the consumer uses a safe default.

Typical flow
~~~~~~~~~~~~
1. Device scanner discovers iPod → ``DiscoveredIPod``
2. User picks one → ``DeviceManager`` calls ``set_current_device(info)``
3. Any backend module: ``device = get_current_device()``

For headless (non-GUI) use::

    from device_info import DeviceInfo, set_current_device, enrich
    info = DeviceInfo(path="/media/ipod")
    enrich(info)            # reads SysInfo once, computes everything
    set_current_device(info)
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────

@dataclass
class DeviceInfo:
    """Comprehensive iPod device information, gathered once and reused everywhere.

    All fields that could not be determined are left at their defaults (empty
    string, 0, empty dict, etc.).  Consumers should always check before using.
    """

    # ── Identity ──────────────────────────────────────────────────────
    path: str = ""                    # Mount root (e.g. "D:\\" or "/Volumes/iPod")
    model_number: str = ""            # Normalised (e.g. "MC297", never "xA623")
    model_family: str = "iPod"        # e.g. "iPod Classic", "iPod Nano"
    generation: str = ""              # e.g. "3rd Gen"
    capacity: str = ""                # e.g. "160GB"
    color: str = ""                   # e.g. "Black"

    # ── Hardware / Identifiers ────────────────────────────────────────
    firewire_guid: str = ""           # Hex string (no 0x prefix)
    serial: str = ""
    firmware: str = ""
    board: str = ""                   # BoardHwName from SysInfo
    usb_pid: int = 0

    # ── Hashing / Security ────────────────────────────────────────────
    checksum_type: int = 99           # ChecksumType value (99 = UNKNOWN)
    hashing_scheme: int = -1          # From iTunesDB header offset 0x30
    hash_info_iv: bytes = b""         # AES IV from HashInfo (16 bytes if present)
    hash_info_rndpart: bytes = b""    # Random bytes from HashInfo (12 bytes)

    # ── Storage ───────────────────────────────────────────────────────
    disk_size_gb: float = 0.0
    free_space_gb: float = 0.0

    # ── Artwork ───────────────────────────────────────────────────────
    artwork_formats: dict[int, tuple[int, int]] = field(default_factory=dict)

    # ── Raw SysInfo cache (so nobody ever has to re-read the file) ────
    sysinfo: dict[str, str] = field(default_factory=dict)

    # ── Provenance ────────────────────────────────────────────────────
    identification_method: str = "unknown"

    # ── Computed helpers ──────────────────────────────────────────────

    @property
    def firewire_id_bytes(self) -> bytes | None:
        """FireWire GUID as raw bytes, or *None* if unavailable / all-zero."""
        if not self.firewire_guid:
            return None
        guid = self.firewire_guid
        if guid.startswith(("0x", "0X")):
            guid = guid[2:]
        try:
            result = bytes.fromhex(guid)
            return None if result == b"\x00" * len(result) else result
        except ValueError:
            return None

    @property
    def drive_letter(self) -> str:
        """Windows drive letter from *path*, or empty string."""
        import sys as _sys
        if _sys.platform == "win32" and self.path and self.path[0].isalpha():
            return self.path[0]
        return ""

    @property
    def display_name(self) -> str:
        """User-friendly one-line description."""
        parts = [self.model_family]
        if self.generation:
            parts.append(self.generation)
        if self.capacity:
            parts.append(self.capacity)
        if self.color:
            parts.append(self.color)
        return " ".join(parts)


# ──────────────────────────────────────────────────────────────────────
# Thread-safe singleton store
# ──────────────────────────────────────────────────────────────────────

class _Store:
    """Holds the *active* DeviceInfo for the running session.

    Thread safety: singleton creation is protected by a lock.  The ``current``
    property is set only from the main thread (via ``set_current_device``),
    so no additional synchronisation is needed for reads from worker threads
    that happen *after* the device is stored.
    """

    _instance: Optional[_Store] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._info: DeviceInfo | None = None

    @classmethod
    def _get(cls) -> _Store:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def current(self) -> DeviceInfo | None:
        return self._info

    @current.setter
    def current(self, info: DeviceInfo | None) -> None:
        self._info = info


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def get_current_device() -> DeviceInfo | None:
    """Return the active DeviceInfo, or *None* if no device is selected."""
    return _Store._get().current


def set_current_device(info: DeviceInfo | None) -> None:
    """Store *info* as the active device (called once during selection)."""
    _Store._get().current = info
    if info is not None:
        logger.info(
            "Device stored: %s %s (%s) checksum=%s formats=%s",
            info.model_family, info.generation, info.model_number,
            info.checksum_type,
            list(info.artwork_formats.keys()) if info.artwork_formats else "none",
        )
    else:
        logger.info("Device cleared")


def clear_current_device() -> None:
    """Clear the stored device info (device disconnected / deselected)."""
    set_current_device(None)


# ──────────────────────────────────────────────────────────────────────
# Enrichment — fills derived fields from the ones already known
# ──────────────────────────────────────────────────────────────────────

def enrich(info: DeviceInfo) -> None:
    """Fill in derived fields by probing **every available source**.

    This is the ONE place in the entire codebase that touches hardware,
    reads files from the device, queries the OS, etc.  It tries multiple
    sources in priority order and never overwrites an already-filled field.

    Sources tried (in order):
      1. SysInfo text file on the device
      2. SysInfoExtended XML plist on the device
      3. Windows PnP device-tree walk (live USB introspection)
      4. Windows registry (persists from previous USB connections)
      5. iTunesDB header (hashing scheme, db version)
      6. ArtworkDB format-ID scan
      7. Disk size via OS
    """

    # ── 1. SysInfo (text key:value file) ──────────────────────────────
    if info.path and not info.sysinfo:
        try:
            from iTunesDB_Writer.device import read_sysinfo
            info.sysinfo = read_sysinfo(info.path)
            logger.debug("enrich: SysInfo loaded (%d keys)", len(info.sysinfo))
        except FileNotFoundError:
            logger.debug("enrich: no SysInfo at %s", info.path)
        except Exception as exc:
            logger.debug("enrich: SysInfo read failed: %s", exc)

    if not info.board and info.sysinfo:
        info.board = info.sysinfo.get("BoardHwName", "")
    # Apple serial from SysInfo always overrides — the scanner often
    # pre-fills info.serial with the FireWire GUID (ioreg USB serial),
    # which is NOT the real Apple serial needed for model lookup.
    if info.sysinfo:
        apple_serial = info.sysinfo.get("pszSerialNumber", "")
        if apple_serial and apple_serial != info.firewire_guid:
            info.serial = apple_serial
    if not info.firmware and info.sysinfo:
        fw_ver = info.sysinfo.get("visibleBuildID", "")
        if fw_ver:
            info.firmware = fw_ver

    # FireWire GUID from SysInfo
    if not info.firewire_guid and info.sysinfo:
        guid = info.sysinfo.get("FirewireGuid", "")
        if guid:
            if guid.startswith(("0x", "0X")):
                guid = guid[2:]
            if guid and guid != "0" * len(guid):
                info.firewire_guid = guid
                logger.debug("enrich: FW GUID from SysInfo: %s", guid)

    # Model number from SysInfo
    if not info.model_number and info.sysinfo:
        try:
            from iTunesDB_Writer.device import _extract_model_number
            raw = info.sysinfo.get("ModelNumStr", "")
            if raw:
                mn = _extract_model_number(raw)
                if mn:
                    info.model_number = mn
                    logger.debug("enrich: model from SysInfo: %s", mn)
        except ImportError:
            pass

    # ── 2. SysInfoExtended (XML plist — has FireWireGUID + more) ──────
    if info.path:
        _enrich_from_sysinfo_extended(info)

    # ── 3. Hardware probe (IOCTL + PnP device tree + USB PID) ─────────
    #   This is the big one on Windows.  It queries the physical device via
    #   IOCTL_STORAGE_QUERY_PROPERTY (gets serial, firmware, vendor/product),
    #   walks the PnP device tree (gets FW GUID, USB PID), and maps the PID
    #   to a model family.  On macOS/Linux the platform-specific probers run.
    _enrich_from_hardware_probe(info)

    # ── 3b. USB VPD query (if SysInfo is missing/empty) ───────────────
    #   After hardware probe gives us usb_pid + firewire_guid,
    #   if we still don't have a SysInfo dict, query the iPod firmware
    #   via SCSI VPD pages and write SysInfo to disk for future runs.
    #   This gets the real Apple serial (→ exact model) and FamilyID.
    if info.path and not info.sysinfo:
        _enrich_from_usb_vpd(info)

    # ── 4. Windows registry (USB serial persists after disconnect) ────
    if not info.firewire_guid:
        _enrich_from_windows_registry(info)

    # ── 5. Model lookup (map model_number → family/gen/capacity/color) ─
    if info.model_number and info.model_family == "iPod":
        try:
            from iTunesDB_Writer.device import IPOD_MODELS
            mi = IPOD_MODELS.get(info.model_number)
            if mi:
                info.model_family = mi[0]
                info.generation = mi[1]
                if not info.capacity:
                    info.capacity = mi[2]
                if not info.color:
                    info.color = mi[3]
                logger.debug("enrich: model DB → %s %s", mi[0], mi[1])
        except ImportError:
            pass

    # ── 5b. Serial-last-3 model lookup ────────────────────────────────
    #   Very reliable — the last 3 chars of the serial encode the exact
    #   model (incl. capacity and color).  Higher confidence than USB PID.
    #   Always run when we have a serial but no model_number yet.
    if info.serial and not info.model_number:
        _enrich_from_serial_lookup(info)

    # ── 5d. Persist ModelNumStr to SysInfo for future scans ───────────
    #   After model resolution (steps 5/5b), write ModelNumStr back to
    #   SysInfo so the scanner can use Layer 1 (fastest) on next launch.
    if info.model_number and info.path:
        _persist_model_to_sysinfo(info)

    # ── 5c. USB PID-based family/generation (if nothing else worked) ──
    if info.usb_pid and info.model_family == "iPod":
        try:
            from GUI.device_scanner import USB_PID_TO_MODEL
            pid_info = USB_PID_TO_MODEL.get(info.usb_pid)
            if pid_info:
                info.model_family = pid_info[0]
                if not info.generation and pid_info[1]:
                    info.generation = pid_info[1]
                logger.debug("enrich: USB PID 0x%04X → %s %s",
                             info.usb_pid, pid_info[0], pid_info[1])
        except ImportError:
            pass

    # ── 6. iTunesDB header (hashing scheme, version) ─────────────────
    if info.path and info.hashing_scheme == -1:
        _enrich_from_itunesdb_header(info)

    # ── 7. Checksum type ──────────────────────────────────────────────
    if info.checksum_type == 99:
        _resolve_checksum_type(info)

    # ── 8. HashInfo (cryptographic material for HASH72 signing) ───────
    if not info.hash_info_iv and info.path:
        hi_path = os.path.join(
            info.path, "iPod_Control", "Device", "HashInfo",
        )
        try:
            if os.path.exists(hi_path):
                with open(hi_path, "rb") as f:
                    hi_data = f.read()
                if len(hi_data) >= 54 and hi_data[:6] == b"HASHv0":
                    info.hash_info_iv = hi_data[38:54]
                    info.hash_info_rndpart = hi_data[26:38]
                    logger.debug("enrich: cached HashInfo (iv=%d, rndpart=%d)",
                                 len(info.hash_info_iv), len(info.hash_info_rndpart))
        except Exception as exc:
            logger.debug("enrich: HashInfo read failed: %s", exc)

    # ── 9. Artwork formats ────────────────────────────────────────────
    # Try model-based lookup first
    if not info.artwork_formats and info.model_family and info.generation:
        try:
            from ArtworkDB_Writer.rgb565 import _family_gen_to_formats
            table = _family_gen_to_formats(info.model_family, info.generation)
            if table:
                info.artwork_formats = dict(table)
                logger.debug("enrich: artwork formats from model: %s",
                             list(info.artwork_formats.keys()))
        except ImportError:
            pass

    # Fallback: scan ArtworkDB for format IDs
    if not info.artwork_formats and info.path:
        _enrich_artwork_from_artworkdb(info)

    # ── 10. Disk size ─────────────────────────────────────────────────
    if info.disk_size_gb == 0.0 and info.path:
        try:
            import shutil
            total, _used, free = shutil.disk_usage(info.path)
            info.disk_size_gb = round(total / 1e9, 1)
            info.free_space_gb = round(free / 1e9, 1)
            logger.debug("enrich: disk %.1f GB, free %.1f GB",
                         info.disk_size_gb, info.free_space_gb)
        except Exception as exc:
            logger.debug("enrich: disk_usage failed: %s", exc)

    # ── 11. Capacity from disk size (if still unknown) ────────────────
    if not info.capacity and info.disk_size_gb > 0:
        try:
            from GUI.device_scanner import _estimate_capacity_from_disk_size
            info.capacity = _estimate_capacity_from_disk_size(info.disk_size_gb)
            if info.capacity:
                logger.debug("enrich: capacity from disk size: %s", info.capacity)
        except ImportError:
            pass

    logger.info(
        "DeviceInfo enriched: %s %s (%s), checksum=%s, fw=%s, formats=%s, "
        "disk=%.1fGB",
        info.model_family, info.generation, info.model_number,
        info.checksum_type, info.firewire_guid or "none",
        list(info.artwork_formats.keys()) if info.artwork_formats else "none",
        info.disk_size_gb,
    )


# ──────────────────────────────────────────────────────────────────────
# Private enrichment helpers — each probes ONE source
# ──────────────────────────────────────────────────────────────────────

def _enrich_from_sysinfo_extended(info: DeviceInfo) -> None:
    """Read SysInfoExtended XML plist for FireWireGUID and model info."""
    sysinfo_ex_path = os.path.join(
        info.path, "iPod_Control", "Device", "SysInfoExtended",
    )
    if not os.path.exists(sysinfo_ex_path):
        return

    try:
        with open(sysinfo_ex_path, "r", errors="ignore") as f:
            content = f.read()
    except Exception as exc:
        logger.debug("enrich: SysInfoExtended read failed: %s", exc)
        return

    import re as _re

    # FireWireGUID
    if not info.firewire_guid:
        m = _re.search(
            r"<key>FireWireGUID</key>\s*<string>([0-9A-Fa-f]+)</string>",
            content,
        )
        if m:
            guid_hex = m.group(1)
            if guid_hex.startswith(("0x", "0X")):
                guid_hex = guid_hex[2:]
            if guid_hex and guid_hex != "0" * len(guid_hex):
                info.firewire_guid = guid_hex
                logger.debug("enrich: FW GUID from SysInfoExtended: %s", guid_hex)

    # Serial number
    if not info.serial:
        m = _re.search(
            r"<key>SerialNumber</key>\s*<string>([^<]+)</string>",
            content,
        )
        if m:
            info.serial = m.group(1).strip()

    # Model number (ProductType or ModelNumStr)
    if not info.model_number:
        m = _re.search(
            r"<key>ModelNumStr</key>\s*<string>([^<]+)</string>",
            content,
        )
        if m:
            try:
                from iTunesDB_Writer.device import _extract_model_number
                mn = _extract_model_number(m.group(1).strip())
                if mn:
                    info.model_number = mn
                    logger.debug("enrich: model from SysInfoExtended: %s", mn)
            except ImportError:
                pass

    # Board hardware name
    if not info.board:
        m = _re.search(
            r"<key>BoardHwName</key>\s*<string>([^<]+)</string>",
            content,
        )
        if m:
            info.board = m.group(1).strip()


def _enrich_from_hardware_probe(info: DeviceInfo) -> None:
    """Run the full hardware probe pipeline (IOCTL + device tree + USB PID).

    On Windows this sends ``IOCTL_STORAGE_QUERY_PROPERTY`` to the drive handle
    (gives serial, firmware, vendor/product), walks the PnP device tree (gives
    FW GUID + USB PID), and maps the PID to a model family.

    On macOS/Linux the platform-specific scanner probers run instead.
    """
    if not info.path:
        return

    import sys as _sys

    try:
        if _sys.platform == "win32":
            drive_letter = info.drive_letter
            if not drive_letter:
                return

            # Full IOCTL probe (serial, firmware, vendor) + device tree walk
            # (FW GUID, USB PID).  _identify_via_direct_ioctl calls
            # _walk_device_tree internally.
            from GUI.device_scanner import (
                _identify_via_direct_ioctl,
                _setup_win32_prototypes,
            )
            _setup_win32_prototypes()
            hw = _identify_via_direct_ioctl(drive_letter)

            if not hw:
                # Fallback: WMI (slower, subprocess)
                try:
                    from GUI.device_scanner import _identify_via_usb_for_drive
                    hw = _identify_via_usb_for_drive(drive_letter)
                except ImportError:
                    hw = None

            if not hw:
                return

        elif _sys.platform == "darwin":
            from GUI.device_scanner import _probe_hardware_macos
            hw = _probe_hardware_macos(info.path)
            if not hw:
                return

        else:  # Linux
            from GUI.device_scanner import _probe_hardware_linux
            hw = _probe_hardware_linux(info.path)
            if not hw:
                return

    except (ImportError, Exception) as exc:
        logger.debug("enrich: hardware probe failed: %s", exc)
        return

    # Merge hardware results into DeviceInfo (never overwrite existing)
    if not info.firewire_guid and hw.get("firewire_guid"):
        guid_hex = hw["firewire_guid"]
        if guid_hex != "0" * len(guid_hex):
            info.firewire_guid = guid_hex
            logger.debug("enrich: FW GUID from hardware: %s", guid_hex)

    if not info.serial and hw.get("serial"):
        info.serial = hw["serial"]
        logger.debug("enrich: serial from hardware: %s", info.serial)

    if not info.firmware and hw.get("firmware"):
        info.firmware = hw["firmware"]
        logger.debug("enrich: firmware from hardware: %s", info.firmware)

    if not info.usb_pid and hw.get("usb_pid"):
        info.usb_pid = hw["usb_pid"]

    if not info.model_number and hw.get("model_number"):
        info.model_number = hw["model_number"]

    if info.identification_method == "unknown":
        info.identification_method = "hardware"


def _try_iokit_vpd(
    info: "DeviceInfo", usb_pid: int, serial_filter: str
) -> dict | None:
    """Attempt IOKit SCSI VPD query (macOS only, no root)."""
    try:
        from ipod_iokit_query import query_ipod_vpd
    except ImportError:
        logger.debug("enrich: ipod_iokit_query not available")
        return None

    logger.info(
        "enrich: SysInfo missing — trying IOKit SCSI VPD "
        "(pid=0x%04X, serial=%s)",
        usb_pid,
        serial_filter,
    )
    try:
        vpd_info = query_ipod_vpd(
            usb_pid=usb_pid, serial_filter=serial_filter
        )
    except Exception as exc:
        logger.debug("enrich: IOKit VPD query failed: %s", exc)
        return None

    if not vpd_info or not vpd_info.get("SerialNumber"):
        logger.debug("enrich: IOKit VPD returned no useful data")
        return None

    logger.info(
        "enrich: IOKit VPD got serial=%s, FamilyID=%s",
        vpd_info.get("SerialNumber"),
        vpd_info.get("FamilyID"),
    )
    return vpd_info


def _apply_vpd_result(info: "DeviceInfo", vpd_info: dict) -> None:
    """Apply VPD query results to DeviceInfo and write SysInfo to iPod."""
    from ipod_usb_query import write_sysinfo

    # Write SysInfo to iPod so future runs don't need VPD
    if info.path and os.path.exists(info.path):
        try:
            wrote = write_sysinfo(info.path, vpd_info)
            if wrote:
                logger.info(
                    "enrich: wrote SysInfo to %s from VPD data", info.path
                )
        except Exception as exc:
            logger.debug("enrich: SysInfo write failed: %s", exc)

    # Apply VPD data directly to info
    vpd_serial = vpd_info.get("SerialNumber", "")
    if vpd_serial:
        info.serial = vpd_serial
    if not info.firewire_guid:
        fw = vpd_info.get("FireWireGUID", vpd_info.get("usb_serial", ""))
        if fw:
            info.firewire_guid = fw.upper()
    vpd_fw = vpd_info.get("VisibleBuildID", vpd_info.get("BuildID", ""))
    if vpd_fw:
        info.firmware = vpd_fw

    # Re-read SysInfo if it was written successfully
    if info.path and not info.sysinfo:
        try:
            from iTunesDB_Writer.device import read_sysinfo

            info.sysinfo = read_sysinfo(info.path)
            if info.sysinfo:
                logger.debug(
                    "enrich: SysInfo re-read after VPD (%d keys)",
                    len(info.sysinfo),
                )
                if not info.board:
                    info.board = info.sysinfo.get("BoardHwName", "")
                if not info.serial:
                    info.serial = info.sysinfo.get("pszSerialNumber", "")
                if not info.firmware:
                    info.firmware = info.sysinfo.get("visibleBuildID", "")
        except Exception:
            pass

    if info.serial:
        info.identification_method = "usb_vpd"


def _enrich_from_usb_vpd(info: DeviceInfo) -> None:
    """Query iPod firmware via USB SCSI VPD pages for device identification.

    This is the fallback when SysInfo is missing or empty (iPod was never
    synced with iTunes).  It sends SCSI INQUIRY commands over USB to read
    Apple-proprietary VPD pages containing a full device XML plist.

    On macOS, the preferred path uses IOKit SCSITaskLib — no root needed
    and the iPod stays mounted.  Falls back to pyusb on other platforms
    (root required on Linux; unmounts then remounts the iPod).

    If the query succeeds, writes SysInfo + SysInfoExtended to the iPod
    so that subsequent runs can identify the device normally.
    """
    import sys as _sys
    import time as _time

    # Use USB PID and/or FireWire GUID to target the right device
    usb_pid = info.usb_pid or 0
    serial_filter = info.firewire_guid or ""

    # ── macOS fast path: IOKit SCSI (no root, no unmount) ──────────
    if _sys.platform == "darwin":
        vpd_info = _try_iokit_vpd(info, usb_pid, serial_filter)
        if vpd_info:
            _apply_vpd_result(info, vpd_info)
            return

    # ── Fallback: pyusb path (requires root on macOS/Linux) ────────
    if _sys.platform != "win32":
        try:
            if os.geteuid() != 0:
                logger.debug("enrich: USB VPD skipped (not root)")
                return
        except AttributeError:
            pass  # Shouldn't happen on Unix, but be safe

    try:
        from ipod_usb_query import query_ipod_vpd
    except ImportError:
        logger.debug("enrich: ipod_usb_query not available")
        return

    logger.info(
        "enrich: SysInfo missing — attempting USB VPD query "
        "(pid=0x%04X, serial=%s)", usb_pid, serial_filter,
    )

    try:
        vpd_info = query_ipod_vpd(
            usb_pid=usb_pid,
            serial_filter=serial_filter,
        )
    except PermissionError:
        logger.debug("enrich: USB VPD query needs root — skipping")
        return
    except Exception as exc:
        logger.debug("enrich: USB VPD query failed: %s", exc)
        return

    if not vpd_info or not vpd_info.get("SerialNumber"):
        logger.debug("enrich: USB VPD returned no useful data")
        return

    logger.info(
        "enrich: USB VPD got serial=%s, FamilyID=%s",
        vpd_info.get("SerialNumber"), vpd_info.get("FamilyID"),
    )

    # On macOS/Linux the disk was unmounted during query — wait for remount.
    # The mount point may change (e.g. "/Volumes/JOHN'S IPOD" → "JOHN'S IPOD 1")
    # if old stale dirs exist, so we use the USB serial to find the new path.
    if _sys.platform != "win32":
        logger.debug("enrich: waiting for iPod to remount after VPD query...")
        usb_serial = vpd_info.get("usb_serial", "") or info.firewire_guid or ""
        new_path: str | None = None
        try:
            from ipod_usb_query import _find_mount_point_for_usb_serial
        except ImportError:
            _find_mount_point_for_usb_serial = None  # type: ignore[assignment]

        for attempt in range(12):
            _time.sleep(1)
            # First try the lookup-by-serial approach (handles renamed mounts)
            if _find_mount_point_for_usb_serial and usb_serial:
                new_path = _find_mount_point_for_usb_serial(usb_serial)
                if new_path:
                    break
            # Fallback: check if original path is still a valid mount
            if os.path.ismount(info.path):
                new_path = info.path
                break

        if new_path and new_path != info.path:
            logger.info(
                "enrich: iPod remounted at new path: %s (was %s)",
                new_path, info.path,
            )
            info.path = new_path
        elif not new_path:
            logger.warning(
                "enrich: iPod did not remount within 12s (serial=%s)",
                usb_serial,
            )
            # Still apply VPD data directly to info (below)

    # Write SysInfo + apply VPD data to info
    _apply_vpd_result(info, vpd_info)


def _enrich_from_serial_lookup(info: DeviceInfo) -> None:
    """Look up exact model from serial number's last 3 characters.

    This is very high confidence — the last 3 chars encode the exact model
    including capacity and color.
    """
    if not info.serial or len(info.serial) < 3:
        return

    try:
        from GUI.device_scanner import SERIAL_LAST3_TO_MODEL
        from iTunesDB_Writer.device import IPOD_MODELS
    except ImportError:
        return

    last3 = info.serial[-3:]
    model_num = SERIAL_LAST3_TO_MODEL.get(last3)
    if not model_num:
        return

    model_info = IPOD_MODELS.get(model_num)
    if not model_info:
        # At least set the model number
        if not info.model_number:
            info.model_number = model_num
        return

    if not info.model_number:
        info.model_number = model_num
    info.model_family = model_info[0]
    info.generation = model_info[1]
    if not info.capacity:
        info.capacity = model_info[2]
    if not info.color:
        info.color = model_info[3]
    if info.identification_method in ("unknown", "hardware"):
        info.identification_method = "serial"
    logger.debug("enrich: serial-last-3 '%s' → %s %s %s %s",
                 last3, model_info[0], model_info[1],
                 model_info[2], model_info[3])


def _persist_model_to_sysinfo(info: DeviceInfo) -> None:
    """Append ModelNumStr to SysInfo if it's missing.

    After serial-based model resolution determines the model_number,
    write it back to the SysInfo file so the scanner's Layer 1 (fast
    SysInfo lookup) works on future launches — no serial lookup needed.
    """
    if not info.path or not info.model_number:
        return

    sysinfo_path = os.path.join(
        info.path, "iPod_Control", "Device", "SysInfo",
    )
    if not os.path.exists(sysinfo_path):
        return

    try:
        content = open(sysinfo_path, "r", errors="replace").read()
        if "ModelNumStr" in content:
            return  # already present

        # Append ModelNumStr in the format the scanner expects
        with open(sysinfo_path, "a") as f:
            f.write(f"ModelNumStr: x{info.model_number[1:]}\n")
        logger.info("enrich: appended ModelNumStr to SysInfo (%s)",
                    info.model_number)
    except Exception as exc:
        logger.debug("enrich: failed to persist ModelNumStr: %s", exc)


def _enrich_from_windows_registry(info: DeviceInfo) -> None:
    """Windows-only: read iPod FireWire GUID from USBSTOR registry entries.

    The USB serial number for iPod Classic IS the FireWire GUID
    (16 hex chars = 8 bytes).  This persists in the registry even after
    the iPod is disconnected.

    If the device's serial is already known we only accept a GUID from
    an instance ID that contains it, avoiding stale GUIDs from
    previously-connected iPods.  When no serial is available we fall
    back to accepting the first valid GUID (best-effort).
    """
    import sys as _sys
    if _sys.platform != "win32":
        return

    try:
        import winreg
    except ImportError:
        return

    try:
        usbstor_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Enum\USBSTOR",
        )
    except OSError:
        return

    # We'll collect ALL valid GUIDs but prefer one that matches the
    # current device's serial (if known).  The serial from hardware
    # probing is usually the FW GUID itself, but the instance ID also
    # contains it so we can cross-check.
    known_serial = info.serial.upper() if info.serial else ""
    best_guid: str | None = None

    try:
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(usbstor_key, i)
                i += 1
            except OSError:
                break

            if "Apple" not in subkey_name or "iPod" not in subkey_name:
                continue

            try:
                device_key = winreg.OpenKey(usbstor_key, subkey_name)
                j = 0
                while True:
                    try:
                        instance_id = winreg.EnumKey(device_key, j)
                        j += 1
                    except OSError:
                        break

                    parts = instance_id.split("&")
                    for part in parts:
                        part = part.strip()
                        if len(part) == 16:
                            try:
                                guid_bytes = bytes.fromhex(part)
                                if guid_bytes == b"\x00" * 8:
                                    continue
                            except ValueError:
                                continue

                            guid_upper = part.upper()

                            # If we know the serial, accept only if it
                            # appears somewhere in the instance ID.
                            if known_serial:
                                if known_serial in instance_id.upper():
                                    info.firewire_guid = guid_upper
                                    logger.debug(
                                        "enrich: FW GUID from registry "
                                        "(serial-matched): %s", guid_upper,
                                    )
                                    winreg.CloseKey(device_key)
                                    winreg.CloseKey(usbstor_key)
                                    return
                            else:
                                # No serial — remember first valid GUID
                                if best_guid is None:
                                    best_guid = guid_upper

                winreg.CloseKey(device_key)
            except OSError:
                continue
    finally:
        winreg.CloseKey(usbstor_key)

    # Fallback: use first valid GUID found (may be from a different iPod)
    if best_guid:
        info.firewire_guid = best_guid
        if known_serial:
            logger.warning(
                "enrich: FW GUID from registry (no serial match, may be "
                "stale): %s", best_guid,
            )
        else:
            logger.debug(
                "enrich: FW GUID from registry (no serial to validate): %s",
                best_guid,
            )


def _enrich_from_itunesdb_header(info: DeviceInfo) -> None:
    """Read the iTunesDB mhbd header for hashing_scheme and db_id."""
    import struct

    itdb_path = os.path.join(info.path, "iPod_Control", "iTunes", "iTunesDB")
    if not os.path.exists(itdb_path):
        return

    try:
        with open(itdb_path, "rb") as f:
            hdr = f.read(256)

        if len(hdr) < 0xA0 or hdr[:4] != b"mhbd":
            return

        info.hashing_scheme = struct.unpack("<H", hdr[0x30:0x32])[0]

        # Check for non-zero hash signatures
        hash58_present = hdr[0x58:0x6C] != b"\x00" * 20
        hash72_present = hdr[0x72:0x74] == bytes([0x01, 0x00])  # sig marker

        logger.debug(
            "enrich: iTunesDB hdr — scheme=%d, hash58=%s, hash72=%s",
            info.hashing_scheme, hash58_present, hash72_present,
        )
    except Exception as exc:
        logger.debug("enrich: iTunesDB header read failed: %s", exc)


def _resolve_checksum_type(info: DeviceInfo) -> None:
    """Determine checksum type using every available signal.

    Priority:
      1. Family + generation → canonical lookup (covers ALL colour variants)
      2. HashInfo file existence → HASH72
      3. iTunesDB hashing_scheme field
      4. Firmware version hints
      5. FirewireGuid presence hints at post-2007 device
      6. Default to NONE (safe for pre-2007 iPods)
    """
    try:
        from iTunesDB_Writer.device import (
            ChecksumType, checksum_type_for_family_gen,
        )
    except ImportError:
        return

    # Priority 1: family + generation lookup (authoritative, no gaps)
    if info.model_family and info.generation:
        ct = checksum_type_for_family_gen(info.model_family, info.generation)
        if ct is not None:
            info.checksum_type = int(ct)
            logger.debug(
                "enrich: checksum %s (family=%s, gen=%s)",
                ct.name, info.model_family, info.generation,
            )
            return

    # Priority 2: HashInfo file existence → HASH72
    if info.path:
        hi_path = os.path.join(
            info.path, "iPod_Control", "Device", "HashInfo",
        )
        if os.path.exists(hi_path):
            info.checksum_type = int(ChecksumType.HASH72)
            logger.debug("enrich: checksum HASH72 (HashInfo file exists)")
            return

    # Priority 3: hashing_scheme from iTunesDB header
    if info.hashing_scheme == 1:
        info.checksum_type = int(ChecksumType.HASH58)
        logger.debug("enrich: checksum HASH58 (from iTunesDB header scheme=1)")
        return
    if info.hashing_scheme == 2:
        info.checksum_type = int(ChecksumType.HASH72)
        logger.debug("enrich: checksum HASH72 (from iTunesDB header scheme=2)")
        return

    # Priority 4: firmware version hints
    if info.firmware:
        try:
            version = int(info.firmware.split(".")[0])
            if version >= 2:
                info.checksum_type = int(ChecksumType.UNKNOWN)
                logger.debug("enrich: checksum UNKNOWN (firmware %s ≥ 2.x)",
                             info.firmware)
                return
        except (ValueError, IndexError):
            pass

    # Priority 5: FirewireGuid hints at post-2007 device
    if info.firewire_guid:
        info.checksum_type = int(ChecksumType.UNKNOWN)
        logger.debug("enrich: checksum UNKNOWN (has FW GUID but no model match)")
        return

    # Priority 6: default
    info.checksum_type = int(ChecksumType.NONE)
    logger.debug("enrich: checksum NONE (default — pre-2007 or unidentifiable)")


def _enrich_artwork_from_artworkdb(info: DeviceInfo) -> None:
    """Scan ArtworkDB binary for mhif format IDs as a last resort."""
    artdb_path = os.path.join(info.path, "iPod_Control", "Artwork", "ArtworkDB")
    if not os.path.exists(artdb_path):
        return

    try:
        from ArtworkDB_Writer.rgb565 import _extract_format_ids, ALL_KNOWN_FORMATS
        with open(artdb_path, "rb") as f:
            data = f.read()

        format_ids = _extract_format_ids(data)
        if format_ids:
            fmts = {}
            for fid in format_ids:
                if fid in ALL_KNOWN_FORMATS:
                    fmts[fid] = ALL_KNOWN_FORMATS[fid]
            if fmts:
                info.artwork_formats = fmts
                logger.debug("enrich: artwork formats from ArtworkDB scan: %s",
                             list(fmts.keys()))
    except Exception as exc:
        logger.debug("enrich: ArtworkDB scan failed: %s", exc)
