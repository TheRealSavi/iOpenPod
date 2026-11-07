"""SubViewer 1/2 packet text after demuxing its time-based cue records."""

import re

from iOpenPod.app.media.subtitles.models import ConvertedText
from iOpenPod.app.media.subtitles.text import decode_text, markup_text


def convert(payload: bytes) -> ConvertedText:
    decoded = decode_text(payload)
    return ConvertedText(
        markup_text(re.sub(r"\[br\]", "\n", decoded.text, flags=re.IGNORECASE)),
        decoded.warnings,
    )


def convert_v1(payload: bytes) -> ConvertedText:
    decoded = decode_text(payload)
    return ConvertedText(markup_text(decoded.text.replace("|", "\n")), decoded.warnings)
