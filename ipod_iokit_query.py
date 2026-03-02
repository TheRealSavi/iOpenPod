"""
macOS-only IOKit SCSI VPD query for iPods.

Uses IOKit's SCSITaskLib CFPlugIn to send SCSI INQUIRY VPD commands
directly to iPod hardware without requiring root, driver detach, or
disk unmount.  Provides the same dict shape as ipod_usb_query so
device_info._enrich_from_usb_vpd can consume it unchanged.

Requirements:  macOS only (IOKit framework).  No third-party packages.
"""

from __future__ import annotations

import ctypes
import logging
import plistlib
import re
import struct
import sys
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_char_p,
    c_int32,
    c_uint8,
    c_uint32,
    c_uint64,
    c_void_p,
    cast,
    create_string_buffer,
)
from typing import Optional

if sys.platform != "darwin":
    raise ImportError("ipod_iokit_query is macOS-only")

log = logging.getLogger(__name__)

# ── IOKit / CoreFoundation via ctypes ────────────────────────────────

_cf = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)
_iok = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/IOKit.framework/IOKit"
)

# CFString helpers
_cf.CFStringGetCString.argtypes = [c_void_p, c_char_p, c_int32, c_uint32]
_cf.CFStringGetCString.restype = ctypes.c_bool
_cf.CFRelease.argtypes = [c_void_p]
_cf.CFRelease.restype = None
_cf.CFGetTypeID.argtypes = [c_void_p]
_cf.CFGetTypeID.restype = c_uint64
_cf.CFStringGetTypeID.argtypes = []
_cf.CFStringGetTypeID.restype = c_uint64
_cf.CFNumberGetTypeID.argtypes = []
_cf.CFNumberGetTypeID.restype = c_uint64
_cf.CFNumberGetValue.argtypes = [c_void_p, c_int32, c_void_p]
_cf.CFNumberGetValue.restype = ctypes.c_bool

_cf.CFUUIDGetConstantUUIDWithBytes.restype = c_void_p
_cf.CFUUIDGetConstantUUIDWithBytes.argtypes = [c_void_p] + [c_uint8] * 16

_cf.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint32]
_cf.CFStringCreateWithCString.restype = c_void_p
kCFStringEncodingUTF8 = 0x08000100

# IOKit registry
_iok.IOServiceMatching.restype = c_void_p
_iok.IOServiceMatching.argtypes = [c_char_p]
_iok.IOServiceGetMatchingServices.argtypes = [c_uint32, c_void_p, POINTER(c_uint32)]
_iok.IOServiceGetMatchingServices.restype = c_int32
_iok.IOIteratorNext.argtypes = [c_uint32]
_iok.IOIteratorNext.restype = c_uint32
_iok.IOObjectRelease.argtypes = [c_uint32]
_iok.IOObjectRelease.restype = c_int32
_iok.IORegistryEntryGetParentEntry.argtypes = [c_uint32, c_char_p, POINTER(c_uint32)]
_iok.IORegistryEntryGetParentEntry.restype = c_int32
_iok.IORegistryEntryCreateCFProperty.argtypes = [c_uint32, c_void_p, c_void_p, c_uint32]
_iok.IORegistryEntryCreateCFProperty.restype = c_void_p
_iok.IORegistryEntryGetName.argtypes = [c_uint32, c_char_p]
_iok.IORegistryEntryGetName.restype = c_int32

_iok.IOCreatePlugInInterfaceForService.argtypes = [
    c_uint32, c_void_p, c_void_p, POINTER(c_void_p), POINTER(c_int32)
]
_iok.IOCreatePlugInInterfaceForService.restype = c_int32

kIOServicePlane = b"IOService"

# ── UUIDs ────────────────────────────────────────────────────────────


def _make_uuid(*b: int) -> c_void_p:
    return _cf.CFUUIDGetConstantUUIDWithBytes(None, *[c_uint8(x) for x in b])


