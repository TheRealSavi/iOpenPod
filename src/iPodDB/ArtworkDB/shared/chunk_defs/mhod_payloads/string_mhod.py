"""ArtworkDB string MHOD prefix and payload definitions."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodPayload, MhodPayloadPrefix
from iPodDB.shared.chunk_field import chunk_field as cf


@dataclass(frozen=True, slots=True)
class MhodStringPrefix(MhodPayloadPrefix):
    """Prefix whose offsets are relative to the declared MHOD header end."""

    string_byte_length: int = cf(0x00, "u32")
    encoding_indicator: int = cf(0x04, "u8", default=1)
    unk_string_mhod_0x05: bytes = cf(0x05, "raw", size=3)
    unk_string_mhod_0x08: int = cf(0x08, "u32")


@dataclass(frozen=True, slots=True)
class MhodStringPayload(MhodPayload):
    value: str
    raw_value: bytes
    trailing_data: bytes


def artwork_string_encoding(encoding_indicator: int) -> str:
    """Map the ArtworkDB encoding indicator to a Python codec name."""
    return "utf-16-le" if encoding_indicator == 2 else "utf-8"


def decode_artwork_string(raw: bytes, encoding_indicator: int) -> str:
    """Decode one ArtworkDB string value without consuming trailing bytes."""
    if encoding_indicator == 2 and len(raw) % 2:
        raise ValueError("UTF-16 ArtworkDB string has an odd byte length")
    return raw.decode(
        artwork_string_encoding(encoding_indicator),
        errors="replace",
    ).rstrip("\x00")


def encode_artwork_string(value: str, encoding_indicator: int) -> bytes:
    """Encode one ArtworkDB string value using its retained indicator."""
    return value.encode(artwork_string_encoding(encoding_indicator))
