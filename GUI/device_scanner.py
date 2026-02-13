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
    - model_number:  SysInfo ModelNumStr → IPOD_MODELS  >  serial last-3 → IPOD_MODELS
    - firewire_guid: device tree  >  SysInfoExtended  >  SysInfo  >  IOCTL serial (if 16 hex)
    - serial:        IOCTL (Apple serial)  >  SysInfo (skip RAND-*)
    - firmware:      IOCTL revision  >  SysInfo visibleBuildID
    - usb_pid:       device tree USB parent  >  WMI fallback
    - model_family:  IPOD_MODELS  >  USB PID table (with disk-size sanity check)  >  hashing_scheme
"""

import ctypes
import ctypes.wintypes as wt
import logging
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── USB Product ID → iPod generation (Apple VID = 0x05AC) ──────────────────
#
# Sources: Linux USB ID Repository, The Apple Wiki, empirical testing.
#
# IMPORTANT: The 0x124x range are DFU/WTF recovery mode PIDs, NOT normal
# operation PIDs.  They should only appear if the iPod is in recovery mode.
# In normal disk mode, iPods use PIDs from 0x120x and 0x126x ranges.
#
# Note: Some PIDs are shared across generations or USB modes.  PID-based
# identification is a LOW-confidence fallback — prefer SysInfo ModelNumStr
# or serial number suffix matching.

USB_PID_TO_MODEL: dict[int, tuple[str, str]] = {
    # (model_family, generation)

    # ── Normal-mode PIDs (0x120x) ──────────────────────────────────────────
    0x1201: ("iPod", "3rd Gen"),       # iPod 3G (dock connector)
    0x1202: ("iPod", "2nd Gen"),       # iPod 2G (touch wheel)
    0x1203: ("iPod", "4th Gen"),       # iPod 4G (click wheel, grayscale)
    0x1204: ("iPod Photo", "4th Gen"),  # iPod Photo / iPod with Colour Display
    0x1205: ("iPod Mini", "1st Gen"),  # iPod Mini 1G
    0x1206: ("iPod Nano", "1st Gen"),  # iPod Nano 1G (A1137)
    0x1207: ("iPod Mini", "2nd Gen"),  # iPod Mini 2G
    0x1208: ("iPod", "1st Gen"),       # iPod 1G (scroll wheel, FireWire)
    0x1209: ("iPod Video", "5th Gen"),  # iPod Video 5G/5.5G (A1136)
    0x120A: ("iPod Nano", "2nd Gen"),  # iPod Nano 2G (A1199) — disk mode

    # ── DFU / WTF recovery mode PIDs (0x124x) ─────────────────────────────
    # These appear when the iPod is in firmware recovery, NOT normal use.
    # Included so recovery-mode devices are still identified, but marked with
    # a "(Recovery)" suffix in the generation string.
    0x1240: ("iPod Nano", "2nd Gen (Recovery)"),     # Nano 2G DFU
    0x1241: ("iPod Classic", "1st Gen (Recovery)"),   # Classic 1G DFU
    0x1242: ("iPod Nano", "3rd Gen (Recovery)"),      # Nano 3G WTF
    0x1243: ("iPod Nano", "4th Gen (Recovery)"),      # Nano 4G WTF
    0x1245: ("iPod Classic", "3rd Gen (Recovery)"),   # Classic 3G WTF
    0x1246: ("iPod Nano", "5th Gen (Recovery)"),      # Nano 5G WTF
    0x1255: ("iPod Nano", "4th Gen (Recovery)"),      # Nano 4G DFU

    # ── Normal-mode PIDs (0x126x) ──────────────────────────────────────────
    0x1260: ("iPod Nano", "2nd Gen"),  # iPod Nano 2G (A1199) — normal mode
    0x1261: ("iPod Classic", ""),      # iPod Classic (all gens share this PID)
    0x1262: ("iPod Nano", "3rd Gen"),  # iPod Nano 3G (A1236)
    0x1263: ("iPod Nano", "4th Gen"),  # iPod Nano 4G (A1285)
    0x1265: ("iPod Nano", "5th Gen"),  # iPod Nano 5G (A1320)
    0x1266: ("iPod Nano", "6th Gen"),  # iPod Nano 6G (A1366)
    0x1267: ("iPod Nano", "7th Gen"),  # iPod Nano 7G (A1446)

    # ── iPod Shuffle PIDs ──────────────────────────────────────────────────
    0x1300: ("iPod Shuffle", "1st Gen"),
    0x1301: ("iPod Shuffle", "2nd Gen"),
    0x1302: ("iPod Shuffle", "3rd Gen"),
    0x1303: ("iPod Shuffle", "4th Gen"),
}


# ── Serial number last-3-char → model number (from libgpod) ────────────────

SERIAL_LAST3_TO_MODEL: dict[str, str] = {
    # iPod Classic
    "Y5N": "MB029", "YMV": "MB147", "YMU": "MB145", "YMX": "MB150",
    "2C5": "MB562", "2C7": "MB565",
    "9ZS": "MC293", "9ZU": "MC297",
    # iPod Mini 1G
    "PFW": "M9160", "PRC": "M9160",
    "QKL": "M9436", "QKQ": "M9436", "QKK": "M9435", "QKP": "M9435",
    "QKJ": "M9434", "QKN": "M9434", "QKM": "M9437", "QKR": "M9437",
    # iPod Mini 2G
    "S41": "M9800", "S4C": "M9800", "S43": "M9802", "S45": "M9804",
    "S47": "M9806", "S4J": "M9806", "S42": "M9801", "S44": "M9803",
    "S48": "M9807",
    # Nano 1G
    "TUZ": "MA004", "TV0": "MA005", "TUY": "MA099", "TV1": "MA107",
    "UYN": "MA350", "UYP": "MA352",
    # Nano 2G  (A1199 — serial from Apple Wiki / libgpod)
    "VQ5": "MA477", "VQ6": "MA477",  # 2GB Silver
    "V8T": "MA426", "V8U": "MA426",  # 4GB Silver
    "V8W": "MA428", "V8X": "MA428",  # 4GB Blue
    "VQH": "MA487", "VQJ": "MA487",  # 4GB Green
    "VQK": "MA489", "VQL": "MA489",  # 4GB Pink
    "WL2": "MA725", "WL3": "MA725",  # 4GB Red
    "X9A": "MA726", "X9B": "MA726",  # 8GB Red
    "VQT": "MA497", "VQU": "MA497",  # 8GB Black
    "YER": "MA899", "YES": "MA899",  # 8GB (PRODUCT) RED
    # Nano 3G
    "Y0P": "MA978", "Y0R": "MA980",
    "YXR": "MB249", "YXV": "MB257", "YXT": "MB253", "YXX": "MB261",
    # Nano 4G
    "37P": "MB663", "37Q": "MB666", "37H": "MB654", "1P1": "MB480",
    "37K": "MB657", "37L": "MB660", "2ME": "MB598",
    "3QS": "MB732", "3QT": "MB735", "3QU": "MB739", "3QW": "MB742",
    "3QX": "MB745", "3QY": "MB748", "3R0": "MB754", "3QZ": "MB751",
    # Nano 5G
    "71V": "MC027", "71Y": "MC031", "721": "MC034", "726": "MC037",
    "72A": "MC040", "72F": "MC046", "72K": "MC049", "72L": "MC050",
    "72Q": "MC060", "72R": "MC062",
    # Video 5G / 5.5G
    "SZ9": "MA002", "TXK": "MA146", "TXM": "MA146",
    "V96": "MA450", "WUC": "MA450", "W9G": "MA664",
}


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


@dataclass
class DiscoveredIPod:
    """A discovered iPod device."""
    path: str  # Drive root path (e.g., "D:\\")
    drive_letter: str  # Just the letter (e.g., "D")

    # Identification (may be partially filled)
    model_family: str = "iPod"  # e.g., "iPod Classic", "iPod Nano"
    generation: str = ""  # e.g., "3rd Gen"
    capacity: str = ""  # e.g., "160GB"
    color: str = ""  # e.g., "Black"
    model_number: str = ""  # e.g., "MC297"

    # Technical
    firewire_guid: str = ""
    serial: str = ""
    firmware: str = ""
    usb_pid: int = 0
    hashing_scheme: int = -1  # from iTunesDB header
    disk_size_gb: float = 0.0
    free_space_gb: float = 0.0

    # How was it identified?
    identification_method: str = "filesystem"  # filesystem, usb_pid, serial, sysinfo, hashing

    @property
    def display_name(self) -> str:
        """User-friendly display name."""
        parts = [self.model_family]
        if self.generation:
            parts.append(self.generation)
        if self.capacity:
            parts.append(self.capacity)
        if self.color:
            parts.append(self.color)
        return " ".join(parts)

    @property
    def subtitle(self) -> str:
        """Secondary line (drive letter + free space)."""
        parts = [f"Drive {self.drive_letter}:"]
        if self.disk_size_gb > 0:
            parts.append(f"{self.free_space_gb:.1f} / {self.disk_size_gb:.1f} GB free")
        return " — ".join(parts)

    @property
    def icon(self) -> str:
        """Emoji icon based on model family."""
        family = self.model_family.lower()
        if "classic" in family or "video" in family or "photo" in family:
            return "📱"
        elif "nano" in family:
            return "🎵"
        elif "shuffle" in family:
            return "🔀"
        elif "mini" in family:
            return "🎶"
        return "🎵"


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


def _identify_via_usb_for_drive(drive_letter: str) -> Optional[dict]:
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
            capture_output=True, text=True, timeout=10,
        )
        pnp_id = ""
        for line in wmi_result.stdout.strip().splitlines():
            line = line.strip()
            if line.startswith("PNP:"):
                pnp_id = line[4:]
            elif line.startswith("SERIAL:"):
                serial = line[7:].strip()
                if serial:
                    result["serial"] = serial
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

                        winreg.CloseKey(pid_key)
                    except OSError:
                        continue

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
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def _identify_via_direct_ioctl(drive_letter: str) -> Optional[dict]:
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

    handle = ctypes.windll.kernel32.CreateFileW(
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

        ok = ctypes.windll.kernel32.DeviceIoControl(
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
            result["serial"] = serial
            # The IOCTL serial for iPods is typically the FireWire GUID
            # (16 hex chars) or the USB instance ID (same thing)
            clean = serial.replace(" ", "").strip()
            if len(clean) == 16:
                try:
                    bytes.fromhex(clean)
                    result["firewire_guid"] = clean
                except ValueError:
                    pass

    finally:
        ctypes.windll.kernel32.CloseHandle(handle)

    # ── Walk the PnP device tree to get FireWire GUID and USB PID ──
    # The SCSI layer gives us vendor/product/serial/firmware, but the
    # FireWire GUID (needed for hash generation) and the USB PID live
    # in the PnP device tree above the SCSI device.
    tree_info = _walk_device_tree(drive_letter)
    if tree_info:
        if tree_info.get("firewire_guid"):
            result["firewire_guid"] = tree_info["firewire_guid"]
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

    k32 = ctypes.windll.kernel32
    sa = ctypes.windll.setupapi
    cm = ctypes.windll.cfgmgr32

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
    kernel32 = ctypes.windll.kernel32
    setupapi = ctypes.windll.setupapi
    cfgmgr32 = ctypes.windll.cfgmgr32

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
    logger.debug("Drive %s: USBSTOR instance = %s", drive_letter, usbstor_id)

    if "USBSTOR" in usbstor_id.upper():
        parts = usbstor_id.split("\\")
        if len(parts) >= 3:
            guid = _extract_guid_from_instance_id(parts[2])
            if guid:
                result["firewire_guid"] = guid

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
                logger.debug("Drive %s: USB parent = %s",
                             drive_letter, usb_id)

                upper_id = usb_id.upper()
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

    return result


# ── Unified probing functions ──────────────────────────────────────────────


def _probe_hardware(drive_letter: str) -> dict:
    """
    Phase 1: Hardware probing — query the device directly via Win32 APIs.

    Tries the fast direct path first (IOCTL + device tree walk), then falls
    back to WMI if the direct path fails entirely.  The result merges data
    from whichever sources succeed.

    Returns a dict that may contain any of:
        vendor, product, serial, firmware, bus_type, firewire_guid,
        usb_pid, model_family, generation
    """
    result: dict = {}

    if sys.platform != "win32":
        return result

    # ── Primary: Direct IOCTL + device tree (fast, no subprocess) ──────
    ioctl_info = _identify_via_direct_ioctl(drive_letter)
    if ioctl_info:
        result.update(ioctl_info)
        logger.debug("Hardware probe (direct): %s", result)

    # ── Fallback: WMI (only if direct gave us nothing useful) ──────────
    # The WMI path is kept as a safety net for edge cases where the direct
    # path can't open the device handle (e.g., permission denied, unusual
    # driver stack).  It's never tried when direct already succeeded.
    if not result:
        logger.debug(
            "Direct probe failed for drive %s, falling back to WMI",
            drive_letter,
        )
        wmi_info = _identify_via_usb_for_drive(drive_letter)
        if wmi_info:
            result.update(wmi_info)
            logger.debug("Hardware probe (WMI fallback): %s", result)

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

    # ── SysInfo / SysInfoExtended ──────────────────────────────────────
    sysinfo = _identify_via_sysinfo(ipod_path)
    if sysinfo:
        result.update(sysinfo)

    # ── iTunesDB header (hashing_scheme) ───────────────────────────────
    hash_info = _identify_via_hashing_scheme(ipod_path)
    if hash_info:
        # Only take hashing_scheme; model_family from this source is low-confidence
        result["hashing_scheme"] = hash_info.get("hashing_scheme", -1)
        # Store the hash-inferred family/gen separately so Phase 3 can use
        # them as a last resort without overriding higher-confidence sources.
        if hash_info.get("model_family"):
            result["hash_model_family"] = hash_info["model_family"]
            result["hash_generation"] = hash_info.get("generation", "")

    return result


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
    identification_method.
    """
    from iTunesDB_Writer.device import IPOD_MODELS

    resolved: dict = {}

    # ── FireWire GUID ──────────────────────────────────────────────────
    # Priority: device tree > SysInfoExtended/SysInfo > IOCTL serial
    # (The device tree USBSTOR instance is the most authoritative because
    # it's guaranteed to be for the currently-connected device at this
    # specific drive letter.  SysInfo can be stale or missing.)
    resolved["firewire_guid"] = hw.get("firewire_guid") or fs.get("firewire_guid") or ""

    # ── Serial ─────────────────────────────────────────────────────────
    # Priority: IOCTL serial > SysInfo serial (but skip "RAND-*" serials)
    hw_serial = hw.get("serial", "")
    fs_serial = fs.get("serial", "")
    if hw_serial and not hw_serial.startswith("RAND"):
        resolved["serial"] = hw_serial
    elif fs_serial and not fs_serial.startswith("RAND"):
        resolved["serial"] = fs_serial
    else:
        resolved["serial"] = hw_serial or fs_serial or ""

    # ── Firmware ───────────────────────────────────────────────────────
    # Priority: IOCTL revision > SysInfo visibleBuildID
    resolved["firmware"] = hw.get("firmware") or fs.get("firmware") or ""

    # ── USB PID ────────────────────────────────────────────────────────
    resolved["usb_pid"] = hw.get("usb_pid", 0)

    # ── Hashing scheme ─────────────────────────────────────────────────
    resolved["hashing_scheme"] = fs.get("hashing_scheme", -1)

    # ── Model identification (layered, highest-confidence wins) ────────
    # Layer 1: SysInfo ModelNumStr → IPOD_MODELS (highest confidence)
    sysinfo_model = fs.get("model_number", "")
    if sysinfo_model:
        info = IPOD_MODELS.get(sysinfo_model)
        if info:
            resolved["model_number"] = sysinfo_model
            resolved["model_family"] = info[0]
            resolved["generation"] = info[1]
            resolved["capacity"] = info[2]
            resolved["color"] = info[3]
            resolved["identification_method"] = "sysinfo"
            return resolved

    # Layer 2: Serial last-3-char → IPOD_MODELS (very reliable)
    serial = resolved["serial"]
    if serial:
        serial_info = _identify_via_serial_lookup(serial)
        if serial_info:
            resolved["model_number"] = serial_info.get("model_number", "")
            resolved["model_family"] = serial_info.get("model_family", "iPod")
            resolved["generation"] = serial_info.get("generation", "")
            resolved["capacity"] = serial_info.get("capacity", "")
            resolved["color"] = serial_info.get("color", "")
            resolved["identification_method"] = "serial"
            return resolved

    # Layer 3: USB PID → family/generation (coarse, sanity-checked)
    pid = resolved["usb_pid"]
    pid_family = hw.get("model_family", "")
    pid_gen = hw.get("generation", "")
    if pid and pid_family:
        if _model_matches_disk_size(pid_family, disk_size_gb):
            resolved["model_family"] = pid_family
            resolved["generation"] = pid_gen
            resolved["identification_method"] = "usb_pid"
        else:
            logger.warning(
                "USB PID 0x%04X says %s but disk is %.1f GB — ignoring "
                "(likely stale or shared PID)", pid, pid_family, disk_size_gb,
            )

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

    return resolved


