"""iPod-oriented metadata cleanup rules for track dictionaries."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IpodTagProfile:
    label: str
    detail: str
    has_cover_flow: bool
    uses_sqlite_db: bool
    supports_album_artist_reliably: bool
    is_shuffle: bool


@dataclass(frozen=True)
class IpodLibraryTagSuggestion:
    profile: IpodTagProfile
    changes_by_track: dict[int, dict[str, Any]]
    warnings: tuple[str, ...] = ()

    def changes_for_track(self, track: dict) -> dict[str, Any]:
        return dict(self.changes_by_track.get(id(track), {}))


@dataclass(frozen=True)
class IndexedIpodTagFixPlan:
    """Tag changes keyed by snapshot position for safe background scanning."""

    changes_by_index: dict[int, dict[str, Any]]
    changed_track_count: int
    changed_field_count: int


_IPOD_TAG_SCAN_FIELDS = (
    "Title",
    "Artist",
    "Album",
    "Album Artist",
    "Composer",
    "Sort Title",
    "Sort Artist",
    "Sort Album",
    "Sort Album Artist",
    "Sort Composer",
    "Sort Show",
    "compilation_flag",
)


def build_ipod_tag_scan_snapshot(library_tracks: list[dict]) -> list[dict]:
    """Copy only fields read by normalization, preserving track positions."""

    return [
        {key: track[key] for key in _IPOD_TAG_SCAN_FIELDS if key in track}
        for track in library_tracks
    ]


def index_ipod_library_tag_fixes(
    library_tracks: list[dict],
    *,
    profile: IpodTagProfile | None = None,
) -> IndexedIpodTagFixPlan:
    """Return a stable plan that can be mapped back to an unchanged cache."""

    suggestion = suggest_ipod_library_tag_fixes(library_tracks, profile=profile)
    changes_by_index = {
        index: changes
        for index, track in enumerate(library_tracks)
        if (changes := suggestion.changes_by_track.get(id(track)))
    }
    return IndexedIpodTagFixPlan(
        changes_by_index=changes_by_index,
        changed_track_count=len(changes_by_index),
        changed_field_count=sum(len(changes) for changes in changes_by_index.values()),
    )


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SPACE_RE = re.compile(r"\s+")
_FEAT_IN_TITLE_RE = re.compile(
    r"\s(?:\(|\[)?(?:feat\.?|ft\.?|featuring)\s+.+(?:\)|\])?\s*$",
    re.IGNORECASE,
)
_LEADING_ARTICLE_RE = re.compile(r"^(?P<article>a|an|the)\s+(?P<body>.+)$", re.IGNORECASE)


class _TagFixAccumulator:
    def __init__(self, tracks: list[dict]):
        self.tracks = tracks
        self._changes: dict[int, dict[str, Any]] = defaultdict(dict)

    def current(self, track: dict, key: str) -> Any:
        return self._changes.get(id(track), {}).get(key, track.get(key))

    def queue(self, track: dict, key: str, value: Any, reason: str) -> None:
        del reason
        if self.current(track, key) == value:
            return
        track_changes = self._changes[id(track)]
        if track.get(key) == value:
            track_changes.pop(key, None)
            if not track_changes:
                self._changes.pop(id(track), None)
            return
        track_changes[key] = value

    def changes_by_track(self) -> dict[int, dict[str, Any]]:
        return {
            track_id: dict(changes)
            for track_id, changes in self._changes.items()
            if changes
        }


def ipod_tag_profile(
    *,
    family: str = "",
    generation: str = "",
    uses_sqlite_db: bool = False,
    is_shuffle: bool = False,
) -> IpodTagProfile:
    family_norm = family.casefold()
    generation_norm = generation.casefold()
    has_cover_flow = (
        "classic" in family_norm
        or ("nano" in family_norm and any(gen in generation_norm for gen in ("3rd", "4th", "5th")))
        or "touch" in family_norm
    )
    if is_shuffle:
        detail = "Shuffle: No visual browser, but VoiceOver still benefits from clean artist/title text."
    elif uses_sqlite_db:
        detail = "SQLite Device: Newer nano databases are less dependent on legacy grouping, but tag cleanup still reduces menu clutter."
    elif has_cover_flow:
        detail = "Cover Flow Device: Albums are listed by artist and album, while the rest of the OS follows legacy grouping rules; Artist, album, composer, sort, and compilation fields drive the visible browser more than Album Artist."
    else:
        detail = "Legacy Grouping: Artist, album, composer, sort, and compilation fields drive the visible browser more than Album Artist."
    return IpodTagProfile(
        label=" ".join(part for part in (family, generation) if part).strip() or "Generic iPod",
        detail=detail,
        has_cover_flow=has_cover_flow,
        uses_sqlite_db=uses_sqlite_db,
        supports_album_artist_reliably=uses_sqlite_db or "touch" in family_norm,
        is_shuffle=is_shuffle,
    )


def suggest_ipod_library_tag_fixes(
    library_tracks: list[dict],
    *,
    profile: IpodTagProfile | None = None,
) -> IpodLibraryTagSuggestion:
    """Return library-wide metadata edits that keep iPod browser identities stable."""

    profile = profile or ipod_tag_profile()
    tracks = list(library_tracks)
    acc = _TagFixAccumulator(tracks)

    for track in tracks:
        _queue_text_cleanup(track, acc)

    if not profile.is_shuffle:
        if not profile.supports_album_artist_reliably:
            for album_title_group in _album_title_groups(tracks, acc).values():
                _queue_inferred_compilation_marking(album_title_group, acc)

        for album_group in _album_groups(tracks, acc).values():
            _queue_explicit_compilation_normalization(album_group, acc)

        if not profile.supports_album_artist_reliably:
            for album_group in _album_groups(tracks, acc).values():
                if not _is_compilation_group(album_group, acc):
                    _queue_featured_artist_cleanup(album_group, acc)
            for album_group in _album_groups(tracks, acc).values():
                if not _is_compilation_group(album_group, acc):
                    _queue_album_artist_unification(album_group, acc)
            _queue_unique_album_edits_for_collisions(tracks, acc)

        _queue_library_sort_consistency(tracks, acc)

    warnings: list[str] = []
    if not profile.supports_album_artist_reliably:
        warnings.append("Album Artist is preserved, but this profile treats Artist as the safer iPod grouping field.")
    if profile.has_cover_flow:
        warnings.append("Cover Flow devices are sensitive to Artist+Album differences and same-name albums.")
    return IpodLibraryTagSuggestion(
        profile=profile,
        changes_by_track=acc.changes_by_track(),
        warnings=tuple(warnings),
    )


def _clean_text(value: Any) -> str:
    return _SPACE_RE.sub(" ", _CONTROL_RE.sub("", str(value or "")).strip())


def _norm(value: Any) -> str:
    return _clean_text(value).casefold()


def _current_clean(track: dict, key: str, acc: _TagFixAccumulator) -> str:
    return _clean_text(acc.current(track, key))


def _current_norm(track: dict, key: str, acc: _TagFixAccumulator) -> str:
    return _norm(acc.current(track, key))


def _album_groups(tracks: list[dict], acc: _TagFixAccumulator) -> dict[tuple[str, str], list[dict]]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for track in tracks:
        album = _current_norm(track, "Album", acc)
        album_artist = _current_norm(track, "Album Artist", acc) or _current_norm(track, "Artist", acc)
        groups[(album, album_artist)].append(track)
    return groups


def _album_title_groups(tracks: list[dict], acc: _TagFixAccumulator) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for track in tracks:
        album = _current_norm(track, "Album", acc)
        if album:
            groups[album].append(track)
    return groups


def _queue_text_cleanup(track: dict, acc: _TagFixAccumulator) -> None:
    for key in (
        "Title",
        "Artist",
        "Album",
        "Album Artist",
        "Composer",
        "Sort Title",
        "Sort Artist",
        "Sort Album",
        "Sort Album Artist",
        "Sort Composer",
        "Sort Show",
    ):
        if key not in track:
            continue
        cleaned = _clean_text(track.get(key))
        if cleaned != str(track.get(key) or ""):
            acc.queue(track, key, cleaned, "Remove hidden/control whitespace that can split identical-looking iPod entries.")


def _queue_album_artist_unification(group: list[dict], acc: _TagFixAccumulator) -> None:
    album_artists = [_current_clean(t, "Album Artist", acc) for t in group if _current_clean(t, "Album Artist", acc)]
    if not album_artists:
        return
    canonical = Counter(album_artists).most_common(1)[0][0]
    for track in group:
        artist = _current_clean(track, "Artist", acc)
        if artist and artist != canonical:
            acc.queue(track, "Artist", canonical, "Use Album Artist as Artist so iPod artist/album menus group the album together.")
        if _current_clean(track, "Album Artist", acc) != canonical:
            acc.queue(track, "Album Artist", canonical, "Normalize Album Artist across the album.")


def _queue_featured_artist_cleanup(group: list[dict], acc: _TagFixAccumulator) -> None:
    album_artists = [_current_clean(t, "Album Artist", acc) for t in group if _current_clean(t, "Album Artist", acc)]
    canonical = Counter(album_artists).most_common(1)[0][0] if album_artists else ""
    if not canonical:
        return
    for track in group:
        artist = _current_clean(track, "Artist", acc)
        title = _current_clean(track, "Title", acc)
        if not artist or artist == canonical or not artist.casefold().startswith(canonical.casefold()):
            continue
        remainder = artist[len(canonical):].strip(" -_/,+;&")
        if not remainder:
            continue
        featured = _featured_suffix_from_artist(remainder)
        if not featured or _FEAT_IN_TITLE_RE.search(title):
            continue
        acc.queue(track, "Artist", canonical, "Move featured artists out of Artist to avoid duplicate artist/album entries.")
        acc.queue(track, "Title", f"{title} (feat. {featured})", "Move featured artists out of Artist to avoid duplicate artist/album entries.")


def _featured_suffix_from_artist(text: str) -> str:
    stripped = _clean_text(text)
    stripped = re.sub(r"^(?:feat\.?|ft\.?|featuring|with)\s+", "", stripped, flags=re.IGNORECASE)
    return stripped.strip(" ()[]")


def _is_compilation_group(group: list[dict], acc: _TagFixAccumulator) -> bool:
    return any(bool(acc.current(track, "compilation_flag")) for track in group)


def _queue_explicit_compilation_normalization(
    group: list[dict],
    acc: _TagFixAccumulator,
) -> None:
    if not _is_compilation_group(group, acc):
        return
    _queue_compilation_fields(group, acc)


def _queue_inferred_compilation_marking(group: list[dict], acc: _TagFixAccumulator) -> None:
    artists = {_current_norm(t, "Artist", acc) for t in group if _current_norm(t, "Artist", acc)}
    album_artists = {
        _current_norm(t, "Album Artist", acc)
        for t in group
        if _current_norm(t, "Album Artist", acc)
    }
    is_various = any(value in {"various artists", "various", "va"} for value in album_artists)
    if len(artists) <= 1 and not is_various:
        return
    if not is_various and album_artists:
        return
    _queue_compilation_fields(group, acc)


def _queue_compilation_fields(group: list[dict], acc: _TagFixAccumulator) -> None:
    for track in group:
        acc.queue(track, "Album Artist", "Various Artists", "Set a stable album artist for true compilations.")
        acc.queue(track, "compilation_flag", 1, "Mark true compilations so iPod compilation handling can keep them together.")


def _queue_library_sort_consistency(tracks: list[dict], acc: _TagFixAccumulator) -> None:
    for display_key, sort_key in (
        ("Artist", "Sort Artist"),
        ("Album Artist", "Sort Album Artist"),
        ("Album", "Sort Album"),
        ("Composer", "Sort Composer"),
    ):
        _queue_sort_pair_consistency(tracks, acc, display_key, sort_key)


def _queue_sort_pair_consistency(
    tracks: list[dict],
    acc: _TagFixAccumulator,
    display_key: str,
    sort_key: str,
) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for track in tracks:
        display_norm = _current_norm(track, display_key, acc)
        if display_norm:
            groups[display_norm].append(track)

    for group in groups.values():
        displays = [_current_clean(track, display_key, acc) for track in group if _current_clean(track, display_key, acc)]
        if not displays:
            continue
        display = _most_common_text(displays)
        existing_sorts = [_current_clean(track, sort_key, acc) for track in group if _current_clean(track, sort_key, acc)]
        canonical_sort = _canonical_sort_value(display, existing_sorts)
        if not canonical_sort:
            continue
        for track in group:
            if _current_clean(track, sort_key, acc) != canonical_sort:
                acc.queue(
                    track,
                    sort_key,
                    canonical_sort,
                    f"Keep {sort_key} consistent for every {display_key} value.",
                )


def _most_common_text(values: list[str]) -> str:
    counts = Counter(values)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold(), item[0]))[0][0]


def _canonical_sort_value(display: str, existing_sorts: list[str]) -> str:
    generated = _intelligent_sort_value(display)
    if generated != display:
        return generated
    if existing_sorts:
        return _most_common_text(existing_sorts)
    return generated


def _intelligent_sort_value(value: Any) -> str:
    text = _clean_text(value)
    match = _LEADING_ARTICLE_RE.match(text)
    if not match:
        return text
    return f"{match.group('body')}, {match.group('article')}"


def _queue_unique_album_edits_for_collisions(library_tracks: list[dict], acc: _TagFixAccumulator) -> None:
    by_album: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    album_artist_presence: dict[str, bool] = defaultdict(bool)
    for track in library_tracks:
        album = _current_clean(track, "Album", acc)
        if not album:
            continue
        album_key = _norm(album)
        if _current_clean(track, "Album Artist", acc):
            album_artist_presence[album_key] = True
        artist = _current_clean(track, "Album Artist", acc) or _current_clean(track, "Artist", acc) or "Unknown Artist"
        by_album[album_key][artist].append(track)

    for album_key, artist_groups in by_album.items():
        if len(artist_groups) <= 1:
            continue
        if not album_artist_presence[album_key]:
            continue
        for artist, tracks in artist_groups.items():
            for track in tracks:
                album = _current_clean(track, "Album", acc)
                if album and artist and f"({artist})" not in album:
                    acc.queue(
                        track,
                        "Album",
                        f"{album} ({artist})",
                        "Make duplicate album titles unique for iPod Albums and Cover Flow grouping.",
                    )
