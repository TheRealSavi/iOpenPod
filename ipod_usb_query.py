"""
Query iPod device information via SCSI INQUIRY VPD pages over USB.

Apple iPods respond to SCSI INQUIRY with vendor-specific VPD (Vital Product
Data) pages 0xC0-0xFF, which contain a fragmented XML plist with detailed
device information including:

  - SerialNumber (Apple serial — last 3 chars encode exact model)
  - FireWireGUID
  - FamilyID / UpdaterFamilyID
  - BuildID / VisibleBuildID
  - ImageSpecifications (artwork format details)
  - Audio codec capabilities

**Platform notes**:

- **macOS / Linux**: Root/sudo is required because the kernel mass-storage
  driver must be temporarily detached to send raw SCSI commands via USB bulk
  endpoints.  The iPod disk will briefly unmount and remount.
- **Windows**: No elevation needed — libusb can access the device through
  WinUSB / libusb-win32 without detaching any driver.

Usage
~~~~~
Standalone (writes SysInfo to iPod)::

    # macOS / Linux
    sudo uv run python ipod_usb_query.py [--write-sysinfo]

    # Windows (no elevation needed for query, may need admin for write)
    uv run python ipod_usb_query.py [--write-sysinfo]

    # Any platform — manually specify iPod mount path
    sudo uv run python ipod_usb_query.py --write-sysinfo --path /Volumes/IPOD

From code::

    from ipod_usb_query import query_ipod_vpd, query_all_ipods
    info = query_ipod_vpd(usb_pid=0x1261)          # one device
    all_info = query_all_ipods()                     # all connected iPods
"""

from __future__ import annotations

import logging
import os
import plistlib
import re
import struct
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# Apple USB Vendor ID
APPLE_VID = 0x05AC

# Known iPod USB PIDs (mass storage mode)
IPOD_PIDS = {
    0x1201, 0x1202, 0x1203, 0x1204, 0x1205, 0x1206, 0x1207, 0x1208,
    0x1209, 0x120A, 0x1260, 0x1261, 0x1262, 0x1263, 0x1265, 0x1266,
    0x1267, 0x1301, 0x1302, 0x1303, 0x1304, 0x1305, 0x1306, 0x1307,
}


def _find_ipod_devices() -> list:
    """Find all connected iPod USB devices.

    Returns a list of pyusb Device objects.
    """
    try:
        import usb.core
    except ImportError:
        logger.error("pyusb not installed — run: uv add pyusb")
        return []

    devices = []
    found = usb.core.find(find_all=True, idVendor=APPLE_VID)
    if found is None:
        return devices
    for dev in found:
        if dev.idProduct in IPOD_PIDS:  # type: ignore[union-attr]
            devices.append(dev)
    return devices


def _scsi_inquiry(dev, ep_out, ep_in, tag: int, cdb: bytes,
                  transfer_len: int) -> tuple[bytes, int]:
    """Send a SCSI CDB via USB Mass Storage Bulk-Only CBW, return (data, status).

    The CBW (Command Block Wrapper) wraps SCSI commands for USB transport.
    After sending the CDB, we read the response data and the CSW (Command
    Status Wrapper) which contains the status byte.
    """
    # Build CBW: signature(4) + tag(4) + transfer_len(4) + flags(1) + lun(1) + cdb_len(1)
    cbw = struct.pack("<IIIBBB", 0x43425355, tag, transfer_len, 0x80, 0, len(cdb))
    cbw += cdb + b"\x00" * (16 - len(cdb))
    ep_out.write(cbw)

    data = bytes(ep_in.read(transfer_len, timeout=5000))

    # Read CSW (13 bytes)
    csw = bytes(ep_in.read(13, timeout=5000))
    status = csw[12] if len(csw) >= 13 else -1

    return data, status