_kSCSITaskDeviceUserClientTypeID = _make_uuid(
    0x7D, 0x66, 0x67, 0x8E, 0x08, 0xA2, 0x11, 0xD5,
    0xA1, 0xB8, 0x00, 0x30, 0x65, 0x7D, 0x05, 0x2A,
)
_kIOCFPlugInInterfaceID = _make_uuid(
    0xC2, 0x44, 0xE8, 0x58, 0x10, 0x9C, 0x11, 0xD4,
    0x91, 0xD4, 0x00, 0x50, 0xE4, 0xC6, 0x42, 0x6F,
)
# Actual SCSITaskDeviceInterfaceID (from binary disassembly — differs
# from the documented kSCSITaskDeviceInterfaceID = 6BD48AE0-…).
_kSCSITaskDeviceInterfaceID_bytes = bytes([
    0x1B, 0xBC, 0x41, 0x32, 0x08, 0xA5, 0x11, 0xD5,
    0x90, 0xED, 0x00, 0x30, 0x65, 0x7D, 0x05, 0x2A,
])

# ── SCSI structures ─────────────────────────────────────────────────


class _IOVirtualRange(Structure):
    _fields_ = [("address", c_uint64), ("length", c_uint64)]


class _SCSISenseData(Structure):
    _fields_ = [("data", c_uint8 * 18)]


_kSCSIDataTransfer_FromTargetToInitiator = 2

# ── COM vtable helpers ───────────────────────────────────────────────
#
# IOKit CFPlugIn interfaces use COM-style vtables:
#   obj → *vtable → [NULL, QI, AddRef, Release, version(0x1), method5, ...]
#
# SCSITaskDeviceInterface vtable (slots 5–10):
#   [5] IsExclusiveAccessAvailable  [6] AddCallbackDispatcherToRunLoop
#   [7] RemoveCallbackDispatcherFromRunLoop  [8] ObtainExclusiveAccess
#   [9] ReleaseExclusiveAccess  [10] CreateSCSITask
#
# SCSITaskInterface vtable (slots 5–24):
#   [5] IsTaskActive  [6] SetTaskAttribute  [7] GetTaskAttribute
#   [8] SetCommandDescriptorBlock(self, uint8*, uint8)
#   [9] GetCommandDescriptorBlockSize  [10] GetCommandDescriptorBlock
#   [11] SetScatterGatherEntries(self, IOVirtualRange*, uint8, uint64, uint8)
#   [12] SetTimeoutDuration(self, uint32)
#   [13] GetTimeoutDuration  [14] SetTaskCompletionCallback
#   [15] ExecuteTaskAsync
#   [16] ExecuteTaskSync(self, SenseData*, TaskStatus*, uint64*)
#   [17] AbortTask  [18] GetServiceResponse  [19] GetTaskState
#   [20] GetTaskStatus  [21] GetRealizedDataTransferCount
#   [22] GetAutoSenseData  [23] SetSenseDataBuffer
#   [24] ResetForNewTask


def _vt_ptr(obj: c_void_p, slot: int):
    """Return raw function pointer at vtable[slot]."""
    vt_base = cast(obj, POINTER(c_void_p))[0]
    return cast(vt_base, POINTER(c_void_p))[slot]


def _vt_call(obj: c_void_p, slot: int, restype, argtypes, *args):
    """Call vtable[slot](obj, *args)."""
    fptr = _vt_ptr(obj, slot)
    fn = ctypes.CFUNCTYPE(restype, c_void_p, *argtypes)(fptr)
    return fn(obj, *args)


# ── IOKit registry helpers ───────────────────────────────────────────

def _cf_property_string(entry: int, key: str) -> Optional[str]:
    """Read a string property from an IOKit registry entry."""
    cf_key = _cf.CFStringCreateWithCString(
        None, key.encode(), kCFStringEncodingUTF8
    )
    if not cf_key:
        return None
    try:
        cf_val = _iok.IORegistryEntryCreateCFProperty(entry, cf_key, None, 0)
        if not cf_val:
            return None
        try:
            if _cf.CFGetTypeID(cf_val) != _cf.CFStringGetTypeID():
                return None
            buf = ctypes.create_string_buffer(512)
            if _cf.CFStringGetCString(cf_val, buf, 512, kCFStringEncodingUTF8):
                return buf.value.decode("utf-8", errors="replace")
            return None
        finally:
            _cf.CFRelease(cf_val)
    finally:
        _cf.CFRelease(cf_key)


