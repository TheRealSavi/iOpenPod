"""Pure format converters for readable iPod subtitles from demuxed packets."""

from collections.abc import Callable

from iOpenPod.app.media.subtitles import (
    ass,
    microdvd,
    mov_text,
    mpl2,
    sami,
    subrip,
    subviewer,
    text,
    webvtt,
)
from iOpenPod.app.media.subtitles.models import ConvertedText as ConvertedText

_CONVERTERS: dict[str, Callable[[bytes], ConvertedText]] = {
    "mov_text": mov_text.convert,
    "tx3g": mov_text.convert,
    "subrip": subrip.convert,
    "srt": subrip.convert,
    "webvtt": webvtt.convert,
    "ass": ass.convert,
    "ssa": ass.convert,
    "sami": sami.convert,
    "subviewer": subviewer.convert,
    "subviewer1": subviewer.convert_v1,
    "microdvd": microdvd.convert,
    "mpl2": mpl2.convert,
    "text": text.convert,
}


def supports(codec: str) -> bool:
    return codec.casefold() in _CONVERTERS


def convert_packet(codec: str, payload: bytes) -> ConvertedText:
    """Return all recoverable words; never substitute text from another stream."""
    converter = _CONVERTERS.get(codec.casefold())
    if converter is None:
        raise ValueError(f"Unsupported text subtitle codec: {codec}")
    return converter(payload)
