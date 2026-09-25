"""Pure adapters from iPod metadata payloads to typed Device Evidence."""

from __future__ import annotations

import plistlib
import re
from typing import TYPE_CHECKING, cast
from xml.parsers.expat import ExpatError

if TYPE_CHECKING:
    from collections.abc import Mapping

from device_registry.identifiers import (
    APPLE_USB_VENDOR_ID,
    normalize_model_number,
    normalize_serial,
    parse_unsigned_integer,
)
from device_registry.models import (
    DeviceEvidence,
    DeviceIdentifier,
    EvidenceAuthority,
    UsbIdentifier,
)


def parse_sysinfo(
    content: str | bytes,
    *,
    source: str = "SysInfo",
    authority: EvidenceAuthority = EvidenceAuthority.DEVICE_METADATA,
) -> DeviceEvidence:
    """Parse a SysInfo payload already read by an authorized caller.

    This function intentionally accepts content rather than a path. It never probes
    hardware or reads a mounted Volume; Storage and the Application Layer own that
    work.
    """

    text = (
        content.decode("utf-8-sig", errors="replace")
        if isinstance(content, bytes)
        else content
    )
    values = _parse_key_values(text)

    model_numbers = _text_identifier(
        normalize_model_number(values.get("ModelNumStr", "")),
        source,
        authority,
    )
    product_serials = _text_identifier(
        normalize_serial(values.get("pszSerialNumber", "")),
        source,
        authority,
    )
    transport_serials = _text_identifier(
        _normalize_transport_serial(values.get("FirewireGuid", "")),
        source,
        authority,
    )
    board_hardware_names = _text_identifier(
        values.get("BoardHwName", "").strip(),
        source,
        authority,
    )
    firmware = next(
        (
            values[key].strip()
            for key in ("visibleBuildID", "VisibleBuildID", "BuildID")
            if values.get(key, "").strip()
        ),
        "",
    )
    firmware_versions = _text_identifier(firmware, source, authority)

    usb_identifiers: tuple[DeviceIdentifier[UsbIdentifier], ...] = ()
    usb_product_id = _parse_usb_product_id(values.get("USBProductID", ""))
    if usb_product_id is not None:
        usb_identifiers = (
            DeviceIdentifier(
                value=UsbIdentifier(
                    vendor_id=APPLE_USB_VENDOR_ID,
                    product_id=usb_product_id,
                ),
                source=source,
                authority=authority,
            ),
        )

    return DeviceEvidence(
        model_numbers=model_numbers,
        product_serials=product_serials,
        transport_serials=transport_serials,
        usb_identifiers=usb_identifiers,
        board_hardware_names=board_hardware_names,
        firmware_versions=firmware_versions,
        family_ids=_integer_identifier(
            values.get("FamilyID") or values.get("iPodFamily") or "",
            source,
            authority,
        ),
        updater_family_ids=_integer_identifier(
            values.get("UpdaterFamilyID", ""),
            source,
            authority,
        ),
    )


def parse_sysinfo_extended(
    content: str | bytes,
    *,
    source: str = "SysInfoExtended",
    authority: EvidenceAuthority = EvidenceAuthority.DEVICE_METADATA,
) -> DeviceEvidence:
    """Parse identity evidence from SysInfoExtended bytes supplied by a caller.

    Real iPods expose this metadata as a plist, but some payloads are wrapped in
    transport bytes or truncated after their scalar fields.  A strict plist parse
    is preferred; the bounded fallback only recovers scalar key/value pairs and
    never evaluates or follows data from the payload.
    """

    raw = (
        content.encode("utf-8", errors="replace")
        if isinstance(content, str)
        else content
    )
    plist = _load_plist_mapping(_extract_plist_bytes(raw))

    serial = _mapping_text(plist, "SerialNumber")
    if serial.upper().startswith("RAND"):
        serial = ""
    transport_serial = _normalize_transport_serial(
        _first_mapping_text(
            plist,
            "FireWireGUID",
            "FirewireGuid",
            "FireWireGuid",
            "usb_serial",
        )
    )
    model_number = normalize_model_number(_mapping_text(plist, "ModelNumStr"))
    firmware = _first_mapping_text(
        plist,
        "FireWireVersion",
        "scsi_revision",
        "VisibleBuildID",
        "BuildID",
        "visibleBuildID",
    )
    board = _first_mapping_text(plist, "BoardHwName", "BoardHwID")

    usb_identifiers: tuple[DeviceIdentifier[UsbIdentifier], ...] = ()
    usb_vendor_id = _mapping_integer(plist, "usb_vid")
    usb_product_id = _mapping_integer(plist, "usb_pid")
    if usb_product_id is None:
        usb_product_id = _mapping_integer(plist, "USBProductID")
    if usb_product_id is not None:
        usb_identifiers = (
            DeviceIdentifier(
                value=UsbIdentifier(
                    vendor_id=(
                        usb_vendor_id
                        if usb_vendor_id is not None
                        else APPLE_USB_VENDOR_ID
                    ),
                    product_id=usb_product_id,
                ),
                source=source,
                authority=authority,
            ),
        )

    return DeviceEvidence(
        model_numbers=_text_identifier(model_number, source, authority),
        product_serials=_text_identifier(
            normalize_serial(serial),
            source,
            authority,
        ),
        transport_serials=_text_identifier(
            transport_serial,
            source,
            authority,
        ),
        usb_identifiers=usb_identifiers,
        board_hardware_names=_text_identifier(board, source, authority),
        firmware_versions=_text_identifier(firmware, source, authority),
        family_ids=_mapping_integer_identifier(
            plist,
            "FamilyID",
            source,
            authority,
        ),
        updater_family_ids=_mapping_integer_identifier(
            plist,
            "UpdaterFamilyID",
            source,
            authority,
        ),
    )


