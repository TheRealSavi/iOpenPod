"""Linux SG_IO SCSI VPD reader for mounted iPods.

This sends SCSI INQUIRY commands to the block device backing the selected
mount point.  It avoids PyUSB driver detach/unmount behavior and anchors the
live SysInfoExtended read to the same mounted iPod the UI selected.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import sys

from .diagnostic_log import CAPABILITY_FIELDS, IDENTITY_FIELDS, format_fields
from .sysinfo import normalize_guid, parse_sysinfo_extended

logger = logging.getLogger(__name__)

_SG_IO = 0x2285
_SG_DXFER_FROM_DEV = -3


class _SG_IO_HDR(ctypes.Structure):
    _fields_ = [
        ("interface_id", ctypes.c_int),
        ("dxfer_direction", ctypes.c_int),
        ("cmd_len", ctypes.c_ubyte),
        ("mx_sb_len", ctypes.c_ubyte),
        ("iovec_count", ctypes.c_ushort),
        ("dxfer_len", ctypes.c_uint),
        ("dxferp", ctypes.c_void_p),
        ("cmdp", ctypes.c_void_p),
        ("sbp", ctypes.c_void_p),
        ("timeout", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("pack_id", ctypes.c_int),
        ("usr_ptr", ctypes.c_void_p),
        ("status", ctypes.c_ubyte),
        ("masked_status", ctypes.c_ubyte),
        ("msg_status", ctypes.c_ubyte),
        ("sb_len_wr", ctypes.c_ubyte),
        ("host_status", ctypes.c_ushort),
        ("driver_status", ctypes.c_ushort),
        ("resid", ctypes.c_int),
        ("duration", ctypes.c_uint),
        ("info", ctypes.c_uint),
    ]


def _whole_disk_candidate(device: str) -> str:
    real = os.path.realpath(device)
    base = os.path.basename(real)
    dirname = os.path.dirname(real)
    if re.match(r"sd[a-z]+\d+$", base):
        return os.path.join(dirname, re.sub(r"\d+$", "", base))
    if re.match(r"(mmcblk|nvme).+p\d+$", base):
        return os.path.join(dirname, re.sub(r"p\d+$", "", base))
    return real


def _block_candidates(mount_path: str) -> list[str]:
    try:
        from .scanner import _linux_find_block_device

        partition = _linux_find_block_device(mount_path)
    except Exception as exc:
        logger.debug("Linux SG_IO: mount lookup failed for %s: %s", mount_path, exc)
        partition = None

    candidates: list[str] = []
    for path in (partition, _whole_disk_candidate(partition) if partition else None):
        if path and path not in candidates:
            candidates.append(path)
    return candidates


def _scsi_inquiry(fd: int, *, evpd: bool, page: int, alloc_len: int = 255) -> bytes:
    import fcntl

    data_buf = ctypes.create_string_buffer(alloc_len)
    sense_buf = ctypes.create_string_buffer(64)
    cdb = (ctypes.c_ubyte * 6)(
        0x12,
        0x01 if evpd else 0x00,
        page & 0xFF,
        0x00,
        alloc_len & 0xFF,
        0x00,
    )

    hdr = _SG_IO_HDR()
    hdr.interface_id = ord("S")
    hdr.dxfer_direction = _SG_DXFER_FROM_DEV
    hdr.cmd_len = 6
    hdr.mx_sb_len = len(sense_buf)
    hdr.dxfer_len = alloc_len
    hdr.dxferp = ctypes.cast(data_buf, ctypes.c_void_p)
    hdr.cmdp = ctypes.cast(cdb, ctypes.c_void_p)
    hdr.sbp = ctypes.cast(sense_buf, ctypes.c_void_p)
    hdr.timeout = 10000

    fcntl.ioctl(fd, _SG_IO, hdr)
    if hdr.status != 0 or hdr.host_status != 0 or hdr.driver_status != 0:
        raise OSError(
            hdr.status or hdr.host_status or hdr.driver_status,
            f"SG_IO INQUIRY failed for page 0x{page:02X}",
        )

    transfer_len = alloc_len - max(int(hdr.resid), 0)
    if transfer_len <= 0:
        transfer_len = alloc_len
    return bytes(data_buf.raw[: min(transfer_len, alloc_len)])


def _read_standard_inquiry(fd: int) -> dict:
    result: dict = {}
    try:
        data = _scsi_inquiry(fd, evpd=False, page=0, alloc_len=96)
    except Exception as exc:
        logger.debug("Linux SG_IO: standard INQUIRY failed: %s", exc)
        return result

    if len(data) >= 36:
        result["scsi_vendor"] = data[8:16].decode("ascii", errors="replace").strip()
        result["scsi_product"] = data[16:32].decode("ascii", errors="replace").strip()
        result["scsi_revision"] = data[32:36].decode("ascii", errors="replace").strip()
    return result


def _read_vpd_serial(fd: int) -> str:
    try:
        data = _scsi_inquiry(fd, evpd=True, page=0x80, alloc_len=255)
    except Exception:
        return ""
    if len(data) <= 4:
        return ""
    return data[4:].split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def _read_vpd_pages(fd: int) -> bytes:
    data_pages: list[int] = []
    try:
        c0 = _scsi_inquiry(fd, evpd=True, page=0xC0, alloc_len=255)
        if len(c0) >= 4:
            count = c0[3]
            data_pages = [p for p in c0[4:4 + count] if p >= 0xC2]
    except Exception as exc:
        logger.debug("Linux SG_IO: VPD page 0xC0 failed: %s", exc)

    if not data_pages:
        data_pages = list(range(0xC2, 0x100))

    chunks: list[bytes] = []
    for page in data_pages:
        try:
            data = _scsi_inquiry(fd, evpd=True, page=page, alloc_len=255)
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
    """Read SCSI VPD SysInfoExtended from a mounted Linux iPod volume."""
    if sys.platform != "linux":
        return None

    logger.info(
        "Linux SG_IO VPD query start: mount=%s pid=%s filter=%s",
        mount_path,
        f"0x{usb_pid:04X}" if usb_pid else "unknown",
        serial_filter or "none",
    )
    for device in _block_candidates(mount_path):
        fd: int | None = None
        try:
            fd = os.open(device, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
            result: dict = {
                "_source": "linux_scsi",
                "_transport": "linux_sg_io_scsi_vpd",
                "block_device": device,
            }
            if usb_pid:
                result["usb_pid"] = usb_pid
                result["usb_vid"] = 0x05AC

            result.update(_read_standard_inquiry(fd))
            vpd_serial = _read_vpd_serial(fd)
            if vpd_serial:
                result["vpd_serial"] = vpd_serial

            raw_xml = _read_vpd_pages(fd)
            if not raw_xml:
                logger.info("Linux SG_IO: no SysInfoExtended payload from %s", device)
                continue

            parsed = parse_sysinfo_extended(raw_xml, source="linux_scsi", live=True)
            if not parsed.plist:
                logger.info(
                    "Linux SG_IO: parsed payload had no plist keys on %s",
                    device,
                )
                continue

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
                logger.info(
                    "Linux SG_IO: serial filter %s did not match %s on %s",
                    wanted,
                    actual,
                    device,
                )
                continue

            logger.info(
                "Linux SG_IO VPD query successful for %s: keys=%d "
                "identity=[%s] caps=[%s]",
                device,
                len(parsed.plist),
                format_fields(log_identity, IDENTITY_FIELDS),
                format_fields(log_identity, CAPABILITY_FIELDS, include_false=True),
            )
            return result
        except PermissionError as exc:
            logger.info("Linux SG_IO: permission denied opening %s: %s", device, exc)
        except Exception as exc:
            logger.info("Linux SG_IO: query failed for %s: %s", device, exc)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    return None
