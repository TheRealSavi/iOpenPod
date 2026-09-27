"""Original iOpenPod tag normalization over immutable, identity-bound Tracks.

The ordered passes intentionally match 1.0's ipodTagNormalizer.py. Suggestions
contain explicit edits only; scanning never changes the workspace or device.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Literal

from iOpenPod.app.display_text import source_text
from iOpenPod.app.library_workspace import TrackUpdate
from iPodDB.library import Track, TrackFieldEdit


@dataclass(frozen=True, slots=True)
class TagProfile:
    label: str = "Generic iPod"
    has_cover_flow: bool = False
    album_artist_aware: bool = False


_DEFAULT_PROFILE = TagProfile()


def tag_profile(
    family: str, generation: str, *, uses_sqlite: bool = False
) -> TagProfile:
    family_lower = family.casefold()
    return TagProfile(
        " ".join((family, generation)).strip() or "Generic iPod",
        "classic" in family_lower
        or (
            "nano" in family_lower
            and any(g in generation.casefold() for g in ("3rd", "4th", "5th"))
        )
        or "touch" in family_lower,
        uses_sqlite or "touch" in family_lower,
    )


@dataclass(frozen=True, slots=True)
class TagSuggestion:
    profile: TagProfile
    updates: tuple[TrackUpdate, ...]
    warnings: tuple[str, ...]

    @property
    def field_count(self) -> int:
        return sum(len(u.edits) for u in self.updates)


@dataclass(frozen=True, slots=True)
class _Tags:
    title: str
    artist: str
    album: str
    album_artist: str
    composer: str
    sort_title: str
    sort_artist: str
    sort_album: str
    sort_album_artist: str
    sort_composer: str
    sort_show: str
    compilation: bool

    @classmethod
    def from_track(cls, track: Track) -> _Tags:
        m = track.metadata
        return cls(
            track.title,
            track.artist,
            track.album,
            track.album_artist,
            m.composer,
            m.sort_title,
            m.sort_artist,
            m.sort_album,
            m.sort_album_artist,
            m.sort_composer,
            m.sort_show,
            m.compilation,
        )


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SPACE = re.compile(r"\s+")
_FEATURED = re.compile(
    r"\s(?:\(|\[)?(?:feat\.?|ft\.?|featuring)\s+.+(?:\)|\])?\s*$", re.IGNORECASE
)
_ARTICLE = re.compile(r"^(?P<article>a|an|the)\s+(?P<body>.+)$", re.IGNORECASE)
_TOP_FIELDS = frozenset(("title", "artist", "album", "album_artist"))
_SORT_FIELDS: tuple[
    tuple[
        str, Literal["sort_artist", "sort_album_artist", "sort_album", "sort_composer"]
    ],
    ...,
] = (
    ("artist", "sort_artist"),
    ("album_artist", "sort_album_artist"),
    ("album", "sort_album"),
    ("composer", "sort_composer"),
)


def _clean(value: str) -> str:
    return _SPACE.sub(" ", _CONTROL.sub("", value).strip())


def _common(values: list[str]) -> str:
    counts = Counter(values)
    return sorted(counts, key=lambda v: (-counts[v], v.casefold(), v))[0]


def normalize_tags(
    tracks: tuple[Track, ...],
    profile: TagProfile = _DEFAULT_PROFILE,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> TagSuggestion:
    """Analyze the whole library, preserving stable IDs and 1.0 pass ordering."""
    original = tuple(_Tags.from_track(t) for t in tracks)
    current = list(original)

    def check() -> None:
        if checkpoint is not None:
            checkpoint()

    def groups(*, by_title: bool = False) -> tuple[tuple[int, ...], ...]:
        grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
        for i, t in enumerate(current):
            if by_title and not t.album:
                continue
            grouped[
                (
                    t.album.casefold(),
                    "" if by_title else (t.album_artist or t.artist).casefold(),
                )
            ].append(i)
        return tuple(tuple(g) for g in grouped.values())

    def compilation(group: tuple[int, ...]) -> None:
        for i in group:
            current[i] = replace(
                current[i], album_artist="Various Artists", compilation=True
            )

    check()
    for i, t in enumerate(current):
        if i % 256 == 0:
            check()
        current[i] = replace(
            t,
            title=_clean(t.title),
            artist=_clean(t.artist),
            album=_clean(t.album),
            album_artist=_clean(t.album_artist),
            composer=_clean(t.composer),
            sort_title=_clean(t.sort_title),
            sort_artist=_clean(t.sort_artist),
            sort_album=_clean(t.sort_album),
            sort_album_artist=_clean(t.sort_album_artist),
            sort_composer=_clean(t.sort_composer),
            sort_show=_clean(t.sort_show),
        )

    if not profile.album_artist_aware:
        for group in groups(by_title=True):
            artists = {current[i].artist.casefold() for i in group if current[i].artist}
            inferred_album_artists = {
                current[i].album_artist.casefold()
                for i in group
                if current[i].album_artist
            }
            various = bool(
                inferred_album_artists & {"various artists", "various", "va"}
            )
            if (len(artists) > 1 or various) and (
                various or not inferred_album_artists
            ):
                compilation(group)
    check()
    for group in groups():
        if any(current[i].compilation for i in group):
            compilation(group)

    if not profile.album_artist_aware:
        for group in groups():
            check()
            if any(current[i].compilation for i in group):
                continue
            album_artists = [
                current[i].album_artist for i in group if current[i].album_artist
            ]
            if not album_artists:
                continue
            canonical = Counter(album_artists).most_common(1)[0][0]
            for i in group:
                t = current[i]
                if (
                    not t.artist
                    or t.artist == canonical
                    or not t.artist.casefold().startswith(canonical.casefold())
                ):
                    continue
                remainder = t.artist[len(canonical) :].strip(" -_/,+;&")
                featured = re.sub(
                    r"^(?:feat\.?|ft\.?|featuring|with)\s+",
                    "",
                    _clean(remainder),
                    flags=re.IGNORECASE,
                ).strip(" ()[]")
                if featured and not _FEATURED.search(t.title):
                    current[i] = replace(
                        t, artist=canonical, title=f"{t.title} (feat. {featured})"
                    )
        for group in groups():
            if any(current[i].compilation for i in group):
                continue
            album_artists = [
                current[i].album_artist for i in group if current[i].album_artist
            ]
            if not album_artists:
                continue
            canonical = Counter(album_artists).most_common(1)[0][0]
            for i in group:
                t = current[i]
                current[i] = replace(
                    t, artist=canonical if t.artist else "", album_artist=canonical
                )

        for group in groups(by_title=True):
            check()
            artists = {
                current[i].album_artist or current[i].artist or "Unknown Artist"
                for i in group
            }
            if len(artists) <= 1 or not any(current[i].album_artist for i in group):
                continue
            for i in group:
                t = current[i]
                artist = t.album_artist or t.artist or "Unknown Artist"
                if f"({artist})" not in t.album:
                    current[i] = replace(t, album=f"{t.album} ({artist})")

    for display_key, sort_key in _SORT_FIELDS:
        check()
        same_display: dict[str, list[int]] = defaultdict(list)
        for i, t in enumerate(current):
            display: str = getattr(t, display_key)
            if display:
                same_display[display.casefold()].append(i)
        for members in same_display.values():
            display = _common([getattr(current[i], display_key) for i in members])
            sorts = [
                getattr(current[i], sort_key)
                for i in members
                if getattr(current[i], sort_key)
            ]
            match = _ARTICLE.match(display)
            canonical_sort = (
                f"{match['body']}, {match['article']}"
                if match
                else _common(sorts)
                if sorts
                else display
            )
            for i in members:
                t = current[i]
                match sort_key:
                    case "sort_artist":
                        current[i] = replace(t, sort_artist=canonical_sort)
                    case "sort_album_artist":
                        current[i] = replace(t, sort_album_artist=canonical_sort)
                    case "sort_album":
                        current[i] = replace(t, sort_album=canonical_sort)
                    case "sort_composer":
                        current[i] = replace(t, sort_composer=canonical_sort)

    updates: list[TrackUpdate] = []
    for track, before, after in zip(tracks, original, current, strict=True):
        edits = tuple(
            TrackFieldEdit(
                f.name if f.name in _TOP_FIELDS else "metadata." + f.name,
                getattr(after, f.name),
            )
            for f in fields(_Tags)
            if getattr(before, f.name) != getattr(after, f.name)
        )
        if edits:
            updates.append(TrackUpdate(track.track_id, edits))
    check()
    warnings: list[str] = []
    if not profile.album_artist_aware:
        warnings.append(
            source_text(
                "Album Artist is preserved, but this profile treats Artist as the safer iPod grouping field."
            )
        )
    if profile.has_cover_flow:
        warnings.append(
            source_text(
                "Cover Flow devices are sensitive to Artist+Album differences and same-name albums."
            )
        )
    return TagSuggestion(profile, tuple(updates), tuple(warnings))
