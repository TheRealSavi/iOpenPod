"""Retain WebVTT words, line breaks, ruby text and entities without visual effects."""

import re

from iOpenPod.app.media.subtitles.models import ConvertedText
from iOpenPod.app.media.subtitles.text import (
    STYLING_SIMPLIFIED,
    decode_text,
    has_markup,
    markup_text,
)

_TIMESTAMP = re.compile(r"<(?:\d{2,}:)?\d{2}:\d{2}\.\d{3}>")


def convert(payload: bytes) -> ConvertedText:
    decoded = decode_text(payload)
    text = _TIMESTAMP.sub("", decoded.text)
    return ConvertedText(
        markup_text(text),
        decoded.warnings
        + ((STYLING_SIMPLIFIED,) if text != decoded.text or has_markup(text) else ()),
    )
