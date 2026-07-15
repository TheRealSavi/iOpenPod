"""
Parsing and evidence helpers for iPod SysInfo and SysInfoExtended data.

This module intentionally contains no hardware probing.  It accepts bytes or
text gathered from files, SCSI VPD, or USB vendor-control reads and turns them
into source-tagged identity/capability data that the scanner and DeviceInfo
enrichment code can consume consistently.
"""

from __future__ import annotations

import plistlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

COVER_ART_KEYS: tuple[str, ...] = (
    "AlbumArt",
    "AlbumArt2",
    "ArtworkFormats",
    "CoverArt",
    "ArtworkCoverArtFormats",
)

PHOTO_ART_KEYS: tuple[str, ...] = (
    "ImageSpecifications",
    "PhotoFormats",
)

CHAPTER_ART_KEYS: tuple[str, ...] = (
    "ChapterImageSpecs",
    "ChapterImageSpecifications",
)


@dataclass(frozen=True)
class EvidenceValue:
    """One resolved value with provenance."""

    value: Any
    source: str
    live: bool = False
    raw_key: str = ""


@dataclass
class DeviceEvidence:
    """Small source-tagged container for identity and capability evidence."""

    fields: dict[str, EvidenceValue] = field(default_factory=dict)
    blobs: dict[str, Any] = field(default_factory=dict)

    def add(
        self,
        field_name: str,
        value: Any,
        source: str,
        *,
        live: bool = False,
        raw_key: str = "",
        replace: bool = False,
    ) -> None:
        if value in (None, "", b""):
            return
        if field_name in self.fields and not replace:
            return
        self.fields[field_name] = EvidenceValue(
            value=value,
            source=source,
            live=live,
            raw_key=raw_key,
        )

    def as_flat_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {k: v.value for k, v in self.fields.items()}
        result["_sources"] = {k: v.source for k, v in self.fields.items()}
        return result


@dataclass
class ParsedSysInfoExtended:
    """Parsed representation of a SysInfoExtended XML/plist blob."""

    plist: dict[str, Any]
    raw_xml: bytes = b""
    source: str = "sysinfo_extended"
    live: bool = False
    used_regex_fallback: bool = False

    @property
    def identity(self) -> dict[str, Any]:
        return identity_from_sysinfo_extended(self, self.source, live=self.live)

    @property
    def cover_art_formats(self) -> dict[int, tuple[int, int]]:
        return extract_image_formats(self.plist, COVER_ART_KEYS)

    @property
    def photo_formats(self) -> dict[int, tuple[int, int]]:
        return extract_image_formats(self.plist, PHOTO_ART_KEYS)

    @property
    def chapter_image_formats(self) -> dict[int, tuple[int, int]]:
        return extract_image_formats(self.plist, CHAPTER_ART_KEYS)


def normalize_guid(value: Any) -> str:
    """Return a compact uppercase 16-hex GUID-ish string, or empty string."""
    if value is None:
        return ""
    guid = str(value).strip().replace(" ", "")
    if guid.startswith(("0x", "0X")):
        guid = guid[2:]
    if not guid or guid == "0" * len(guid):
        return ""
    try:
        bytes.fromhex(guid)
    except ValueError:
        return ""
    return guid.upper()


def _coerce_int(value: Any) -> int | str:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return 0
    # SysInfo often stores values like "0x00000003" or
    # "0x00000003 (3.0 0)"; only the leading numeric token matters.
    token = text.split(None, 1)[0]
    try:
        return int(token, 0)
    except ValueError:
        return text


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().casefold()
    return text in {"1", "true", "yes", "y", "on"}


def parse_sysinfo_text(content: str) -> dict[str, str]:
    """Parse plain SysInfo key/value text."""
    result: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def identity_from_sysinfo(
    sysinfo: dict[str, str],
    source: str = "sysinfo",
) -> dict[str, Any]:
    """Return normalized DeviceInfo-style fields from a SysInfo dict."""
    result: dict[str, Any] = {"_sources": {}}
    sources: dict[str, str] = result["_sources"]

    board = sysinfo.get("BoardHwName", "")
    if board:
        result["board"] = board
        sources["board"] = source

    serial = sysinfo.get("pszSerialNumber", "").strip()
    if serial:
        result["serial"] = serial
        sources["serial"] = source

    guid = normalize_guid(sysinfo.get("FirewireGuid", ""))
    if guid:
        result["firewire_guid"] = guid
        sources["firewire_guid"] = source

    firmware = (
        sysinfo.get("visibleBuildID")
        or sysinfo.get("VisibleBuildID")
        or sysinfo.get("BuildID")
        or ""
    )
    if firmware:
        result["firmware"] = firmware
        sources["firmware"] = source

    raw_model = sysinfo.get("ModelNumStr", "")
    if raw_model:
        try:
            from .lookup import extract_model_number

            model_number = extract_model_number(raw_model)
        except Exception:
            model_number = raw_model.strip()
        if model_number:
            result["model_raw"] = raw_model
            result["model_number"] = model_number
            sources["model_number"] = source

    for key, field_name in (
        ("ModelFamily", "model_family"),
        ("Generation", "generation"),
        ("Capacity", "capacity"),
        ("Color", "color"),
    ):
        value = sysinfo.get(key, "")
        if value:
            result[field_name] = value
            sources[field_name] = source

    pid = sysinfo.get("USBProductID", "")
    if pid:
        try:
            result["usb_pid"] = int(pid, 0)
            sources["usb_pid"] = source
        except ValueError:
            pass

    for keys, field_name in (
        (("FamilyID", "iPodFamily"), "family_id"),
        (("UpdaterFamilyID",), "updater_family_id"),
    ):
        value = next((sysinfo.get(key) for key in keys if key in sysinfo), None)
        if value not in (None, ""):
            result[field_name] = _coerce_int(value)
            sources[field_name] = source

    return result


