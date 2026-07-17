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

    from iopenpod.device import DeviceInfo, set_current_device, enrich
    info = DeviceInfo(path="/media/ipod")
    enrich(info)            # reads SysInfo once, computes everything
    set_current_device(info)
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from dataclasses import dataclass, field, replace
from typing import Any

from .diagnostic_log import (
    CAPABILITY_FIELDS,
    IDENTITY_FIELDS,
    SOURCE_FIELDS,
    format_fields,
    format_sources,
)

logger = logging.getLogger(__name__)


_LIVE_VALIDATION_LOCK = threading.Lock()
_LIVE_VALIDATION_INFLIGHT: set[str] = set()


def _source_rank(source: str) -> int:
    try:
        from .authority import _WORST_RANK, SOURCE_RANK

        return SOURCE_RANK.get(source, _WORST_RANK)
    except Exception:
        return 999


def _values_match(field: str, left, right) -> bool:
    if field == "firewire_guid":
        try:
            from .sysinfo import normalize_guid

            return normalize_guid(left) == normalize_guid(right)
        except Exception:
            pass
    return str(left or "").strip() == str(right or "").strip()


def _set_field_from_source(
    info: DeviceInfo,
    field: str,
    value,
    source: str,
    *,
    label: str = "live probe",
) -> None:
    """Set or provenance-upgrade a DeviceInfo field from a ranked source."""
    if value in (None, "", b""):
        return

    current = getattr(info, field, None)
    current_source = info._field_sources.get(field, "unknown")
    new_rank = _source_rank(source)
    current_rank = _source_rank(current_source)

    if not current:
        setattr(info, field, value)
        info._field_sources[field] = source
        logger.debug("enrich: %s from %s: %s", field, label, value)
        return

    if _values_match(field, current, value):
        if new_rank <= current_rank:
            info._field_sources[field] = source
        return

    if new_rank <= current_rank:
        logger.warning(
            "enrich: %s from %s overrides %r from %s with %r",
            field,
            label,
            current,
            current_source,
            value,
        )
        setattr(info, field, value)
        info._field_sources[field] = source


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
    family_id: int | str = 0
    updater_family_id: int | str = 0
    product_type: str = ""
    usb_pid: int = 0
    usb_vid: int = 0
    usb_serial: str = ""              # Usually the FireWire GUID on iPods
    usbstor_instance_id: str = ""
    usb_parent_instance_id: str = ""
    usb_grandparent_instance_id: str = ""
    scsi_vendor: str = ""
    scsi_product: str = ""
    scsi_revision: str = ""
    connected_bus: str = ""
    reported_volume_format: str = ""  # SysInfoExtended hint, not an OS probe
    filesystem_type: str = ""         # Actual mounted filesystem (vfat, hfsplus, ...)
    volume_identity_key: str = ""      # Host-observed identity captured during scan

    # ── Device capabilities from SysInfoExtended / VPD ────────────────
    db_version: int = 0
    shadow_db_version: int = 0
    uses_sqlite_db: bool = False
    supports_sparse_artwork: bool = False
    max_tracks: int = 0
    max_file_size_gb: int | float = 0
    max_transfer_speed: int = 0
    podcasts_supported: bool = False
    voice_memos_supported: bool = False
    audio_codecs: dict[str, Any] = field(default_factory=dict)
    power_information: dict[str, Any] = field(default_factory=dict)
    apple_drm_version: dict[str, Any] = field(default_factory=dict)

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
    photo_formats: dict[int, tuple[int, int]] = field(default_factory=dict)
    chapter_image_formats: dict[int, tuple[int, int]] = field(default_factory=dict)

    # ── Raw SysInfo cache (so nobody ever has to re-read the file) ────
    sysinfo: dict[str, str] = field(default_factory=dict)
    raw_identity_evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    identity_conflicts: list[dict[str, Any]] = field(default_factory=list)

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
    def volume_format(self) -> str:
        """Legacy alias for :attr:`reported_volume_format`."""
        return self.reported_volume_format

    @volume_format.setter
    def volume_format(self, value: str) -> None:
        self.reported_volume_format = str(value or "")

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
        generation = self.generation.lower()
        full_size_display_generations = {
            "4th gen (photo)",
            "4th gen (color)",
            "5th gen",
            "5.5th gen",
        }
        if "classic" in family or (
            family == "ipod" and generation in full_size_display_generations
        ):
            return "📱"
        elif "nano" in family:
            return "🎵"
        elif "shuffle" in family:
            return "🔀"
        elif "mini" in family:
            return "🎶"
        return "🎵"

    @property
    def capabilities(self):
        """Return the DeviceCapabilities for this device, or defaults.

        Uses family-level fallback when generation is unknown but all
        generations of the family share identical capabilities.
        """
        from .capabilities import DeviceCapabilities, capabilities_for_family_gen
        caps = None
        if self.model_family:
            caps = capabilities_for_family_gen(
                self.model_family,
                self.generation or "",
                capacity=self.capacity,
                model_number=self.model_number,
            )
        if caps is None:
            caps = DeviceCapabilities()

        overrides: dict[str, Any] = {}
        if self.db_version:
            overrides["db_version"] = int(self.db_version)
        if self.shadow_db_version:
            overrides["shadow_db_version"] = int(self.shadow_db_version)
        if "uses_sqlite_db" in self._field_sources:
            overrides["uses_sqlite_db"] = bool(self.uses_sqlite_db)
        if "supports_sparse_artwork" in self._field_sources:
            overrides["supports_sparse_artwork"] = bool(self.supports_sparse_artwork)
        if "podcasts_supported" in self._field_sources:
            overrides["supports_podcast"] = bool(self.podcasts_supported)
        return replace(caps, **overrides) if overrides else caps


# ──────────────────────────────────────────────────────────────────────
# Utility functions (used by multiple modules)
# ──────────────────────────────────────────────────────────────────────

def _capability_itdb_filename(ipod_path: str) -> str | None:
    """Return the database filename required by the matched device, if known."""
    dev = get_current_device_for_path(ipod_path)
    if not dev or not dev.model_family:
        return None

    from .capabilities import capabilities_for_family_gen

    caps = capabilities_for_family_gen(dev.model_family, dev.generation or "")
    if caps is None:
        return None
    return "iTunesCDB" if caps.supports_compressed_db else "iTunesDB"


def resolve_itdb_path(ipod_path: str) -> str | None:
    """Return the path to the iTunesDB (or iTunesCDB) on the iPod.

    Newer iPods (Nano 5G+) use ``iTunesCDB`` instead of ``iTunesDB``.
    iTunesCDB is **zlib-compressed**: the mhbd header is stored
    uncompressed, followed by a zlib stream containing all mhsd children.
    The parser transparently decompresses it; the writer compresses when
    ``DeviceCapabilities.supports_compressed_db`` is True.  The firmware
    on those devices reads ``iTunesCDB`` and ignores ``iTunesDB``.

    When the mounted path matches the selected device and its capabilities are
    known, only the database filename that firmware uses is considered.  This
    prevents a stale, non-empty alternate database from being loaded while the
    writer and generation guard operate on the real database.

    Without matched device capabilities, check order is (ignoring zero-byte
    stale-filename markers while a non-empty alternate exists):

    1. ``iTunesCDB`` — used by devices with ``supports_compressed_db``
    2. ``iTunesDB``  — used by all other devices

    Returns the path to whichever file exists, or ``None`` if neither is
    present.
    """
    itunes_dir = os.path.join(ipod_path, "iPod_Control", "iTunes")
    cdb = os.path.join(itunes_dir, "iTunesCDB")
    db = os.path.join(itunes_dir, "iTunesDB")
    required_filename = _capability_itdb_filename(ipod_path)
    if required_filename is not None:
        required_path = os.path.join(itunes_dir, required_filename)
        alternate_path = cdb if required_filename == "iTunesDB" else db
        for candidate in (required_path, alternate_path):
            try:
                if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                    if candidate == alternate_path:
                        logger.warning(
                            "The identified iPod has only the alternate database "
                            "%s; it will be used as the recovery source while the "
                            "next guarded write restores %s",
                            os.path.basename(alternate_path),
                            required_filename,
                        )
                    return candidate
            except OSError as exc:
                from .write_guard import DeviceWriteSafetyError

                raise DeviceWriteSafetyError(
                    "Could not safely inspect the iPod database filenames: "
                    f"{exc}"
                ) from exc
        for candidate in (required_path, alternate_path):
            try:
                if os.path.exists(candidate):
                    return candidate
            except OSError as exc:
                from .write_guard import DeviceWriteSafetyError

                raise DeviceWriteSafetyError(
                    "Could not safely inspect the iPod database filenames: "
                    f"{exc}"
                ) from exc
        return None

    # The writer deliberately leaves the obsolete alternate filename as a
    # zero-byte marker for firmware compatibility. Never mistake that marker
    # for the live database when the other file contains a committed DB.
    for candidate in (cdb, db):
        try:
            if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
                return candidate
        except OSError:
            continue
    for candidate in (cdb, db):
        if os.path.exists(candidate):
            return candidate
    return None


