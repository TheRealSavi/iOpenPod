"""SubRip packet text; timestamps have already been supplied by the demuxer."""

import re

from iOpenPod.app.media.subtitles.models import ConvertedText
from iOpenPod.app.media.subtitles.text import (
    STYLING_SIMPLIFIED,
    decode_text,
    has_markup,
    markup_text,
)


def convert(payload: bytes) -> ConvertedText:
    decoded = decode_text(payload)
    # Some SRT tracks use ASS positioning/formatting overrides inside their text.
    text = re.sub(r"\{\\[^}]*\}", "", decoded.text)
    return ConvertedText(
        markup_text(text),
        decoded.warnings
        + ((STYLING_SIMPLIFIED,) if text != decoded.text or has_markup(text) else ()),
    )
