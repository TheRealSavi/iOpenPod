"""MusicBrainz recording identity, distinct from release-track identity."""

from __future__ import annotations

from typing import Protocol, cast
from uuid import UUID

from mutagen.apev2 import APETextValue
from mutagen.id3 import ID3, UFID


def recording_mbid(value: object) -> str:
    """Accept only a canonical UUID, never a URL or arbitrary tag text."""
    if not isinstance(value, str):
        return ""
    value = value.strip().lower()
    try:
        parsed = UUID(value)
    except ValueError:
        return ""
    return value if str(parsed) == value and parsed.int else ""


class _Tags(Protocol):
    def get(self, key: str) -> object: ...


def _values(value: object) -> list[str]:
    if isinstance(value, bytes):
        try:
            return [value.decode("utf-8")]
        except UnicodeError:
            return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, APETextValue):
        return str(value).split("\0")
    if isinstance(value, list):
        return [part for item in cast("list[object]", value) for part in _values(item)]
    return []


def embedded_recording_mbid(media: object) -> str:
    """Read Picard's recording tags; release-track IDs are deliberately excluded."""
    tags: object = getattr(media, "tags", None)
    values: list[str] = []
    if isinstance(tags, ID3):
        frame = cast("_Tags", tags).get("UFID:http://musicbrainz.org")
        if isinstance(frame, UFID):
            values.extend(_values(getattr(frame, "data", None)))
    elif tags is not None and hasattr(tags, "get"):
        reader = cast("_Tags", tags)
        for key in (
            "----:com.apple.iTunes:MusicBrainz Track Id",
            "musicbrainz_trackid",
            "MusicBrainz/Track Id",
        ):
            values.extend(_values(reader.get(key)))
    ids = {recording_mbid(value) for value in values}
    return ids.pop() if len(ids) == 1 else ""