def itdb_write_filename(ipod_path: str) -> str:
    """Return the filename to use when **writing** the iTunesDB.

    Uses the device capabilities (``supports_compressed_db``) when
    available.  Falls back to whichever file already exists on disk, and
    finally defaults to ``"iTunesDB"``.
    """
    # 1. Ask the matched device store (capabilities handles family fallback).
    required_filename = _capability_itdb_filename(ipod_path)
    if required_filename is not None:
        return required_filename

    # 2. Without capabilities, follow the non-empty committed database. The
    # obsolete alternate filename may intentionally remain as a zero-byte
    # firmware marker and must not influence the next write target.
    existing = resolve_itdb_path(ipod_path)
    if existing:
        try:
            if os.path.getsize(existing) > 0:
                return os.path.basename(existing)
        except OSError:
            pass

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

    try:
        with open(sysinfo_path, errors="ignore") as f:
            content = f.read()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"SysInfo not found at {sysinfo_path}") from exc

    from .sysinfo import parse_sysinfo_text
    return parse_sysinfo_text(content)


def _estimate_capacity_from_disk_size(disk_gb: float) -> str:
    """Map raw disk size (GB) to a marketed capacity string.

    iPod capacities are advertised in base-10, but actual formatted space
    is lower due to filesystem overhead and base-2/base-10 conversion.
    This uses generous thresholds to handle both.
    """
    thresholds = [
        (140, "160GB"), (100, "120GB"), (65, "80GB"),
        (50, "60GB"), (35, "40GB"), (25, "30GB"),
        (17, "20GB"), (14, "16GB"), (12, "15GB"),
        (8.5, "10GB"), (6.5, "8GB"), (5.2, "6GB"),
        (4.2, "5GB"), (3, "4GB"), (1.5, "2GB"),
        (0.7, "1GB"), (0.3, "512MB"),
    ]
    for threshold, label in thresholds:
        if disk_gb >= threshold:
            return label
    return ""


def _normalise_identity_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _normalise_identity_capacity(value: str | None) -> str:
    return str(value or "").replace(" ", "").strip().casefold()


def _matching_model_variants(
    family: str,
    generation: str,
    *,
    capacity: str = "",
    color: str = "",
) -> list[tuple[str, str, str, str]]:
    """Return known model-table tuples matching the supplied identity pieces."""
    if not family or not generation:
        return []

    family_norm = _normalise_identity_text(family)
    generation_norm = _normalise_identity_text(generation)
    capacity_norm = _normalise_identity_capacity(capacity)
    color_norm = _normalise_identity_text(color)

    from .models import IPOD_MODELS

    matches: list[tuple[str, str, str, str]] = []
    for model_info in IPOD_MODELS.values():
        model_family, model_generation, model_capacity, model_color = model_info
        if _normalise_identity_text(model_family) != family_norm:
            continue
        if _normalise_identity_text(model_generation) != generation_norm:
            continue
        if (
            capacity_norm
            and _normalise_identity_capacity(model_capacity) != capacity_norm
        ):
            continue
        if color_norm and _normalise_identity_text(model_color) != color_norm:
            continue
        matches.append(model_info)
    return matches


def _clear_variant_field(info: DeviceInfo, field: str, reason: str) -> None:
    old_value = getattr(info, field, "")
    if not old_value:
        return
    logger.warning(
        "enrich: dropping inconsistent %s=%r for %s %s (%s)",
        field,
        old_value,
        info.model_family or "unknown family",
        info.generation or "unknown generation",
        reason,
    )
    setattr(info, field, "")
    info._field_sources.pop(field, None)


def _restore_usb_pid_identity_if_needed(info: DeviceInfo) -> None:
    """Use the live USB PID as an anchor when only cached identity is present."""
    if not info.usb_pid:
        return

    try:
        from .models import USB_PID_TO_MODEL
    except ImportError:
        return

    pid_info = USB_PID_TO_MODEL.get(info.usb_pid)
    if not pid_info:
        return

    pid_family, pid_generation = pid_info
    if info.model_number:
        model_info = None
        usb_pid_identity_conflicts = None
        try:
            from .lookup import get_model_info
            from .lookup import usb_pid_identity_conflicts as _usb_pid_identity_conflicts
            model_info = get_model_info(info.model_number)
            usb_pid_identity_conflicts = _usb_pid_identity_conflicts
        except Exception:
            model_info = None
        if model_info and usb_pid_identity_conflicts and not usb_pid_identity_conflicts(
            model_info[0],
            model_info[1],
            pid_family,
            pid_generation,
        ):
            return
        if model_info:
            logger.warning(
                "enrich: clearing stale model_number %s (%s %s) because "
                "live USB PID 0x%04X identifies %s %s",
                info.model_number,
                model_info[0],
                model_info[1],
                info.usb_pid,
                pid_family,
                pid_generation,
            )
            info.model_number = ""
            info._field_sources.pop("model_number", None)

    if pid_family and info.model_family:
        if (
            _normalise_identity_text(info.model_family)
            != _normalise_identity_text(pid_family)
        ):
            logger.warning(
                "enrich: cached family %r conflicts with live USB PID "
                "0x%04X family %r; using live USB identity",
                info.model_family,
                info.usb_pid,
                pid_family,
            )
            info.model_family = pid_family
            info._field_sources["model_family"] = "usb_pid"

    if pid_generation and info.generation:
        if (
            _normalise_identity_text(info.generation)
            != _normalise_identity_text(pid_generation)
        ):
            source = info._field_sources.get("generation", "unknown")
            if source in {
                "usb_pid",
                "sysinfo",
                "sysinfo_extended",
                "hashing",
                "unknown",
            }:
                logger.warning(
                    "enrich: cached generation %r conflicts with live USB "
                    "PID 0x%04X generation %r; using live USB identity",
                    info.generation,
                    info.usb_pid,
                    pid_generation,
                )
                info.generation = pid_generation
                info._field_sources["generation"] = "usb_pid"


