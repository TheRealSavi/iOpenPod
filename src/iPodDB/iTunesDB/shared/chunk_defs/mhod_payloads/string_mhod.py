"""Standard string MHOD prefix and payload definitions."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodPayload, MhodPayloadPrefix
from iPodDB.shared.chunk_field import chunk_field as cf


@dataclass(frozen=True, slots=True)
class MhodStringPrefix(MhodPayloadPrefix):
    encoding_indicator: int = cf(0x18, "u32", default=1)
    string_length: int = cf(0x1C, "u32")
    # Classic source-1 text: 0 composes adjacent pairs; 1..255 bypass. This
    # byte is not endian-swapped, and is not a Unicode-normalization enum.
    bypass_pair_composition: int = cf(0x20, "u8", default=1)
    unknown_0x21: bytes = cf(0x21, "raw", size=3)
    unk_string_mhod_0x24: int = cf(0x24, "u32")


@dataclass(frozen=True, slots=True)
class MhodStringPayload(MhodPayload):
    value: str
