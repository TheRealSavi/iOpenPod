import plistlib
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import cast

from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.plist_mhod import (
    MhodPlistPayload,
    PlistValue,
)
from iPodDB.shared.diagnostics import report_unknown_data
from iPodDB.shared.types import MhodPayloadParseContext


def _normalize_plist_value(value: object) -> PlistValue:
    if isinstance(value, bool | bytes | datetime | float | int | str):
        return value

    if isinstance(value, list):
        list_items = cast("list[object]", value)
        return tuple(_normalize_plist_value(item) for item in list_items)

    if isinstance(value, dict):
        mapping_items = cast("dict[object, object]", value)
        normalized: dict[str, PlistValue] = {}
        for key, item in mapping_items.items():
            if not isinstance(key, str):
                raise TypeError("plist dictionary keys must be strings")
            normalized[key] = _normalize_plist_value(item)
        return MappingProxyType(normalized)

    raise TypeError(f"unsupported plist value {type(value).__name__}")


def parse_plist_payload(
    context: MhodPayloadParseContext[None],
) -> MhodPlistPayload:
    data = bytes(context.data[context.payload_offset : context.payload_end])
    properties: Mapping[str, PlistValue] | None = None

    try:
        raw_loaded = cast("object", plistlib.loads(data))
        loaded = _normalize_plist_value(raw_loaded)
    except (plistlib.InvalidFileException, TypeError, ValueError, OverflowError):
        pass
    else:
        if isinstance(loaded, Mapping):
            properties = loaded

    if properties is None:
        report_unknown_data(
            f"MHOD {int(context.mhod_type)} opaque plist",
            context.payload_offset,
            len(data),
        )
    return MhodPlistPayload(
        data=data,
        properties=properties,
    )