def _sanitize_variant_fields(info: DeviceInfo) -> None:
    """Drop impossible capacity/color pairings before they reach the UI/SysInfo.

    Family/generation often come from live USB PID data, while capacity/color can
    come from cached SysInfo fields written by a previous run.  If those pieces
    do not exist together in the model table, prefer a partial, honest identity
    over a stitched-together impossible one.
    """
    if not info.model_family or not info.generation:
        return
    if not info.capacity and not info.color:
        return

    _restore_usb_pid_identity_if_needed(info)

    base_matches = _matching_model_variants(info.model_family, info.generation)
    if not base_matches:
        return

    if _matching_model_variants(
        info.model_family,
        info.generation,
        capacity=info.capacity,
        color=info.color,
    ):
        return

    capacity_valid = (
        not info.capacity
        or bool(_matching_model_variants(
            info.model_family,
            info.generation,
            capacity=info.capacity,
        ))
    )
    color_valid = (
        not info.color
        or bool(_matching_model_variants(
            info.model_family,
            info.generation,
            color=info.color,
        ))
    )

    if not capacity_valid:
        _clear_variant_field(info, "capacity", "no matching model capacity")
    if not color_valid:
        _clear_variant_field(info, "color", "no matching model color")

    if capacity_valid and color_valid and info.capacity and info.color:
        try:
            from .authority import _WORST_RANK, SOURCE_RANK
            cap_rank = SOURCE_RANK.get(
                info._field_sources.get("capacity", "unknown"),
                _WORST_RANK,
            )
            color_rank = SOURCE_RANK.get(
                info._field_sources.get("color", "unknown"),
                _WORST_RANK,
            )
        except Exception:
            cap_rank = color_rank = 0

        if cap_rank < color_rank:
            _clear_variant_field(info, "color", "capacity/color combo is invalid")
        elif color_rank < cap_rank:
            _clear_variant_field(info, "capacity", "capacity/color combo is invalid")
        else:
            _clear_variant_field(info, "capacity", "capacity/color combo is invalid")
            _clear_variant_field(info, "color", "capacity/color combo is invalid")


def _infer_color_from_variant_table(info: DeviceInfo) -> None:
    """Fill color when all known variants for the identity share one color."""
    if info.color or not info.model_family or not info.generation:
        return

    matches = _matching_model_variants(
        info.model_family,
        info.generation,
        capacity=info.capacity,
    )
    colors = sorted({variant[3] for variant in matches if variant[3]})
    if len(colors) != 1:
        return

    info.color = colors[0]
    info._field_sources["color"] = "model_table"
    logger.debug(
        "enrich: inferred color %s from %s %s%s",
        info.color,
        info.model_family,
        info.generation,
        f" {info.capacity}" if info.capacity else "",
    )


def _canonicalize_device_identity(info: DeviceInfo) -> None:
    """Repair stale non-community model names before they reach callers."""
    try:
        from .lookup import get_model_info
        from .models import canonicalize_model_identity
    except ImportError:
        return

    model_info = get_model_info(info.model_number) if info.model_number else None
    if model_info:
        updates = {
            "model_family": model_info[0],
            "generation": model_info[1],
            "capacity": model_info[2],
            "color": model_info[3],
        }
        source = info._field_sources.get("model_number", "model_table")
    else:
        family, generation, color = canonicalize_model_identity(
            info.model_family,
            info.generation,
            capacity=info.capacity,
            color=info.color,
        )
        updates = {
            "model_family": family,
            "generation": generation,
            "color": color,
        }
        source = "model_table"

    for field_name, value in updates.items():
        if not value:
            continue
        current = getattr(info, field_name, "")
        if _values_match(field_name, current, value):
            continue
        logger.debug(
            "enrich: canonicalized %s from %r to %r",
            field_name,
            current,
            value,
        )
        setattr(info, field_name, value)
        info._field_sources[field_name] = source


# ──────────────────────────────────────────────────────────────────────
# Thread-safe singleton store
# ──────────────────────────────────────────────────────────────────────


class UnidentifiedDeviceError(ValueError):
    """Raised when code tries to activate an iPod without an exact model."""


def has_exact_model_number(info: object | None) -> bool:
    """Return whether *info* has the exact model number required for use."""

    return bool(str(getattr(info, "model_number", "") or "").strip())


def require_exact_model_number(info: object) -> None:
    """Reject an iPod that was discovered without an exact model number."""

    if has_exact_model_number(info):
        return
    path = str(getattr(info, "path", "") or "unknown mount")
    raise UnidentifiedDeviceError(
        f"Refusing to activate unidentified iPod at {path}: "
        "no exact model number was resolved"
    )


class _Store:
    """Holds the *active* DeviceInfo for the running session.

    Thread safety: singleton creation is protected by a lock.  The ``current``
    property is set only from the main thread (via ``set_current_device``),
    so no additional synchronisation is needed for reads from worker threads
    that happen *after* the device is stored.
    """

    _instance: _Store | None = None
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


def get_current_device_for_path(ipod_path: str | os.PathLike[str]) -> DeviceInfo | None:
    """Return the active device only when it describes *ipod_path* exactly."""
    device = get_current_device()
    if device is None or not str(device.path or "").strip():
        return None
    try:
        selected = os.path.normcase(os.path.realpath(os.fspath(ipod_path)))
        identified = os.path.normcase(os.path.realpath(device.path))
    except (OSError, TypeError, ValueError):
        return None
    return device if selected == identified else None


