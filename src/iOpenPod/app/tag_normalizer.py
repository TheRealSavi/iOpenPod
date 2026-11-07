"""Conservative tag normalization over immutable, identity-bound Tracks.

Original iOpenPod supplies the baseline; ADR-0163 limits inference to supported
credits and unambiguous evidence. Scanning never changes the workspace or device.
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
from iPodDB.library import MediaKind, Track, TrackFieldEdit


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
    r"\s(?P<opener>\(|\[)?(?:feat\.?|ft\.?|featuring)\s+(?P<credit>.+?)\s*$",
    re.IGNORECASE,
)
_CREDIT_MARKER = re.compile(r"^(?:feat\.?|ft\.?|featuring|with)\s+", re.IGNORECASE)
_VARIOUS_ARTISTS = frozenset(("various artists", "various", "va"))
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


def _featured_credit(artist: str, album_artist: str) -> str:
    """Require a whole lead credit and a recognized collaboration separator."""
    lead = re.match(re.escape(album_artist), artist, re.IGNORECASE)
    if lead is None:
        return ""
    suffix = artist[lead.end() :]
    separated = suffix.lstrip().startswith(("/", ",", ";", "+", "&"))
    if separated:
        suffix = suffix.lstrip()[1:].strip()
    elif not suffix.startswith((" ", "(", "[")):
        return ""
    suffix = suffix.strip()
    if suffix.startswith(("(", "[")):
        closer = ")" if suffix[0] == "(" else "]"
        if not suffix.endswith(closer):
            return ""
        suffix = suffix[1:-1].strip()
    marker = _CREDIT_MARKER.match(suffix)
    if marker is not None:
        return suffix[marker.end() :].strip()
    return suffix if separated else ""


def _title_credit(title: str) -> str:
    match = _FEATURED.search(title)
    if match is None:
        return ""
    credit = match["credit"].strip()
    closer = ")" if match["opener"] == "(" else "]" if match["opener"] == "[" else ""
    # Remove only the wrapper; a guest name can itself contain brackets.
    return credit[:-1].rstrip() if closer and credit.endswith(closer) else credit


def _default_sort(display: str) -> str:
    match = _ARTICLE.match(display)
    return f"{match['body']}, {match['article']}" if match else display


def normalize_tags(
    tracks: tuple[Track, ...],
    profile: TagProfile = _DEFAULT_PROFILE,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> TagSuggestion:
    """Analyze the whole Library without treating uncertain metadata as fact."""
    original = tuple(_Tags.from_track(t) for t in tracks)
    current = list(original)

    def check() -> None:
        if checkpoint is not None:
            checkpoint()

    def groups(*, by_title: bool = False) -> tuple[tuple[int, ...], ...]:
        grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
        for i, t in enumerate(current):
            if not t.album or tracks[i].media_kind is not MediaKind.MUSIC:
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
            t = current[i]
            current[i] = replace(
                t,
                album_artist="Various Artists"
                if not t.album_artist or t.album_artist.casefold() in _VARIOUS_ARTISTS
                else t.album_artist,
                compilation=True,
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

    # A shared title alone cannot distinguish a compilation from separate albums.
    check()
    for group in groups():
        check()
        if any(
            current[i].compilation
            or current[i].album_artist.casefold() in _VARIOUS_ARTISTS
            for i in group
        ):
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
            canonical = _common(album_artists)
            for i in group:
                t = current[i]
                artist, title = t.artist, t.title
                if artist.casefold() == canonical.casefold():
                    artist = canonical
                elif title and (featured := _featured_credit(artist, canonical)):
                    existing_credit = _title_credit(title)
                    if not existing_credit:
                        artist, title = canonical, f"{title} (feat. {featured})"
                    elif existing_credit.casefold() == featured.casefold():
                        artist = canonical
                current[i] = replace(
                    t, artist=artist, title=title, album_artist=canonical
                )

        for group in groups(by_title=True):
            check()
            # Incomplete Album Artist tags can describe one album's collaborations.
            if not all(current[i].album_artist for i in group):
                continue
            artists = {current[i].album_artist.casefold() for i in group}
            if len(artists) <= 1:
                continue
            for i in group:
                t = current[i]
                artist = t.album_artist
                if not t.album.casefold().endswith(f"({artist})".casefold()):
                    current[i] = replace(t, album=f"{t.album} ({artist})")

    for display_key, sort_key in _SORT_FIELDS:
        check()
        same_display: dict[tuple[MediaKind, str, str], list[int]] = defaultdict(list)
        for i, t in enumerate(current):
            display: str = getattr(t, display_key)
            if display:
                owner = (
                    (t.album_artist or t.artist).casefold()
                    if display_key == "album"
                    else ""
                )
                same_display[(tracks[i].media_kind, display.casefold(), owner)].append(
                    i
                )
        for members in same_display.values():
            check()
            display = _common([getattr(current[i], display_key) for i in members])
            # Existing sorts belong to their own Track. Only unambiguous custom
            # evidence for an unchanged identity can fill a missing peer's sort.
            sorts = [
                getattr(current[i], sort_key)
                for i in members
                if getattr(current[i], sort_key)
                and _clean(getattr(original[i], display_key)).casefold()
                == getattr(current[i], display_key).casefold()
                and not (display_key == "artist" and _title_credit(current[i].title))
                and getattr(current[i], sort_key)
                not in (
                    getattr(current[i], display_key),
                    _default_sort(getattr(current[i], display_key)),
                )
            ]
            canonical_sort = (
                next(iter(sorts)) if len(set(sorts)) == 1 else _default_sort(display)
            )
            for i in members:
                t = current[i]
                existing: str = getattr(t, sort_key)
                if existing:
                    # A redundant sort may gain article handling; custom sorts
                    # (including collaboration credits) are never outvoted.
                    if existing != getattr(t, display_key):
                        continue
                    proposed = _default_sort(existing)
                else:
                    proposed = canonical_sort
                match sort_key:
                    case "sort_artist":
                        current[i] = replace(t, sort_artist=proposed)
                    case "sort_album_artist":
                        current[i] = replace(t, sort_album_artist=proposed)
                    case "sort_album":
                        current[i] = replace(t, sort_album=proposed)
                    case "sort_composer":
                        current[i] = replace(t, sort_composer=proposed)

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
