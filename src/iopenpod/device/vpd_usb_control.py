"""
Read iPod SysInfoExtended via Apple's USB vendor-control command.

libgpod uses this path for devices such as later nanos that can expose richer
SysInfoExtended data over a device-level vendor request than through SCSI VPD.
It is intentionally separate from ``vpd_libusb``'s Mass Storage Bulk-Only/SCSI
path so callers can preserve transport provenance.
"""

from __future__ import annotations

import logging

from .diagnostic_log import CAPABILITY_FIELDS, IDENTITY_FIELDS, format_fields
from .models import IPOD_USB_PIDS
from .sysinfo import parse_sysinfo_extended
from .usb_backend import backend_diagnostic, get_libusb_backend

logger = logging.getLogger(__name__)

APPLE_VID = 0x05AC

_REQUEST_TYPE_IN_VENDOR_DEVICE = 0xC0
_REQUEST_READ_SYSINFO_EXTENDED = 0x40
_VALUE_SYSINFO_EXTENDED = 0x0002
_CHUNK_SIZE = 0x1000
_MAX_CHUNKS = 0xFFFF
_TIMEOUT_MS = 5000


def _find_ipod_devices() -> list:
    try:
        import usb.core
    except ImportError:
        logger.info("USB vendor SysInfoExtended: pyusb not installed")
        return []

    backend = get_libusb_backend()
    if backend is None:
        logger.info(
            "USB vendor SysInfoExtended: no PyUSB backend available: %s",
            backend_diagnostic(),
        )
        return []

    found = usb.core.find(find_all=True, idVendor=APPLE_VID, backend=backend)
    if found is None:
        return []
    return [dev for dev in found if getattr(dev, "idProduct", None) in IPOD_USB_PIDS]


def _device_serial(dev) -> str:
    try:
        return (dev.serial_number or "").replace(" ", "").strip().upper()
    except Exception:
        return ""


def _read_sysinfo_extended_from_device(dev) -> bytes:
    raw = bytearray()

    for index in range(_MAX_CHUNKS):
        chunk = dev.ctrl_transfer(
            _REQUEST_TYPE_IN_VENDOR_DEVICE,
            _REQUEST_READ_SYSINFO_EXTENDED,
            _VALUE_SYSINFO_EXTENDED,
            index,
            _CHUNK_SIZE,
            timeout=_TIMEOUT_MS,
        )
        data = bytes(chunk)
        raw.extend(data)
        if len(data) != _CHUNK_SIZE:
            break

    return bytes(raw).rstrip(b"\x00")


def query_ipod_usb_sysinfo_extended(
    usb_pid: int = 0,
    serial_filter: str = "",
) -> dict | None:
    """Query one iPod through Apple's USB vendor-control SysInfo command.

    Returns a dict shaped similarly to the SCSI VPD readers, with parsed
    SysInfoExtended keys plus ``vpd_raw_xml``, ``usb_pid``, ``usb_serial`` and
    provenance metadata.  Returns ``None`` if no matching iPod answers.
    """
    # _find_ipod_devices already checks for pyusb availability and the backend.
    # No need to import usb.core again here.

    serial_filter = serial_filter.replace(" ", "").strip().upper()
    logger.info(
        "USB vendor SysInfoExtended query start: pid=%s filter=%s",
        f"0x{usb_pid:04X}" if usb_pid else "any",
        serial_filter or "none",
    )
    candidates = [
        dev for dev in _find_ipod_devices()
        if not usb_pid or getattr(dev, "idProduct", None) == usb_pid
    ]
    logger.info(
        "USB vendor SysInfoExtended candidates: count=%d pids=%s",
        len(candidates),
        ", ".join(f"0x{getattr(dev, 'idProduct', 0):04X}" for dev in candidates) or "none",
    )
    target = None
    if serial_filter:
        for dev in candidates:
            serial = _device_serial(dev)
            if serial == serial_filter:
                target = dev
                break
        if target is None and len(candidates) == 1 and usb_pid:
            # Some Windows libusb driver stacks enumerate the device but refuse
            # string descriptors.  If PID has already narrowed this to a single
            # candidate, it is still safe to attempt the read.
            target = candidates[0]
    elif candidates:
        target = candidates[0]

    if target is None:
        logger.info("USB vendor SysInfoExtended query: no matching target")
        return None

    usb_serial = _device_serial(target)
    try:
        raw_xml = _read_sysinfo_extended_from_device(target)
    except Exception as exc:
        message = str(exc)
        if "not supported" in message.lower() or "not implemented" in message.lower():
            logger.info(
                "USB vendor SysInfoExtended backend is available, but Windows "
                "driver access does not support device control transfers for "
                "PID=0x%04X serial=%s: %s",
                getattr(target, "idProduct", 0),
                usb_serial,
                exc,
            )
        else:
            logger.info(
                "USB vendor SysInfoExtended read failed for PID=0x%04X serial=%s: %s",
                getattr(target, "idProduct", 0),
                usb_serial,
                exc,
            )
        return None

    if not raw_xml:
        logger.info(
            "USB vendor SysInfoExtended query returned empty payload: "
            "PID=0x%04X serial=%s",
            getattr(target, "idProduct", 0),
            usb_serial,
        )
        return None

    parsed = parse_sysinfo_extended(raw_xml, source="usb_vendor", live=True)
    if not parsed.plist:
        logger.info(
            "USB vendor SysInfoExtended parse returned no plist keys: "
            "PID=0x%04X serial=%s",
            getattr(target, "idProduct", 0),
            usb_serial,
        )
        return None

    result: dict = {
        "usb_pid": getattr(target, "idProduct", 0),
        "usb_serial": usb_serial,
        "vpd_raw_xml": parsed.raw_xml or raw_xml,
        "_source": "usb_vendor",
        "_transport": "usb_vendor_control",
        "_used_usb_vendor": True,
    }
    result.update(parsed.plist)
    log_identity = dict(parsed.identity)
    log_identity["usb_pid"] = getattr(target, "idProduct", 0)
    if usb_serial:
        log_identity["usb_serial"] = usb_serial

    logger.info(
        "USB vendor SysInfoExtended query successful: PID=0x%04X serial=%s "
        "keys=%d identity=[%s] caps=[%s]",
        getattr(target, "idProduct", 0),
        usb_serial,
        len(parsed.plist),
        format_fields(log_identity, IDENTITY_FIELDS),
        format_fields(log_identity, CAPABILITY_FIELDS, include_false=True),
    )
    return result


def query_all_ipod_usb_sysinfo_extended() -> list[dict]:
    """Query every connected iPod that answers the vendor-control command."""
    results: list[dict] = []
    for dev in _find_ipod_devices():
        try:
            info = query_ipod_usb_sysinfo_extended(
                usb_pid=getattr(dev, "idProduct", 0),
                serial_filter=_device_serial(dev),
            )
            if info:
                results.append(info)
        except Exception as exc:
            logger.debug(
                "USB vendor SysInfoExtended query failed for PID=0x%04X: %s",
                getattr(dev, "idProduct", 0),
                exc,
            )
    return results