def set_current_device(info: DeviceInfo | None) -> None:
    """Store *info* as the active device (called once during selection)."""
    if info is not None:
        require_exact_model_number(info)
    _Store._get().current = info
    if info is not None:
        logger.info(
            "Device stored: %s %s (%s) serial=…%s fwguid=%s "
            "checksum=%s method=%s capacity=%s formats=%s",
            info.model_family, info.generation, info.model_number,
            info.serial[-4:] if info.serial else "none",
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
    Returns a :class:`iopenpod.device.ChecksumType` enum value.
    """
    from .capabilities import checksum_type_for_family_gen
    from .checksum import ChecksumType
    from .lookup import extract_model_number, get_model_info

    # Fast path: centralised store
    device = get_current_device_for_path(ipod_path)
    if device is not None and device.checksum_type != 99:
        return ChecksumType(device.checksum_type)

    try:
        from .virtual import has_virtual_ipod_info, load_virtual_ipod_info

        if has_virtual_ipod_info(ipod_path):
            virtual = load_virtual_ipod_info(ipod_path)
            if virtual.checksum_type != 99:
                return ChecksumType(virtual.checksum_type)
    except Exception:
        pass

    # Fallback: probe from scratch
    try:
        sysinfo = read_sysinfo(ipod_path)
    except FileNotFoundError:
        return ChecksumType.UNKNOWN

    model_str = sysinfo.get("ModelNumStr", "")
    model_num = extract_model_number(model_str)

    if model_num:
        mi = get_model_info(model_num)
        if mi:
            ct = checksum_type_for_family_gen(mi[0], mi[1])
            if ct is not None:
                return ct

    hi_path = os.path.join(ipod_path, "iPod_Control", "Device", "HashInfo")
    try:
        os.stat(hi_path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        from .write_guard import DeviceWriteSafetyError

        raise DeviceWriteSafetyError(
            f"Could not inspect the iPod HashInfo checksum material: {exc}"
        ) from exc
    else:
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

    # An identified legacy model above can positively select NONE. Empty or
    # unidentifiable physical metadata cannot: guessing "no checksum" would
    # produce a database that modern firmware rejects.
    return ChecksumType.UNKNOWN


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
    device = get_current_device_for_path(ipod_path)
    if device is not None:
        fwid = device.firewire_id_bytes
        if fwid:
            return fwid

    # Source 1b: virtual iPod metadata
    try:
        from .virtual import has_virtual_ipod_info, load_virtual_ipod_info

        if has_virtual_ipod_info(ipod_path):
            virtual = load_virtual_ipod_info(ipod_path)
            fwid = virtual.firewire_id_bytes
            if fwid:
                return fwid
    except Exception:
        pass

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
            with open(sysinfo_ex_path, errors="ignore") as f:
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
    logger.debug(
        "Device enrich start: mount=%s identity=[%s] sources=[%s]",
        info.path or "unknown",
        format_fields(info.__dict__, IDENTITY_FIELDS),
        format_sources(info._field_sources, SOURCE_FIELDS),
    )

    # ── 0. Load SysInfo dict (always — needed for reference) ──────────
    if info.path and not info.sysinfo:
        try:
            info.sysinfo = read_sysinfo(info.path)
            logger.debug("enrich: SysInfo loaded (%d keys)", len(info.sysinfo))
        except FileNotFoundError:
            logger.debug("enrich: no SysInfo at %s", info.path)
        except Exception as exc:
            logger.debug("enrich: SysInfo read failed: %s", exc)

    # ── 1. Authority coverage check ───────────────────────────────────
    _authority_is_high = False
    _run_background_live_validation = False
    if info.path:
        try:
            from .authority import check_authority_coverage
            _all_tracked, _auth_sources = check_authority_coverage(info.path)
            if _all_tracked:
                _authority_is_high = True
                # Pre-populate _field_sources from authority so the rest
                # of the pipeline sees the correct provenance.
                for _field, _source in _auth_sources.items():
                    if _field not in info._field_sources:
                        info._field_sources[_field] = _source
                logger.debug(
                    "enrich: authority covers all core fields — "
                    "trusting SysInfo, skipping hardware/VPD probes; "
                    "sources=[%s]",
                    format_sources(_auth_sources, SOURCE_FIELDS),
                )
            elif _auth_sources:
                logger.debug(
                    "enrich: authority has untracked core fields — "
                    "probing highest to lowest authority; sources=[%s]",
                    format_sources(_auth_sources, SOURCE_FIELDS),
                )
            else:
                logger.debug(
                    "enrich: no authority coverage — probing highest to "
                    "lowest authority",
                )
        except Exception as exc:
            logger.debug("enrich: authority check failed: %s", exc)

    if _authority_is_high:
        # ── HIGH authority path: SysInfo is trustworthy ───────────────
        _populate_fields_from_sysinfo(info)
        if info.path:
            _enrich_from_sysinfo_extended(info)
            _run_background_live_validation = True
    else:
        # ── LOW authority path: probe highest → lowest ────────────────
        #   Each source fills only gaps (if not info.X guards), so the
        #   first source to provide a value wins — which is the highest
        #   authority source.

        # 2a. Hardware probe (IOCTL + device tree + USB PID)
        _enrich_from_hardware_probe(info)

        # 2b. Live VPD query (highest authority on supported non-Windows
        #   platforms — Apple serial + model). Runs even if SysInfo exists,
        #   because low-authority SysInfo values should be upgraded with
        #   live data when possible.
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
            from .lookup import get_model_info
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
                logger.debug("enrich: model DB -> %s %s %s %s",
                             mi[0], mi[1], mi[2], mi[3])
        except ImportError:
            pass

    # ── 3b. Serial-suffix model lookup ─────────────────────────────────
    #   Very reliable — a published 3- or 4-character suffix encodes the
    #   exact model (incl. capacity and color). Run whenever the serial is
    #   available: the lookup is cheap and _enrich_from_serial_lookup
    #   uses authority-rank comparison, so it only overwrites fields
    #   whose current source is less reliable than the serial.  This
    #   catches devices where ModelNumStr is wrong (e.g. corrupted NVRAM
    #   or logic-board swap) even when all fields appear "populated".
    if info.serial:
        _enrich_from_serial_lookup(info)

    # ── 3c. USB PID-based family/generation (if nothing else worked) ──
    if info.usb_pid and info.model_family in ("iPod", ""):
        try:
            from .models import USB_PID_TO_MODEL
            pid_info = USB_PID_TO_MODEL.get(info.usb_pid)
            if pid_info:
                info.model_family = pid_info[0]
                info._field_sources.setdefault("model_family", "usb_pid")
                if not info.generation and pid_info[1]:
                    info.generation = pid_info[1]
                    info._field_sources.setdefault("generation", "usb_pid")
                logger.debug(
                    "enrich: USB PID 0x%04X -> %s %s",
                    info.usb_pid, pid_info[0], pid_info[1],
                )
        except ImportError:
            pass

    # ── 3d. Generation inference from family + capacity ───────────────
    #   When we know the family (e.g. from USB PID) but not the generation,
    #   use capacity to narrow it down.  For example, only iPod Classic
    #   6.5th Gen came in 120GB.  Disk-size-based capacity estimation
    #   (stage 8/9) hasn't run yet, so this only works if capacity was
    #   already resolved from serial, model number, or SysInfo.
    if info.model_family and not info.generation:
        _cap = info.capacity
        if not _cap and info.disk_size_gb > 0:
            _cap = _estimate_capacity_from_disk_size(info.disk_size_gb)
        if not _cap and info.path:
            try:
                import shutil
                total, _used, free = shutil.disk_usage(info.path)
                _disk_gb = round(total / 1e9, 1)
                _cap = _estimate_capacity_from_disk_size(_disk_gb)
            except Exception:
                pass
        if _cap:
            try:
                from .lookup import infer_generation
                _gen = infer_generation(info.model_family, _cap)
                if _gen:
                    info.generation = _gen
                    info._field_sources.setdefault("generation", "inferred")
                    logger.debug(
                        "enrich: inferred generation %s from %s + %s",
                        _gen, info.model_family, _cap,
                    )
            except ImportError:
                pass

    # Cached derived SysInfo fields are useful, but they must not be allowed
    # to combine with live USB identity into an impossible model label.
    _canonicalize_device_identity(info)
    _restore_usb_pid_identity_if_needed(info)
    _sanitize_variant_fields(info)

    # ── 4. iTunesDB header (hashing scheme, version) ─────────────────
    if info.path and info.hashing_scheme == -1:
        _enrich_from_itunesdb_header(info)

    # ── 5. Checksum type ──────────────────────────────────────────────
    if info.checksum_type == 99:
        _resolve_checksum_type(info)

    # ── 6. HashInfo (cryptographic material for HASH72 signing) ───────
    if not info.hash_info_iv and info.path:
        # Try HashInfo file first
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
                    logger.debug(
                        "enrich: cached HashInfo present (iv=%d, rndpart=%d)",
                        len(info.hash_info_iv), len(info.hash_info_rndpart),
                    )
        except Exception as exc:
            logger.debug("enrich: HashInfo read failed: %s", exc)

        # Fallback: extract IV/rndpart from existing iTunesCDB hash72 signature
        if not info.hash_info_iv:
            try:
                itdb_path = resolve_itdb_path(info.path)
                if itdb_path:
                    with open(itdb_path, "rb") as f:
                        itdb_data = f.read()
                    if (len(itdb_data) >= 0xA0
                            and itdb_data[:4] == b"mhbd"
                            and itdb_data[0x72:0x74] == b"\x01\x00"):
                        from iopenpod.itunesdb_writer.hash72 import extract_hash_info_to_dict
                        hd = extract_hash_info_to_dict(itdb_data)
                        if hd:
                            info.hash_info_iv = hd["iv"]
                            info.hash_info_rndpart = hd["rndpart"]
                            logger.debug(
                                "enrich: extracted HashInfo from existing %s",
                                os.path.basename(itdb_path),
                            )
            except Exception as exc:
                logger.debug("enrich: HashInfo extraction from CDB failed: %s", exc)

    # ── 7. Artwork formats ────────────────────────────────────────────
    # Try model-based lookup first (ithmb_formats_for_device handles
    # family-level fallback when generation is unknown).
    if not info.artwork_formats and info.model_family:
        try:
            from .artwork import ithmb_formats_for_device
            table = ithmb_formats_for_device(
                info.model_family,
                info.generation,
                capacity=info.capacity,
                model_number=info.model_number,
            )
            if table:
                info.artwork_formats = dict(table)
                logger.debug(
                    "enrich: artwork formats from model: %s",
                    list(info.artwork_formats.keys()),
                )
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
            logger.debug(
                "enrich: disk %.1f GB, free %.1f GB",
                info.disk_size_gb, info.free_space_gb,
            )
        except Exception as exc:
            logger.debug("enrich: disk_usage failed: %s", exc)

    # ── 9. Capacity from disk size (if still unknown) ────────────────
    if not info.capacity and info.disk_size_gb > 0:
        info.capacity = _estimate_capacity_from_disk_size(info.disk_size_gb)
        if info.capacity:
            info._field_sources["capacity"] = "disk_size"
            logger.debug("enrich: capacity from disk size: %s", info.capacity)

    _restore_usb_pid_identity_if_needed(info)
    _sanitize_variant_fields(info)
    _infer_color_from_variant_table(info)

    # ── 10. Backfill _field_sources for derived fields ───────────────────
    #   The scanner's _resolve_model may have set model_family/generation/
    #   capacity/color/usb_pid without tracking sources.  Before writing
    #   authority, ensure every populated field has a source entry.
    #   Derived fields inherit from the identification method that resolved
    #   them (model_number's source, or the identification_method itself).
    _derived_fields = (
        "model_family",
        "generation",
        "capacity",
        "color",
        "usb_pid",
    )
    _backfill_src = info._field_sources.get(
        "model_number",
        (
            info.identification_method
            if info.identification_method != "unknown"
            else "unknown"
        ),
    )
    for _df in _derived_fields:
        if getattr(info, _df, None) and _df not in info._field_sources:
            info._field_sources[_df] = _backfill_src

    # ── 11. SysInfo authority update ───────────────────────────────────────
    #   After all identification and enrichment is complete, reconcile our
    #   gathered data with the on-disk SysInfo file via the authority system.
    if info.path:
        try:
            from .authority import update_sysinfo as _update_sysinfo
            _update_sysinfo(info)
        except Exception as exc:
            logger.warning("enrich: SysInfo authority update failed: %s", exc)

    if _run_background_live_validation:
        _start_live_identity_validation(info)

    logger.debug(
        "DeviceInfo enriched: mount=%s identity=[%s] caps=[%s] checksum=%s "
        "hash_scheme=%s method=%s disk=%.1fGB free=%.1fGB sources=[%s]",
        info.path or "unknown",
        format_fields(info.__dict__, IDENTITY_FIELDS),
        format_fields(info.__dict__, CAPABILITY_FIELDS, include_false=True),
        info.checksum_type,
        info.hashing_scheme,
        info.identification_method,
        info.disk_size_gb,
        info.free_space_gb,
        format_sources(info._field_sources, SOURCE_FIELDS),
    )


def _live_validation_key(info: DeviceInfo) -> str:
    path = os.path.abspath(info.path) if info.path else ""
    return "|".join([
        path,
        info.firewire_guid.upper(),
        f"0x{info.usb_pid:04X}" if info.usb_pid else "",
    ])


def _cache_live_sysinfo_extended(
    ipod_path: str,
    vpd_raw: dict,
    source: str,
    expected_volume_identity_key: str = "",
) -> None:
    raw_xml = vpd_raw.get("vpd_raw_xml") if isinstance(vpd_raw, dict) else b""
    if not raw_xml:
        return

    live_sources = {
        "windows_scsi",
        "scsi_vpd",
        "iokit",
        "usb_vendor",
        "vpd",
    }
    if source not in live_sources:
        return

    try:
        from .authority import cache_sysinfo_extended

        metadata = {
            key: vpd_raw.get(key)
            for key in (
                "_transport",
                "usb_vid",
                "usb_pid",
                "usb_serial",
                "vpd_serial",
                "scsi_vendor",
                "scsi_product",
                "scsi_revision",
                "block_device",
            )
            if vpd_raw.get(key) not in (None, "", b"")
        }
        cache_sysinfo_extended(
            ipod_path,
            raw_xml,
            source=source,
            metadata=metadata,
            expected_volume_identity_key=expected_volume_identity_key,
        )
    except Exception as exc:
        logger.debug("enrich: live SysInfoExtended cache failed: %s", exc)


def _sysinfo_extended_cache_metadata(ipod_path: str) -> dict[str, Any]:
    try:
        from .authority import read_authority

        authority = read_authority(ipod_path)
        file_entry = authority.get("files", {}).get("SysInfoExtended", {})
        metadata = file_entry.get("metadata", {})
        if not isinstance(metadata, dict):
            return {}
        result = dict(metadata)
        if file_entry.get("source"):
            result["_source"] = file_entry["source"]
        return result
    except Exception:
        return {}


def _log_live_validation_differences(
    cached: DeviceInfo,
    live_result: dict,
    live_source: str,
) -> None:
    checks = {
        "serial": live_result.get("serial", ""),
        "firewire_guid": live_result.get("firewire_guid", ""),
        "model_number": live_result.get("model_number", ""),
        "model_family": live_result.get("model_family", ""),
        "generation": live_result.get("generation", ""),
        "capacity": live_result.get("capacity", ""),
        "color": live_result.get("color", ""),
    }
    mismatches = []
    for fld, live_value in checks.items():
        cached_value = getattr(cached, fld, "")
        if (
            cached_value
            and live_value
            and not _values_match(fld, cached_value, live_value)
        ):
            mismatches.append(f"{fld}: cached={cached_value!r}, live={live_value!r}")
    if mismatches:
        logger.warning(
            "Live identity validation from %s disagreed with cache for %s: %s",
            live_source,
            cached.path,
            "; ".join(mismatches),
        )


def _apply_live_result_to_cache(
    path: str,
    mount_name: str,
    usb_pid: int,
    usb_pid_source: str,
    live_result: dict,
    live_source: str,
    expected_volume_identity_key: str = "",
) -> None:
    validated = DeviceInfo()
    validated.path = path
    validated.mount_name = mount_name
    validated.usb_pid = usb_pid
    validated.volume_identity_key = expected_volume_identity_key
    if usb_pid:
        validated._field_sources["usb_pid"] = usb_pid_source or "unknown"

    for fld in (
        "serial",
        "firewire_guid",
        "firmware",
        "model_number",
        "model_family",
        "generation",
        "capacity",
        "color",
    ):
        value = live_result.get(fld, "")
        if value:
            setattr(validated, fld, value)
            validated._field_sources[fld] = live_source

    vpd_info = live_result.get("vpd_info") or {}
    for vpd_key, fld in (
        ("FamilyID", "family_id"),
        ("UpdaterFamilyID", "updater_family_id"),
    ):
        value = vpd_info.get(vpd_key)
        if value not in (None, ""):
            setattr(validated, fld, value)
            validated._field_sources[fld] = live_source

    try:
        from .authority import update_sysinfo as _update_sysinfo

        _update_sysinfo(validated)
        logger.debug(
            "live validation: refreshed SysInfo authority cache for %s "
            "identity=[%s] sources=[%s]",
            path,
            format_fields(validated.__dict__, IDENTITY_FIELDS),
            format_sources(validated._field_sources, SOURCE_FIELDS),
        )
    except Exception as exc:
        logger.debug("live validation: SysInfo authority update failed: %s", exc)


def _start_live_identity_validation(info: DeviceInfo) -> None:
    """Validate high-authority cached identity with live SCSI in the background."""
    if not info.path:
        return
    if sys.platform == "win32":
        logger.debug(
            "Live identity validation skipped on Windows: mount=%s",
            info.path,
        )
        return

    key = _live_validation_key(info)
    with _LIVE_VALIDATION_LOCK:
        if key in _LIVE_VALIDATION_INFLIGHT:
            logger.debug(
                "Live identity validation already running: mount=%s key=%s",
                info.path,
                key,
            )
            return
        _LIVE_VALIDATION_INFLIGHT.add(key)

    logger.debug(
        "Live identity validation scheduled: mount=%s identity=[%s] sources=[%s]",
        info.path,
        format_fields(info.__dict__, IDENTITY_FIELDS),
        format_sources(info._field_sources, SOURCE_FIELDS),
    )

    cached = DeviceInfo()
    cached.path = info.path
    cached.mount_name = info.mount_name
    cached.model_number = info.model_number
    cached.model_family = info.model_family
    cached.generation = info.generation
    cached.capacity = info.capacity
    cached.color = info.color
    cached.firewire_guid = info.firewire_guid
    cached.serial = info.serial
    cached.firmware = info.firmware
    cached.usb_pid = info.usb_pid
    cached.volume_identity_key = info.volume_identity_key
    cached._field_sources.update(info._field_sources)

    def _run() -> None:
        try:
            from .vpd_libusb import identify_via_vpd

            logger.debug(
                "Live identity validation start: mount=%s pid=%s fwguid=%s",
                cached.path,
                f"0x{cached.usb_pid:04X}" if cached.usb_pid else "unknown",
                cached.firewire_guid or "unknown",
            )
            result = identify_via_vpd(
                mount_path=cached.path,
                usb_pid=cached.usb_pid or 0,
                firewire_guid=cached.firewire_guid or "",
                write_sysinfo_to_device=False,
            )
            if not result:
                logger.debug(
                    "Live identity validation returned no VPD data: mount=%s",
                    cached.path,
                )
                return

            vpd_raw = result.get("vpd_info") or {}
            live_source = str(vpd_raw.get("_source") or result.get("source") or "vpd")
            logger.debug(
                "Live identity validation result: mount=%s source=%s "
                "identity=[%s] caps=[%s]",
                cached.path,
                live_source,
                format_fields(result, IDENTITY_FIELDS),
                format_fields(vpd_raw, CAPABILITY_FIELDS, include_false=True),
            )
            _log_live_validation_differences(cached, result, live_source)
            _cache_live_sysinfo_extended(
                cached.path,
                vpd_raw,
                live_source,
                cached.volume_identity_key,
            )
            for fld in (
                "serial",
                "firewire_guid",
                "firmware",
                "model_number",
                "model_family",
                "generation",
                "capacity",
                "color",
            ):
                _set_field_from_source(
                    info,
                    fld,
                    result.get(fld),
                    live_source,
                    label=f"{live_source} validation",
                )
            try:
                from .sysinfo import (
                    ParsedSysInfoExtended,
                    identity_from_sysinfo_extended,
                    parse_sysinfo_extended,
                )

                parsed = (
                    parse_sysinfo_extended(
                        vpd_raw["vpd_raw_xml"],
                        source=live_source,
                        live=True,
                    )
                    if vpd_raw.get("vpd_raw_xml")
                    else ParsedSysInfoExtended(
                        plist=vpd_raw,
                        source=live_source,
                        live=True,
                    )
                )
                identity = identity_from_sysinfo_extended(
                    parsed,
                    live_source,
                    live=True,
                )
                identity_sources = identity.setdefault("_sources", {})
                for fld in (
                    "usb_pid",
                    "usb_vid",
                    "usb_serial",
                    "scsi_vendor",
                    "scsi_product",
                    "scsi_revision",
                ):
                    value = vpd_raw.get(fld)
                    if value not in (None, "", b""):
                        identity[fld] = value
                        identity_sources[fld] = live_source
                _apply_sysinfo_extended_identity(info, identity, live_source)
            except Exception as exc:
                logger.debug("live validation: applying rich fields failed: %s", exc)
            _apply_live_result_to_cache(
                cached.path,
                cached.mount_name,
                cached.usb_pid,
                cached._field_sources.get("usb_pid", ""),
                result,
                live_source,
                cached.volume_identity_key,
            )
        except Exception as exc:
            logger.debug("Live identity validation failed for %s: %s", cached.path, exc)
        finally:
            with _LIVE_VALIDATION_LOCK:
                _LIVE_VALIDATION_INFLIGHT.discard(key)
            logger.debug("Live identity validation finished: mount=%s", cached.path)

    threading.Thread(
        target=_run,
        name=f"iPodLiveValidation-{os.path.basename(info.path.rstrip(os.sep))}",
        daemon=True,
    ).start()


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
            logger.debug("enrich: serial (Apple) from SysInfo: %s", apple_serial)
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
            logger.debug("enrich: firmware from SysInfo: %s", fw_ver)

    if not info.firewire_guid:
        guid = info.sysinfo.get("FirewireGuid", "")
        if guid:
            if guid.startswith(("0x", "0X")):
                guid = guid[2:]
            if guid and guid != "0" * len(guid):
                info.firewire_guid = guid
                info._field_sources.setdefault("firewire_guid", "sysinfo")
                logger.debug("enrich: FW GUID from SysInfo: %s", guid)

    if not info.model_number:
        try:
            from .lookup import extract_model_number
            raw = info.sysinfo.get("ModelNumStr", "")
            if raw:
                mn = extract_model_number(raw)
                if mn:
                    info.model_number = mn
                    info._field_sources.setdefault("model_number", "sysinfo")
                    logger.debug("enrich: model from SysInfo: %s", mn)
        except ImportError:
            pass

    # ── Derived / resolved fields (written by iOpenPod) ───────────────
    # These are only present if a previous iOpenPod run cached them.
    # model_family default is "iPod" (sentinel), so only replace it with
    # a more specific value.
    _mf = info.sysinfo.get("ModelFamily", "")
    if _mf and _mf != "iPod" and info.model_family in ("iPod", ""):
        current_source = info._field_sources.get("model_family", "unknown")
        if current_source == "usb_pid" and info.generation:
            logger.warning(
                "enrich: ignoring cached SysInfo ModelFamily %r because "
                "live USB PID already identified %s %s",
                _mf,
                info.model_family,
                info.generation,
            )
        else:
            info.model_family = _mf
            info._field_sources.setdefault("model_family", "sysinfo")
            logger.debug("enrich: model_family from SysInfo: %s", _mf)

    if not info.generation:
        _gen = info.sysinfo.get("Generation", "")
        if _gen:
            info.generation = _gen
            info._field_sources.setdefault("generation", "sysinfo")
            logger.debug("enrich: generation from SysInfo: %s", _gen)

    if not info.capacity:
        _cap = info.sysinfo.get("Capacity", "")
        if _cap:
            info.capacity = _cap
            info._field_sources.setdefault("capacity", "sysinfo")
            logger.debug("enrich: capacity from SysInfo: %s", _cap)

    if not info.color:
        _col = info.sysinfo.get("Color", "")
        if _col:
            info.color = _col
            info._field_sources.setdefault("color", "sysinfo")
            logger.debug("enrich: color from SysInfo: %s", _col)

    if not info.usb_pid:
        _pid_str = info.sysinfo.get("USBProductID", "")
        if _pid_str:
            try:
                info.usb_pid = int(_pid_str, 0)  # handles "0x1261" and "4705"
                info._field_sources.setdefault("usb_pid", "sysinfo")
                logger.debug("enrich: usb_pid from SysInfo: 0x%04X", info.usb_pid)
            except ValueError:
                pass

    try:
        from .sysinfo import identity_from_sysinfo

        identity = identity_from_sysinfo(info.sysinfo, "sysinfo")
        for fld in ("family_id", "updater_family_id"):
            if fld in identity:
                _set_field_from_source(
                    info,
                    fld,
                    identity[fld],
                    identity.get("_sources", {}).get(fld, "sysinfo"),
                    label="SysInfo",
                )
    except Exception:
        pass


def _enrich_from_sysinfo_extended(info: DeviceInfo) -> None:
    """Read SysInfoExtended XML plist for identity and artwork capabilities."""
    sysinfo_ex_path = os.path.join(
        info.path, "iPod_Control", "Device", "SysInfoExtended",
    )
    if not os.path.exists(sysinfo_ex_path):
        logger.debug("enrich: SysInfoExtended not present at %s", sysinfo_ex_path)
        return

    try:
        with open(sysinfo_ex_path, "rb") as f:
            content = f.read()
    except Exception as exc:
        logger.debug("enrich: SysInfoExtended read failed: %s", exc)
        return

    try:
        from .sysinfo import parse_sysinfo_extended

        parsed = parse_sysinfo_extended(content, source="sysinfo_extended")
        identity = parsed.identity
        metadata = _sysinfo_extended_cache_metadata(info.path)
        if metadata:
            sources = identity.setdefault("_sources", {})
            for fld, key in (
                ("usb_vid", "usb_vid"),
                ("usb_pid", "usb_pid"),
                ("usb_serial", "usb_serial"),
                ("scsi_vendor", "scsi_vendor"),
                ("scsi_product", "scsi_product"),
                ("scsi_revision", "scsi_revision"),
            ):
                value = metadata.get(key)
                if value not in (None, "", b""):
                    identity[fld] = value
                    sources[fld] = metadata.get("_source", "sysinfo_extended")
        logger.debug(
            "enrich: SysInfoExtended parsed bytes=%d keys=%d regex_fallback=%s "
            "identity=[%s] caps=[%s]",
            len(content),
            len(parsed.plist),
            parsed.used_regex_fallback,
            format_fields(identity, IDENTITY_FIELDS),
            format_fields(identity, CAPABILITY_FIELDS, include_false=True),
        )
        _apply_sysinfo_extended_identity(info, identity, "SysInfoExtended")
    except Exception as exc:
        logger.debug("enrich: SysInfoExtended parse failed: %s", exc)


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
    try:
        from .sysinfo import parse_sysinfo_extended

        return parse_sysinfo_extended(content).cover_art_formats
    except Exception:
        return {}


def _apply_sysinfo_extended_identity(
    info: DeviceInfo,
    identity: dict,
    label: str,
) -> None:
    """Merge parsed SysInfoExtended identity/capability fields into DeviceInfo."""
    if not identity:
        return

    sources = identity.get("_sources", {})

    fields = (
        "firewire_guid",
        "serial",
        "model_number",
        "model_family",
        "generation",
        "capacity",
        "color",
        "firmware",
        "board",
        "family_id",
        "updater_family_id",
        "product_type",
        "usb_pid",
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
    for fld in fields:
        if fld not in identity:
            continue
        _set_field_from_source(
            info,
            fld,
            identity[fld],
            sources.get(fld, "sysinfo_extended"),
            label=label,
        )


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
            from .scanner import (
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
                    from .scanner import _identify_via_usb_for_drive
                    hw = _identify_via_usb_for_drive(drive_letter)
                    if hw:
                        _hw_method = "wmi"
                except ImportError:
                    hw = None

            if not hw:
                logger.debug(
                    "enrich: hardware probe returned no data for mount=%s",
                    info.path,
                )
                return

        elif _sys.platform == "darwin":
            from .scanner import _probe_hardware_macos
            hw = _probe_hardware_macos(info.path)
            _hw_method = "ioreg"
            if not hw:
                logger.debug(
                    "enrich: hardware probe returned no data for mount=%s",
                    info.path,
                )
                return

        else:  # Linux
            from .scanner import _probe_hardware_linux
            hw = _probe_hardware_linux(info.path)
            _hw_method = "sysfs"
            if not hw:
                logger.debug(
                    "enrich: hardware probe returned no data for mount=%s",
                    info.path,
                )
                return

    except (ImportError, Exception) as exc:
        logger.debug("enrich: hardware probe failed for %s: %s", info.path, exc)
        return

    logger.debug(
        "enrich: hardware probe result method=%s identity=[%s]",
        _hw_method or "unknown",
        format_fields(hw, IDENTITY_FIELDS),
    )

    # On Windows, FW GUID comes from the device tree walk specifically
    _fw_source = "device_tree" if _hw_method in ("ioctl", "wmi") else _hw_method

    # Merge hardware results into DeviceInfo (never overwrite existing)
    if not info.firewire_guid and hw.get("firewire_guid"):
        guid_hex = hw["firewire_guid"]
        if guid_hex != "0" * len(guid_hex):
            info.firewire_guid = guid_hex
            info._field_sources["firewire_guid"] = _fw_source
            logger.debug("enrich: FW GUID from hardware: %s", guid_hex)

    if not info.serial and hw.get("serial"):
        info.serial = hw["serial"]
        info._field_sources["serial"] = _hw_method
        logger.debug("enrich: serial from hardware: %s", info.serial)

    if not info.firmware and hw.get("firmware"):
        info.firmware = hw["firmware"]
        info._field_sources["firmware"] = _hw_method
        logger.debug("enrich: firmware from hardware: %s", info.firmware)

    if not info.usb_pid and hw.get("usb_pid"):
        info.usb_pid = hw["usb_pid"]
        info._field_sources["usb_pid"] = _fw_source
        logger.debug("enrich: USB PID from hardware: 0x%04X", info.usb_pid)

    if not info.model_number and hw.get("model_number"):
        info.model_number = hw["model_number"]
        info._field_sources["model_number"] = _hw_method
        logger.debug("enrich: model_number from hardware: %s", info.model_number)

    for fld, value, source in (
        ("usb_vid", hw.get("usb_vid"), _fw_source),
        ("usb_serial", hw.get("usb_serial"), _fw_source),
        ("usbstor_instance_id", hw.get("usbstor_instance_id"), _fw_source),
        ("usb_parent_instance_id", hw.get("usb_parent_instance_id"), _fw_source),
        (
            "usb_grandparent_instance_id",
            hw.get("usb_grandparent_instance_id"),
            _fw_source,
        ),
        ("scsi_vendor", hw.get("scsi_vendor") or hw.get("vendor"), _hw_method),
        ("scsi_product", hw.get("scsi_product") or hw.get("product"), _hw_method),
        ("scsi_revision", hw.get("scsi_revision") or hw.get("firmware"), _hw_method),
    ):
        _set_field_from_source(info, fld, value, source, label="hardware")

    if info.identification_method == "unknown":
        info.identification_method = "hardware"


def _enrich_from_usb_vpd(info: DeviceInfo) -> None:
    """Query iPod firmware via USB SCSI VPD pages for device identification.

    Delegates to :func:`iopenpod.device.vpd_libusb.identify_via_vpd` on supported
    non-Windows platforms, resolves the exact model via serial-suffix lookup,
    and handles post-query remount on Linux/macOS.

    SysInfo writing is NOT done here — the authority module handles it
    after all identification is complete.
    """
    if sys.platform == "win32":
        logger.debug(
            "enrich: live VPD skipped on Windows for mount=%s",
            info.path,
        )
        return

    try:
        from .vpd_libusb import identify_via_vpd
    except ImportError:
        logger.debug("enrich: iopenpod.device.vpd_libusb not available")
        return

    logger.debug(
        "enrich: live VPD query start mount=%s pid=%s fwguid=%s",
        info.path,
        f"0x{info.usb_pid:04X}" if info.usb_pid else "unknown",
        info.firewire_guid or "unknown",
    )
    result = identify_via_vpd(
        mount_path=info.path,
        usb_pid=info.usb_pid or 0,
        firewire_guid=info.firewire_guid or "",
        write_sysinfo_to_device=False,
    )
    if result is None:
        logger.debug("enrich: live VPD query returned no data for %s", info.path)
        return

    vpd_raw = result.get("vpd_info") or {}
    vpd_source = str(vpd_raw.get("_source") or result.get("source") or "vpd")
    logger.debug(
        "enrich: live VPD query result source=%s identity=[%s] caps=[%s]",
        vpd_source,
        format_fields(result, IDENTITY_FIELDS),
        format_fields(vpd_raw, CAPABILITY_FIELDS, include_false=True),
    )
    _cache_live_sysinfo_extended(info.path, vpd_raw, vpd_source)

    # Apply VPD-derived fields to DeviceInfo
    _set_field_from_source(
        info,
        "serial",
        result["serial"],
        vpd_source,
        label=vpd_source,
    )
    _set_field_from_source(
        info,
        "firewire_guid",
        result["firewire_guid"],
        vpd_source,
        label=vpd_source,
    )
    _set_field_from_source(
        info,
        "firmware",
        result["firmware"],
        vpd_source,
        label=vpd_source,
    )
    if result["model_number"]:
        info.model_number = result["model_number"]
        info.model_family = result["model_family"]
        info.generation = result["generation"]
        info._field_sources["model_number"] = vpd_source
        info._field_sources["model_family"] = vpd_source
        info._field_sources["generation"] = vpd_source
        # A VPD serial suffix is authoritative — always overwrite capacity
        # and color even if they were pre-populated from a stale/wrong
        # SysInfo model number (e.g. MB029 → 80GB when device is MB565 → 120GB).
        if result["capacity"]:
            info.capacity = result["capacity"]
            info._field_sources["capacity"] = vpd_source
        if result["color"]:
            info.color = result["color"]
            info._field_sources["color"] = vpd_source

    # Extract board from VPD raw data (previously obtained via SysInfo re-read)
    _set_field_from_source(
        info,
        "board",
        vpd_raw.get("BoardHwName"),
        vpd_source,
        label=vpd_source,
    )

    try:
        from .sysinfo import (
            ParsedSysInfoExtended,
            identity_from_sysinfo_extended,
            parse_sysinfo_extended,
        )

        parsed: ParsedSysInfoExtended | None = None
        if vpd_raw.get("vpd_raw_xml"):
            parsed = parse_sysinfo_extended(
                vpd_raw["vpd_raw_xml"],
                source=vpd_source,
                live=True,
            )
        elif isinstance(vpd_raw, dict):
            parsed = ParsedSysInfoExtended(
                plist=vpd_raw,
                source=vpd_source,
                live=True,
            )
        if parsed:
            identity = identity_from_sysinfo_extended(
                parsed,
                vpd_source,
                live=True,
            )
            identity_sources = identity.setdefault("_sources", {})
            for fld in (
                "usb_pid",
                "usb_vid",
                "usb_serial",
                "scsi_vendor",
                "scsi_product",
                "scsi_revision",
            ):
                value = vpd_raw.get(fld)
                if value not in (None, "", b""):
                    identity[fld] = value
                    identity_sources[fld] = vpd_source
            _apply_sysinfo_extended_identity(info, identity, vpd_source)
    except Exception as exc:
        logger.debug("enrich: VPD artwork/capability parse failed: %s", exc)

    # Update mount path if pyusb caused a remount to a different location
    if result["mount_path"] and result["mount_path"] != info.path:
        logger.info("enrich: mount path changed %s → %s",
                    info.path, result["mount_path"])
        info.path = result["mount_path"]

    if info.serial:
        info.identification_method = "usb_vpd"


def _enrich_from_serial_lookup(info: DeviceInfo) -> None:
    """Look up the exact model from its longest published serial suffix.

    This is very high confidence — the suffix encodes the exact model
    including capacity, color, and hardware revision.  Always fills gaps
    even when ``model_number`` is already known, because serial-suffix lookup
    provides exact variant resolution that generic model lookup may miss.

    The derived fields inherit the serial number's authority source, since
    the lookup is a deterministic mapping — the trust of the output equals
    the trust of the input.
    """
    if not info.serial or len(info.serial) < 3:
        return

    try:
        from .lookup import lookup_by_serial, match_serial_suffix
    except ImportError:
        return

    matched_suffix = match_serial_suffix(info.serial)
    result = lookup_by_serial(info.serial)
    if not result:
        return

    model_num, model_info = result

    # Inherit the serial's source — the derived values are exactly as
    # trustworthy as the serial they came from.
    _src = info._field_sources.get("serial", "serial_lookup")

    from .authority import _WORST_RANK, SOURCE_RANK
    _serial_rank = SOURCE_RANK.get(_src, _WORST_RANK)

    # Apply model_number with the same rank comparison used for other fields.
    # This lets a high-authority serial (e.g. from VPD) override a stale or
    # wrong ModelNumStr that was read from SysInfo (e.g. a device whose NVRAM
    # reports the wrong model after a botched restore or board swap).
    _cur_mn_rank = SOURCE_RANK.get(
        info._field_sources.get("model_number", "unknown"), _WORST_RANK,
    )
    if not info.model_number or _serial_rank <= _cur_mn_rank:
        if info.model_number and info.model_number != model_num:
            logger.warning(
                "enrich: serial suffix '%s' gives model %s but current "
                "model_number is %s (source: %s, rank %d); overriding with "
                "serial result (serial source: %s, rank %d)",
                matched_suffix, model_num, info.model_number,
                info._field_sources.get("model_number", "unknown"),
                _cur_mn_rank, _src, _serial_rank,
            )
        info.model_number = model_num
        info._field_sources["model_number"] = _src

    # Serial lookup is authoritative for family/gen — always set these
    # (unless a higher-authority source already has them).
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

    # Serial-suffix lookup is authoritative for capacity/color — use the same
    # rank comparison as family/generation so it overwrites stale values
    # from a wrong SysInfo model number.
    _cur_cap_rank = SOURCE_RANK.get(
        info._field_sources.get("capacity", "unknown"), _WORST_RANK,
    )
    if model_info[2] and _serial_rank <= _cur_cap_rank:
        info.capacity = model_info[2]
        info._field_sources["capacity"] = _src

    _cur_color_rank = SOURCE_RANK.get(
        info._field_sources.get("color", "unknown"), _WORST_RANK,
    )
    if model_info[3] and _serial_rank <= _cur_color_rank:
        info.color = model_info[3]
        info._field_sources["color"] = _src

    if info.identification_method in ("unknown", "hardware"):
        info.identification_method = "serial"
    logger.debug(
        "enrich: serial suffix '%s' -> %s %s %s %s model=%s source=%s",
        matched_suffix, model_info[0], model_info[1],
        model_info[2], model_info[3], model_num, _src,
    )


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
            "enrich: iTunesDB hdr: scheme=%d, hash58=%s, hash72=%s",
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
        from .capabilities import checksum_type_for_family_gen
        from .checksum import ChecksumType
    except ImportError:
        return

    # Priority 1: family + generation lookup (authoritative, no gaps)
    if info.model_family:
        ct = checksum_type_for_family_gen(
            info.model_family, info.generation or "",
        )
        if ct is not None:
            info.checksum_type = int(ct)
            logger.debug(
                "enrich: checksum %s (family=%s, gen=%s)",
                ct.name, info.model_family, info.generation or "(all)",
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
                logger.debug(
                    "enrich: checksum UNKNOWN (firmware %s >= 2.x)",
                    info.firmware,
                )
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
    logger.debug("enrich: checksum NONE (default; pre-2007 or unidentifiable)")


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
        from iopenpod.artworkdb_writer.rgb565 import ALL_KNOWN_FORMATS, _extract_format_ids
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
                logger.debug(
                    "enrich: artwork formats from ArtworkDB scan: %s",
                    list(fmts.keys()),
                )
    except Exception as exc:
        logger.debug("enrich: ArtworkDB scan failed: %s", exc)