def _identify_via_sysinfo(ipod_path: str) -> Optional[dict]:
    """Try to identify via SysInfo / SysInfoExtended files."""
    from iTunesDB_Writer.device import IPOD_MODELS

    result: dict = {}

    # Try SysInfoExtended first
    sie_path = os.path.join(ipod_path, "iPod_Control", "Device", "SysInfoExtended")
    if os.path.exists(sie_path):
        try:
            import re
            content = Path(sie_path).read_text(errors="replace")
            serial_match = re.search(
                r"<key>SerialNumber</key>\s*<string>([^<]+)</string>", content
            )
            if serial_match:
                result["serial"] = serial_match.group(1)
            guid_match = re.search(
                r"<key>FireWireGUID</key>\s*<string>([0-9A-Fa-f]+)</string>", content
            )
            if guid_match:
                guid = guid_match.group(1)
                if guid.startswith(("0x", "0X")):
                    guid = guid[2:]
                result["firewire_guid"] = guid
        except Exception:
            pass

    # Try SysInfo
    sysinfo_path = os.path.join(ipod_path, "iPod_Control", "Device", "SysInfo")
    if os.path.exists(sysinfo_path):
        try:
            content = Path(sysinfo_path).read_text(errors="replace")
            for line in content.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    key, val = key.strip(), val.strip()
                    if key == "ModelNumStr" and val:
                        result["model_raw"] = val
                        # Parse model number
                        model_str = val
                        if model_str.startswith("x"):
                            model_str = "M" + model_str[1:]
                        import re
                        match = re.match(r"^(M[A-Z]?\d{3,4})", model_str.upper())
                        if match:
                            model_num = match.group(1)
                            result["model_number"] = model_num
                            info = IPOD_MODELS.get(model_num)
                            if info:
                                result["model_family"] = info[0]
                                result["generation"] = info[1]
                                result["capacity"] = info[2]
                                result["color"] = info[3]
                    elif key == "pszSerialNumber" and val:
                        result.setdefault("serial", val)
                    elif key == "FirewireGuid" and val:
                        guid = val
                        if guid.startswith(("0x", "0X")):
                            guid = guid[2:]
                        result.setdefault("firewire_guid", guid)
                    elif key == "visibleBuildID" and val:
                        result["firmware"] = val
        except Exception:
            pass

    return result if result else None