def _cf_property_int(entry: int, key: str) -> Optional[int]:
    """Read an integer property from an IOKit registry entry."""
    cf_key = _cf.CFStringCreateWithCString(
        None, key.encode(), kCFStringEncodingUTF8
    )
    if not cf_key:
        return None
    try:
        cf_val = _iok.IORegistryEntryCreateCFProperty(entry, cf_key, None, 0)
        if not cf_val:
            return None
        try:
            if _cf.CFGetTypeID(cf_val) != _cf.CFNumberGetTypeID():
                return None
            val = c_int32(0)
            # kCFNumberSInt32Type = 3
            _cf.CFNumberGetValue(cf_val, 3, byref(val))
            return val.value
        finally:
            _cf.CFRelease(cf_val)
    finally:
        _cf.CFRelease(cf_key)


def _walk_parents_for_usb_info(service: int) -> dict:
    """Walk IOKit registry parents to find USB device properties."""
    result: dict = {}
    entry = service
    # Walk up to 10 levels — wrapped in try/finally so the last
    # parent IOKit handle is always released even on unexpected errors.
    try:
        for _ in range(10):
            parent = c_uint32(0)
            kr = _iok.IORegistryEntryGetParentEntry(entry, kIOServicePlane, byref(parent))
            if kr != 0:
                break
            # Check for USB device properties
            pid = _cf_property_int(parent.value, "idProduct")
            if pid is not None and "usb_pid" not in result:
                result["usb_pid"] = pid
            vid = _cf_property_int(parent.value, "idVendor")
            if vid is not None and "usb_vid" not in result:
                result["usb_vid"] = vid
            serial = _cf_property_string(parent.value, "USB Serial Number")
            if serial and "usb_serial" not in result:
                result["usb_serial"] = serial
            if entry != service:
                _iok.IOObjectRelease(entry)
            entry = parent.value
            if "usb_pid" in result and "usb_serial" in result:
                break
    finally:
        if entry != service:
            try:
                _iok.IOObjectRelease(entry)
            except Exception:
                pass
    return result


# ── SCSI command helpers ─────────────────────────────────────────────

class _SCSISession:
    """Manages exclusive access to one iPod's SCSI interface."""

    def __init__(self, service: int):
        self._service = service
        self._plugin: Optional[c_void_p] = None
        self._device_if: Optional[c_void_p] = None
        self._task = None
        self._exclusive = False

    def open(self) -> bool:
        """Create plugin → QueryInterface → ObtainExclusiveAccess → CreateTask."""
        # 1. Create plugin
        plugin = c_void_p(0)
        score = c_int32(0)
        kr = _iok.IOCreatePlugInInterfaceForService(
            self._service,
            _kSCSITaskDeviceUserClientTypeID,
            _kIOCFPlugInInterfaceID,
            byref(plugin),
            byref(score),
        )
        if kr != 0:
            log.debug("IOCreatePlugInInterfaceForService failed: 0x%08X", kr)
            return False
        self._plugin = plugin

        # 2. QueryInterface for SCSITaskDeviceInterface
        uuid_lo, uuid_hi = struct.unpack("<QQ", _kSCSITaskDeviceInterfaceID_bytes)
        device_if = c_void_p(0)
        hr = _vt_call(
            plugin, 1, c_uint32,
            [c_uint64, c_uint64, POINTER(c_void_p)],
            c_uint64(uuid_lo), c_uint64(uuid_hi), byref(device_if),
        )
        if hr != 0:
            log.debug("QueryInterface failed: 0x%08X", hr)
            return False
        self._device_if = device_if

        # 3. ObtainExclusiveAccess [8]
        kr = _vt_call(device_if, 8, c_int32, [])
        if kr != 0:
            log.debug("ObtainExclusiveAccess failed: 0x%08X", kr)
            return False
        self._exclusive = True

        # 4. CreateSCSITask [10]
        task = _vt_call(device_if, 10, c_void_p, [])
        if not task:
            log.debug("CreateSCSITask returned NULL")
            return False
        self._task = task
        return True

    def close(self):
        """Release all resources.  Each step is guarded so a failure
        in one does not prevent cleanup of the others."""
        if self._task:
            try:
                _vt_call(c_void_p(self._task), 3, c_uint32, [])  # Release
            except Exception:
                log.debug("SCSISession: task Release failed", exc_info=True)
            self._task = None
        if self._exclusive and self._device_if:
            try:
                _vt_call(self._device_if, 9, c_int32, [])  # ReleaseExclusive
            except Exception:
                log.debug("SCSISession: ReleaseExclusive failed", exc_info=True)
            self._exclusive = False
        if self._device_if:
            try:
                _vt_call(self._device_if, 3, c_uint32, [])  # Release
            except Exception:
                log.debug("SCSISession: device_if Release failed", exc_info=True)
            self._device_if = None
        if self._plugin:
            try:
                _vt_call(self._plugin, 3, c_uint32, [])  # Release
            except Exception:
                log.debug("SCSISession: plugin Release failed", exc_info=True)
            self._plugin = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def inquiry(self, evpd: bool, page: int, alloc_len: int = 255) -> Optional[bytes]:
        """Send SCSI INQUIRY. Returns response bytes or None on failure."""
        if not self._task:
            return None

        task = c_void_p(self._task)

        # ResetForNewTask [24]
        _vt_call(task, 24, c_int32, [])

        # SetCDB [8]
        cdb = (c_uint8 * 16)(
            0x12,
            0x01 if evpd else 0x00,
            page & 0xFF,
            0x00,
            alloc_len & 0xFF,
            0x00,
            *([0] * 10),
        )
        kr = _vt_call(
            task, 8, c_int32,
            [POINTER(c_uint8), c_uint8],
            cast(cdb, POINTER(c_uint8)), c_uint8(6),
        )
        if kr != 0:
            return None

        # SetScatterGatherEntries [11]
        resp = create_string_buffer(alloc_len)
        iovr = _IOVirtualRange(address=ctypes.addressof(resp), length=alloc_len)
        kr = _vt_call(
            task, 11, c_int32,
            [POINTER(_IOVirtualRange), c_uint8, c_uint64, c_uint8],
            byref(iovr), c_uint8(1), c_uint64(alloc_len),
            c_uint8(_kSCSIDataTransfer_FromTargetToInitiator),
        )
        if kr != 0:
            return None

        # SetTimeoutDuration [12]
        _vt_call(task, 12, c_int32, [c_uint32], c_uint32(10000))

        # ExecuteTaskSync [16]
        sense = _SCSISenseData()
        status = c_uint32(0)
        realized = c_uint64(0)
        kr = _vt_call(
            task, 16, c_int32,
            [POINTER(_SCSISenseData), POINTER(c_uint32), POINTER(c_uint64)],
            byref(sense), byref(status), byref(realized),
        )
        if kr != 0 or realized.value == 0:
            return None

        return bytes(resp)[: realized.value]


