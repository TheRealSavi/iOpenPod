"""MicroDVD packet text; demuxed timestamps, not output fps, determine cue timing."""

import re

from iOpenPod.app.media.subtitles.models import ConvertedText
from iOpenPod.app.media.subtitles.text import (
    STYLING_SIMPLIFIED,
    clean_text,
    decode_text,
)

_STYLE = re.compile(r"\{[YyFfSsCcPpOo]:[^}]*\}")


def convert(payload: bytes) -> ConvertedText:
    decoded = decode_text(payload)
    text = _STYLE.sub("", decoded.text)
    return ConvertedText(
        clean_text(text.replace("|", "\n")),
        decoded.warnings + ((STYLING_SIMPLIFIED,) if text != decoded.text else ()),
    )