def _parse_key_values(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", maxsplit=1)
        normalized_key = key.strip()
        if normalized_key:
            values[normalized_key] = value.strip()
    return values


def _extract_plist_bytes(raw: bytes) -> bytes:
    starts = tuple(
        index
        for marker in (b"<?xml", b"<plist", b"bplist")
        if (index := raw.find(marker)) >= 0
    )
    if starts:
        raw = raw[min(starts) :]
    return raw.rstrip(b"\x00")


def _load_plist_mapping(raw: bytes) -> Mapping[str, object]:
    if raw:
        candidates = [raw]
        if b"<plist" in raw and b"</plist>" not in raw:
            candidates.append(raw + b"\n</dict>\n</plist>")
        for candidate in candidates:
            try:
                parsed = plistlib.loads(candidate)
            except (
                ExpatError,
                plistlib.InvalidFileException,
                TypeError,
                ValueError,
            ):
                continue
            if isinstance(parsed, dict):
                untyped_mapping = cast("dict[object, object]", parsed)
                validated: dict[str, object] = {}
                for key, value in untyped_mapping.items():
                    if not isinstance(key, str):
                        break
                    validated[key] = value
                else:
                    return validated
    return _parse_plist_scalars(raw)


def _parse_plist_scalars(raw: bytes) -> Mapping[str, object]:
    text = raw.decode("utf-8", errors="replace")
    result: dict[str, object] = {}
    pattern = re.compile(
        r"<key>([^<]+)</key>\s*"
        r"(?:(?:<string>(.*?)</string>)|(?:<integer>(.*?)</integer>)|"
        r"(<true\s*/>)|(<false\s*/>))",
        flags=re.DOTALL,
    )
    for match in pattern.finditer(text):
        key = match.group(1).strip()
        if not key:
            continue
        if match.group(2) is not None:
            result[key] = match.group(2).strip()
        elif match.group(3) is not None:
            integer = parse_unsigned_integer(match.group(3))
            result[key] = integer if integer is not None else match.group(3).strip()
        else:
            result[key] = match.group(4) is not None
    return result


def _mapping_text(values: Mapping[str, object], key: str) -> str:
    value = values.get(key)
    return value.strip() if isinstance(value, str) else ""


def _first_mapping_text(values: Mapping[str, object], *keys: str) -> str:
    return next(
        (value for key in keys if (value := _mapping_text(values, key))),
        "",
    )


def _mapping_integer(values: Mapping[str, object], key: str) -> int | None:
    value = values.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        return parse_unsigned_integer(value)
    return None


def _mapping_integer_identifier(
    values: Mapping[str, object],
    key: str,
    source: str,
    authority: EvidenceAuthority,
) -> tuple[DeviceIdentifier[int], ...]:
    value = _mapping_integer(values, key)
    if value is None:
        return ()
    return (DeviceIdentifier(value=value, source=source, authority=authority),)


def _text_identifier(
    value: str,
    source: str,
    authority: EvidenceAuthority,
) -> tuple[DeviceIdentifier[str], ...]:
    if not value:
        return ()
    return (DeviceIdentifier(value=value, source=source, authority=authority),)


def _integer_identifier(
    value: str,
    source: str,
    authority: EvidenceAuthority,
) -> tuple[DeviceIdentifier[int], ...]:
    parsed = parse_unsigned_integer(value)
    if parsed is None:
        return ()
    return (DeviceIdentifier(value=parsed, source=source, authority=authority),)


def _parse_usb_product_id(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    if not text.lower().startswith("0x") and len(text) == 4:
        try:
            return int(text, 16)
        except ValueError:
            return None
    return parse_unsigned_integer(text)


def _normalize_transport_serial(value: str) -> str:
    normalized = normalize_serial(value.removeprefix("0x").removeprefix("0X"))
    if not normalized or set(normalized) == {"0"}:
        return ""
    return normalized
