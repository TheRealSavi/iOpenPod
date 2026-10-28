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
    # Classic consumes the complete word, including the formerly unnamed
    # upper three bytes, through the serialized-order conversion routine.
    limit_sort: int = cf(0x1C, "u32")

    limit_value: int = cf(0x20, "u32")

    match_checked_only: int = cf(0x24, "u8")
    reverse_sort: int = cf(0x25, "u8")
    # First byte: nonzero inhibits setting the importer's attachment flag.
    # That flag is sticky across MHOD50/51 visits; this is not unconditional
    # final suppression. The remaining 57 bytes are unidentified.
    attachment_inhibit: int = cf(0x26, "u8")
    padding_0x27: bytes = cf(0x27, "raw", size=57)


@dataclass(frozen=True, slots=True)
class MhodSmartPrefsPayload(MhodPayload):
    """Retain Unknown Data following the understood preferences prefix."""

    trailing_data: bytes = b""
