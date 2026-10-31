"""Pair iPod Tracks with Jellyfin items by metadata, never by guessing."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iPodDB.library import Track

    from .models import JellyfinTrack

LENGTH_TOLERANCE_MS = 3_000


class MatchOutcome(Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class Match:
    outcome: MatchOutcome
    remote: JellyfinTrack | None = None


def normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _same_artist(track: Track, remote: JellyfinTrack) -> bool:
    local = {normalized(track.artist), normalized(track.album_artist)} - {""}
    names = {normalized(name) for name in (*remote.artists, remote.album_artist)}
    names -= {""}
    if not local or not names:
        return True
    if local & names:
        return True
    # "A feat. B" on the iPod against Jellyfin's split ["A", "B"].
    artist = normalized(track.artist)
    return any(len(name) > 1 and name in artist for name in names)


def _compatible(track: Track, remote: JellyfinTrack) -> bool:
    if (
        track.track_number
        and remote.track_number
        and track.track_number != remote.track_number
    ):
        return False
    disc = track.metadata.disc_number
    if disc and remote.disc_number and disc != remote.disc_number:
        return False
    if (
        track.length_ms
        and remote.length_ms
        and abs(track.length_ms - remote.length_ms) > LENGTH_TOLERANCE_MS
    ):
        return False
    return _same_artist(track, remote)


class TrackIndex:
    def __init__(self, remote: tuple[JellyfinTrack, ...]) -> None:
        self._by_id = {item.item_id: item for item in remote}
        self._by_name: dict[tuple[str, str], list[JellyfinTrack]] = {}
        for item in remote:
            key = (normalized(item.title), normalized(item.album))
            self._by_name.setdefault(key, []).append(item)

    def match(self, track: Track, remembered: str = "") -> Match:
        if remembered and (item := self._by_id.get(remembered)) is not None:
            return Match(MatchOutcome.MATCHED, item)
        title = normalized(track.title)
        if not title:
            return Match(MatchOutcome.UNMATCHED)
        candidates = [
            item
            for item in self._by_name.get((title, normalized(track.album)), ())
            if _compatible(track, item)
        ]
        if not candidates:
            return Match(MatchOutcome.UNMATCHED)
        if len(candidates) > 1:
            return Match(MatchOutcome.AMBIGUOUS)
        return Match(MatchOutcome.MATCHED, candidates[0])
