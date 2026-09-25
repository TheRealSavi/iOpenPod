"""Pure SysInfo reconciliation and iOpenPod authority-file support."""

from __future__ import annotations

import hashlib
import json
import plistlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from xml.parsers.expat import ExpatError

from device_registry.identifiers import normalize_model_number, normalize_serial
from device_registry.models import (
    DeviceEvidence,
    DeviceIdentifier,
    DeviceProfile,
    EvidenceAuthority,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SYSINFO_AUTHORITY_FILENAME = "iOpenPodSysInfoAuthority"

_CORE_KEYS = frozenset({"pszSerialNumber", "FirewireGuid", "ModelNumStr"})
_DERIVED_KEYS = frozenset(
    {"ModelFamily", "Generation", "Capacity", "Color", "USBProductID"}
)
_CURRENT_HARDWARE_SOURCES = frozenset(
    {
        "scsi_vpd",
        "windows_scsi",
        "linux_scsi",
        "sysfs_vpd",
        "udev_scsi_id",
        "usb_vendor",
        "vpd",
        "iokit",
        "ioctl",
        "device_tree",
        "ioreg",
        "sysfs",
        "udev",
        "wmi",
    }
)


@dataclass(frozen=True, slots=True)
class DeviceMetadataPlan:
    """Desired metadata bytes and whether each atomic replacement is needed."""

    sysinfo: bytes
    sysinfo_extended: bytes
    authority: bytes
    sysinfo_changed: bool
    sysinfo_extended_changed: bool
    authority_changed: bool

    @property
    def changed(self) -> bool:
        return (
            self.sysinfo_changed
            or self.sysinfo_extended_changed
            or self.authority_changed
        )


@dataclass(frozen=True, slots=True)
class _ResolvedField:
    value: str
    source: str
    authority: EvidenceAuthority


def authority_covers_metadata(
    authority: bytes | str,
    *,
    sysinfo: bytes,
    sysinfo_extended: bytes,
) -> bool:
    """Return whether current hardware covers untampered core metadata."""

    parsed = _load_authority(authority)
    if parsed.get("version") != 1 or not _authority_hashes_match(
        parsed,
        sysinfo=sysinfo,
        sysinfo_extended=sysinfo_extended,
    ):
        return False
    fields = _string_object_dict(parsed.get("fields"))
    if fields is None:
        return False
    sysinfo_values = _parse_sysinfo(sysinfo)
    for key in _CORE_KEYS:
        entry = _string_object_dict(fields.get(key))
        if entry is None:
            return False
        if _entry_authority(entry) is not EvidenceAuthority.CURRENT_HARDWARE:
            return False
        expected = entry.get("value")
        current = sysinfo_values.get(key, "")
        if not isinstance(expected, str) or not current:
            return False
        if _normalize_sysinfo_value(key, expected) != _normalize_sysinfo_value(
            key,
            current,
        ):
            return False
    return True


def reconcile_device_metadata(
    *,
    evidence: DeviceEvidence,
    profile: DeviceProfile,
    existing_sysinfo: bytes = b"",
    existing_sysinfo_extended: bytes = b"",
    existing_authority: bytes = b"",
    live_sysinfo_extended: bytes = b"",
    observed_at: str | None = None,
) -> DeviceMetadataPlan:
    """Build a deterministic, path-free plan from ranked evidence.

    Unknown SysInfo keys and SysInfoExtended plist keys are retained. Current
    hardware can correct stale device metadata, while lower-authority values cannot
    overwrite higher-authority entries recorded by the original version-1 format.
    """

    timestamp = observed_at or datetime.now(UTC).isoformat()
    old_authority = _load_authority(existing_authority)
    hashes_match = _authority_hashes_match(
        old_authority,
        sysinfo=existing_sysinfo,
        sysinfo_extended=existing_sysinfo_extended,
    )
    old_entries = (
        _string_object_dict(old_authority.get("fields")) if hashes_match else {}
    )
    if old_entries is None:
        old_entries = {}

    existing_fields = _parse_sysinfo(existing_sysinfo)
    updated_fields = dict(existing_fields)
    resolved = _resolved_fields(evidence, profile)
    authority_fields: dict[str, object] = {}

    for key, candidate in resolved.items():
        old_value = existing_fields.get(key, "")
        old_entry = _string_object_dict(old_entries.get(key)) or {}
        old_authority_level = _entry_authority(old_entry)
        if not old_entry:
            old_authority_level = EvidenceAuthority.DEVICE_METADATA

        same_value = bool(old_value) and _normalize_sysinfo_value(
            key,
            old_value,
        ) == _normalize_sysinfo_value(key, candidate.value)
        should_replace_value = (
            not old_value
            or key in _DERIVED_KEYS
            or candidate.authority >= old_authority_level
        )
        if should_replace_value and not same_value:
            updated_fields[key] = candidate.value
        retained_value = updated_fields.get(key, "")
        if not retained_value:
            continue

        use_candidate_provenance = (
            not old_entry
            or candidate.authority >= old_authority_level
            or (key in _DERIVED_KEYS and not same_value)
        )
        if use_candidate_provenance:
            source = candidate.source
            authority_level = candidate.authority
        else:
            source = _entry_source(old_entry, default="sysinfo")
            authority_level = old_authority_level
        authority_fields[key] = _authority_entry(
            retained_value,
            source=source,
            authority=authority_level,
            timestamp=timestamp,
            previous=old_entry,
        )

    for key, entry in old_entries.items():
        if key in authority_fields or key not in updated_fields:
            continue
        typed_entry = _string_object_dict(entry)
        if typed_entry is not None:
            authority_fields[key] = typed_entry

    sysinfo = _serialize_sysinfo(updated_fields)
    sysinfo_extended = _build_sysinfo_extended(
        existing=existing_sysinfo_extended,
        live=live_sysinfo_extended,
        sysinfo_fields=updated_fields,
        profile=profile,
    )

    file_hashes = {
        "SysInfo": _sha256(sysinfo),
        "SysInfoExtended": _sha256(sysinfo_extended),
    }
    files: dict[str, object] = dict(
        _string_object_dict(old_authority.get("files")) or {}
    )
    previous_extended_file = _string_object_dict(files.get("SysInfoExtended"))
    extended_source = "device_registry"
    if live_sysinfo_extended:
        extended_source = _live_payload_source(evidence)
    elif (
        existing_sysinfo_extended == sysinfo_extended
        and previous_extended_file is not None
        and isinstance(previous_extended_file.get("source"), str)
    ):
        extended_source = cast("str", previous_extended_file["source"])
    elif existing_sysinfo_extended:
        extended_source = "sysinfo_extended"
    if not (
        previous_extended_file is not None
        and previous_extended_file.get("source") == extended_source
        and previous_extended_file.get("bytes") == len(sysinfo_extended)
        and existing_sysinfo_extended == sysinfo_extended
    ):
        files["SysInfoExtended"] = {
            "source": extended_source,
            "updated": timestamp,
            "bytes": len(sysinfo_extended),
        }

    authority_document: dict[str, object] = {
        "version": 1,
        "fields": authority_fields,
        "files": files,
        "file_hashes": file_hashes,
    }
    old_without_timestamp = {
        key: value for key, value in old_authority.items() if key != "last_updated"
    }
    if old_without_timestamp == authority_document and existing_authority:
        authority = existing_authority
    else:
        authority_document["last_updated"] = timestamp
        authority = (
            json.dumps(authority_document, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")

    return DeviceMetadataPlan(
        sysinfo=sysinfo,
        sysinfo_extended=sysinfo_extended,
        authority=authority,
        sysinfo_changed=sysinfo != existing_sysinfo,
        sysinfo_extended_changed=sysinfo_extended != existing_sysinfo_extended,
        authority_changed=authority != existing_authority,
    )


def _resolved_fields(
    evidence: DeviceEvidence,
    profile: DeviceProfile,
) -> dict[str, _ResolvedField]:
    result: dict[str, _ResolvedField] = {}
    serial = _best_identifier(evidence.product_serials)
    transport = _best_identifier(evidence.transport_serials)
    firmware = _best_identifier(evidence.firmware_versions)
    board = _best_identifier(evidence.board_hardware_names)
    family_id = _best_identifier(evidence.family_ids)
    updater_family_id = _best_identifier(evidence.updater_family_ids)
    usb = _best_identifier(evidence.usb_identifiers)
    model_proof = _model_proof(evidence, profile)

    _put(result, "pszSerialNumber", serial, _format_serial)
    _put(result, "FirewireGuid", transport, _format_guid)
    _put(result, "visibleBuildID", firmware, str)
    _put(result, "BoardHwName", board, str)
    result["ModelNumStr"] = _ResolvedField(
        _format_model_number(profile.model_number),
        model_proof.source,
        model_proof.authority,
    )
    _put(result, "FamilyID", family_id, str)
    _put(result, "UpdaterFamilyID", updater_family_id, str)

    result["ModelFamily"] = _ResolvedField(
        profile.family,
        "model_table",
        EvidenceAuthority.DERIVED,
    )
    result["Generation"] = _ResolvedField(
        profile.generation,
        "model_table",
        EvidenceAuthority.DERIVED,
    )
    result["Capacity"] = _ResolvedField(
        profile.advertised_capacity,
        "model_table",
        EvidenceAuthority.DERIVED,
    )
    result["Color"] = _ResolvedField(
        profile.finish,
        "model_table",
        EvidenceAuthority.DERIVED,
    )
    if usb is not None:
        result["USBProductID"] = _ResolvedField(
            f"0x{usb.value.product_id:04X}",
            usb.source,
            usb.authority,
        )
    return result


def _put[Value](
    result: dict[str, _ResolvedField],
    key: str,
    identifier: DeviceIdentifier[Value] | None,
    formatter: Any,
) -> None:
    if identifier is None:
        return
    formatted = str(formatter(identifier.value)).strip()
    if formatted:
        result[key] = _ResolvedField(
            formatted,
            identifier.source,
            identifier.authority,
        )


def _best_identifier[Value](
    identifiers: Sequence[DeviceIdentifier[Value]],
) -> DeviceIdentifier[Value] | None:
    if not identifiers:
        return None
    return max(
        identifiers,
        key=lambda item: (int(item.authority), item.source.casefold()),
    )


def _model_proof(
    evidence: DeviceEvidence,
    profile: DeviceProfile,
) -> _ResolvedField:
    matching = tuple(
        identifier
        for identifier in evidence.model_numbers
        if normalize_model_number(identifier.value) == profile.model_number
    )
    direct = _best_identifier(matching)
    serial = _best_identifier(
        tuple(
            identifier
            for identifier in evidence.product_serials
            if _serial_resolves_to_profile(identifier.value, profile)
        )
    )
    proofs = tuple(
        _ResolvedField(profile.model_number, item.source, item.authority)
        for item in (direct, serial)
        if item is not None
    )
    if proofs:
        return max(
            proofs,
            key=lambda proof: (int(proof.authority), proof.source.casefold()),
        )
    return _ResolvedField(
        profile.model_number,
        "model_table",
        EvidenceAuthority.DERIVED,
    )


def _serial_resolves_to_profile(value: str, profile: DeviceProfile) -> bool:
    # Local import avoids coupling catalog construction back to reconciliation.
    from device_registry.data.catalog import DEFAULT_CATALOG

    serial = normalize_serial(value)
    matches = tuple(
        definition
        for definition in DEFAULT_CATALOG.serial_suffixes
        if serial.endswith(definition.suffix)
    )
    if not matches:
        return False
    longest = max(len(definition.suffix) for definition in matches)
    models = {
        definition.model_number
        for definition in matches
        if len(definition.suffix) == longest
    }
    return models == {profile.model_number}


def _build_sysinfo_extended(
    *,
    existing: bytes,
    live: bytes,
    sysinfo_fields: Mapping[str, str],
    profile: DeviceProfile,
) -> bytes:
    values = _load_plist_mapping(live) if live else _load_plist_mapping(existing)
    values = dict(values)

    _set_if(values, "SerialNumber", sysinfo_fields.get("pszSerialNumber", ""))
    _set_if(
        values,
        "FireWireGUID",
        _normalize_sysinfo_value(
            "FirewireGuid",
            sysinfo_fields.get("FirewireGuid", ""),
        ),
    )
    _set_if(values, "FireWireVersion", sysinfo_fields.get("visibleBuildID", ""))
    _set_if(values, "BoardHwName", sysinfo_fields.get("BoardHwName", ""))
    _set_if(values, "ModelNumStr", profile.model_number)
    _set_integer(values, "FamilyID", sysinfo_fields.get("FamilyID", ""))
    _set_integer(
        values,
        "UpdaterFamilyID",
        sysinfo_fields.get("UpdaterFamilyID", ""),
    )
    usb_product_id = _parse_integer(sysinfo_fields.get("USBProductID", ""))
    if usb_product_id is not None:
        values["usb_vid"] = 0x05AC
        values["usb_pid"] = usb_product_id

    capabilities = profile.capabilities
    values["ProductType"] = profile.family
    values["DBVersion"] = capabilities.database.binary_version
    values["SQLiteDB"] = capabilities.database.uses_sqlite_database
    values["PodcastsSupported"] = capabilities.audio.supports_podcasts
    values["ScreenWidth"] = capabilities.display.width
    values["ScreenHeight"] = capabilities.display.height
    values["ColorDisplay"] = capabilities.display.color
    values["VideoSupported"] = capabilities.video.supported
    if capabilities.video.supported:
        values["MaxVideoWidth"] = capabilities.video.max_width
        values["MaxVideoHeight"] = capabilities.video.max_height
    else:
        values.pop("MaxVideoWidth", None)
        values.pop("MaxVideoHeight", None)
    if capabilities.artwork.cover_formats:
        values["AlbumArt"] = [
            _artwork_plist_entry(item) for item in capabilities.artwork.cover_formats
        ]
    else:
        values.pop("AlbumArt", None)
    if capabilities.artwork.photo_formats:
        values["ImageSpecifications"] = [
            _artwork_plist_entry(item) for item in capabilities.artwork.photo_formats
        ]
    else:
        values.pop("ImageSpecifications", None)
    return plistlib.dumps(values, fmt=plistlib.FMT_XML, sort_keys=True)


def _artwork_plist_entry(item: Any) -> dict[str, object]:
    return {
        "FormatId": item.format_id,
        "RenderWidth": item.width,
        "RenderHeight": item.height,
        "RowBytes": item.row_bytes,
        "PixelFormat": item.pixel_format.value,
    }


def _string_object_dict(value: object) -> dict[str, object] | None:
    """Validate and narrow an untyped serialized mapping."""

    if not isinstance(value, dict):
        return None
    raw = cast("dict[object, object]", value)
    result: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            return None
        result[key] = item
    return result


def _load_plist_mapping(content: bytes) -> Mapping[str, object]:
    if not content:
        return {}
    raw = content.rstrip(b"\x00")
    starts = tuple(
        index
        for marker in (b"<?xml", b"<plist", b"bplist")
        if (index := raw.find(marker)) >= 0
    )
    if starts:
        raw = raw[min(starts) :]
    candidates = [raw]
    if b"<plist" in raw and b"</plist>" not in raw:
        candidates.append(raw + b"\n</dict>\n</plist>")
    for candidate in candidates:
        try:
            parsed = cast("object", plistlib.loads(candidate))
        except (ExpatError, plistlib.InvalidFileException, TypeError, ValueError):
            continue
        mapping = _string_object_dict(parsed)
        if mapping is not None:
            return mapping
    return {}


def _parse_sysinfo(content: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    text = content.decode("utf-8-sig", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", maxsplit=1)
        normalized_key = key.strip()
        if normalized_key:
            result[normalized_key] = value.strip()
    return result


def _serialize_sysinfo(values: Mapping[str, str]) -> bytes:
    return (
        "".join(f"{key}: {value}\n" for key, value in values.items() if value)
    ).encode("utf-8")


def _load_authority(content: bytes | str) -> dict[str, object]:
    if not content:
        return {}
    try:
        parsed = cast("object", json.loads(content))
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return {}
    return _string_object_dict(parsed) or {}


def _authority_hashes_match(
    authority: Mapping[str, object],
    *,
    sysinfo: bytes,
    sysinfo_extended: bytes,
) -> bool:
    hashes = _string_object_dict(authority.get("file_hashes"))
    if not hashes:
        return False
    expected_sysinfo = hashes.get("SysInfo")
    if not isinstance(expected_sysinfo, str) or expected_sysinfo != _sha256(sysinfo):
        return False
    expected_extended = hashes.get("SysInfoExtended")
    return expected_extended is None or (
        isinstance(expected_extended, str)
        and expected_extended == _sha256(sysinfo_extended)
    )


def _authority_entry(
    value: str,
    *,
    source: str,
    authority: EvidenceAuthority,
    timestamp: str,
    previous: Mapping[str, object],
) -> dict[str, object]:
    authority_name = authority.name.casefold()
    if (
        previous.get("value") == value
        and previous.get("source") == source
        and previous.get("authority", authority_name) == authority_name
        and isinstance(previous.get("updated"), str)
    ):
        updated = cast("str", previous["updated"])
    else:
        updated = timestamp
    return {
        "value": value,
        "source": source,
        "authority": authority_name,
        "updated": updated,
    }


def _entry_authority(entry: Mapping[str, object]) -> EvidenceAuthority:
    raw = entry.get("authority")
    if isinstance(raw, str):
        try:
            return EvidenceAuthority[raw.upper()]
        except KeyError:
            pass
    source = _entry_source(entry, default="sysinfo")
    if source in _CURRENT_HARDWARE_SOURCES:
        return EvidenceAuthority.CURRENT_HARDWARE
    if source in {"model_table", "serial_lookup", "usb_pid", "inferred"}:
        return EvidenceAuthority.DERIVED
    return EvidenceAuthority.DEVICE_METADATA


def _entry_source(entry: Mapping[str, object], *, default: str) -> str:
    source = entry.get("source")
    return source if isinstance(source, str) and source.strip() else default


def _format_serial(value: object) -> str:
    return normalize_serial(str(value))


def _format_guid(value: object) -> str:
    normalized = normalize_serial(str(value).removeprefix("0x").removeprefix("0X"))
    return f"0x{normalized}" if normalized else ""


def _format_model_number(value: str) -> str:
    normalized = normalize_model_number(value)
    return f"x{normalized[1:]}" if normalized.startswith("M") else normalized


def _normalize_sysinfo_value(key: str, value: object) -> str:
    text = str(value).strip().rstrip("\x00")
    if key == "FirewireGuid":
        return text.removeprefix("0x").removeprefix("0X").upper()
    if key == "ModelNumStr":
        return normalize_model_number(text)
    if key == "USBProductID":
        parsed = _parse_integer(text)
        return str(parsed) if parsed is not None else text.upper()
    return text


def _parse_integer(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except ValueError:
        return None


def _set_if(values: dict[str, object], key: str, value: str) -> None:
    if value:
        values[key] = value


def _set_integer(values: dict[str, object], key: str, value: str) -> None:
    parsed = _parse_integer(value)
    if parsed is not None:
        values[key] = parsed


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _live_payload_source(evidence: DeviceEvidence) -> str:
    candidates: list[DeviceIdentifier[object]] = [
        *evidence.product_serials,
        *evidence.transport_serials,
        *evidence.firmware_versions,
    ]
    current = tuple(
        item
        for item in candidates
        if item.authority is EvidenceAuthority.CURRENT_HARDWARE
    )
    best = _best_identifier(current)
    return best.source if best is not None else "current_hardware"
