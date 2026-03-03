"""
Centralised device information store for iOpenPod.

When an iPod is selected, every knowable detail about it is gathered **once**
by the device scanner / loader and stored here.  Every other module — GUI,
writer, sync engine — accesses device info exclusively through this store.
**No consumer should ever probe hardware, read SysInfo, or query the registry
on its own.**  If the store is empty the consumer uses a safe default.

Typical flow
~~~~~~~~~~~~
1. Device scanner discovers iPod → ``DeviceInfo``
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
    mount_name: str = ""              # Volume display name (e.g. "D:", "IPOD")
    ipod_name: str = ""               # User-assigned name from master playlist Title
    model_number: str = ""            # Normalised (e.g. "MC297", never "xA623")
    model_family: str = "iPod"        # e.g. "iPod Classic", "iPod Nano"
    generation: str = ""              # e.g. "3rd Gen"
    capacity: str = ""                # e.g. "160GB"
    color: str = ""                   # e.g. "Black"

    # ── Hardware / Identifiers ────────────────────────────────────────
    firewire_guid: str = ""           # 16 hex chars (8 bytes), used for hash signing
    serial: str = ""                  # Apple serial (e.g. "YM0350TRVQ5"), NOT the FW GUID
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
    _field_sources: dict[str, str] = field(default_factory=dict, init=False, repr=False)

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

    @property
    def subtitle(self) -> str:
        """Secondary line (mount name + free space)."""
        parts = [self.mount_name] if self.mount_name else []
        if self.disk_size_gb > 0:
            parts.append(f"{self.free_space_gb:.1f} of {self.disk_size_gb:.1f} GB free")
        return " — ".join(parts) if parts else ""

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


# ──────────────────────────────────────────────────────────────────────
# Utility functions (used by multiple modules)
# ──────────────────────────────────────────────────────────────────────

def resolve_itdb_path(ipod_path: str) -> str | None:
    """Return the path to the iTunesDB (or iTunesCDB) on the iPod.

    Newer iPods (Nano 5G+) use ``iTunesCDB`` instead of ``iTunesDB``.
    iTunesCDB is **zlib-compressed**: the mhbd header is stored
    uncompressed, followed by a zlib stream containing all mhsd children.
    The parser transparently decompresses it; the writer compresses when
    ``DeviceCapabilities.supports_compressed_db`` is True.  The firmware
    on those devices reads ``iTunesCDB`` and ignores ``iTunesDB``.

    Check order:

    1. ``iTunesCDB`` — used by devices with ``supports_compressed_db``
    2. ``iTunesDB``  — used by all other devices

    Returns the path to whichever file exists, or ``None`` if neither is
    present.
    """
    itunes_dir = os.path.join(ipod_path, "iPod_Control", "iTunes")
    cdb = os.path.join(itunes_dir, "iTunesCDB")
    if os.path.exists(cdb):
        return cdb
    db = os.path.join(itunes_dir, "iTunesDB")
    if os.path.exists(db):
        return db
    return None


def itdb_write_filename(ipod_path: str) -> str:
    """Return the filename to use when **writing** the iTunesDB.

    Uses the device capabilities (``supports_compressed_db``) when
    available.  Falls back to whichever file already exists on disk, and
    finally defaults to ``"iTunesDB"``.
    """
    # 1. Ask the device store
    try:
        dev = get_current_device()
        if dev and dev.model_family and dev.generation:
            from ipod_models import capabilities_for_family_gen
            caps = capabilities_for_family_gen(dev.model_family, dev.generation)
            if caps and caps.supports_compressed_db:
                return "iTunesCDB"
    except Exception:
        pass

    # 2. If an iTunesCDB already exists on disk, keep using it
    cdb = os.path.join(ipod_path, "iPod_Control", "iTunes", "iTunesCDB")
    if os.path.exists(cdb):
        return "iTunesCDB"

    return "iTunesDB"


def read_sysinfo(ipod_path: str) -> dict:
    """Parse the SysInfo file from an iPod.

    The SysInfo file at ``/iPod_Control/Device/SysInfo`` contains device
    identification info as ``key: value`` pairs (one per line):

    - ``ModelNumStr`` — device model (e.g. ``"xA623"``)
    - ``FirewireGuid`` — device GUID for hash computation
    - ``pszSerialNumber`` — Apple serial number
    - ``BoardHwName`` — hardware identifier
    - ``visibleBuildID`` — firmware version

    Returns:
        Dictionary of SysInfo key→value pairs.

    Raises:
        FileNotFoundError: If SysInfo doesn't exist.
    """
    sysinfo_path = os.path.join(ipod_path, "iPod_Control", "Device", "SysInfo")

    if not os.path.exists(sysinfo_path):
        raise FileNotFoundError(f"SysInfo not found at {sysinfo_path}")

    sysinfo: dict[str, str] = {}
    with open(sysinfo_path, "r", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if ":" in line:
                key, value = line.split(":", 1)
                sysinfo[key.strip()] = value.strip()

    return sysinfo


def _estimate_capacity_from_disk_size(disk_gb: float) -> str:
    """Map raw disk size (GB) to a marketed capacity string.

    iPod capacities are advertised in base-10, but actual formatted space
    is lower due to filesystem overhead and base-2/base-10 conversion.
    This uses generous thresholds to handle both.
    """
    thresholds = [
        (140, "160GB"), (100, "120GB"), (65, "80GB"),
        (50, "60GB"), (35, "40GB"), (25, "30GB"),
        (17, "20GB"), (13, "16GB"), (6.5, "8GB"), (3, "4GB"),
        (1.5, "2GB"), (0.7, "1GB"), (0.3, "512MB"),
    ]
    for threshold, label in thresholds:
        if disk_gb >= threshold:
            return label
    return ""


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
            "Device stored: %s %s (%s) serial=…%s fwguid=%s "
            "checksum=%s method=%s capacity=%s formats=%s",
            info.model_family, info.generation, info.model_number,
            info.serial[-3:] if info.serial else "none",
            info.firewire_guid or "none",
            info.checksum_type,
            info.identification_method,
            info.capacity or "unknown",
            list(info.artwork_formats.keys()) if info.artwork_formats else "none",
        )
    else:
        logger.info("Device cleared")


def clear_current_device() -> None:
    """Clear the stored device info (device disconnected / deselected)."""
    set_current_device(None)


def detect_checksum_type(ipod_path: str):
    """Detect which checksum type an iPod requires.

    Reads from the centralised store first; falls back to SysInfo probing.
    Returns a :class:`ipod_models.ChecksumType` enum value.
    """
    from ipod_models import (
        ChecksumType,
        checksum_type_for_family_gen,
        extract_model_number,
        get_model_info,
    )

    # Fast path: centralised store
    device = get_current_device()
    if device is not None and device.checksum_type != 99:
        return ChecksumType(device.checksum_type)

    # Fallback: probe from scratch
    try:
        sysinfo = read_sysinfo(ipod_path)
    except FileNotFoundError:
        return ChecksumType.NONE

    model_str = sysinfo.get("ModelNumStr", "")
    model_num = extract_model_number(model_str)

    if model_num:
        mi = get_model_info(model_num)
        if mi:
            ct = checksum_type_for_family_gen(mi[0], mi[1])
            if ct is not None:
                return ct

    hi_path = os.path.join(ipod_path, "iPod_Control", "Device", "HashInfo")
    if os.path.exists(hi_path):
        return ChecksumType.HASH72

    firmware = sysinfo.get("visibleBuildID", "")
    if firmware:
        try:
            version = int(firmware.split(".")[0])
            if version >= 2:
                return ChecksumType.UNKNOWN
        except (ValueError, IndexError):
            pass

    if "FirewireGuid" in sysinfo:
        return ChecksumType.UNKNOWN

    return ChecksumType.NONE


def get_firewire_id(ipod_path: str, *, known_guid: str | None = None) -> bytes:
    """Get the FireWire GUID for an iPod, trying multiple sources.

    Sources (in priority order):
      0. ``known_guid`` parameter
      1. Centralised DeviceInfo store
      2. SysInfo file
      3. SysInfoExtended plist

    Returns:
        FireWire GUID as raw bytes (typically 8 bytes).

    Raises:
        RuntimeError: If the GUID cannot be found from any source.
    """
    # Source 0: caller-supplied
    if known_guid:
        try:
            guid_bytes = bytes.fromhex(known_guid)
            if guid_bytes != b"\x00" * len(guid_bytes):
                return guid_bytes
        except ValueError:
            pass

    # Source 1: centralised store
    device = get_current_device()
    if device is not None:
        fwid = device.firewire_id_bytes
        if fwid:
            return fwid

    # Source 2: SysInfo
    try:
        sysinfo = read_sysinfo(ipod_path)
        guid = sysinfo.get("FirewireGuid", "")
        if guid:
            if guid.startswith(("0x", "0X")):
                guid = guid[2:]
            result = bytes.fromhex(guid)
            if result != b"\x00" * len(result):
                return result
    except (FileNotFoundError, ValueError):
        pass

    # Source 3: SysInfoExtended
    sysinfo_ex_path = os.path.join(ipod_path, "iPod_Control", "Device", "SysInfoExtended")
    if os.path.exists(sysinfo_ex_path):
        try:
            with open(sysinfo_ex_path, "r", errors="ignore") as f:
                content = f.read()
            import re as _re
            m = _re.search(
                r"<key>FireWireGUID</key>\s*<string>([0-9A-Fa-f]+)</string>",
                content,
            )
            if m:
                guid_hex = m.group(1)
                if guid_hex.startswith(("0x", "0X")):
                    guid_hex = guid_hex[2:]
                result = bytes.fromhex(guid_hex)
                if result != b"\x00" * len(result):
                    return result
        except Exception:
            pass

    raise RuntimeError(
        "Could not find iPod FireWire GUID. Tried:\n"
        "  0. known_guid parameter\n"
        "  1. Centralised device info store\n"
        "  2. SysInfo file\n"
        "  3. SysInfoExtended plist\n"
        "\n"
        "Connect the iPod and try again."
    )


# ──────────────────────────────────────────────────────────────────────
# Enrichment — fills derived fields from the ones already known
# ──────────────────────────────────────────────────────────────────────

def enrich(info: DeviceInfo) -> None:
    """Fill in derived fields by probing sources in authority order.

    This is the ONE place in the entire codebase that touches hardware,
    reads files from the device, queries the OS, etc.

    The authority file determines the strategy:

    * **HIGH authority** (all fields sourced from live hardware on a
      previous run) → trust SysInfo / SysInfoExtended values, skip
      expensive hardware and VPD probes.
    * **LOW authority** (any field sourced from a guess, or no authority
      file yet) → probe from highest authority to lowest, filling gaps
      as each source is tried:

      1. Hardware probe (IOCTL / IOKit / sysfs)
      2. USB VPD query (SCSI inquiry — gets Apple serial + model)
      3. SysInfoExtended XML plist
      4. SysInfo text file
      5. Windows registry fallback

    After all identification, ``update_sysinfo()`` writes the gathered
    data back to SysInfo and updates the authority file + hashes.
    """

    # ── 0. Load SysInfo dict (always — needed for reference) ──────────
    if info.path and not info.sysinfo:
        try:
            info.sysinfo = read_sysinfo(info.path)
            logger.info("enrich: SysInfo loaded (%d keys)", len(info.sysinfo))
        except FileNotFoundError:
            logger.info("enrich: no SysInfo at %s", info.path)
        except Exception as exc:
            logger.info("enrich: SysInfo read failed: %s", exc)

    # ── 1. Authority coverage check ───────────────────────────────────
    _authority_is_high = False
    if info.path:
        try:
            from sysinfo_authority import check_authority_coverage
            _all_tracked, _auth_sources = check_authority_coverage(info.path)
            if _all_tracked:
                _authority_is_high = True
                # Pre-populate _field_sources from authority so the rest
                # of the pipeline sees the correct provenance.
                for _field, _source in _auth_sources.items():
                    if _field not in info._field_sources:
                        info._field_sources[_field] = _source
                logger.info(
                    "enrich: authority covers all core fields — "
                    "trusting SysInfo, skipping hardware/VPD probes",
                )
            elif _auth_sources:
                logger.info(
                    "enrich: authority has untracked core fields — "
                    "probing highest → lowest authority",
                )
        except Exception as exc:
            logger.debug("enrich: authority check failed: %s", exc)

    if _authority_is_high:
        # ── HIGH authority path: SysInfo is trustworthy ───────────────
        _populate_fields_from_sysinfo(info)
        if info.path:
            _enrich_from_sysinfo_extended(info)
    else:
        # ── LOW authority path: probe highest → lowest ────────────────
        #   Each source fills only gaps (if not info.X guards), so the
        #   first source to provide a value wins — which is the highest
        #   authority source.

        # 2a. Hardware probe (IOCTL + device tree + USB PID)
        _enrich_from_hardware_probe(info)

        # 2b. USB VPD query (highest authority — Apple serial + model)
        #   Runs even if SysInfo exists, because low-authority SysInfo
        #   values should be upgraded with VPD data when possible.
        if info.path:
            _enrich_from_usb_vpd(info)

        # 2c. SysInfoExtended (fills gaps)
        if info.path:
            _enrich_from_sysinfo_extended(info)

        # 2d. SysInfo (fills remaining gaps — lowest useful authority)
        _populate_fields_from_sysinfo(info)

        # 2e. Windows registry fallback for FW GUID
        if not info.firewire_guid:
            _enrich_from_windows_registry(info)

    # ── 3. Model lookup (map model_number → family/gen/capacity/color) ─
    #   This is a cheap dict lookup — always run it to fill derived fields.
    #   Uses the model_number's source as provenance for derived fields,
    #   since they are deterministically derived from it.
    if info.model_number and info.model_family in ("iPod", ""):
        try:
            from ipod_models import get_model_info
            mi = get_model_info(info.model_number)
            if mi:
                _mn_source = info._field_sources.get("model_number", "unknown")
                info.model_family = mi[0]
                info._field_sources.setdefault("model_family", _mn_source)
                info.generation = mi[1]
                info._field_sources.setdefault("generation", _mn_source)
                if not info.capacity:
                    info.capacity = mi[2]
                    info._field_sources.setdefault("capacity", _mn_source)
                if not info.color:
                    info.color = mi[3]
                    info._field_sources.setdefault("color", _mn_source)
                logger.info("enrich: model DB → %s %s %s %s",
                            mi[0], mi[1], mi[2], mi[3])
        except ImportError:
            pass

    # ── 3b. Serial-last-3 model lookup ────────────────────────────────
    #   Very reliable — the last 3 chars of the serial encode the exact
    #   model (incl. capacity and color).  Always run when the serial is
    #   available and ANY of model_number, capacity, or color is still
    #   missing — serial lookup is higher confidence than USB PID and
    #   provides the exact variant including color/revision.
    if info.serial and (
        not info.model_number or not info.capacity or not info.color
    ):
        _enrich_from_serial_lookup(info)

    # ── 3c. USB PID-based family/generation (if nothing else worked) ──
    if info.usb_pid and info.model_family in ("iPod", ""):
        try:
            from ipod_models import USB_PID_TO_MODEL
            pid_info = USB_PID_TO_MODEL.get(info.usb_pid)
            if pid_info:
                info.model_family = pid_info[0]
                info._field_sources.setdefault("model_family", "usb_pid")
                if not info.generation and pid_info[1]:
                    info.generation = pid_info[1]
                    info._field_sources.setdefault("generation", "usb_pid")
                logger.debug("enrich: USB PID 0x%04X → %s %s",
                             info.usb_pid, pid_info[0], pid_info[1])
        except ImportError:
            pass

    # ── 4. iTunesDB header (hashing scheme, version) ─────────────────
    if info.path and info.hashing_scheme == -1:
        _enrich_from_itunesdb_header(info)

    # ── 5. Checksum type ──────────────────────────────────────────────
    if info.checksum_type == 99:
        _resolve_checksum_type(info)

    # ── 6. HashInfo (cryptographic material for HASH72 signing) ───────
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

    # ── 7. Artwork formats ────────────────────────────────────────────
    # Try model-based lookup first
    if not info.artwork_formats and info.model_family and info.generation:
        try:
            from ipod_models import ithmb_formats_for_device
            table = ithmb_formats_for_device(info.model_family, info.generation)
            if table:
                info.artwork_formats = dict(table)
                logger.info("enrich: artwork formats from model: %s",
                            list(info.artwork_formats.keys()))
        except ImportError:
            pass

    # Fallback: scan ArtworkDB for format IDs
    if not info.artwork_formats and info.path:
        _enrich_artwork_from_artworkdb(info)

    # ── 8. Disk size ─────────────────────────────────────────────────
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

    # ── 9. Capacity from disk size (if still unknown) ────────────────
    if not info.capacity and info.disk_size_gb > 0:
        info.capacity = _estimate_capacity_from_disk_size(info.disk_size_gb)
        if info.capacity:
            logger.info("enrich: capacity from disk size: %s", info.capacity)

    # ── 10. Backfill _field_sources for derived fields ───────────────────
    #   The scanner's _resolve_model may have set model_family/generation/
    #   capacity/color/usb_pid without tracking sources.  Before writing
    #   authority, ensure every populated field has a source entry.
    #   Derived fields inherit from the identification method that resolved
    #   them (model_number's source, or the identification_method itself).
    _derived_fields = ("model_family", "generation", "capacity", "color", "usb_pid")
    _backfill_src = info._field_sources.get(
        "model_number",
        info.identification_method if info.identification_method != "unknown" else "unknown",
    )
    for _df in _derived_fields:
        if getattr(info, _df, None) and _df not in info._field_sources:
            info._field_sources[_df] = _backfill_src

    # ── 11. SysInfo authority update ───────────────────────────────────────
    #   After all identification and enrichment is complete, reconcile our
    #   gathered data with the on-disk SysInfo file via the authority system.
    if info.path:
        try:
            from sysinfo_authority import update_sysinfo as _update_sysinfo
            _update_sysinfo(info)
        except Exception as exc:
            logger.warning("enrich: SysInfo authority update failed: %s", exc)

    logger.info(
        "DeviceInfo enriched: %s %s (%s), serial=%s, fwguid=%s, "
        "checksum=%s, scheme=%s, method=%s, capacity=%s, "
        "formats=%s, disk=%.1fGB",
        info.model_family, info.generation, info.model_number,
        info.serial[-3:] if info.serial else "none",
        info.firewire_guid or "none",
        info.checksum_type, info.hashing_scheme,
        info.identification_method,
        info.capacity or "unknown",
        list(info.artwork_formats.keys()) if info.artwork_formats else "none",
        info.disk_size_gb,
    )


# ──────────────────────────────────────────────────────────────────────
# Private enrichment helpers — each probes ONE source
# ──────────────────────────────────────────────────────────────────────

def _populate_fields_from_sysinfo(info: DeviceInfo) -> None:
    """Fill empty DeviceInfo fields from the cached SysInfo dict.

    Only fills fields that are **not already populated**, and uses
    ``setdefault`` for ``_field_sources`` so higher-authority source
    annotations from earlier probes are preserved.

    Called at different points depending on authority level:

    * **HIGH** authority → called early (before probes), so all fields
      are still empty and get filled from the trusted SysInfo.
    * **LOW** authority → called late (after probes), so only the gaps
      that the hardware/VPD probes couldn't fill get patched from SysInfo.
    """
    if not info.sysinfo:
        return

    if not info.board:
        _board = info.sysinfo.get("BoardHwName", "")
        if _board:
            info.board = _board
            info._field_sources.setdefault("board", "sysinfo")

    if not info.serial:
        apple_serial = info.sysinfo.get("pszSerialNumber", "")
        if apple_serial and apple_serial != info.firewire_guid:
            info.serial = apple_serial
            info._field_sources.setdefault("serial", "sysinfo")
            logger.info("enrich: serial (Apple) from SysInfo: %s", apple_serial)
        elif apple_serial and apple_serial == info.firewire_guid:
            logger.warning(
                "enrich: SysInfo pszSerialNumber equals FW GUID (%s) "
                "— not a real Apple serial, skipping",
                apple_serial,
            )

    if not info.firmware:
        fw_ver = info.sysinfo.get("visibleBuildID", "")
        if fw_ver:
            info.firmware = fw_ver
            info._field_sources.setdefault("firmware", "sysinfo")
            logger.info("enrich: firmware from SysInfo: %s", fw_ver)

    if not info.firewire_guid:
        guid = info.sysinfo.get("FirewireGuid", "")
        if guid:
            if guid.startswith(("0x", "0X")):
                guid = guid[2:]
            if guid and guid != "0" * len(guid):
                info.firewire_guid = guid
                info._field_sources.setdefault("firewire_guid", "sysinfo")
                logger.info("enrich: FW GUID from SysInfo: %s", guid)

    if not info.model_number:
        try:
            from ipod_models import extract_model_number
            raw = info.sysinfo.get("ModelNumStr", "")
            if raw:
                mn = extract_model_number(raw)
                if mn:
                    info.model_number = mn
                    info._field_sources.setdefault("model_number", "sysinfo")
                    logger.info("enrich: model from SysInfo: %s", mn)
        except ImportError:
            pass

    # ── Derived / resolved fields (written by iOpenPod) ───────────────
    # These are only present if a previous iOpenPod run cached them.
    # model_family default is "iPod" (sentinel), so only replace it with
    # a more specific value.
    _mf = info.sysinfo.get("ModelFamily", "")
    if _mf and _mf != "iPod" and info.model_family in ("iPod", ""):
        info.model_family = _mf
        info._field_sources.setdefault("model_family", "sysinfo")
        logger.info("enrich: model_family from SysInfo: %s", _mf)

    if not info.generation:
        _gen = info.sysinfo.get("Generation", "")
        if _gen:
            info.generation = _gen
            info._field_sources.setdefault("generation", "sysinfo")
            logger.info("enrich: generation from SysInfo: %s", _gen)

    if not info.capacity:
        _cap = info.sysinfo.get("Capacity", "")
        if _cap:
            info.capacity = _cap
            info._field_sources.setdefault("capacity", "sysinfo")
            logger.info("enrich: capacity from SysInfo: %s", _cap)

    if not info.color:
        _col = info.sysinfo.get("Color", "")
        if _col:
            info.color = _col
            info._field_sources.setdefault("color", "sysinfo")
            logger.info("enrich: color from SysInfo: %s", _col)

    if not info.usb_pid:
        _pid_str = info.sysinfo.get("USBProductID", "")
        if _pid_str:
            try:
                info.usb_pid = int(_pid_str, 0)  # handles "0x1261" and "4705"
                info._field_sources.setdefault("usb_pid", "sysinfo")
                logger.info("enrich: usb_pid from SysInfo: 0x%04X", info.usb_pid)
            except ValueError:
                pass


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
        logger.info("enrich: SysInfoExtended read failed: %s", exc)
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
                info._field_sources["firewire_guid"] = "sysinfo_extended"
                logger.info("enrich: FW GUID from SysInfoExtended: %s", guid_hex)

    # Serial number
    if not info.serial:
        m = _re.search(
            r"<key>SerialNumber</key>\s*<string>([^<]+)</string>",
            content,
        )
        if m:
            info.serial = m.group(1).strip()
            info._field_sources["serial"] = "sysinfo_extended"
            logger.info("enrich: serial from SysInfoExtended: %s", info.serial)

    # Model number (ProductType or ModelNumStr)
    if not info.model_number:
        m = _re.search(
            r"<key>ModelNumStr</key>\s*<string>([^<]+)</string>",
            content,
        )
        if m:
            try:
                from ipod_models import extract_model_number
                mn = extract_model_number(m.group(1).strip())
                if mn:
                    info.model_number = mn
                    info._field_sources["model_number"] = "sysinfo_extended"
                    logger.info("enrich: model from SysInfoExtended: %s", mn)
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
            info._field_sources["board"] = "sysinfo_extended"
            logger.info("enrich: board from SysInfoExtended: %s", info.board)

    # ── Artwork formats from SysInfoExtended (Nano 6G/7G) ─────────
    # Newer iPods (especially Nano 6G+) define their artwork formats in the
    # SysInfoExtended XML plist rather than relying on hardcoded tables.
    # libgpod's itdb_sysinfo.c parses these for cover-art format discovery.
    if not info.artwork_formats:
        try:
            artwork_fmts = _parse_sysinfo_artwork_formats(content)
            if artwork_fmts:
                info.artwork_formats = artwork_fmts
                info._field_sources["artwork_formats"] = "sysinfo_extended"
                logger.info("enrich: artwork formats from SysInfoExtended: %s",
                            list(artwork_fmts.keys()))
        except Exception as exc:
            logger.debug("enrich: SysInfoExtended artwork parse failed: %s", exc)


def _parse_sysinfo_artwork_formats(content: str) -> dict[int, tuple[int, int]]:
    """Extract artwork format definitions from SysInfoExtended XML plist.

    Newer iPods (Nano 6G/7G) embed their artwork capabilities in
    SysInfoExtended under keys like ``AlbumArt`` or ``ArtworkFormats``.
    Each entry is a dict with at least ``FormatId``, ``RenderWidth``,
    ``RenderHeight``.  libgpod calls ``itdb_sysinfo_properties_get_cover_art_formats``
    to parse these.

    Returns:
        ``{correlation_id: (width, height)}`` — same format as
        ``ithmb_formats_for_device()``.  Empty dict if nothing found.
    """
    import plistlib

    # SysInfoExtended is an XML plist.  Parse it properly.
    try:
        plist = plistlib.loads(content.encode("utf-8"))
    except Exception:
        return {}

    if not isinstance(plist, dict):
        return {}

    # Look for artwork format arrays under various known keys.
    # libgpod checks: AlbumArt, ArtworkFormats, CoverArt
    artwork_entries: list[dict] = []
    for key in ("AlbumArt", "AlbumArt2", "ArtworkFormats", "CoverArt",
                "ArtworkCoverArtFormats"):
        val = plist.get(key)
        if isinstance(val, list):
            artwork_entries.extend(val)

    if not artwork_entries:
        return {}

    formats: dict[int, tuple[int, int]] = {}
    for entry in artwork_entries:
        if not isinstance(entry, dict):
            continue

        # FormatId / CorrelationID
        fmt_id = entry.get("FormatId") or entry.get("CorrelationID")
        if fmt_id is None:
            continue
        fmt_id = int(fmt_id)

        # RenderWidth / Width, RenderHeight / Height
        w = entry.get("RenderWidth") or entry.get("Width")
        h = entry.get("RenderHeight") or entry.get("Height")
        if w is None or h is None:
            continue
        w, h = int(w), int(h)

        if fmt_id > 0 and w > 0 and h > 0:
            formats[fmt_id] = (w, h)

    return formats


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

    _hw_method = ""
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
            if hw:
                _hw_method = "ioctl"

            if not hw:
                # Fallback: WMI (slower, subprocess)
                try:
                    from GUI.device_scanner import _identify_via_usb_for_drive
                    hw = _identify_via_usb_for_drive(drive_letter)
                    if hw:
                        _hw_method = "wmi"
                except ImportError:
                    hw = None

            if not hw:
                return

        elif _sys.platform == "darwin":
            from GUI.device_scanner import _probe_hardware_macos
            hw = _probe_hardware_macos(info.path)
            _hw_method = "ioreg"
            if not hw:
                return

        else:  # Linux
            from GUI.device_scanner import _probe_hardware_linux
            hw = _probe_hardware_linux(info.path)
            _hw_method = "sysfs"
            if not hw:
                return

    except (ImportError, Exception) as exc:
        logger.debug("enrich: hardware probe failed: %s", exc)
        return

    # On Windows, FW GUID comes from the device tree walk specifically
    _fw_source = "device_tree" if _hw_method in ("ioctl", "wmi") else _hw_method

    # Merge hardware results into DeviceInfo (never overwrite existing)
    if not info.firewire_guid and hw.get("firewire_guid"):
        guid_hex = hw["firewire_guid"]
        if guid_hex != "0" * len(guid_hex):
            info.firewire_guid = guid_hex
            info._field_sources["firewire_guid"] = _fw_source
            logger.info("enrich: FW GUID from hardware: %s", guid_hex)

    if not info.serial and hw.get("serial"):
        info.serial = hw["serial"]
        info._field_sources["serial"] = _hw_method
        logger.info("enrich: serial from hardware: %s", info.serial)

    if not info.firmware and hw.get("firmware"):
        info.firmware = hw["firmware"]
        info._field_sources["firmware"] = _hw_method
        logger.info("enrich: firmware from hardware: %s", info.firmware)

    if not info.usb_pid and hw.get("usb_pid"):
        info.usb_pid = hw["usb_pid"]
        logger.info("enrich: USB PID from hardware: 0x%04X", info.usb_pid)

    if not info.model_number and hw.get("model_number"):
        info.model_number = hw["model_number"]
        logger.info("enrich: model_number from hardware: %s", info.model_number)

    if info.identification_method == "unknown":
        info.identification_method = "hardware"


def _enrich_from_usb_vpd(info: DeviceInfo) -> None:
    """Query iPod firmware via USB SCSI VPD pages for device identification.

    Delegates to :func:`ipod_usb_query.identify_via_vpd` which handles all
    platforms (IOKit on macOS, pyusb on Linux/Windows), resolves the exact
    model via serial-last-3 lookup, and handles post-query remount on
    Linux/macOS.

    SysInfo writing is NOT done here — the authority module handles it
    after all identification is complete.
    """
    try:
        from ipod_usb_query import identify_via_vpd
    except ImportError:
        logger.debug("enrich: ipod_usb_query not available")
        return

    result = identify_via_vpd(
        mount_path=info.path,
        usb_pid=info.usb_pid or 0,
        firewire_guid=info.firewire_guid or "",
        write_sysinfo_to_device=False,
    )
    if result is None:
        return

    # Apply VPD-derived fields to DeviceInfo
    if result["serial"]:
        info.serial = result["serial"]
        info._field_sources["serial"] = "vpd"
    if not info.firewire_guid and result["firewire_guid"]:
        info.firewire_guid = result["firewire_guid"]
        info._field_sources["firewire_guid"] = "vpd"
    if result["firmware"]:
        info.firmware = result["firmware"]
        info._field_sources["firmware"] = "vpd"
    if result["model_number"]:
        info.model_number = result["model_number"]
        info.model_family = result["model_family"]
        info.generation = result["generation"]
        info._field_sources["model_number"] = "vpd"
        if not info.capacity:
            info.capacity = result["capacity"]
        if not info.color:
            info.color = result["color"]

    # Extract board from VPD raw data (previously obtained via SysInfo re-read)
    vpd_raw = result.get("vpd_info") or {}
    if not info.board and vpd_raw.get("BoardHwName"):
        info.board = vpd_raw["BoardHwName"]
        info._field_sources["board"] = "vpd"
        logger.info("enrich: board from VPD: %s", info.board)

    # Update mount path if pyusb caused a remount to a different location
    if result["mount_path"] and result["mount_path"] != info.path:
        logger.info("enrich: mount path changed %s → %s",
                    info.path, result["mount_path"])
        info.path = result["mount_path"]

    if info.serial:
        info.identification_method = "usb_vpd"


def _enrich_from_serial_lookup(info: DeviceInfo) -> None:
    """Look up exact model from serial number's last 3 characters.

    This is very high confidence — the last 3 chars encode the exact model
    including capacity, color, and hardware revision.  Always fills gaps
    even when ``model_number`` is already known, because serial-last-3
    provides exact variant resolution that generic model lookup may miss.

    The derived fields inherit the serial number's authority source, since
    the lookup is a deterministic mapping — the trust of the output equals
    the trust of the input.
    """
    if not info.serial or len(info.serial) < 3:
        return

    try:
        from ipod_models import lookup_by_serial
    except ImportError:
        return

    result = lookup_by_serial(info.serial)
    if not result:
        return

    model_num, model_info = result

    # Inherit the serial's source — the derived values are exactly as
    # trustworthy as the serial they came from.
    _src = info._field_sources.get("serial", "serial_lookup")

    if not info.model_number:
        info.model_number = model_num
        info._field_sources.setdefault("model_number", _src)

    # Serial lookup is authoritative for family/gen — always set these
    # (unless a higher-authority source already has them).
    from sysinfo_authority import SOURCE_RANK, _WORST_RANK
    _serial_rank = SOURCE_RANK.get(_src, _WORST_RANK)

    _cur_family_rank = SOURCE_RANK.get(
        info._field_sources.get("model_family", "unknown"), _WORST_RANK,
    )
    if _serial_rank <= _cur_family_rank:
        info.model_family = model_info[0]
        info._field_sources["model_family"] = _src

    _cur_gen_rank = SOURCE_RANK.get(
        info._field_sources.get("generation", "unknown"), _WORST_RANK,
    )
    if _serial_rank <= _cur_gen_rank:
        info.generation = model_info[1]
        info._field_sources["generation"] = _src

    if not info.capacity:
        info.capacity = model_info[2]
        info._field_sources.setdefault("capacity", _src)

    if not info.color:
        info.color = model_info[3]
        info._field_sources.setdefault("color", _src)

    if info.identification_method in ("unknown", "hardware"):
        info.identification_method = "serial"
    logger.debug("enrich: serial-last-3 '%s' → %s %s %s %s (source: %s)",
                 info.serial[-3:], model_info[0], model_info[1],
                 model_info[2], model_info[3], _src)


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
            except OSError:
                continue

            try:
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
                                    return
                            else:
                                # No serial — remember first valid GUID
                                if best_guid is None:
                                    best_guid = guid_upper
            finally:
                winreg.CloseKey(device_key)
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
    """Read the iTunesDB/iTunesCDB mhbd header for hashing_scheme and db_id."""
    import struct

    itdb_path = resolve_itdb_path(info.path)
    if not itdb_path:
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
      1. Family + generation → canonical lookup (covers ALL color variants)
      2. HashInfo file existence → HASH72
      3. iTunesDB hashing_scheme field
      4. Firmware version hints
      5. FirewireGuid presence hints at post-2007 device
      6. Default to NONE (safe for pre-2007 iPods)
    """
    try:
        from ipod_models import (
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
    """Scan ArtworkDB binary for mhif format IDs as a last resort.

    Only reads the file header and dataset/format-list chunks (typically
    < 8 KB) rather than the entire ArtworkDB, which can be many MB.
    """
    artdb_path = os.path.join(info.path, "iPod_Control", "Artwork", "ArtworkDB")
    if not os.path.exists(artdb_path):
        return

    # The format-ID entries live in the first dataset (mhsd type 3).
    # Cap the read at 64 KB — far more than enough for the header region,
    # and safe even over a slow USB connection.
    _MAX_HEADER_READ = 65536

    try:
        from ArtworkDB_Writer.rgb565 import _extract_format_ids, ALL_KNOWN_FORMATS
        with open(artdb_path, "rb") as f:
            data = f.read(_MAX_HEADER_READ)

        if len(data) < 24 or data[:4] != b"mhfd":
            return

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
