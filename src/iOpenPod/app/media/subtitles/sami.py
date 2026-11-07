"""SAMI packet text, excluding stylesheet/header data and retaining paragraph breaks."""

from iOpenPod.app.media.subtitles.models import ConvertedText
from iOpenPod.app.media.subtitles.text import decode_text, markup_text


def convert(payload: bytes) -> ConvertedText:
    decoded = decode_text(payload)
    return ConvertedText(markup_text(decoded.text), decoded.warnings)