def _read_vpd_pages(dev, ep_out, ep_in) -> bytes:
    """Read Apple VPD pages and concatenate the XML payload.

    The iPod's VPD page layout:
      - Page 0xC0: Supported pages list (page codes of data pages)
      - Page 0xC1: Unused / empty
      - Pages 0xC2+: XML plist data, each page carrying up to 248 bytes

    We first read page 0xC0 to discover which pages have data, then read
    each data page and concatenate the payloads.
    """
    tag = 100

    # Step 1: Read page 0xC0 to get the list of supported data pages
    supported_pages: list[int] = []
    try:
        cdb = bytes([0x12, 0x01, 0xC0, 0x00, 255, 0x00])
        data, status = _scsi_inquiry(dev, ep_out, ep_in, tag, cdb, 255)
        tag += 1

        if status == 0 and len(data) >= 4:
            page_len = data[3]  # Number of page codes listed
            supported_pages = list(data[4:4 + page_len])
            logger.debug("VPD supported pages: %s",
                         [f"0x{p:02X}" for p in supported_pages])
    except Exception as exc:
        logger.debug("VPD page 0xC0 read failed: %s", exc)

    if not supported_pages:
        # Fallback: try pages 0xC2-0xFF directly
        supported_pages = list(range(0xC2, 0x100))

    # Step 2: Read each data page (skip 0xC0 and 0xC1 which are metadata)
    xml_chunks = []
    for page in supported_pages:
        if page <= 0xC1:
            continue  # Skip metadata pages

        try:
            cdb = bytes([0x12, 0x01, page, 0x00, 255, 0x00])
            data, status = _scsi_inquiry(dev, ep_out, ep_in, tag, cdb, 255)
            tag += 1

            if status != 0 or len(data) <= 4:
                continue  # Skip failed pages, try next

            page_len = data[3]  # Actual payload length
            if page_len == 0:
                continue

            payload = data[4:4 + page_len]

            # Check if page has any real content
            if not any(b != 0 for b in payload):
                continue

            xml_chunks.append(payload)
        except Exception:
            continue  # Skip failures, try remaining pages

    if not xml_chunks:
        return b""

    # Concatenate all chunks
    raw = b"".join(xml_chunks)

    # Trim trailing nulls
    while raw and raw[-1:] == b"\x00":
        raw = raw[:-1]

    return raw


def _parse_vpd_xml(raw: bytes) -> dict:
    """Parse the reassembled VPD XML plist into a Python dict.

    The XML may be incomplete or malformed at boundaries, so we try
    plistlib first, then fall back to regex extraction.
    """
    result: dict = {}

    if not raw:
        return result

    # Try to find the XML plist boundaries
    xml_start = raw.find(b"<?xml")
    if xml_start < 0:
        xml_start = raw.find(b"<plist")
    if xml_start < 0:
        # No XML found — try plain text parsing
        return _parse_vpd_regex(raw)

    xml_data = raw[xml_start:]

    # Ensure the plist is properly closed
    if b"</plist>" not in xml_data:
        xml_data += b"\n</dict>\n</plist>"

    try:
        plist = plistlib.loads(xml_data)
        if isinstance(plist, dict):
            return plist
    except Exception:
        pass

    # plistlib failed — fall back to regex
    return _parse_vpd_regex(raw)


def _parse_vpd_regex(raw: bytes) -> dict:
    """Extract key-value pairs from XML plist using regex.

    This handles incomplete/truncated XML that plistlib can't parse.
    """
    result: dict = {}
    text = raw.decode("utf-8", errors="replace")

    # Simple key-value extraction: <key>X</key><string>Y</string>
    # or <key>X</key><integer>Y</integer>
    for m in re.finditer(
        r"<key>([^<]+)</key>\s*<(string|integer)>([^<]*)</\2>", text
    ):
        key, typ, val = m.group(1), m.group(2), m.group(3)
        if typ == "integer":
            try:
                result[key] = int(val)
            except ValueError:
                result[key] = val
        else:
            result[key] = val

    return result


def _read_standard_inquiry(dev, ep_out, ep_in) -> dict:
    """Read standard SCSI INQUIRY data (vendor, product, revision)."""
    result = {}
    try:
        cdb = bytes([0x12, 0x00, 0x00, 0x00, 96, 0x00])
        data, status = _scsi_inquiry(dev, ep_out, ep_in, 1, cdb, 96)
        if status == 0 and len(data) >= 36:
            result["scsi_vendor"] = data[8:16].decode("ascii", errors="replace").strip()
            result["scsi_product"] = data[16:32].decode("ascii", errors="replace").strip()
            result["scsi_revision"] = data[32:36].decode("ascii", errors="replace").strip()
    except Exception as exc:
        logger.debug("Standard INQUIRY failed: %s", exc)
    return result


