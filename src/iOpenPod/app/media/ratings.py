"""Narrow, verified rating edits on a private media stream."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, BinaryIO, cast

from mutagen.flac import FLAC
from mutagen.id3 import ID3, POPM
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4FreeForm
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from iOpenPod.app.media.tags import read_tag_values

# These are the five-star POPM values understood by the shared Host tag reader.
_POPM_VALUES = (0, 1, 64, 128, 196, 255)
_RATING_KEY = "----:com.apple.iTunes:RATING"
_RATING_SUFFIXES = frozenset(
    (".mp3", ".m4a", ".m4b", ".mp4", ".m4v", ".flac", ".ogg", ".opus")
)
_POPM: Any = POPM
_FREE_FORM: Any = MP4FreeForm


def rating_supported(file_name: str) -> bool:
    return PurePosixPath(file_name).suffix.casefold() in _RATING_SUFFIXES


def rewrite_rating_stream(
    stream: BinaryIO, file_name: str, rating: int, *, expected_rating: int | None = None
) -> None:
    """Change only rating tags; preserve other fields and existing POPM counts."""
    if rating not in range(0, 101, 20):
        raise ValueError("An iPod star rating must be 0, 20, 40, 60, 80 or 100.")
    if not rating_supported(file_name):
        raise ValueError("Rating Back Sync supports MP3 and MP4 media only.")
    stream.seek(0)
    options = (
        {"translate": False}
        if PurePosixPath(file_name).suffix.casefold() == ".mp3"
        else {}
    )
    suffix = PurePosixPath(file_name).suffix.casefold()
    factory: Any = {
        ".mp3": MP3,
        ".flac": FLAC,
        ".ogg": OggVorbis,
        ".opus": OggOpus,
    }.get(suffix, MP4)
    audio: Any = factory(stream, **options)
    if audio is None:
        raise ValueError("The Host media format could not be read.")
    current = _rating(audio.tags)
    if expected_rating is not None and current != expected_rating:
        raise ValueError(
            "The Host rating changed after scanning; rescan before retrying."
        )
    if current == rating:
        return
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    stream.seek(0)
    if isinstance(tags, ID3):
        native = cast("Any", tags)
        if native.version[:2] == (2, 2):
            raise ValueError(
                "Rating Back Sync cannot safely convert legacy ID3v2.2 tags."
            )
        version = 4 if native.version[1] == 4 else 3
        owners = native.getall("POPM")
        if owners:
            for owner in owners:
                owner.rating = _POPM_VALUES[rating // 20]
        else:
            native.add(
                _POPM(email="iOpenPod", rating=_POPM_VALUES[rating // 20], count=0)
            )
        audio.save(stream, v2_version=version)
    elif suffix in {".flac", ".ogg", ".opus"}:
        tags["RATING"] = [str(rating)]
        audio.save(stream)
    else:
        tags[_RATING_KEY] = [_FREE_FORM(str(rating).encode("ascii"))]
        audio.save(stream)
    stream.flush()
    stream.seek(0)
    checked: Any = factory(stream, **options)
    if checked is None or _rating(checked.tags) != rating:
        raise ValueError("Host rating failed read-back verification.")


def _rating(tags: Any) -> int:
    return int(
        next((tag.value for tag in read_tag_values(tags) if tag.name == "rating"), "0")
    )
