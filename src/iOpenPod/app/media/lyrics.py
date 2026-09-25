"""Transform captured media bytes, independently of optional full-file tagging."""

from __future__ import annotations

import io
from pathlib import PurePosixPath
from typing import Any, Protocol, cast

import mutagen
import mutagen.id3 as id3_frames
from mutagen.aiff import AIFF
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.wave import WAVE

_FRAMES: Any = id3_frames
_ID3_SUFFIXES = frozenset((".mp3", ".wav", ".wave", ".aif", ".aiff", ".aifc"))
_MP4_SUFFIXES = frozenset((".m4a", ".m4b", ".m4v", ".mp4", ".mov"))


class _TaggedMedia(Protocol):
    tags: Any

    def add_tags(self) -> None: ...

    def save(self, *args: Any, **kwargs: Any) -> None: ...


class _MediaFactory(Protocol):
    def __call__(self, filething: io.BytesIO, **kwargs: Any) -> _TaggedMedia: ...


class _ID3Version(Protocol):
    @property
    def version(self) -> tuple[int, ...]: ...


def _no_padding(_info: object) -> int:
    return 0


def embedded_lyrics(parsed: Any) -> str:
    """Read unsynchronized text without treating a database flag as lyrics."""
    tags = getattr(parsed, "tags", None)
    if tags is None:
        return ""
    if isinstance(tags, ID3):
        frames = cast("Any", tags).getall("USLT")
        # Prefer the ordinary descriptionless frame, with a stable fallback.
        frame = next((f for f in frames if not f.desc), next(iter(frames), None))
        return str(frame.text) if frame is not None else ""
    values = tags.get("\xa9lyr", ())
    return str(values[0]) if values else ""


def rewrite_lyrics(data: bytes, file_name: str, lyrics: str) -> bytes:
    """Replace only lyrics on a private byte buffer and verify by reparsing.

    Existing ID3v2.3/v2.4 versions are retained; new tags use v2.3 UTF-16,
    following the Original iOpenPod compatibility policy. No tag padding is added.
    An unchanged value returns the original bytes, including existing padding.
    """
    suffix = PurePosixPath(file_name).suffix.casefold()
    if suffix not in _ID3_SUFFIXES | _MP4_SUFFIXES:
        raise ValueError(
            f"Embedded lyrics are unsupported for {suffix or 'this file type'}."
        )
    lyrics.encode("utf-16-le")
    factory = (
        MP4
        if suffix in _MP4_SUFFIXES
        else MP3
        if suffix == ".mp3"
        else WAVE
        if suffix in (".wav", ".wave")
        else AIFF
    )

    def load(buffer: io.BytesIO) -> _TaggedMedia:
        return cast("_MediaFactory", factory)(
            buffer, **({} if suffix in _MP4_SUFFIXES else {"translate": False})
        )

    try:
        buffer = io.BytesIO(data)
        audio = load(buffer)
        if _matches(audio, lyrics):
            return data
        id3_version = (
            cast("_ID3Version", audio.tags).version
            if isinstance(audio.tags, ID3)
            else (2, 3, 0)
        )
        if id3_version[:2] == (2, 2):
            raise ValueError(
                "Lyrics edits require converting this legacy ID3v2.2 tag explicitly first; automatic conversion could discard unknown frames."
            )
        version = 4 if id3_version[1] == 4 else 3
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        if tags is None:
            raise ValueError(f"Could not create embedded metadata for {file_name}.")
        if isinstance(tags, ID3):
            tags = cast("Any", tags)
            tags.delall("USLT")
            if lyrics:
                tags.add(
                    _FRAMES.USLT(
                        encoding=3 if version == 4 else 1,
                        lang="eng",
                        desc="",
                        text=lyrics,
                    )
                )
            buffer.seek(0)
            audio.save(buffer, v2_version=version, padding=_no_padding)
        else:
            if lyrics:
                tags["\xa9lyr"] = [lyrics]
            else:
                tags.pop("\xa9lyr", None)
            buffer.seek(0)
            audio.save(buffer, padding=_no_padding)
        output = buffer.getvalue()
        if not _matches(load(io.BytesIO(output)), lyrics):
            raise ValueError("Embedded lyrics failed read-back verification.")
        return output
    except (mutagen.MutagenError, OSError) as error:
        raise ValueError(
            f"Could not prepare embedded lyrics for {file_name}: {error}"
        ) from error


def _matches(audio: _TaggedMedia, lyrics: str) -> bool:
    tags = audio.tags
    if tags is None:
        return not lyrics
    if isinstance(tags, ID3):
        frames = cast("Any", tags).getall("USLT")
        return (len(frames) == 1 and frames[0].text == lyrics) if lyrics else not frames
    return bool(tags.get("\xa9lyr", []) == ([lyrics] if lyrics else []))
