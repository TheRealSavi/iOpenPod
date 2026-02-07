"""
iPod device scanner - discovers connected iPods by scanning mounted drives.

Detection strategy (in priority order):
1. Scan all drive letters (Windows) for iPod_Control directory
2. For each candidate, identify model via:
   a. USB registry (USBSTOR) — FireWire GUID + serial → model lookup
   b. SysInfoExtended serial number last-3-char lookup
   c. SysInfo ModelNumStr → model table lookup
   d. USB Product ID (PID) → generation mapping
   e. iTunesDB hashing_scheme → generation class
   f. Disk capacity heuristic as last resort
"""

import logging
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ── USB Product ID → iPod generation (Apple VID = 0x05AC) ──────────────────

USB_PID_TO_MODEL: dict[int, tuple[str, str]] = {
    # (model_family, generation)
    0x1201: ("iPod", "1st Gen"),
    0x1202: ("iPod", "2nd Gen"),
    0x1203: ("iPod", "3rd Gen"),
    0x1204: ("iPod Mini", "1st Gen"),
    0x1205: ("iPod Video", "5th Gen"),
    0x1206: ("iPod Nano", "1st Gen"),
    0x1207: ("iPod Mini", "2nd Gen"),
    0x1208: ("iPod Photo", ""),
    0x1209: ("iPod Video", "5.5th Gen"),
    0x120A: ("iPod Nano", "2nd Gen"),
    0x1240: ("iPod Nano", "3rd Gen"),
    0x1241: ("iPod Classic", "1st Gen"),
    0x1242: ("iPod Classic", "1st Gen"),
    0x1243: ("iPod Nano", "4th Gen"),
    0x1245: ("iPod Classic", "2nd Gen"),
    0x1246: ("iPod Nano", "5th Gen"),
    0x1255: ("iPod Nano", "6th Gen"),
    0x1260: ("iPod Classic", "3rd Gen"),
    0x1261: ("iPod Classic", "3rd Gen"),
    0x1262: ("iPod Nano", "7th Gen"),
    0x1263: ("iPod Shuffle", "3rd Gen"),
    0x1265: ("iPod Shuffle", "4th Gen"),
    0x1266: ("iPod Nano", "7th Gen"),
}


# ── Serial number last-3-char → model number (from libgpod) ────────────────

SERIAL_LAST3_TO_MODEL: dict[str, str] = {
    # iPod Classic
    "Y5N": "MB029", "YMV": "MB147", "YMU": "MB145", "YMX": "MB150",
    "2C5": "MB562", "2C7": "MB565",
    "9ZS": "MC293", "9ZU": "MC297",
    # iPod Mini
    "PFW": "M9160", "PRC": "M9160",
    "QKL": "M9436", "QKQ": "M9436", "QKK": "M9435", "QKP": "M9435",
    "QKJ": "M9434", "QKN": "M9434", "QKM": "M9437", "QKR": "M9437",
    "S41": "M9800", "S4C": "M9800", "S43": "M9802", "S45": "M9804",
    "S47": "M9806", "S4J": "M9806", "S42": "M9801", "S44": "M9803",
    "S48": "M9807",
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


def _identify_via_usb_registry(drive_letter: str) -> Optional[dict]:
    """
    Identify iPod via Windows USBSTOR registry entries.

    Cross-references the drive letter to a USBSTOR device entry to get:
    - FireWire GUID (from instance ID)
    - Firmware revision
    - USB serial number (for last-3-char model lookup)

    Returns dict with keys: firewire_guid, serial, firmware, usb_pid, model_family, generation
    """
    if sys.platform != "win32":
        return None

    try:
        import winreg
    except ImportError:
        return None

    result: dict = {}

    # Step 1: Find the iPod USBSTOR entry
    try:
        usbstor_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Enum\USBSTOR"
        )
    except OSError:
        return None

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

            # Extract firmware from Rev_ field
            if "Rev_" in subkey_name:
                result["firmware"] = subkey_name.split("Rev_")[-1]

            # Get instance IDs
            try:
                device_key = winreg.OpenKey(usbstor_key, subkey_name)
                j = 0
                while True:
                    try:
                        instance_id = winreg.EnumKey(device_key, j)
                        j += 1
                    except OSError:
                        break

                    # Extract FireWire GUID from instance ID
                    parts = instance_id.split("&")
                    for part in parts:
                        part = part.strip()
                        if len(part) == 16:
                            try:
                                bytes.fromhex(part)
                                result["firewire_guid"] = part
                            except ValueError:
                                pass

                winreg.CloseKey(device_key)
            except OSError:
                continue

    finally:
        winreg.CloseKey(usbstor_key)

    # Step 2: Get USB serial from WMI (for model identification)
    try:
        import subprocess
        wmi_result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Get-WmiObject Win32_DiskDrive | Where-Object {{$_.Model -match 'iPod'}} | "
                f"ForEach-Object {{ $_.SerialNumber.Trim() }}"
            ],
            capture_output=True, text=True, timeout=5,
        )
        serial = wmi_result.stdout.strip()
        if serial:
            result["serial"] = serial
    except Exception:
        pass

    # Step 3: Get USB PID for iPod
    try:
        import winreg
        usb_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Enum\USB"
        )
        k = 0
        while True:
            try:
                subkey = winreg.EnumKey(usb_key, k)
                k += 1
            except OSError:
                break

            upper = subkey.upper()
            if "VID_05AC" in upper and "PID_" in upper and "MI_" not in upper:
                pid_str = upper.split("PID_")[1][:4]
                try:
                    pid = int(pid_str, 16)
                    if 0x1200 <= pid <= 0x12FF:  # iPod PID range
                        result["usb_pid"] = pid
                        model_info = USB_PID_TO_MODEL.get(pid)
                        if model_info:
                            result["model_family"] = model_info[0]
                            result["generation"] = model_info[1]
                except ValueError:
                    pass

        winreg.CloseKey(usb_key)
    except OSError:
        pass

    return result if result else None


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