def parse_sysinfo_extended(
    content: bytes | str,
    *,
    source: str = "sysinfo_extended",
    live: bool = False,
) -> ParsedSysInfoExtended:
    """Parse SysInfoExtended XML/plist data.

    The same payload can come from an on-disk file, SCSI VPD pages, or Apple's
    USB vendor-control command.  Some devices return leading/trailing bytes or
    truncated XML; plist parsing is tried first, then a conservative regex
    fallback extracts scalar fields.
    """
    if isinstance(content, str):
        raw = content.encode("utf-8", errors="replace")
    else:
        raw = bytes(content)

    raw = _extract_xml_bytes(raw)
    plist: dict[str, Any] = {}
    used_fallback = False

    if raw:
        parse_candidates = [raw]
        if b"</plist>" not in raw:
            parse_candidates.append(raw + b"\n</dict>\n</plist>")

        for candidate in parse_candidates:
            try:
                parsed = plistlib.loads(candidate)
            except Exception:
                continue
            if isinstance(parsed, dict):
                plist = parsed
                raw = candidate
                break

    if not plist:
        plist = _parse_sysinfo_extended_regex(raw)
        used_fallback = bool(plist)

    return ParsedSysInfoExtended(
        plist=plist,
        raw_xml=raw,
        source=source,
        live=live,
        used_regex_fallback=used_fallback,
    )


def identity_from_sysinfo_extended(
    parsed: ParsedSysInfoExtended | dict[str, Any],
    source: str = "sysinfo_extended",
    *,
    live: bool = False,
) -> dict[str, Any]:
    """Return normalized DeviceInfo-style fields from SysInfoExtended data."""
    plist = parsed.plist if isinstance(parsed, ParsedSysInfoExtended) else parsed
    result: dict[str, Any] = {"_sources": {}}
    sources: dict[str, str] = result["_sources"]

    def put(field_name: str, value: Any, raw_key: str = "") -> None:
        if value in (None, ""):
            return
        result[field_name] = value
        sources[field_name] = source

    serial = str(plist.get("SerialNumber") or "").strip()
    if serial and not serial.upper().startswith("RAND"):
        put("serial", serial, "SerialNumber")

    guid = normalize_guid(
        plist.get("FireWireGUID")
        or plist.get("FirewireGuid")
        or plist.get("FireWireGuid")
    )
    if guid:
        put("firewire_guid", guid, "FireWireGUID")

    firmware = (
        plist.get("FireWireVersion")
        or plist.get("scsi_revision")
        or plist.get("VisibleBuildID")
        or plist.get("BuildID")
        or plist.get("visibleBuildID")
        or ""
    )
    if firmware:
        put("firmware", str(firmware), "FireWireVersion")

    board = plist.get("BoardHwName") or plist.get("BoardHwID") or ""
    if board:
        put("board", str(board), "BoardHwName")

    raw_model = str(plist.get("ModelNumStr") or "").strip()
    if raw_model:
        try:
            from .lookup import extract_model_number

            model_number = extract_model_number(raw_model)
        except Exception:
            model_number = raw_model
        if model_number:
            result["model_raw"] = raw_model
            put("model_number", model_number, "ModelNumStr")

    for key, field_name in (
        ("FamilyID", "family_id"),
        ("UpdaterFamilyID", "updater_family_id"),
        ("DBVersion", "db_version"),
        ("ShadowDBVersion", "shadow_db_version"),
        ("MaxTracks", "max_tracks"),
        ("MaxTransferSpeed", "max_transfer_speed"),
    ):
        if key in plist:
            put(field_name, _coerce_int(plist[key]), key)

    for key, field_name in (
        ("ProductType", "product_type"),
        ("ConnectedBus", "connected_bus"),
        ("VolumeFormat", "volume_format"),
        ("scsi_vendor", "scsi_vendor"),
        ("scsi_product", "scsi_product"),
        ("scsi_revision", "scsi_revision"),
        ("usb_serial", "usb_serial"),
    ):
        if key in plist:
            put(field_name, str(plist[key]), key)

    for key, field_name in (
        ("usb_pid", "usb_pid"),
        ("usb_vid", "usb_vid"),
        ("MaxFileSizeInGB", "max_file_size_gb"),
    ):
        if key in plist:
            put(field_name, _coerce_int(plist[key]), key)

    for key, field_name in (
        ("SQLiteDB", "uses_sqlite_db"),
        ("SupportsSparseArtwork", "supports_sparse_artwork"),
        ("PodcastsSupported", "podcasts_supported"),
        ("VoiceMemosSupported", "voice_memos_supported"),
    ):
        if key in plist:
            put(field_name, _coerce_bool(plist[key]), key)

    for key, field_name in (
        ("AudioCodecs", "audio_codecs"),
        ("PowerInformation", "power_information"),
        ("AppleDRMVersion", "apple_drm_version"),
    ):
        value = plist.get(key)
        if isinstance(value, dict):
            put(field_name, value, key)

    artwork_formats = extract_image_formats(plist, COVER_ART_KEYS)
    if artwork_formats:
        result["artwork_formats"] = artwork_formats
        sources["artwork_formats"] = source
    photo_formats = extract_image_formats(plist, PHOTO_ART_KEYS)
    if photo_formats:
        result["photo_formats"] = photo_formats
        sources["photo_formats"] = source
    chapter_formats = extract_image_formats(plist, CHAPTER_ART_KEYS)
    if chapter_formats:
        result["chapter_image_formats"] = chapter_formats
        sources["chapter_image_formats"] = source

    if isinstance(parsed, ParsedSysInfoExtended):
        if parsed.raw_xml:
            result["sysinfo_extended_raw_xml"] = parsed.raw_xml
        result["sysinfo_extended_used_regex_fallback"] = parsed.used_regex_fallback

    return result