def query_ipod_vpd(
    usb_pid: int = 0,
    serial_filter: str = "",
) -> Optional[dict]:
    """Query a single iPod's device information via SCSI VPD pages.

    Parameters
    ----------
    usb_pid : int, optional
        If non-zero, target only the iPod with this USB Product ID.
    serial_filter : str, optional
        If non-empty, target only the iPod whose USB serial number
        (FireWire GUID) matches this string (case-insensitive).

    Returns
    -------
    dict or None
        A dict with keys like ``SerialNumber``, ``FireWireGUID``,
        ``FamilyID``, ``BuildID``, ``usb_pid``, ``usb_serial``, etc.
        Returns None if no iPod found or query failed.

    Raises
    ------
    PermissionError
        If not running as root (kernel driver detach requires root).
    """
    try:
        import usb.core
        import usb.util
    except ImportError:
        logger.error("pyusb not installed")
        return None

    # Find target device
    devices = _find_ipod_devices()
    if not devices:
        logger.info("No iPod USB devices found")
        return None

    dev = None
    for d in devices:
        if usb_pid and d.idProduct != usb_pid:
            continue
        if serial_filter:
            try:
                if d.serial_number.upper() != serial_filter.upper():
                    continue
            except Exception:
                continue
        dev = d
        break

    if not dev:
        logger.info("No matching iPod found (pid=0x%04X, serial=%s)",
                    usb_pid, serial_filter)
        return None

    pid = dev.idProduct
    try:
        usb_serial = dev.serial_number or ""
    except Exception:
        usb_serial = ""

    logger.info("Querying iPod PID=0x%04X serial=%s", pid, usb_serial)

    # Detach kernel driver (macOS/Linux require root; Windows doesn't need this)
    detached = False
    if sys.platform != "win32":
        try:
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
                detached = True
                logger.debug("Kernel driver detached")
            else:
                logger.debug("No kernel driver active on interface 0")
        except usb.core.USBError as exc:
            if "Access denied" in str(exc) or "Operation not permitted" in str(exc):
                raise PermissionError(
                    "Root/sudo required to detach kernel driver for USB VPD query. "
                    "Run with: sudo uv run python ipod_usb_query.py"
                ) from exc
            raise

    result: dict = {
        "usb_pid": pid,
        "usb_serial": usb_serial,
    }

    try:
        usb.util.claim_interface(dev, 0)

        # Find bulk endpoints
        cfg = dev.get_active_configuration()
        intf = cfg[(0, 0)]
        ep_out = ep_in = None
        for ep in intf:
            direction = usb.util.endpoint_direction(ep.bEndpointAddress)
            if direction == usb.util.ENDPOINT_OUT and not ep_out:
                ep_out = ep
            elif direction == usb.util.ENDPOINT_IN and not ep_in:
                ep_in = ep

        if not ep_out or not ep_in:
            logger.error("Could not find bulk endpoints")
            return None

        # Standard INQUIRY
        std_info = _read_standard_inquiry(dev, ep_out, ep_in)
        result.update(std_info)

        # Apple VPD pages
        raw_xml = _read_vpd_pages(dev, ep_out, ep_in)
        if raw_xml:
            vpd_info = _parse_vpd_xml(raw_xml)
            result["vpd_raw_xml"] = raw_xml  # Keep for SysInfoExtended writing
            result.update(vpd_info)
            logger.info("VPD query successful: %d keys extracted",
                        len(vpd_info))
        else:
            logger.warning("No VPD data returned from iPod")

        usb.util.release_interface(dev, 0)

    except usb.core.USBError as exc:
        logger.error("USB error during VPD query: %s", exc)
    finally:
        if detached:
            try:
                dev.attach_kernel_driver(0)
                logger.debug("Kernel driver reattached — iPod will remount")
            except Exception as exc:
                logger.warning(
                    "Could not reattach kernel driver: %s. "
                    "Physically disconnect and reconnect the iPod.", exc
                )

    return result


