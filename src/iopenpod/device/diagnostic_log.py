"""Compact log formatting helpers for device-identification diagnostics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

FieldSpec = tuple[str, str]


IDENTITY_FIELDS: tuple[FieldSpec, ...] = (
    ("model_number", "model"),
    ("model_family", "family"),
    ("generation", "gen"),
    ("capacity", "capacity"),
    ("color", "color"),
    ("serial", "serial"),
    ("firewire_guid", "fwguid"),
    ("firmware", "fw"),
    ("usb_vid", "vid"),
    ("usb_pid", "pid"),
    ("usb_serial", "usb_serial"),
    ("scsi_vendor", "scsi_vendor"),
    ("scsi_product", "scsi_product"),
    ("scsi_revision", "scsi_rev"),
)

CAPABILITY_FIELDS: tuple[FieldSpec, ...] = (
    ("family_id", "family_id"),
    ("updater_family_id", "updater_id"),
    ("product_type", "product"),
    ("db_version", "db_version"),
    ("shadow_db_version", "shadow_db"),
    ("uses_sqlite_db", "sqlite"),
    ("supports_sparse_artwork", "sparse_art"),
    ("max_tracks", "max_tracks"),
    ("max_file_size_gb", "max_file_gb"),
    ("max_transfer_speed", "max_transfer"),
    ("podcasts_supported", "podcasts"),
    ("voice_memos_supported", "voice_memos"),
    ("artwork_formats", "art_ids"),
    ("photo_formats", "photo_ids"),
    ("chapter_image_formats", "chapter_ids"),
)

SOURCE_FIELDS: tuple[FieldSpec, ...] = (
    ("serial", "serial"),
    ("firewire_guid", "fwguid"),
    ("model_number", "model"),
    ("model_family", "family"),
    ("generation", "gen"),
    ("capacity", "capacity"),
    ("color", "color"),
    ("usb_pid", "pid"),
    ("firmware", "fw"),
)

_HEX_WIDTHS: dict[str, int] = {
    "usb_vid": 4,
    "usb_pid": 4,
    "db_version": 0,
    "shadow_db_version": 0,
}


def is_missing(value: Any) -> bool:
    return value is None or value == "" or value == b"" or value == {} or value == []


def compact(value: Any, *, max_chars: int = 96) -> str:
    text = str(value)
    if len(text) <= max_chars:
        return text
    head = max_chars // 2 - 2
    tail = max_chars - head - 3
    return f"{text[:head]}...{text[-tail:]}"


def format_value(field: str, value: Any) -> str:
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if field in _HEX_WIDTHS:
        try:
            number = int(value)
            if not number:
                return "0"
            width = _HEX_WIDTHS[field]
            return f"0x{number:0{width}X}" if width else f"0x{number:X}"
        except (TypeError, ValueError):
            return compact(value)
    if isinstance(value, Mapping):
        if field.endswith("_formats") or field in {
            "artwork_formats",
            "photo_formats",
            "chapter_image_formats",
        }:
            ids = ", ".join(str(k) for k in sorted(value)[:12])
            suffix = "..." if len(value) > 12 else ""
            return f"{len(value)}[{ids}{suffix}]"
        keys = ", ".join(str(k) for k in sorted(value, key=str)[:8])
        suffix = "..." if len(value) > 8 else ""
        return f"{len(value)} keys[{keys}{suffix}]"
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        items = list(value)
        shown = ", ".join(str(item) for item in items[:12])
        suffix = "..." if len(items) > 12 else ""
        return f"{len(items)}[{shown}{suffix}]"
    return compact(value)


def format_fields(
    data: Mapping[str, Any],
    fields: Iterable[FieldSpec] = IDENTITY_FIELDS,
    *,
    include_false: bool = False,
) -> str:
    parts: list[str] = []
    for field, label in fields:
        if field not in data:
            continue
        value = data.get(field)
        if is_missing(value):
            continue
        if value == 0 and not isinstance(value, bool):
            continue
        if value is False and not include_false:
            continue
        parts.append(f"{label}={format_value(field, value)}")
    return ", ".join(parts) if parts else "none"


def format_sources(
    sources: Mapping[str, Any] | None,
    fields: Iterable[FieldSpec] = SOURCE_FIELDS,
) -> str:
    if not sources:
        return "none"
    parts = []
    for field, label in fields:
        source = sources.get(field)
        if source:
            parts.append(f"{label}:{source}")
    return ", ".join(parts) if parts else "none"


def format_conflicts(conflicts: Any) -> str:
    if not conflicts:
        return "none"
    if not isinstance(conflicts, list):
        return compact(conflicts)

    parts: list[str] = []
    for conflict in conflicts[:6]:
        if isinstance(conflict, Mapping):
            field = conflict.get("field", "?")
            winner = conflict.get("winner", "")
            rejected_source = conflict.get("rejected_source", "")
            rejected_value = conflict.get("rejected_value", "")
            reason = conflict.get("reason", "")
            detail = f"{field}"
            if winner:
                detail += f" winner={winner}"
            if rejected_source or rejected_value:
                detail += (
                    f" rejected={rejected_source or '?'}:"
                    f"{compact(rejected_value, max_chars=36)}"
                )
            if reason:
                detail += f" reason={compact(reason, max_chars=64)}"
            parts.append(detail)
        else:
            parts.append(compact(conflict, max_chars=96))
    if len(conflicts) > 6:
        parts.append(f"+{len(conflicts) - 6} more")
    return "; ".join(parts)