# ── VPD parsing ──────────────────────────────────────────────────────

def _read_vpd_pages(session: _SCSISession) -> bytes:
    """Read and concatenate VPD data pages (0xC2+) from iPod."""
    # Page 0xC0 lists the available data pages
    data_pages: list[int] = []
    c0 = session.inquiry(evpd=True, page=0xC0)
    if c0 and len(c0) >= 4:
        count = c0[3]
        data_pages = [p for p in c0[4:4 + count] if p >= 0xC2]
    if not data_pages:
        # Fallback: try 0xC2–0xFF
        data_pages = list(range(0xC2, 0x100))

    raw = bytearray()
    for page in data_pages:
        resp = session.inquiry(evpd=True, page=page)
        if not resp or len(resp) < 4:
            continue
        payload_len = resp[3]
        payload = resp[4:4 + payload_len]
        if not any(payload):
            continue
        raw.extend(payload)

    # Strip trailing nulls
    return bytes(raw).rstrip(b"\x00")


def _parse_vpd_xml(raw: bytes) -> dict:
    """Parse XML plist from concatenated VPD page data."""
    result: dict = {}
    if not raw:
        return result

    # Find XML start
    for marker in (b"<?xml", b"<plist"):
        idx = raw.find(marker)
        if idx >= 0:
            raw = raw[idx:]
            break

    # Ensure plist is closed (may be truncated)
    if b"</plist>" not in raw:
        raw = raw + b"\n</dict>\n</plist>"

    try:
        plist = plistlib.loads(raw)
        if isinstance(plist, dict):
            result = plist
    except Exception:
        # Fallback: regex extraction
        result = _parse_vpd_regex(raw)

    return result


def _parse_vpd_regex(raw: bytes) -> dict:
    """Regex fallback for truncated XML plists."""
    result: dict = {}
    text = raw.decode("utf-8", errors="replace")
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


# ── Public API ───────────────────────────────────────────────────────