def query_all_ipods() -> list[dict]:
    """Query all connected iPods and return a list of info dicts.

    Each entry is the result of ``query_ipod_vpd()`` for one device.
    Devices that fail to query are silently skipped.

    A brief pause is inserted between device queries to allow the USB
    bus to stabilise after kernel driver detach/reattach cycles.
    """
    import time

    try:
        import usb.core  # noqa: F401 – needed so query_ipod_vpd can find it
    except ImportError:
        return []

    devices = _find_ipod_devices()
    results = []

    for i, dev in enumerate(devices):
        try:
            usb_serial = dev.serial_number or ""
        except Exception:
            usb_serial = ""

        # Brief pause between devices to let USB bus settle
        if i > 0:
            logger.debug("Waiting 3s for USB bus to settle...")
            time.sleep(3)

        try:
            info = query_ipod_vpd(
                usb_pid=dev.idProduct,
                serial_filter=usb_serial,
            )
            if info:
                results.append(info)
        except PermissionError:
            raise  # Propagate — all queries need root
        except Exception as exc:
            logger.debug("Query failed for PID=0x%04X: %s",
                         dev.idProduct, exc)

    return results


def write_sysinfo(ipod_path: str, vpd_info: dict) -> bool:
    """Write SysInfo and SysInfoExtended to the iPod from VPD data.

    This populates the files that iTunes normally creates, so that
    subsequent non-root runs of iOpenPod can identify the device.

    Parameters
    ----------
    ipod_path : str
        Mount point of the iPod (e.g., "/Volumes/JOHN'S IPOD").
    vpd_info : dict
        Result dict from ``query_ipod_vpd()``.

    Returns
    -------
    bool
        True if at least one file was written successfully.
    """
    device_dir = os.path.join(ipod_path, "iPod_Control", "Device")
    os.makedirs(device_dir, exist_ok=True)

    wrote_any = False

    # ── Write SysInfo (plain text key:value format) ────────────────
    sysinfo_path = os.path.join(device_dir, "SysInfo")
    try:
        lines = []
        serial = vpd_info.get("SerialNumber", "")
        if serial:
            lines.append(f"pszSerialNumber: {serial}")

        fw_guid = vpd_info.get("FireWireGUID", "")
        if not fw_guid:
            fw_guid = vpd_info.get("usb_serial", "")
        if fw_guid:
            lines.append(f"FirewireGuid: 0x{fw_guid}")

        build_id = vpd_info.get("VisibleBuildID",
                                vpd_info.get("BuildID", ""))
        if build_id:
            lines.append(f"visibleBuildID: {build_id}")

        board = vpd_info.get("BoardHwName", "")
        if board:
            lines.append(f"BoardHwName: {board}")

        model = vpd_info.get("ModelNumStr", "")
        if model:
            lines.append(f"ModelNumStr: {model}")

        # Also store FamilyID and UpdaterFamilyID for future use
        fam_id = vpd_info.get("FamilyID")
        if fam_id is not None:
            lines.append(f"FamilyID: {fam_id}")

        upd_fam_id = vpd_info.get("UpdaterFamilyID")
        if upd_fam_id is not None:
            lines.append(f"UpdaterFamilyID: {upd_fam_id}")

        if lines:
            with open(sysinfo_path, "w") as f:
                f.write("\n".join(lines) + "\n")
            wrote_any = True
            logger.info("Wrote SysInfo (%d fields) to %s",
                        len(lines), sysinfo_path)

    except Exception as exc:
        logger.error("Failed to write SysInfo: %s", exc)

    # ── Write SysInfoExtended (XML plist) ──────────────────────────
    sysinfo_ext_path = os.path.join(device_dir, "SysInfoExtended")
    raw_xml = vpd_info.get("vpd_raw_xml", b"")
    if raw_xml:
        try:
            # Use raw VPD XML directly — it's already a plist
            xml_start = raw_xml.find(b"<?xml")
            if xml_start < 0:
                xml_start = raw_xml.find(b"<plist")
            if xml_start >= 0:
                xml_data = raw_xml[xml_start:]
                # Ensure proper termination
                if b"</plist>" not in xml_data:
                    xml_data += b"\n</dict>\n</plist>"
                with open(sysinfo_ext_path, "wb") as f:
                    f.write(xml_data)
                wrote_any = True
                logger.info("Wrote SysInfoExtended to %s", sysinfo_ext_path)
        except Exception as exc:
            logger.error("Failed to write SysInfoExtended: %s", exc)

    return wrote_any


# ──────────────────────────────────────────────────────────────────────
# Mount-point resolution — per-platform implementations
# ──────────────────────────────────────────────────────────────────────

