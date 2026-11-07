"""Shared text decoding and conservative cleanup, without file or tool access."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from iOpenPod.app.media.subtitles.models import ConvertedText

ENCODING_FALLBACK = (
    "Subtitle character encoding was not UTF-8; readable text was recovered using "
    "Windows-1252. Some characters may need correction."
)
STYLING_SIMPLIFIED = "Subtitle styling was simplified to readable text for this iPod."


def decode_text(payload: bytes) -> ConvertedText:
    """Honor Unicode markers first; preserve legacy bytes with a visible warning."""
    encoding = (
        "utf-32"
        if payload.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"))
        else "utf-16"
        if payload.startswith((b"\xff\xfe", b"\xfe\xff"))
        else "utf-8-sig"
    )
    try:
        return ConvertedText(payload.decode(encoding))
    except UnicodeDecodeError:
        if encoding != "utf-8-sig":
            return ConvertedText(
                payload.decode(encoding, errors="replace"),
                (
                    "Damaged subtitle characters were replaced; remaining text was kept.",
                ),
            )
        return ConvertedText(
            payload.decode("cp1252", errors="replace"), (ENCODING_FALLBACK,)
        )


def clean_text(text: str) -> str:
    """Remove non-display controls and empty lines that could split a staged cue."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(
        char
        for char in text
        if char in "\n\t" or (ord(char) >= 32 and char not in "\x7f\ufeff")
    )
    return "\n".join(
        cleaned for line in text.split("\n") if (cleaned := " ".join(line.split()))
    )


def encode_literal(text: str) -> str:
    """Stage literal text for FFmpeg's ``text`` decoder, keep_ass_markup=1.

    The text decoder avoids subtitle markup interpretation but still passes through
    ASS on its way to mov_text. Inserting a consumed, no-op style reset after
    each opening brace and backslash prevents literal words becoming ASS syntax.
    A reset at each line start also keeps timestamp-like words from being
    mistaken for cue boundaries. This is private staging syntax, never
    user-visible formatting.
    """
    guarded = "".join(char + r"{\r}" if char in "\\{" else char for char in text)
    return "\n".join(r"{\r}" + line for line in guarded.split("\n"))


class _SubtitleMarkup(HTMLParser):
    """Keep unknown angle-bracket text instead of mistaking it for formatting."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"head", "style", "script"}:
            self.hidden += 1
        elif tag == "body":
            self.hidden = 0
        elif not self.hidden:
            if tag in {"br", "p", "div", "sync"}:
                self.parts.append("\n")
            elif tag.split(".")[0] not in {
                "html",
                "sami",
                "body",
                "b",
                "i",
                "u",
                "s",
                "font",
                "span",
                "ruby",
                "rt",
                "c",
                "v",
                "lang",
                "bdi",
            }:
                self.parts.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"head", "style", "script"}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in {"p", "div"}:
            self.parts.append("\n")
        elif not self.hidden and tag.split(".")[0] not in {
            "html",
            "sami",
            "body",
            "br",
            "sync",
            "b",
            "i",
            "u",
            "s",
            "font",
            "span",
            "ruby",
            "rt",
            "c",
            "v",
            "lang",
            "bdi",
        }:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def markup_text(text: str) -> str:
    parser = _SubtitleMarkup()
    parser.feed(text)
    parser.close()
    return clean_text("".join(parser.parts))


def convert(payload: bytes) -> ConvertedText:
    """Plain timed text needs only character decoding; timing belongs to the packet."""
    decoded = decode_text(payload)
    return ConvertedText(clean_text(decoded.text), decoded.warnings)


def has_markup(text: str) -> bool:
    return bool(re.search(r"</?(?:b|i|u|s|font|span|ruby|rt|c|v|lang)(?:[ .>])", text))