def query_ipod_vpd(
    usb_pid: int = 0, serial_filter: str = ""
) -> Optional[dict]:
    """
    Query a single iPod's device info via IOKit SCSI VPD.

    No root required.  Does not detach the mass-storage driver or
    unmount the iPod disk — the device stays mounted throughout.

    Parameters
    ----------
    usb_pid : int
        Target specific USB Product ID (0 = any).
    serial_filter : str
        Target specific USB serial / FireWire GUID (case-insensitive).

    Returns
    -------
    dict or None
        Keys include ``SerialNumber``, ``FireWireGUID``, ``FamilyID``,
        ``UpdaterFamilyID``, ``vpd_raw_xml``, ``scsi_vendor``, etc.
    """
    match_dict = _iok.IOServiceMatching(b"com_apple_driver_iPodSBCNub")
    if not match_dict:
        return None
    iterator = c_uint32(0)
    kr = _iok.IOServiceGetMatchingServices(0, match_dict, byref(iterator))
    if kr != 0:
        return None

    try:
        while True:
            svc = _iok.IOIteratorNext(iterator.value)
            if svc == 0:
                break
            try:
                result = _query_one_service(svc, usb_pid, serial_filter)
                if result is not None:
                    return result
            except Exception as exc:
                log.debug("Failed to query iPod service %d: %s", svc, exc)
            finally:
                _iok.IOObjectRelease(svc)
    finally:
        _iok.IOObjectRelease(iterator.value)

    return None


def query_all_ipods() -> list[dict]:
    """
    Query every connected iPod via IOKit SCSI VPD.

    Returns a list of dicts (same format as ``query_ipod_vpd``).
    No root required; disks stay mounted.
    """
    match_dict = _iok.IOServiceMatching(b"com_apple_driver_iPodSBCNub")
    if not match_dict:
        return []
    iterator = c_uint32(0)
    kr = _iok.IOServiceGetMatchingServices(0, match_dict, byref(iterator))
    if kr != 0:
        return []

    results: list[dict] = []
    try:
        while True:
            svc = _iok.IOIteratorNext(iterator.value)
            if svc == 0:
                break
            try:
                result = _query_one_service(svc, 0, "")
                if result is not None:
                    results.append(result)
            except Exception as exc:
                log.debug("Failed to query iPod service %d: %s", svc, exc)
            finally:
                _iok.IOObjectRelease(svc)
    finally:
        _iok.IOObjectRelease(iterator.value)

    return results


# ── Internal ─────────────────────────────────────────────────────────

def _query_one_service(
    service: int, usb_pid: int, serial_filter: str
) -> Optional[dict]:
    """Query one iPod IOKit service.  Returns dict or None."""
    # Get USB info from IOKit registry parents
    usb_info = _walk_parents_for_usb_info(service)

    # Apply filters
    if usb_pid and usb_info.get("usb_pid") != usb_pid:
        return None
    if serial_filter:
        svc_serial = usb_info.get("usb_serial", "")
        if svc_serial.upper() != serial_filter.upper():
            return None

    with _SCSISession(service) as session:
        if not session.open():
            log.debug("Failed to open SCSI session for service %d", service)
            return None

        info: dict = {}

        # USB identifiers
        if "usb_pid" in usb_info:
            info["usb_pid"] = usb_info["usb_pid"]
        if "usb_serial" in usb_info:
            info["usb_serial"] = usb_info["usb_serial"]

        # Standard INQUIRY
        std = session.inquiry(evpd=False, page=0, alloc_len=96)
        if std and len(std) >= 36:
            info["scsi_vendor"] = std[8:16].decode("ascii", errors="replace").strip()
            info["scsi_product"] = std[16:32].decode("ascii", errors="replace").strip()
            info["scsi_revision"] = std[32:36].decode("ascii", errors="replace").strip()

        # VPD page 0x80 — Unit Serial Number
        p80 = session.inquiry(evpd=True, page=0x80)
        if p80 and len(p80) > 4:
            sn = p80[4:].split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
            if sn:
                info["vpd_serial"] = sn

        # VPD data pages → XML plist
        raw_xml = _read_vpd_pages(session)
        if raw_xml:
            info["vpd_raw_xml"] = raw_xml
            plist_data = _parse_vpd_xml(raw_xml)
            info.update(plist_data)

    return info if info else None