def _identify_via_hashing_scheme(ipod_path: str) -> Optional[dict]:
    """
    Identify generation class from iTunesDB hashing_scheme field.

    This is a fallback — it tells us the generation class but not the exact model.
    """
    itdb_path = os.path.join(ipod_path, "iPod_Control", "iTunes", "iTunesDB")
    if not os.path.exists(itdb_path):
        return None

    try:
        with open(itdb_path, "rb") as f:
            header = f.read(0x72)
        if len(header) < 0x32 or header[:4] != b"mhbd":
            return None

        scheme = struct.unpack("<H", header[0x30:0x32])[0]

        result: dict = {"hashing_scheme": scheme}

        if scheme == 0:
            result["model_family"] = "iPod"
            result["generation"] = "(pre-2007)"
        elif scheme == 1:
            result["model_family"] = "iPod Classic"
            result["generation"] = ""  # Could be Classic or Nano 3G/4G
        elif scheme == 2:
            result["model_family"] = "iPod"
            result["generation"] = "(HASH72)"

        return result
    except Exception:
        return None


def _identify_via_serial_lookup(serial: str) -> Optional[dict]:
    """Look up model from serial number's last 3 characters."""
    from iTunesDB_Writer.device import IPOD_MODELS

    if not serial or len(serial) < 3:
        return None

    last3 = serial[-3:]
    model_num = SERIAL_LAST3_TO_MODEL.get(last3)
    if not model_num:
        return None

    info = IPOD_MODELS.get(model_num)
    if info:
        return {
            "model_number": model_num,
            "model_family": info[0],
            "generation": info[1],
            "capacity": info[2],
            "color": info[3],
        }
    return {"model_number": model_num}


