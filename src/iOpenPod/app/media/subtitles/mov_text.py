"""Decode tx3g's counted text, excluding the trailing binary style atoms."""

from iOpenPod.app.media.subtitles.models import ConvertedText
from iOpenPod.app.media.subtitles.text import clean_text, decode_text


def _has_styles(atoms: bytes) -> bool:
    """Recognize complete tx3g display modifiers, ignoring empty style records."""
    offset = 0
    while len(atoms) - offset >= 8:
        length = int.from_bytes(atoms[offset : offset + 4], "big")
        if length < 8 or length > len(atoms) - offset:
            return False
        kind = atoms[offset + 4 : offset + 8]
        if kind == b"styl":
            if length >= 10 and int.from_bytes(atoms[offset + 8 : offset + 10], "big"):
                return True
        elif kind in {
            b"hlit",
            b"hclr",
            b"krok",
            b"dlay",
            b"href",
            b"tbox",
            b"blnk",
            b"twrp",
        }:
            return True
        offset += length
    return False


def convert(payload: bytes) -> ConvertedText:
    if len(payload) < 2:
        return ConvertedText(
            "", ("The MOV text packet has no readable text-length field.",)
        )
    length = int.from_bytes(payload[:2], "big")
    decoded = decode_text(payload[2 : 2 + length])
    warnings = decoded.warnings
    if length > len(payload) - 2:
        warnings += ("The MOV text packet was truncated; remaining text was kept.",)
    elif _has_styles(payload[2 + length :]):
        warnings += ("MOV text styling was simplified to readable text for this iPod.",)
    return ConvertedText(clean_text(decoded.text), warnings)
