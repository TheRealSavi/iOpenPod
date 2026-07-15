"""
iOpenPod SysInfo Authority — manages authoritative SysInfo writing.

After device identification is complete, reconciles gathered data with
the existing SysInfo file on the iPod, using per-field provenance tracking
to keep the most reliable value for each field.

The authority file at ``/iPod_Control/Device/iOpenPodSysInfoAuthority``
(JSON) records which data source was used to populate each SysInfo field.
On subsequent runs, if a field's value has changed, the authority
determines whether the new or existing value is more trustworthy.

Source reliability (most → least)::

    Sure (live hardware):
        scsi_vpd / windows_scsi / linux_scsi / usb_vendor > vpd > iokit > ioctl
            > device_tree / ioreg / sysfs > wmi
    Guesses (files / lookups / derivations):
        sysinfo_extended > sysinfo > itunes > serial_lookup
            > usb_pid > hashing > unknown
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .info import DeviceInfo

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Source reliability ranking — lower index = more reliable
# ──────────────────────────────────────────────────────────────────────

_SOURCE_ORDER: list[str] = [
    # ── Sure: live hardware probes ──────────────────────────────────
    "scsi_vpd",             # Live SCSI INQUIRY VPD plist
    "windows_scsi",         # Windows SCSI pass-through VPD
    "linux_scsi",           # Linux SG_IO SCSI pass-through VPD
    "usb_vendor",           # Live Apple USB vendor-control plist
    "vpd",                  # SCSI Vital Product Data — gold standard
    "iokit",                # macOS IOKit SCSI (effectively VPD, no unmount)
    "ioctl",                # Windows direct SCSI inquiry
    "device_tree",          # Windows PnP device tree (live hardware)
    "ioreg",                # macOS ioreg (live hardware)
    "sysfs",                # Linux sysfs (live hardware)
    "wmi",                  # Windows WMI (live hardware query)
    # ── Guesses: lookups, derivations, files ────────────────────────
    "itunes",               # Pre-existing value assumed to be from iTunes
    "serial_lookup",        # Derived from serial last-3 chars
    "usb_pid",              # Coarse USB PID mapping
    "disk_size",            # Live disk-size based capacity estimate
    "model_table",          # Deterministic inference from known model tuples
    "inferred",             # Other deterministic inference from known fields
    "sysinfo_extended",     # SysInfoExtended XML plist — on-disk, stale-prone
    "sysinfo",              # SysInfo plain text — on-disk, stale-prone
    "hashing",              # Inferred from hashing scheme
    "unknown",              # Source not tracked
]

SOURCE_RANK: dict[str, int] = {src: i for i, src in enumerate(_SOURCE_ORDER)}
"""Map source name → rank (lower = more reliable)."""

_WORST_RANK: int = len(_SOURCE_ORDER)

# Anything with rank < _SURE_THRESHOLD is a "sure" (live hardware) source.
# Anything >= is a "guess" (file / lookup / derivation).
_SURE_THRESHOLD: int = SOURCE_RANK["itunes"]  # first guess source


# ──────────────────────────────────────────────────────────────────────
# SysInfo key ↔ DeviceInfo field mapping
# ──────────────────────────────────────────────────────────────────────

SYSINFO_FIELDS: list[tuple[str, str]] = [
    # ── Core identifiers (written by iTunes / hardware probes) ────────
    ("pszSerialNumber", "serial"),
    ("FirewireGuid", "firewire_guid"),
    ("visibleBuildID", "firmware"),
    ("BoardHwName", "board"),
    ("ModelNumStr", "model_number"),
    ("FamilyID", "family_id"),
    ("UpdaterFamilyID", "updater_family_id"),
    # ── Derived / resolved by iOpenPod for full device granularity ────
    # These are deterministically derived from model_number (via
    # IPOD_MODELS or serial-last-3 lookup), but caching them in SysInfo
    # avoids re-derivation and lets the authority system track provenance.
    ("ModelFamily", "model_family"),
    ("Generation", "generation"),
    ("Capacity", "capacity"),
    ("Color", "color"),
    ("USBProductID", "usb_pid"),
]

# Fields whose default DeviceInfo value is a non-empty sentinel that should
# NOT be treated as "already populated" when reading from SysInfo.
# model_family defaults to "iPod" (generic, unresolved).
_SENTINEL_DEFAULTS: dict[str, str] = {
    "model_family": "iPod",
}

_DERIVED_SYSINFO_KEYS: frozenset[str] = frozenset({
    "ModelFamily",
    "Generation",
    "Capacity",
    "Color",
    "USBProductID",
})

# Core identification fields — these drive the "all sure" determination for
# the HIGH authority path.  If ALL core fields have sure (live hardware)
# provenance, the expensive hardware and VPD probes are skipped.
#
# Only the essential identification trio is included:
#   - Serial number (needed for serial-last-3 exact model resolution)
#   - FireWire GUID (needed for database signing)
#   - Model number (needed for family/gen/capacity/color derivation)
#
# Other fields (firmware, board) are informational — their absence from
# live hardware probes should NOT force re-probing.  Derived fields
# (ModelFamily, Generation, etc.) are excluded because they inherit trust
# from a core field and don't require independent hardware probing.
_CORE_FIELDS: frozenset[str] = frozenset({
    "pszSerialNumber",
    "FirewireGuid",
    "ModelNumStr",
})

AUTHORITY_FILENAME = "iOpenPodSysInfoAuthority"


# ──────────────────────────────────────────────────────────────────────
# Authority coverage check
# ──────────────────────────────────────────────────────────────────────

def check_authority_coverage(
    ipod_path: str,
) -> tuple[bool, dict[str, str]]:
    """Check whether the authority file indicates core fields are all tracked.

    Returns ``(all_tracked, field_sources)`` where:

    * *all_tracked* is ``True`` when every **core** SysInfo field has an
      authority entry (i.e., iOpenPod has previously identified this device
      and cached the results).  The SysInfo is trusted as high-authority
      because either (a) it was written by iTunes, or (b) iOpenPod wrote
      it after probing hardware.  The only things that invalidate trust
      are external modification (detected via SHA-256 hashes) or missing
      authority file (first run).
    * *field_sources* maps DeviceInfo field names to their authority source
      strings (e.g. ``{"serial": "vpd", "firewire_guid": "ioctl", ...}``).

    If the authority file is missing or empty, returns ``(False, {})`` so
    that the caller runs the full probe pipeline.
    """
    authority = read_authority(ipod_path)
    fields = authority.get("fields", {})
    if not fields:
        return False, {}

    # Tamper detection — if SysInfo/SysInfoExtended were modified externally
    # (by iTunes or another tool), we can't trust the cached provenance.
    stored_hashes = authority.get("file_hashes", {})
    if stored_hashes:
        tampered = False
        for label, path in [
            ("SysInfo", _sysinfo_path(ipod_path)),
            ("SysInfoExtended", _sysinfo_extended_path(ipod_path)),
        ]:
            stored = stored_hashes.get(label)
            if stored is not None:
                current = _hash_file(path)
                if current != stored:
                    tampered = True
                    break
        if tampered:
            logger.info(
                "Authority coverage: external modification detected, "
                "treating all sources as low-authority",
            )
            return False, {}

    field_sources: dict[str, str] = {}
    all_tracked = True
    for sysinfo_key, device_field in SYSINFO_FIELDS:
        entry = fields.get(sysinfo_key)
        if entry is None:
            # Field not in authority at all.  Only core fields affect
            # the "all tracked" flag — missing derived fields are fine
            # (they'll be re-derived cheaply from model lookup).
            if sysinfo_key in _CORE_FIELDS:
                all_tracked = False
            continue
        source = entry.get("source", "unknown")
        field_sources[device_field] = source

    return all_tracked, field_sources


# ──────────────────────────────────────────────────────────────────────
# Formatting helpers
# ──────────────────────────────────────────────────────────────────────

def _format_for_sysinfo(sysinfo_key: str, device_value) -> str:
    """Convert a DeviceInfo field value to the SysInfo on-disk format.

    Handles both string and non-string field types (e.g. usb_pid is int).
    """
    if sysinfo_key == "USBProductID":
        # usb_pid is an int on DeviceInfo
        if isinstance(device_value, int):
            return f"0x{device_value:04X}" if device_value else ""
        # String passthrough (shouldn't happen, but safe)
        return str(device_value) if device_value else ""
    if not device_value:
        return ""
    device_value = str(device_value)
    if sysinfo_key == "FirewireGuid":
        clean = device_value
        if clean.startswith(("0x", "0X")):
            return f"0x{clean[2:].upper()}"
        return f"0x{clean.upper()}"
    if sysinfo_key == "ModelNumStr":
        # SysInfo stores "xA623" — the 'M' prefix becomes 'x'
        if device_value.startswith("M"):
            return f"x{device_value[1:]}"
        return device_value
    return device_value


def _normalise_sysinfo_value(sysinfo_key: str, raw_value) -> str:
    """Normalise a raw SysInfo value to a comparable canonical form.

    Strips null padding, ``0x`` prefixes, and whitespace so that
    comparisons are not tripped up by trivial formatting differences.
    """
    val = str(raw_value).strip().rstrip("\x00")
    if sysinfo_key == "FirewireGuid":
        if val.startswith(("0x", "0X")):
            val = val[2:]
        return val.upper()
    if sysinfo_key == "ModelNumStr":
        if val.startswith("x"):
            val = "M" + val[1:]
        return val.upper().rstrip("\x00")
    if sysinfo_key == "USBProductID":
        if val.upper().startswith("0X"):
            val = val[2:]
        return val.upper().lstrip("0") or "0"
    return val


# ──────────────────────────────────────────────────────────────────────
# File I/O
# ──────────────────────────────────────────────────────────────────────

def _authority_path(ipod_path: str) -> str:
    return os.path.join(
        ipod_path, "iPod_Control", "Device", AUTHORITY_FILENAME,
    )


def _sysinfo_path(ipod_path: str) -> str:
    return os.path.join(ipod_path, "iPod_Control", "Device", "SysInfo")


def _sysinfo_extended_path(ipod_path: str) -> str:
    return os.path.join(ipod_path, "iPod_Control", "Device", "SysInfoExtended")


def _hash_file(path: str) -> str | None:
    """Return hex SHA-256 of a file, or ``None`` if the file is missing."""
    if not os.path.exists(path):
        return None
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as exc:
        logger.warning("Failed to hash %s: %s", path, exc)
        return None


def read_authority(ipod_path: str) -> dict:
    """Read the authority file.  Returns ``{}`` if missing or corrupt."""
    path = _authority_path(ipod_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        logger.warning("Authority file read failed: %s", exc)
    return {}


def _write_authority(ipod_path: str, authority: dict) -> None:
    path = _authority_path(ipod_path)
    device_dir = os.path.dirname(path)
    os.makedirs(device_dir, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(authority, f, indent=2, ensure_ascii=False)
        logger.debug("Wrote authority file to %s", path)
    except Exception as exc:
        logger.warning("Failed to write authority file: %s", exc)


def _read_sysinfo_raw(ipod_path: str) -> dict[str, str]:
    """Read all key:value pairs from SysInfo, preserving raw values."""
    path = _sysinfo_path(ipod_path)
    result: dict[str, str] = {}
    if not os.path.exists(path):
        return result
    try:
        with open(path, errors="replace") as f:
            for line in f:
                if ":" in line:
                    key, val = line.split(":", 1)
                    result[key.strip()] = val.strip()
    except Exception as exc:
        logger.warning("SysInfo read failed: %s", exc)
    return result


def _write_sysinfo_file(ipod_path: str, fields: dict[str, str]) -> None:
    """Write all fields to the SysInfo file."""
    path = _sysinfo_path(ipod_path)
    device_dir = os.path.dirname(path)
    os.makedirs(device_dir, exist_ok=True)
    lines = [f"{k}: {v}" for k, v in fields.items() if v]
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        logger.info("Wrote SysInfo (%d fields) to %s", len(lines), path)
    except Exception as exc:
        logger.warning("Failed to write SysInfo: %s", exc)


def _normalise_sysinfo_extended(raw_xml: bytes | str) -> bytes:
    """Return canonical SysInfoExtended plist bytes suitable for caching."""
    if isinstance(raw_xml, str):
        raw = raw_xml.encode("utf-8", errors="replace")
    else:
        raw = bytes(raw_xml or b"")
    if not raw:
        return b""

    try:
        from .sysinfo import parse_sysinfo_extended

        parsed = parse_sysinfo_extended(raw)
        if parsed.plist and parsed.raw_xml:
            return parsed.raw_xml
    except Exception:
        pass

    for marker in (b"<?xml", b"<plist"):
        idx = raw.find(marker)
        if idx >= 0:
            raw = raw[idx:]
            break
    raw = raw.strip(b"\x00\r\n\t ")
    if raw and b"</plist>" not in raw:
        raw += b"\n</dict>\n</plist>"
    return raw


def cache_sysinfo_extended(
    ipod_path: str,
    raw_xml: bytes | str,
    *,
    source: str = "unknown",
    metadata: dict | None = None,
) -> bool:
    """Cache a live SysInfoExtended payload and refresh authority hashes."""
    if not ipod_path or not raw_xml:
        return False

    device_dir = os.path.join(ipod_path, "iPod_Control", "Device")
    if not os.path.isdir(device_dir):
        return False

    data = _normalise_sysinfo_extended(raw_xml)
    if not data:
        return False

    path = _sysinfo_extended_path(ipod_path)
    try:
        with open(path, "wb") as f:
            f.write(data)
    except Exception as exc:
        logger.warning("Failed to cache SysInfoExtended: %s", exc)
        return False

    authority = read_authority(ipod_path)
    now = datetime.now(UTC).isoformat()
    files = authority.setdefault("files", {})
    files["SysInfoExtended"] = {
        "source": source,
        "updated": now,
        "bytes": len(data),
    }
    if metadata:
        files["SysInfoExtended"]["metadata"] = {
            str(k): v
            for k, v in metadata.items()
            if isinstance(v, (str, int, float, bool)) and v not in ("", None)
        }
    authority["version"] = 1
    authority["last_updated"] = now
    _store_file_hashes(ipod_path, authority)
    _write_authority(ipod_path, authority)
    logger.debug(
        "Cached SysInfoExtended (%d bytes, source=%s) to %s",
        len(data),
        source,
        path,
    )
    return True


# ──────────────────────────────────────────────────────────────────────
# Tamper detection
# ──────────────────────────────────────────────────────────────────────

def _detect_external_modification(
    ipod_path: str,
    authority: dict,
    fields: dict[str, dict],
    now: str,
) -> None:
    """Check whether SysInfo or SysInfoExtended were modified externally.

    Compares the stored SHA-256 hashes in the authority file against the
    current on-disk files.  If either file has been changed (e.g. by
    iTunes or another tool), **all** authority source levels are reset to
    ``"sysinfo"`` because we can no longer trust the provenance — the
    external software may have overwritten fields with different values.
    """
    stored_hashes: dict[str, str] = authority.get("file_hashes", {})
    if not stored_hashes:
        # First run or no hashes recorded — nothing to compare.
        return

    tampered: list[str] = []

    for label, path in [
        ("SysInfo", _sysinfo_path(ipod_path)),
        ("SysInfoExtended", _sysinfo_extended_path(ipod_path)),
    ]:
        stored = stored_hashes.get(label)
        if stored is None:
            # We never recorded a hash for this file — skip.
            continue
        current = _hash_file(path)
        if current is None:
            # File was deleted externally — that counts as a change.
            tampered.append(f"{label} (deleted)")
        elif current != stored:
            tampered.append(label)

    if not tampered:
        return

    logger.warning(
        "External modification detected in %s — resetting all "
        "authority sources to 'sysinfo'",
        ", ".join(tampered),
    )
    for _sysinfo_key, entry in fields.items():
        if isinstance(entry, dict) and entry.get("source") != "sysinfo":
            entry["source"] = "sysinfo"
            entry["updated"] = now


def _store_file_hashes(ipod_path: str, authority: dict) -> None:
    """Compute and store SHA-256 hashes of SysInfo and SysInfoExtended."""
    hashes: dict[str, str] = {}
    for label, path in [
        ("SysInfo", _sysinfo_path(ipod_path)),
        ("SysInfoExtended", _sysinfo_extended_path(ipod_path)),
    ]:
        h = _hash_file(path)
        if h is not None:
            hashes[label] = h
    authority["file_hashes"] = hashes


# ──────────────────────────────────────────────────────────────────────
# Authority-aware SysInfo update
# ──────────────────────────────────────────────────────────────────────

def _rank(source: str) -> int:
    """Lower = more reliable.  Unknown sources get worst rank."""
    return SOURCE_RANK.get(source, _WORST_RANK)


def _default_existing_source(sysinfo_key: str, old_raw: str) -> str:
    """Return provenance for an existing SysInfo value with no authority entry."""
    if not old_raw:
        return "unknown"
    if sysinfo_key in _DERIVED_SYSINFO_KEYS:
        return "sysinfo"
    return "itunes"


def update_sysinfo(info: DeviceInfo) -> None:
    """Reconcile gathered DeviceInfo with the on-disk SysInfo.

    Called **after** all identification and enrichment is complete.

    For each SysInfo-mappable field:

    * Missing from SysInfo → add it.
    * Same value → refresh authority timestamp (upgrade source if better).
    * Different value → keep the one from the more reliable source.

    Also writes/updates the ``iOpenPodSysInfoAuthority`` JSON alongside
    SysInfo so future runs can make informed decisions.
    """
    if not info.path:
        return

    ipod_path = info.path
    device_dir = os.path.join(ipod_path, "iPod_Control", "Device")
    if not os.path.isdir(device_dir):
        return

    existing_sysinfo = _read_sysinfo_raw(ipod_path)
    authority = read_authority(ipod_path)
    fields = authority.get("fields", {})
    now = datetime.now(UTC).isoformat()

    # ── Tamper detection: hash SysInfo / SysInfoExtended ──────────
    _detect_external_modification(ipod_path, authority, fields, now)

    # Start with all existing SysInfo fields so we preserve any we don't map
    updated_sysinfo: dict[str, str] = dict(existing_sysinfo)
    sysinfo_changed = False

    for sysinfo_key, device_field in SYSINFO_FIELDS:
        new_value = getattr(info, device_field, "")

        # Skip empty / default-sentinel values — these haven't been
        # resolved to anything useful yet.
        sentinel = _SENTINEL_DEFAULTS.get(device_field)
        if sentinel is not None and new_value == sentinel:
            continue
        if not new_value:
            continue

        new_source: str = info._field_sources.get(device_field, "unknown")
        new_formatted = _format_for_sysinfo(sysinfo_key, new_value)

        old_raw = existing_sysinfo.get(sysinfo_key, "")
        old_source: str = fields.get(sysinfo_key, {}).get(
            "source", _default_existing_source(sysinfo_key, old_raw),
        )

        # ── Field missing from SysInfo → add it ──────────────────────
        if not old_raw:
            updated_sysinfo[sysinfo_key] = new_formatted
            fields[sysinfo_key] = {
                "value": new_formatted,
                "source": new_source,
                "updated": now,
            }
            sysinfo_changed = True
            logger.debug(
                "SysInfo: adding %s = %s (source: %s)",
                sysinfo_key, new_formatted, new_source,
            )
            continue

        # ── Compare normalised values ─────────────────────────────────
        old_normalised = _normalise_sysinfo_value(sysinfo_key, old_raw)
        new_normalised = _normalise_sysinfo_value(sysinfo_key, new_formatted)

        if old_normalised == new_normalised:
            # Same effective value — upgrade authority source if we're
            # more (or equally) reliable, otherwise ensure the existing
            # best source is still recorded (so authority coverage check
            # sees the field as tracked).
            best_source = (
                new_source
                if _rank(new_source) <= _rank(old_source)
                else old_source
            )
            if sysinfo_key not in fields or _rank(best_source) <= _rank(
                fields[sysinfo_key].get("source", "unknown"),
            ):
                fields[sysinfo_key] = {
                    "value": old_raw,      # keep existing formatting
                    "source": best_source,
                    "updated": now,
                }
            continue

        # iOpenPod-derived fields are cache material, not immutable iTunes
        # facts.  If our current resolver produces a different derived label
        # after a table/provenance fix, let it refresh stale authority entries
        # even when the old cached source had a better historical rank.
        if sysinfo_key in _DERIVED_SYSINFO_KEYS:
            updated_sysinfo[sysinfo_key] = new_formatted
            fields[sysinfo_key] = {
                "value": new_formatted,
                "source": new_source,
                "updated": now,
            }
            sysinfo_changed = True
            logger.debug(
                "SysInfo: refreshing derived %s: %r → %r (source: %s)",
                sysinfo_key,
                old_raw,
                new_formatted,
                new_source,
            )
            continue

        # ── Values differ — use the more reliable source ──────────────
        if _rank(new_source) <= _rank(old_source):
            # New source is at least as reliable → overwrite
            updated_sysinfo[sysinfo_key] = new_formatted
            fields[sysinfo_key] = {
                "value": new_formatted,
                "source": new_source,
                "updated": now,
            }
            sysinfo_changed = True

            logger.debug(
                "SysInfo: updating %s: %r → %r (source %s [rank %d] "
                "beats %s [rank %d])",
                sysinfo_key, old_raw, new_formatted,
                new_source, _rank(new_source),
                old_source, _rank(old_source),
            )
        else:
            # Existing value from a more reliable source → keep it
            logger.debug(
                "SysInfo: keeping %s = %r (source %s [rank %d] beats "
                "new %s [rank %d] with %r)",
                sysinfo_key, old_raw,
                old_source, _rank(old_source),
                new_source, _rank(new_source), new_formatted,
            )

    # ── Persist ───────────────────────────────────────────────────────
    if sysinfo_changed:
        _write_sysinfo_file(ipod_path, updated_sysinfo)

    # Always ensure the authority dict is well-formed before writing.
    authority["version"] = 1
    authority["fields"] = fields
    authority["last_updated"] = now

    # Always refresh file hashes so the next run can detect tampering.
    _store_file_hashes(ipod_path, authority)
    _write_authority(ipod_path, authority)