def _estimate_capacity_from_disk_size(disk_gb: float) -> str:
    """Estimate marketed capacity from actual disk size."""
    # Marketed vs actual (base-10 GB → base-2):
    # 1GB → ~0.93, 2GB → ~1.86, 4GB → ~3.73, 8GB → ~7.45
    # 16GB → ~14.9, 30GB → ~27.9, 60GB → ~55.9, 80GB → ~74.5
    # 120GB → ~111.8, 160GB → ~149.0
    thresholds = [
        (140, "160GB"), (105, "120GB"), (70, "80GB"),
        (50, "60GB"), (25, "30GB"), (18, "20GB"),
        (13, "16GB"), (6.5, "8GB"), (3, "4GB"),
        (1.5, "2GB"), (0.7, "1GB"), (0.3, "512MB"),
    ]
    for threshold, label in thresholds:
        if disk_gb >= threshold:
            return label
    return ""


def _model_matches_disk_size(model_family: str, disk_gb: float) -> bool:
    """
    Sanity-check whether the identified model is plausible given the disk size.

    This catches misidentification where e.g. a 2GB Nano is wrongly identified
    as a 160GB Classic due to stale USB PID entries.
    """
    family = model_family.lower()

    if "classic" in family:
        # iPod Classic: 80GB, 120GB, 160GB  → real disk > 60GB
        return disk_gb > 60
    elif "video" in family:
        # iPod Video: 30GB, 60GB, 80GB → real disk > 20GB
        return disk_gb > 20
    elif "photo" in family:
        # iPod Photo: 20GB, 30GB, 40GB, 60GB → real disk > 15GB
        return disk_gb > 15
    elif "mini" in family:
        # iPod Mini: 4GB, 6GB → real disk 2-8GB
        return 2 <= disk_gb <= 10
    elif "nano" in family:
        # iPod Nano: 1-16GB → real disk < 20GB
        return disk_gb < 20
    elif "shuffle" in family:
        # iPod Shuffle: 512MB - 4GB → real disk < 5GB
        return disk_gb < 5
    elif family == "ipod":
        # Generic iPod (1G-4G): 5-40GB → real disk > 3GB
        return disk_gb > 3

    # Unknown family — don't reject
    return True


