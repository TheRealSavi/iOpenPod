"""Virtual iPod metadata creation and loading.

Virtual iPods are ordinary folders seeded with enough iPod identity metadata
for the rest of iOpenPod to treat them like a selected device.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import string
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .bootstrap import _seed_ipod_layout, ensure_device_itunes_database
from .capabilities import capabilities_for_family_gen
from .checksum import CHECKSUM_MHBD_SCHEME, ChecksumType
from .info import DeviceInfo, resolve_itdb_path
from .models import (
    IPOD_MODELS,
    IPOD_RECOVERY_USB_PIDS,
    SERIAL_SUFFIX_TO_MODEL,
    USB_PID_TO_MODEL,
)

VIRTUAL_IPOD_INFO_FILENAME = "iPodInfo.json"
_SCHEMA_VERSION = 1
_SERIAL_ALPHABET = string.ascii_uppercase + string.digits


def virtual_ipod_info_path(ipod_path: str | os.PathLike[str]) -> Path:
    """Return the root-level metadata path for a virtual iPod."""

    return Path(ipod_path) / VIRTUAL_IPOD_INFO_FILENAME


def has_virtual_ipod_info(ipod_path: str | os.PathLike[str]) -> bool:
    """Return whether *ipod_path* contains virtual iPod metadata."""

    if not str(ipod_path):
        return False
    return virtual_ipod_info_path(ipod_path).is_file()


def available_virtual_ipod_models() -> list[dict[str, str]]:
    """Return model choices that can be backed by a known serial suffix."""

    suffix_by_model = _serial_suffix_by_model()
    rows: list[dict[str, str]] = []
    for model_number, (family, generation, capacity, color) in IPOD_MODELS.items():
        suffix = suffix_by_model.get(model_number)
        if not suffix:
            continue
        rows.append(
            {
                "model_number": model_number,
                "model_family": family,
                "generation": generation,
                "capacity": capacity,
                "color": color,
                "serial_suffix": suffix,
                "display_name": _model_display_name(
                    model_number,
                    family,
                    generation,
                    capacity,
                    color,
                ),
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["model_family"],
            row["generation"],
            row["capacity"],
            row["color"],
            row["model_number"],
        ),
    )


def create_virtual_ipod(
    ipod_path: str | os.PathLike[str],
    model_number: str,
    *,
    ipod_name: str = "iPod",
) -> DeviceInfo:
    """Create a virtual iPod root and return its hydrated DeviceInfo."""

    root = Path(ipod_path).expanduser().resolve()
    if not model_number:
        raise ValueError("Choose an iPod model")
    if model_number not in IPOD_MODELS:
        raise ValueError(f"Unknown iPod model: {model_number}")

    suffix = _serial_suffix_by_model().get(model_number)
    if not suffix:
        raise ValueError(f"No known serial suffix for model {model_number}")

    family, generation, capacity, color = IPOD_MODELS[model_number]
    caps = capabilities_for_family_gen(family, generation)
    checksum = caps.checksum if caps is not None else ChecksumType.NONE
    firewire_guid = _generate_firewire_guid()
    serial = _generate_serial(suffix)
    hash_iv = secrets.token_bytes(16)
    hash_rndpart = secrets.token_bytes(12)

    _seed_ipod_layout(root, uses_sqlite_db=bool(caps and caps.uses_sqlite_db))

    payload: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "created_by": "iOpenPod",
        "created_at": datetime.now(UTC).isoformat(),
        "ipod_name": ipod_name.strip() or "iPod",
        "mount_name": root.name or "iPod",
        "model_number": model_number,
        "model_family": family,
        "generation": generation,
        "capacity": capacity,
        "color": color,
        "serial": serial,
        "serial_suffix": suffix,
        "firewire_guid": firewire_guid,
        "firmware": _default_firmware(family, generation),
        "board": _default_board_name(family, generation),
        "family_id": _default_family_id(family),
        "updater_family_id": _default_family_id(family),
        "product_type": model_number,
        "usb_vid": 0x05AC,
        "usb_pid": _usb_pid_for_identity(family, generation),
        "usb_serial": firewire_guid,
        "connected_bus": "USB",
        "reported_volume_format": "FAT32",
        "filesystem_type": "fat32",
        "scsi_vendor": "Apple",
        "scsi_product": "iPod",
        "scsi_revision": _default_firmware(family, generation),
        "checksum_type": int(checksum),
        "hashing_scheme": CHECKSUM_MHBD_SCHEME.get(checksum, 0),
        "hash_info_iv": hash_iv.hex().upper(),
        "hash_info_rndpart": hash_rndpart.hex().upper(),
        "db_version": caps.db_version if caps is not None else 0,
        "shadow_db_version": caps.shadow_db_version if caps is not None else 0,
        "uses_sqlite_db": caps.uses_sqlite_db if caps is not None else False,
        "supports_sparse_artwork": (
            caps.supports_sparse_artwork if caps is not None else False
        ),
        "podcasts_supported": caps.supports_podcast if caps is not None else True,
        "voice_memos_supported": False,
        "artwork_formats": _format_map(
            caps.cover_art_formats if caps is not None else ()
        ),
        "photo_formats": _format_map(
            caps.photo_formats if caps is not None else ()
        ),
        "chapter_image_formats": {},
    }

    _write_json(root, payload)
    _write_virtual_sysinfo(root, payload)
    _write_virtual_hash_info(root, firewire_guid, hash_iv, hash_rndpart)
    ensure_virtual_itunes_database(root)
    return load_virtual_ipod_info(root)


def ensure_virtual_itunes_database(ipod_path: str | os.PathLike[str]) -> str | None:
    """Create an empty iTunesDB/iTunesCDB for a virtual iPod if it is missing."""

    root = Path(ipod_path).expanduser().resolve()
    existing = resolve_itdb_path(str(root))
    if existing:
        return existing

    info = load_virtual_ipod_info(root)
    return ensure_device_itunes_database(root, info)


def load_virtual_ipod_info(
    ipod_path: str | os.PathLike[str],
) -> DeviceInfo:
    """Load a virtual iPod root into a normal DeviceInfo object."""

    root = Path(ipod_path).expanduser().resolve()
    path = virtual_ipod_info_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"Virtual iPod metadata not found at {path}")

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid virtual iPod metadata at {path}")

    info = DeviceInfo(
        path=str(root),
        mount_name=str(payload.get("mount_name") or root.name or "iPod"),
    )
    info.ipod_name = str(payload.get("ipod_name") or "")
    for field in (
        "model_number",
        "model_family",
        "generation",
        "capacity",
        "color",
        "firewire_guid",
        "serial",
        "firmware",
        "board",
        "product_type",
        "connected_bus",
        "reported_volume_format",
        "filesystem_type",
        "scsi_vendor",
        "scsi_product",
        "scsi_revision",
    ):
        value = payload.get(field)
        if value not in (None, ""):
            setattr(info, field, str(value))
            info._field_sources[field] = VIRTUAL_IPOD_INFO_FILENAME

    # Schema v1 used the ambiguous name ``volume_format`` for this
    # SysInfoExtended hint. Keep old virtual devices readable without
    # conflating it with the host-observed filesystem type.
    if not info.reported_volume_format and payload.get("volume_format"):
        info.reported_volume_format = str(payload["volume_format"])
        info._field_sources["reported_volume_format"] = VIRTUAL_IPOD_INFO_FILENAME

    for field in (
        "family_id",
        "updater_family_id",
        "usb_pid",
        "usb_vid",
        "db_version",
        "shadow_db_version",
        "checksum_type",
        "hashing_scheme",
    ):
        raw_value = payload.get(field)
        if raw_value not in (None, ""):
            value = _coerce_int(raw_value)
            setattr(info, field, value)
            info._field_sources[field] = VIRTUAL_IPOD_INFO_FILENAME

    for field in (
        "uses_sqlite_db",
        "supports_sparse_artwork",
        "podcasts_supported",
        "voice_memos_supported",
    ):
        if field in payload:
            setattr(info, field, bool(payload.get(field)))
            info._field_sources[field] = VIRTUAL_IPOD_INFO_FILENAME

    info.usb_serial = str(payload.get("usb_serial") or info.firewire_guid or "")
    if info.usb_serial:
        info._field_sources["usb_serial"] = VIRTUAL_IPOD_INFO_FILENAME

    info.hash_info_iv = _bytes_from_hex(payload.get("hash_info_iv"), 16)
    info.hash_info_rndpart = _bytes_from_hex(payload.get("hash_info_rndpart"), 12)
    if info.hash_info_iv:
        info._field_sources["hash_info_iv"] = VIRTUAL_IPOD_INFO_FILENAME
    if info.hash_info_rndpart:
        info._field_sources["hash_info_rndpart"] = VIRTUAL_IPOD_INFO_FILENAME

    info.artwork_formats = _coerce_format_map(payload.get("artwork_formats"))
    info.photo_formats = _coerce_format_map(payload.get("photo_formats"))
    info.chapter_image_formats = _coerce_format_map(
        payload.get("chapter_image_formats")
    )
    for field in ("artwork_formats", "photo_formats", "chapter_image_formats"):
        if getattr(info, field):
            info._field_sources[field] = VIRTUAL_IPOD_INFO_FILENAME

    caps = capabilities_for_family_gen(info.model_family, info.generation)
    if caps is not None:
        if not info.db_version:
            info.db_version = caps.db_version
        if info.checksum_type == 99:
            info.checksum_type = int(caps.checksum)
        if not info.artwork_formats:
            info.artwork_formats = _format_map(caps.cover_art_formats)
        if not info.photo_formats:
            info.photo_formats = _format_map(caps.photo_formats)
        info.shadow_db_version = info.shadow_db_version or caps.shadow_db_version
        info.uses_sqlite_db = bool(info.uses_sqlite_db or caps.uses_sqlite_db)
        info.supports_sparse_artwork = bool(
            info.supports_sparse_artwork or caps.supports_sparse_artwork
        )
        info.podcasts_supported = bool(info.podcasts_supported or caps.supports_podcast)

    try:
        total_bytes, _used_bytes, free_bytes = shutil.disk_usage(root)
        info.disk_size_gb = round(total_bytes / 1e9, 1)
        info.free_space_gb = round(free_bytes / 1e9, 1)
    except OSError:
        pass

    info.identification_method = "filesystem"
    return info


def _serial_suffix_by_model() -> dict[str, str]:
    suffix_by_model: dict[str, str] = {}
    ordered_suffixes = sorted(
        SERIAL_SUFFIX_TO_MODEL.items(),
        key=lambda item: (-len(item[0]), item[0]),
    )
    for suffix, model_number in ordered_suffixes:
        suffix_by_model.setdefault(model_number, suffix)
    return suffix_by_model


def _model_display_name(
    model_number: str,
    family: str,
    generation: str,
    capacity: str,
    color: str,
) -> str:
    parts = [family, generation, capacity, color]
    return f"{' '.join(part for part in parts if part)} ({model_number})"


def _generate_serial(suffix: str) -> str:
    prefix = "".join(secrets.choice(_SERIAL_ALPHABET) for _ in range(8))
    return prefix + suffix


def _generate_firewire_guid() -> str:
    while True:
        guid = secrets.token_hex(8).upper()
        if guid != "0" * 16:
            return guid


def _write_json(root: Path, payload: dict[str, Any]) -> None:
    with virtual_ipod_info_path(root).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _write_virtual_sysinfo(root: Path, payload: dict[str, Any]) -> None:
    sysinfo_path = root / "iPod_Control" / "Device" / "SysInfo"
    fields = {
        "ModelNumStr": payload.get("model_number", ""),
        "FirewireGuid": payload.get("firewire_guid", ""),
        "pszSerialNumber": payload.get("serial", ""),
        "BoardHwName": payload.get("board", ""),
        "visibleBuildID": payload.get("firmware", ""),
        "ModelFamily": payload.get("model_family", ""),
        "Generation": payload.get("generation", ""),
        "Capacity": payload.get("capacity", ""),
        "Color": payload.get("color", ""),
        "USBProductID": _hex_int(payload.get("usb_pid")),
        "FamilyID": _hex_int(payload.get("family_id")),
        "UpdaterFamilyID": _hex_int(payload.get("updater_family_id")),
    }
    lines = [f"{key}: {value}" for key, value in fields.items() if value not in ("", None)]
    sysinfo_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_virtual_hash_info(
    root: Path,
    firewire_guid: str,
    hash_iv: bytes,
    hash_rndpart: bytes,
) -> None:
    try:
        from iopenpod.itunesdb_writer.hash72 import write_hash_info

        uuid = bytearray(20)
        guid_bytes = bytes.fromhex(firewire_guid)
        uuid[: len(guid_bytes)] = guid_bytes
        write_hash_info(str(root), bytes(uuid), hash_iv, hash_rndpart)
    except Exception:
        # The in-memory DeviceInfo carries the same values; this file is a
        # compatibility cache for non-GUI write paths.
        return


def _default_firmware(family: str, generation: str) -> str:
    if family == "iPod Classic":
        return "2.0.5"
    if family == "iPod Nano" and generation in {"5th Gen", "6th Gen", "7th Gen"}:
        return "1.0.4"
    if family == "iPod" and generation in {"5th Gen", "5.5th Gen"}:
        return "1.3"
    return "1.0"


def _default_board_name(family: str, generation: str) -> str:
    text = f"{family} {generation}".strip()
    return "".join(ch for ch in text if ch.isalnum()) or "iPod"


def _default_family_id(family: str) -> int:
    family_norm = family.casefold()
    if "shuffle" in family_norm:
        return 0x00000006
    if "nano" in family_norm:
        return 0x0000000A
    if "classic" in family_norm:
        return 0x0000000B
    if "mini" in family_norm:
        return 0x00000008
    return 0x00000001


def _usb_pid_for_identity(family: str, generation: str) -> int:
    normal_pids = {
        pid: identity
        for pid, identity in USB_PID_TO_MODEL.items()
        if pid not in IPOD_RECOVERY_USB_PIDS
    }
    for pid, (pid_family, pid_generation) in normal_pids.items():
        if pid_family == family and pid_generation == generation:
            return pid
    for pid, (pid_family, pid_generation) in normal_pids.items():
        if pid_family == family and not pid_generation:
            return pid
    return 0


def _format_map(formats: Any) -> dict[int, tuple[int, int]]:
    result: dict[int, tuple[int, int]] = {}
    for fmt in formats or ():
        fmt_id = int(fmt.format_id)
        result[fmt_id] = (int(fmt.width), int(fmt.height))
    return result


def _coerce_format_map(value: Any) -> dict[int, tuple[int, int]]:
    if not isinstance(value, dict):
        return {}
    result: dict[int, tuple[int, int]] = {}
    for key, item in value.items():
        try:
            fmt_id = int(key)
            width, height = item
            result[fmt_id] = (int(width), int(height))
        except (TypeError, ValueError):
            continue
    return result


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool) or value in (None, ""):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except ValueError:
        return 0


def _bytes_from_hex(value: Any, expected_len: int) -> bytes:
    if not value:
        return b""
    try:
        data = bytes.fromhex(str(value))
    except ValueError:
        return b""
    return data if len(data) == expected_len else b""


def _hex_int(value: Any) -> str:
    number = _coerce_int(value)
    return f"0x{number:08X}" if number else ""
