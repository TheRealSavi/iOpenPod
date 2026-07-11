"""
Windows SCSI pass-through reader for iPod SysInfoExtended VPD pages.

This sends SCSI INQUIRY commands to the selected drive with
IOCTL_SCSI_PASS_THROUGH_DIRECT.  It is a live hardware source and avoids
selecting the wrong iPod by anchoring the query to the mounted drive letter.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys

from .diagnostic_log import CAPABILITY_FIELDS, IDENTITY_FIELDS, format_fields
from .sysinfo import normalize_guid, parse_sysinfo_extended

logger = logging.getLogger(__name__)

# Win32 wintypes are imported inside Windows-only functions to satisfy
# static analysis and keep runtime imports platform-local.


_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3

_IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x0004D014
_SCSI_IOCTL_DATA_IN = 1


class _SCSI_PASS_THROUGH_DIRECT(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("ScsiStatus", ctypes.c_ubyte),
        ("PathId", ctypes.c_ubyte),
        ("TargetId", ctypes.c_ubyte),
        ("Lun", ctypes.c_ubyte),
        ("CdbLength", ctypes.c_ubyte),
        ("SenseInfoLength", ctypes.c_ubyte),
        ("DataIn", ctypes.c_ubyte),
        ("DataTransferLength", ctypes.c_ulong),
        ("TimeOutValue", ctypes.c_ulong),
        ("DataBuffer", ctypes.c_void_p),
        ("SenseInfoOffset", ctypes.c_ulong),
        ("Cdb", ctypes.c_ubyte * 16),
    ]


def _setup_win32_prototypes() -> None:
    if sys.platform != "win32":
        return
    from ctypes import wintypes as wt
    ctypes.windll.kernel32.CreateFileW.argtypes = [  # type: ignore[attr-defined]
        wt.LPCWSTR,
        wt.DWORD,
        wt.DWORD,
        wt.LPVOID,
        wt.DWORD,
        wt.DWORD,
        wt.HANDLE,
    ]
    ctypes.windll.kernel32.CreateFileW.restype = wt.HANDLE  # type: ignore[attr-defined]
    ctypes.windll.kernel32.DeviceIoControl.argtypes = [  # type: ignore[attr-defined]
        wt.HANDLE,
        wt.DWORD,
        wt.LPVOID,
        wt.DWORD,
        wt.LPVOID,
        wt.DWORD,
        ctypes.POINTER(wt.DWORD),
        wt.LPVOID,
    ]
    ctypes.windll.kernel32.DeviceIoControl.restype = wt.BOOL  # type: ignore[attr-defined]
    ctypes.windll.kernel32.CloseHandle.argtypes = [wt.HANDLE]  # type: ignore[attr-defined]
    ctypes.windll.kernel32.CloseHandle.restype = wt.BOOL  # type: ignore[attr-defined]


def _drive_letter_from_path(path: str) -> str:
    if not path:
        return ""
    drive, _tail = os.path.splitdrive(path)
    if drive and drive[0].isalpha():
        return drive[0].upper()
    if path[0].isalpha():
        return path[0].upper()
    return ""


def _open_drive(drive_letter: str):
    path = f"\\\\.\\{drive_letter}:"
    handle = ctypes.windll.kernel32.CreateFileW(  # type: ignore[attr-defined]
        path,
        _GENERIC_READ | _GENERIC_WRITE,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,
        None,
        _OPEN_EXISTING,
        0,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        err = getattr(ctypes, "get_last_error", lambda: 0)()
        logger.info("Windows SCSI VPD: cannot open %s (err=%d)", path, err)
        return None
    return handle


def _scsi_inquiry(handle, *, evpd: bool, page: int, alloc_len: int = 255) -> bytes:
    from ctypes import wintypes as wt
    data_buf = ctypes.create_string_buffer(alloc_len)
    sptd = _SCSI_PASS_THROUGH_DIRECT()
    sptd.Length = ctypes.sizeof(_SCSI_PASS_THROUGH_DIRECT)
    sptd.CdbLength = 6
    sptd.DataIn = _SCSI_IOCTL_DATA_IN
    sptd.DataTransferLength = alloc_len
    sptd.TimeOutValue = 10
    sptd.DataBuffer = ctypes.cast(data_buf, ctypes.c_void_p)
    sptd.SenseInfoLength = 0
    sptd.SenseInfoOffset = 0

    cdb = bytes([
        0x12,
        0x01 if evpd else 0x00,
        page & 0xFF,
        0x00,
        alloc_len & 0xFF,
        0x00,
    ])
    for idx, byte in enumerate(cdb):
        sptd.Cdb[idx] = byte

    returned = wt.DWORD(0)
    ok = ctypes.windll.kernel32.DeviceIoControl(  # type: ignore[attr-defined]
        handle,
        _IOCTL_SCSI_PASS_THROUGH_DIRECT,
        ctypes.byref(sptd),
        ctypes.sizeof(sptd),
        ctypes.byref(sptd),
        ctypes.sizeof(sptd),
        ctypes.byref(returned),
        None,
    )
    if not ok:
        err = getattr(ctypes, "get_last_error", lambda: 0)()
        raise OSError(err, f"DeviceIoControl INQUIRY failed for page 0x{page:02X}")
    if sptd.ScsiStatus != 0:
        raise OSError(sptd.ScsiStatus, f"SCSI status for page 0x{page:02X}")

    transfer_len = min(int(sptd.DataTransferLength or alloc_len), alloc_len)
    return bytes(data_buf.raw[:transfer_len])


def _read_standard_inquiry(handle) -> dict:
    result: dict = {}
    try:
        data = _scsi_inquiry(handle, evpd=False, page=0, alloc_len=96)
    except Exception as exc:
        logger.debug("Windows SCSI VPD: standard INQUIRY failed: %s", exc)
        return result

    if len(data) >= 36:
        result["scsi_vendor"] = data[8:16].decode("ascii", errors="replace").strip()
        result["scsi_product"] = data[16:32].decode("ascii", errors="replace").strip()
        result["scsi_revision"] = data[32:36].decode("ascii", errors="replace").strip()
    return result


def _read_vpd_serial(handle) -> str:
    try:
        data = _scsi_inquiry(handle, evpd=True, page=0x80, alloc_len=255)
    except Exception:
        return ""
    if len(data) <= 4:
        return ""
    return data[4:].split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def _read_vpd_pages(handle) -> bytes:
    data_pages: list[int] = []
    try:
        c0 = _scsi_inquiry(handle, evpd=True, page=0xC0, alloc_len=255)
        if len(c0) >= 4:
            count = c0[3]
            data_pages = [p for p in c0[4:4 + count] if p >= 0xC2]
            logger.debug(
                "Windows SCSI VPD pages: %s",
                [f"0x{page:02X}" for page in data_pages],
            )
    except Exception as exc:
        logger.debug("Windows SCSI VPD: page 0xC0 failed: %s", exc)

    if not data_pages:
        data_pages = list(range(0xC2, 0x100))

    chunks: list[bytes] = []
    for page in data_pages:
        try:
            data = _scsi_inquiry(handle, evpd=True, page=page, alloc_len=255)
        except Exception:
            continue
        if len(data) < 4:
            continue
        payload_len = data[3]
        payload = data[4:4 + payload_len]
        if payload and any(payload):
            chunks.append(payload)

    return b"".join(chunks).rstrip(b"\x00")


def query_ipod_vpd_for_path(
    mount_path: str,
    *,
    usb_pid: int = 0,
    serial_filter: str = "",
) -> dict | None:
    """Read SCSI VPD SysInfoExtended from the selected Windows drive."""
    if sys.platform != "win32":
        return None

    drive_letter = _drive_letter_from_path(mount_path)
    if not drive_letter:
        logger.debug(
            "Windows SCSI VPD: no drive letter for mount path %s",
            mount_path,
        )
        return None

    logger.debug(
        "Windows SCSI VPD query start: drive=%s mount=%s pid=%s filter=%s",
        drive_letter,
        mount_path,
        f"0x{usb_pid:04X}" if usb_pid else "unknown",
        serial_filter or "none",
    )
    _setup_win32_prototypes()
    handle = _open_drive(drive_letter)
    if handle is None:
        return None

    try:
        result: dict = {
            "_source": "windows_scsi",
            "_transport": "windows_scsi_pass_through",
        }
        if usb_pid:
            result["usb_vid"] = 0x05AC
            result["usb_pid"] = usb_pid

        result.update(_read_standard_inquiry(handle))
        vpd_serial = _read_vpd_serial(handle)
        if vpd_serial:
            result["vpd_serial"] = vpd_serial

        raw_xml = _read_vpd_pages(handle)
        if not raw_xml:
            logger.debug(
                "Windows SCSI VPD: no SysInfoExtended payload for %s",
                drive_letter,
            )
            return None

        parsed = parse_sysinfo_extended(raw_xml, source="windows_scsi", live=True)
        if not parsed.plist:
            logger.debug(
                "Windows SCSI VPD: parsed payload had no plist keys for %s",
                drive_letter,
            )
            return None

        result["vpd_raw_xml"] = parsed.raw_xml or raw_xml
        result.update(parsed.plist)
        log_identity = dict(parsed.identity)
        for field in (
            "usb_vid",
            "usb_pid",
            "scsi_vendor",
            "scsi_product",
            "scsi_revision",
        ):
            if result.get(field) not in (None, "", b""):
                log_identity[field] = result[field]

        wanted = normalize_guid(serial_filter)
        actual = normalize_guid(
            result.get("FireWireGUID")
            or result.get("usb_serial")
            or result.get("vpd_serial")
        )
        if wanted and actual and wanted != actual:
            logger.debug(
                "Windows SCSI VPD: serial filter %s did not match %s",
                wanted,
                actual,
            )
            return None

        logger.debug(
            "Windows SCSI VPD query successful for %s: keys=%d identity=[%s] caps=[%s]",
            drive_letter,
            len(parsed.plist),
            format_fields(log_identity, IDENTITY_FIELDS),
            format_fields(log_identity, CAPABILITY_FIELDS, include_false=True),
        )
        return result
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