def scan_for_ipods() -> list[DiscoveredIPod]:
    """
    Scan all drives for connected iPods.

    Uses a unified three-phase pipeline:

      **Phase 1 — Hardware probing** (Win32 APIs, no subprocess):
        Direct IOCTL + device tree walk, with silent WMI fallback.

      **Phase 2 — Filesystem probing** (file reads on iPod):
        SysInfo / SysInfoExtended + iTunesDB header.

      **Phase 3 — Model resolution** (per-field priority merge):
        SysInfo ModelNumStr > serial last-3 > USB PID > hashing_scheme.

    Returns a list of DiscoveredIPod objects, sorted by drive letter.
    """
    ipods: list[DiscoveredIPod] = []

    if sys.platform != "win32":
        logger.warning("Drive scanning is only supported on Windows")
        return ipods

    for letter in _get_drive_letters():
        drive_path = f"{letter}:\\"

        # Quick check: skip if not accessible or no iPod_Control
        try:
            if not _has_ipod_control(drive_path):
                continue
        except PermissionError:
            continue

        logger.info("Found iPod_Control on drive %s:", letter)

        ipod = DiscoveredIPod(path=drive_path, drive_letter=letter)
        ipod.disk_size_gb, ipod.free_space_gb = _get_disk_info(drive_path)

        # ── Phase 1: Hardware probing ──────────────────────────────────
        hw = _probe_hardware(letter)

        # ── Phase 2: Filesystem probing ────────────────────────────────
        fs = _probe_filesystem(drive_path)

        # ── Phase 3: Model resolution (per-field priority merge) ───────
        resolved = _resolve_model(hw, fs, ipod.disk_size_gb)

        # Apply resolved fields to the DiscoveredIPod
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

        # Estimate capacity from disk size if still unknown
        if not ipod.capacity and ipod.disk_size_gb > 0:
            ipod.capacity = _estimate_capacity_from_disk_size(ipod.disk_size_gb)

        logger.info(
            "  Identified: %s (method=%s, model=%s, serial=%s)",
            ipod.display_name, ipod.identification_method,
            ipod.model_number or "unknown",
            ipod.serial[-3:] if ipod.serial else "none",
        )

        ipods.append(ipod)

    return ipods
