"""Smart playlist preferences MHOD prefix and payload definitions."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodPayload, MhodPayloadPrefix
from iPodDB.shared.chunk_field import chunk_field as cf


@dataclass(frozen=True, slots=True)
class MhodSmartPrefsPrefix(MhodPayloadPrefix):
    live_update: int = cf(0x18, "u8")
    check_rules: int = cf(0x19, "u8")
    check_limits: int = cf(0x1A, "u8")
    limit_type: int = cf(0x1B, "u8")
    limit_sort: int = cf(0x1C, "u8")

    padding_0x1D: bytes = cf(0x1D, "raw", size=3)

    limit_value: int = cf(0x20, "u32")

    match_checked_only: int = cf(0x24, "u8")
    reverse_sort: int = cf(0x25, "u8")
    padding_0x26: bytes = cf(0x26, "raw", size=58)


@dataclass(frozen=True, slots=True)
class MhodSmartPrefsPayload(MhodPayload):
    pass
