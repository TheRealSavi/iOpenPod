"""MPL2 packet text, retaining each line while simplifying its italic prefix."""

from iOpenPod.app.media.subtitles.models import ConvertedText
from iOpenPod.app.media.subtitles.text import (
    STYLING_SIMPLIFIED,
    clean_text,
    decode_text,
)


def convert(payload: bytes) -> ConvertedText:
    decoded = decode_text(payload)
    lines = decoded.text.split("|")
    simplified = any(line.startswith("/") for line in lines)
    return ConvertedText(
        clean_text("\n".join(line.removeprefix("/") for line in lines)),
        decoded.warnings + ((STYLING_SIMPLIFIED,) if simplified else ()),
    )
