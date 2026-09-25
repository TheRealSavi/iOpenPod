"""Standard string MHOD prefix and payload definitions."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodPayload, MhodPayloadPrefix
from iPodDB.shared.chunk_field import chunk_field as cf


@dataclass(frozen=True, slots=True)
class MhodStringPrefix(MhodPayloadPrefix):
    encoding_indicator: int = cf(0x18, "u32", default=1)
    string_length: int = cf(0x1C, "u32")
    unk_string_mhod_0x20: int = cf(0x20, "u32", default=1)
    unk_string_mhod_0x24: int = cf(0x24, "u32")


@dataclass(frozen=True, slots=True)
class MhodStringPayload(MhodPayload):
    value: str
