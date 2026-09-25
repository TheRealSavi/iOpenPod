"""Photo Database string MHOD prefix and payload definitions."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
    artwork_string_encoding,
    decode_artwork_string,
    encode_artwork_string,
)


def photos_string_encoding(encoding_indicator: int) -> str:
    """Map a Photo Database string indicator to a Python codec name."""

    return artwork_string_encoding(encoding_indicator)


def decode_photos_string(raw: bytes, encoding_indicator: int) -> str:
    """Decode one Photo Database string without consuming trailing bytes."""

    return decode_artwork_string(raw, encoding_indicator)


def encode_photos_string(value: str, encoding_indicator: int) -> bytes:
    """Encode one Photo Database string using its retained indicator."""

    return encode_artwork_string(value, encoding_indicator)


__all__ = [
    "MhodStringPayload",
    "MhodStringPrefix",
    "decode_photos_string",
    "encode_photos_string",
    "photos_string_encoding",
]