def _get_mount_point_diskutil(dev_identifier: str) -> Optional[str]:
    """macOS: get mount point for a BSD device identifier like 'disk4s2'."""
    import plistlib as _plistlib
    import subprocess

    try:
        proc = subprocess.run(
            ["diskutil", "info", "-plist", dev_identifier],
            capture_output=True, timeout=10,
        )
        if proc.returncode == 0:
            disk_info = _plistlib.loads(proc.stdout)
            mp = disk_info.get("MountPoint", "")
            if mp:
                return mp
    except Exception:
        pass
    return None


def _find_mount_macos(usb_serial: str) -> Optional[str]:
    """macOS: find iPod mount point via ioreg + diskutil."""
    import subprocess

    serial_upper = usb_serial.upper()
    bsd_disk: Optional[str] = None

    try:
        proc = subprocess.run(
            ["ioreg", "-r", "-c", "IOUSBHostDevice", "-n", "iPod",
             "-l", "-d", "20", "-w", "0"],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0:
            current_serial = ""
            for line in proc.stdout.splitlines():
                m = re.search(r'"USB Serial Number"\s*=\s*"([^"]+)"', line)
                if m:
                    current_serial = m.group(1).replace(" ", "").strip().upper()
                    continue
                m = re.search(r'"BSD Name"\s*=\s*"(disk\d+)"', line)
                if m and current_serial == serial_upper:
                    bsd_disk = m.group(1)
                    break
    except Exception:
        pass

    if not bsd_disk:
        return None

    # Try all partitions on this disk via diskutil list
    import plistlib as _plistlib

    try:
        proc = subprocess.run(
            ["diskutil", "list", "-plist", bsd_disk],
            capture_output=True, timeout=10,
        )
        if proc.returncode == 0:
            disk_list = _plistlib.loads(proc.stdout)
            partitions = disk_list.get("AllDisksAndPartitions", [])
            for entry in partitions:
                for part in entry.get("Partitions", []):
                    dev_id = part.get("DeviceIdentifier", "")
                    if dev_id:
                        mp = _get_mount_point_diskutil(dev_id)
                        if mp:
                            return mp
                dev_id = entry.get("DeviceIdentifier", "")
                if dev_id:
                    mp = _get_mount_point_diskutil(dev_id)
                    if mp:
                        return mp
    except Exception:
        pass

    # Fallback: try s1/s2/s3 directly
    for suffix in ("s1", "s2", "s3"):
        mp = _get_mount_point_diskutil(bsd_disk + suffix)
        if mp:
            return mp

    # Last resort: parse mount output
    try:
        proc = subprocess.run(
            ["mount"], capture_output=True, text=True, timeout=5,
        )
        for line in proc.stdout.splitlines():
            if bsd_disk in line and " on /Volumes/" in line:
                m = re.search(r" on (/Volumes/.+?) \(", line)
                if m:
                    return m.group(1)
    except Exception:
        pass

    return None


def _find_mount_linux(usb_serial: str) -> Optional[str]:
    """Linux: find iPod mount point via /proc/mounts + sysfs.

    Scans all mounted FAT/HFS+ volumes, traces each back through sysfs
    to its USB parent, and matches against the USB serial (FireWire GUID).
    """
    serial_upper = usb_serial.upper()

    try:
        with open("/proc/mounts", "r") as f:
            mounts = f.readlines()
    except Exception:
        return None

    for line in mounts:
        parts = line.split()
        if len(parts) < 2:
            continue
        device, mount_point = parts[0], parts[1]

        if not device.startswith("/dev/sd") and not device.startswith("/dev/disk"):
            continue

        # Get the base disk name (sdb from /dev/sdb1)
        dev_name = os.path.basename(device)
        base_disk = re.sub(r"\d+$", "", dev_name)

        # Walk sysfs to find the parent USB device
        sysfs_path = f"/sys/block/{base_disk}/device"
        if not os.path.exists(sysfs_path):
            continue

        current = os.path.realpath(sysfs_path)
        for _ in range(8):
            vendor_file = os.path.join(current, "idVendor")
            if os.path.exists(vendor_file):
                try:
                    with open(vendor_file) as vf:
                        vendor = vf.read().strip()
                except Exception:
                    break
                if vendor != "05ac":  # Not Apple
                    break

                serial_file = os.path.join(current, "serial")
                if os.path.exists(serial_file):
                    try:
                        with open(serial_file) as sf:
                            serial = sf.read().strip().replace(" ", "").upper()
                    except Exception:
                        break
                    if serial == serial_upper:
                        # Unescape octal sequences in mount point
                        # (e.g. /media/JOHNG\047S\ IPO)
                        mp = mount_point.encode("utf-8").decode(
                            "unicode_escape", errors="replace"
                        )
                        return mp
                break
            current = os.path.dirname(current)

    return None


def _find_mount_windows(usb_serial: str) -> Optional[str]:
    """Windows: find iPod drive letter via WMI.

    Queries Win32_DiskDrive (USBSTOR) → Win32_DiskDriveToDiskPartition →
    Win32_LogicalDiskToPartition → Win32_LogicalDisk to trace from the USB
    serial to a drive letter.
    """
    import subprocess

    serial_upper = usb_serial.upper()

    # Strategy 1: Parse wmic output to match USB serial → drive letter
    try:
        # Get all USB disk drives
        proc = subprocess.run(
            ["wmic", "diskdrive", "where", "InterfaceType='USB'",
             "get", "DeviceID,PNPDeviceID", "/format:csv"],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            # wmic might not be available on newer Windows — try PowerShell
            return _find_mount_windows_ps(usb_serial)

        target_device_id = None
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("Node"):
                continue
            # CSV: Node,DeviceID,PNPDeviceID
            parts = line.split(",")
            if len(parts) >= 3:
                pnp_id = parts[2].upper()
                if serial_upper in pnp_id:
                    target_device_id = parts[1]
                    break

        if not target_device_id:
            return _find_mount_windows_ps(usb_serial)

        # Map DeviceID → Partition → LogicalDisk
        # Use wmic associators
        escaped_id = target_device_id.replace("\\", "\\\\")
        proc = subprocess.run(
            ["wmic", "path", "Win32_DiskDriveToDiskPartition", "where",
             f'Antecedent="\\\\\\\\.\\\\{escaped_id}"',
             "get", "Dependent", "/format:csv"],
            capture_output=True, text=True, timeout=15,
        )

        # This is getting complex — fall back to PowerShell approach
        if proc.returncode != 0:
            return _find_mount_windows_ps(usb_serial)

    except FileNotFoundError:
        # wmic not available
        return _find_mount_windows_ps(usb_serial)
    except Exception:
        return _find_mount_windows_ps(usb_serial)

    return _find_mount_windows_ps(usb_serial)


def _find_mount_windows_ps(usb_serial: str) -> Optional[str]:
    """Windows: find iPod drive letter via PowerShell.

    Uses CIM/WMI cmdlets to trace USB disk → partition → logical disk.
    """
    import subprocess

    serial_upper = usb_serial.upper()

    # PowerShell one-liner that finds the drive letter for a USB disk
    # matching a given serial number in the PNPDeviceID
    ps_script = (
        "Get-CimInstance Win32_DiskDrive "
        "| Where-Object { $_.InterfaceType -eq 'USB' -and "
        f"$_.PNPDeviceID -like '*{serial_upper}*' }} "
        "| ForEach-Object { "
        "$disk = $_; "
        "Get-CimAssociatedInstance -InputObject $disk "
        "-ResultClassName Win32_DiskPartition "
        "| ForEach-Object { "
        "Get-CimAssociatedInstance -InputObject $_ "
        "-ResultClassName Win32_LogicalDisk } } "
        "| Select-Object -ExpandProperty DeviceID"
    )

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=20,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            drive_letter = proc.stdout.strip().splitlines()[0].strip()
            if len(drive_letter) >= 2 and drive_letter[0].isalpha():
                # Return as "D:\" style path
                return drive_letter[0] + ":\\"
    except Exception as exc:
        logger.debug("PowerShell mount lookup failed: %s", exc)

    return None


def _find_mount_point_for_usb_serial(usb_serial: str) -> Optional[str]:
    """Find the iPod mount point matching a USB serial (FireWire GUID).

    Dispatches to the platform-specific implementation:
      - macOS: ioreg + diskutil
      - Linux: /proc/mounts + sysfs
      - Windows: WMI/PowerShell
    """
    if not usb_serial:
        return None

    if sys.platform == "darwin":
        return _find_mount_macos(usb_serial)
    elif sys.platform == "linux":
        return _find_mount_linux(usb_serial)
    elif sys.platform == "win32":
        return _find_mount_windows(usb_serial)
    else:
        logger.warning("Unsupported platform for mount point lookup: %s",
                       sys.platform)
        return None


# ──────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────

def main() -> int:
    """CLI entry point: query all connected iPods and optionally write SysInfo."""
    import argparse

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Query iPod device information via USB SCSI VPD pages.",
    )
    parser.add_argument(
        "--write-sysinfo", action="store_true",
        help="Write SysInfo/SysInfoExtended to the iPod for future detection",
    )
    parser.add_argument(
        "--pid", type=lambda x: int(x, 16), default=0,
        help="Target a specific USB PID (hex, e.g. 1261)",
    )
    parser.add_argument(
        "--path", type=str, default="",
        help="iPod mount path (e.g. /Volumes/IPOD or D:\\). "
             "If specified, writes SysInfo here instead of auto-detecting.",
    )
    args = parser.parse_args()

    # Root check — only applies on macOS/Linux (Windows doesn't need it)
    if sys.platform != "win32":
        if os.geteuid() != 0:
            print("ERROR: Root privileges required. "
                  "Run with: sudo uv run python ipod_usb_query.py")
            return 1

    print("Scanning for iPod USB devices...\n")

    try:
        all_info = query_all_ipods()
    except PermissionError as exc:
        print(f"ERROR: {exc}")
        return 1

    if not all_info:
        print("No iPods found or query failed.")
        return 1

    for info in all_info:
        pid = info.get("usb_pid", 0)
        serial = info.get("SerialNumber", info.get("usb_serial", "?"))
        fw_guid = info.get("FireWireGUID", info.get("usb_serial", ""))
        family_id = info.get("FamilyID", "?")
        build_id = info.get("VisibleBuildID", info.get("BuildID", "?"))

        print(f"{'=' * 60}")
        print(f"iPod (USB PID 0x{pid:04X})")
        print(f"{'=' * 60}")
        print(f"  Apple Serial:    {serial}")
        print(f"  FireWire GUID:   {fw_guid}")
        print(f"  FamilyID:        {family_id}")
        print(f"  UpdaterFamilyID: {info.get('UpdaterFamilyID', '?')}")
        print(f"  BuildID:         {build_id}")
        print(f"  SCSI Vendor:     {info.get('scsi_vendor', '?')}")
        print(f"  SCSI Product:    {info.get('scsi_product', '?')}")
        print(f"  SCSI Revision:   {info.get('scsi_revision', '?')}")

        # Try serial-last-3 model lookup
        apple_serial = info.get("SerialNumber", "")
        if apple_serial and len(apple_serial) >= 3:
            last3 = apple_serial[-3:]
            try:
                from GUI.device_scanner import SERIAL_LAST3_TO_MODEL
                from iTunesDB_Writer.device import IPOD_MODELS
                model_num = SERIAL_LAST3_TO_MODEL.get(last3)
                if model_num:
                    model_info = IPOD_MODELS.get(model_num)
                    if model_info:
                        print(f"\n  Model:           {model_info[0]} {model_info[1]}")
                        print(f"  Capacity:        {model_info[2]}")
                        print(f"  Color:           {model_info[3]}")
                        print(f"  Model Number:    {model_num}")
            except ImportError:
                pass

        print()

    # ── Write SysInfo (separate phase — iPods need time to remount) ──
    if args.write_sysinfo:
        import time

        # On macOS/Linux the disk unmounts during VPD query; Windows doesn't
        if sys.platform != "win32":
            print("Waiting for iPods to remount...")
            time.sleep(8)

        for info in all_info:
            usb_ser = info.get("usb_serial", "")
            pid = info.get("usb_pid", 0)

            # Use --path if provided, otherwise auto-detect mount point
            if args.path:
                mount = args.path
            else:
                mount = None
                for attempt in range(3):
                    mount = _find_mount_point_for_usb_serial(usb_ser)
                    if mount:
                        break
                    print(f"  PID 0x{pid:04X}: waiting for remount "
                          f"(attempt {attempt + 2}/3)...")
                    time.sleep(5)

            if mount:
                print(f"Writing SysInfo for PID 0x{pid:04X} to {mount}...")
                if write_sysinfo(mount, info):
                    print("  Done!")
                else:
                    print("  WARNING: SysInfo write failed")
            else:
                print(f"WARNING: Could not find mount point for PID 0x{pid:04X} "
                      f"(serial {usb_ser})")
                print("  Use --path to specify the iPod mount path manually.")

        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
