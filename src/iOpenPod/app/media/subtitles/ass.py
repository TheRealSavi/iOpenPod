"""Recover ASS/SSA dialogue while excluding vector drawings and animation syntax."""

import re

from iOpenPod.app.media.subtitles.models import ConvertedText
from iOpenPod.app.media.subtitles.text import clean_text, decode_text

_OVERRIDE = re.compile(r"\{[^}]*\}")
_DRAWING = re.compile(r"\\p(-?\d+)")
_ESCAPE = re.compile(r"\\([Nnh])")
_STYLE_WARNING = (
    "ASS/SSA styling, positioning and effects were simplified to readable text."
)


def _dialogue(text: str) -> str:
    """Accept Matroska's packet prefix and full ASS/SSA Dialogue lines."""
    if text.lstrip().lower().startswith("comment:"):
        return ""
    if text.lstrip().lower().startswith("dialogue:"):
        return text.split(":", 1)[1].split(",", 9)[-1]
    fields = text.split(",", 8)
    if (
        len(fields) == 9
        and fields[0].strip().isdigit()
        and fields[1].strip().lstrip("-").isdigit()
    ):
        return fields[8]
    return text


def convert(payload: bytes) -> ConvertedText:
    decoded = decode_text(payload)
    text = _dialogue(decoded.text)
    parts: list[str] = []
    drawing = False
    drawing_removed = False
    position = 0
    for match in _OVERRIDE.finditer(text):
        segment = text[position : match.start()]
        if not drawing:
            parts.append(segment)
        elif segment.strip():
            drawing_removed = True
        for mode in _DRAWING.finditer(match.group()):
            drawing = int(mode[1]) > 0
        position = match.end()
    if not drawing:
        parts.append(text[position:])
    elif text[position:].strip():
        drawing_removed = True
    dialogue = _ESCAPE.sub(
        lambda match: " " if match[1] == "h" else "\n", "".join(parts)
    )
    warnings = decoded.warnings + ((_STYLE_WARNING,) if text else ())
    if drawing_removed:
        warnings += (
            "ASS/SSA vector drawings cannot become text; readable dialogue was kept.",
        )
    return ConvertedText(clean_text(dialogue), warnings)