def scan_for_ipods() -> list[DiscoveredIPod]:
    """
    Scan all drives for connected iPods.

    Returns a list of DiscoveredIPod objects, sorted by drive letter.
    """
    ipods: list[DiscoveredIPod] = []

    if sys.platform != "win32":
        logger.warning("Drive scanning is only supported on Windows")
        return ipods

    # Get USB info once — it applies to the connected iPod(s)
    usb_info = _identify_via_usb_registry("")

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

        # Get disk size
        ipod.disk_size_gb, ipod.free_space_gb = _get_disk_info(drive_path)

        # Try all identification methods, merging results

        # 1. SysInfo / SysInfoExtended
        sysinfo = _identify_via_sysinfo(drive_path)
        if sysinfo:
            ipod.identification_method = "sysinfo"
            ipod.model_family = sysinfo.get("model_family", ipod.model_family)
            ipod.generation = sysinfo.get("generation", ipod.generation)
            ipod.capacity = sysinfo.get("capacity", ipod.capacity)
            ipod.color = sysinfo.get("color", ipod.color)
            ipod.model_number = sysinfo.get("model_number", ipod.model_number)
            ipod.serial = sysinfo.get("serial", ipod.serial)
            ipod.firewire_guid = sysinfo.get("firewire_guid", ipod.firewire_guid)
            ipod.firmware = sysinfo.get("firmware", ipod.firmware)

        # 2. USB registry (serial → model lookup, PID → generation)
        if usb_info:
            if not ipod.firewire_guid and usb_info.get("firewire_guid"):
                ipod.firewire_guid = usb_info["firewire_guid"]
            if not ipod.firmware and usb_info.get("firmware"):
                ipod.firmware = usb_info["firmware"]
            if not ipod.serial and usb_info.get("serial"):
                ipod.serial = usb_info["serial"]
            if usb_info.get("usb_pid"):
                ipod.usb_pid = usb_info["usb_pid"]

            # If SysInfo didn't give us a model, try USB PID
            if ipod.model_family == "iPod" and usb_info.get("model_family"):
                ipod.model_family = usb_info["model_family"]
                ipod.generation = usb_info.get("generation", ipod.generation)
                ipod.identification_method = "usb_pid"

        # 3. Serial number last-3-char lookup (most specific)
        if ipod.serial:
            serial_info = _identify_via_serial_lookup(ipod.serial)
            if serial_info:
                # Serial lookup is very reliable — prefer it
                ipod.model_family = serial_info.get("model_family", ipod.model_family)
                ipod.generation = serial_info.get("generation", ipod.generation)
                ipod.capacity = serial_info.get("capacity", ipod.capacity)
                ipod.color = serial_info.get("color", ipod.color)
                ipod.model_number = serial_info.get("model_number", ipod.model_number)
                ipod.identification_method = "serial"

        # 4. iTunesDB hashing scheme (fallback)
        hash_info = _identify_via_hashing_scheme(drive_path)
        if hash_info:
            ipod.hashing_scheme = hash_info.get("hashing_scheme", -1)
            if ipod.model_family == "iPod" and hash_info.get("model_family"):
                ipod.model_family = hash_info["model_family"]
                ipod.generation = hash_info.get("generation", ipod.generation)
                ipod.identification_method = "hashing"

        # 5. Estimate capacity from disk size if not known
        if not ipod.capacity and ipod.disk_size_gb > 0:
            ipod.capacity = _estimate_capacity_from_disk_size(ipod.disk_size_gb)

        logger.info(
            "  Identified: %s (method=%s, model=%s)",
            ipod.display_name, ipod.identification_method, ipod.model_number or "unknown"
        )

        ipods.append(ipod)

    return ipods