def evidence_from_identity(
    identity: dict[str, Any],
    *,
    source: str,
    live: bool = False,
) -> DeviceEvidence:
    evidence = DeviceEvidence()
    sources = identity.get("_sources", {})
    for key, value in identity.items():
        if key.startswith("_") or key in {"model_raw", "sysinfo_extended_raw_xml"}:
            continue
        evidence.add(
            key,
            value,
            sources.get(key, source),
            live=live,
            replace=True,
        )
    return evidence


def extract_image_formats(
    plist: dict[str, Any],
    keys: Iterable[str] = COVER_ART_KEYS,
) -> dict[int, tuple[int, int]]:
    """Extract image format IDs and dimensions from SysInfoExtended plist data."""
    entries: list[Any] = []
    for key in keys:
        value = plist.get(key)
        if isinstance(value, list):
            entries.extend(value)

    formats: dict[int, tuple[int, int]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue

        fmt_id = (
            entry.get("FormatId")
            or entry.get("CorrelationID")
            or entry.get("format_id")
        )
        if fmt_id is None:
            continue

        width = (
            entry.get("RenderWidth")
            or entry.get("DisplayWidth")
            or entry.get("Width")
            or entry.get("width")
        )
        height = (
            entry.get("RenderHeight")
            or entry.get("DisplayHeight")
            or entry.get("Height")
            or entry.get("height")
        )
        if width is None or height is None:
            continue

        try:
            fmt_int = int(fmt_id)
            width_int = int(width)
            height_int = int(height)
        except (TypeError, ValueError):
            continue

        if fmt_int > 0 and width_int > 0 and height_int > 0:
            formats[fmt_int] = (width_int, height_int)

    return formats


def _extract_xml_bytes(raw: bytes) -> bytes:
    raw = bytes(raw or b"").strip(b"\x00\r\n\t ")
    if not raw:
        return b""
    for marker in (b"<?xml", b"<plist"):
        idx = raw.find(marker)
        if idx >= 0:
            raw = raw[idx:]
            break
    return raw.rstrip(b"\x00")


def _parse_sysinfo_extended_regex(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    result: dict[str, Any] = {}

    for match in re.finditer(
        r"<key>([^<]+)</key>\s*"
        r"(?:(<string>(.*?)</string>)|(<integer>(.*?)</integer>)|"
        r"(<true\s*/>)|(<false\s*/>))",
        text,
        flags=re.DOTALL,
    ):
        key = match.group(1).strip()
        string_val = match.group(3)
        int_val = match.group(5)
        if string_val is not None:
            result[key] = string_val.strip()
        elif int_val is not None:
            try:
                result[key] = int(int_val.strip(), 0)
            except ValueError:
                result[key] = int_val.strip()
        elif match.group(6) is not None:
            result[key] = True
        elif match.group(7) is not None:
            result[key] = False

    return result
