"""Semantic inputs to native browse groups, independent of candidate documents."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, fields

from iPodDB.library.models import MediaKind, Track


def group_key(track: Track, *, album: bool) -> tuple[str, ...]:
    # Preserve the established grouping policy. Changing album equivalence is a
    # separate compatibility decision from maintaining a group's native metadata.
    return (
        (
            track.album,
            track.album_artist or track.artist,
            str(track.metadata.compilation),
            track.show,
            str(track.season_number),
        )
        if album
        else (track.artist,)
    )


def browse_groups(
    tracks: Sequence[Track], *, album: bool
) -> dict[tuple[str, ...], tuple[Track, ...]]:
    groups: dict[tuple[str, ...], list[Track]] = defaultdict(list)
    for track in tracks:
        groups[group_key(track, album=album)].append(track)
    return {key: tuple(members) for key, members in groups.items()}


def native_browse_groups(
    tracks: Sequence[Track], *, album: bool
) -> dict[tuple[str, ...], tuple[Track, ...]]:
    """Retain Podcast album ownership across optional Episode tag differences.

    A retained show can contain different artists, show tags, and seasons. Those
    values still distinguish sort-4 browse groups, but must not cause repeated
    rewrites of one MHIA. Separate source albums remain separate; merging them
    belongs to explicit Podcast normalization. Title/feed edits can split a show.
    """
    feeds: dict[tuple[int, str], set[str]] = defaultdict(set)
    for track in tracks:
        if (
            album
            and (track.media_kind is MediaKind.PODCAST or track.metadata.podcast)
            and track.ipod
            and track.ipod.album_id
            and track.metadata.podcast_rss_url
        ):
            feeds[track.ipod.album_id, track.album].add(track.metadata.podcast_rss_url)
    retained: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    keys: dict[int, tuple[str, ...]] = {}
    for track in tracks:
        if (
            album
            and (track.media_kind is MediaKind.PODCAST or track.metadata.podcast)
            and track.ipod
            and track.ipod.album_id
        ):
            feed = track.metadata.podcast_rss_url
            candidates = feeds[track.ipod.album_id, track.album]
            if not feed and len(candidates) == 1:
                feed = next(iter(candidates))
            key: tuple[str, ...] = (
                "podcast",
                str(track.ipod.album_id),
                track.album,
                feed,
            )
            keys[track.track_id] = key
            retained[track.album].add(key)
    groups: dict[tuple[str, ...], list[Track]] = defaultdict(list)
    for track in tracks:
        key = keys.get(track.track_id, ("browse", *group_key(track, album=album)))
        if (
            album
            and (track.media_kind is MediaKind.PODCAST or track.metadata.podcast)
            and (not track.ipod or not track.ipod.album_id)
        ):
            # A new Episode can join one unambiguous retained show. Do not
            # choose between duplicate source albums or conflicting feeds.
            matches = {
                k
                for k in retained[track.album]
                if not track.metadata.podcast_rss_url
                or not k[3]
                or k[3] == track.metadata.podcast_rss_url
            }
            if len(matches) == 1:
                key = next(iter(matches))
        groups[key].append(track)
    return {key: tuple(members) for key, members in groups.items()}


def podcast_groups(tracks: Sequence[Track]) -> dict[str, tuple[Track, ...]]:
    """Podcast show rows use album titles; conflicting feeds are ambiguous."""
    groups: dict[str, list[Track]] = defaultdict(list)
    for track in tracks:
        if track.media_kind is MediaKind.PODCAST or track.metadata.podcast:
            groups[track.album].append(track)
    for title, members in groups.items():
        feeds = {
            t.metadata.podcast_rss_url for t in members if t.metadata.podcast_rss_url
        }
        if len(feeds) > 1:
            raise ValueError(f"Podcast show {title!r} has conflicting feed identities.")
    return {title: tuple(members) for title, members in groups.items()}


@dataclass(frozen=True, slots=True)
class AlbumValues:
    title: str
    artist: str
    sort_artist: str
    podcast_url: str
    show: str
    compilation: bool
    season: int
    content_type: int


def album_values(members: Sequence[Track]) -> AlbumValues:
    """Original write_mhla selects the first nonempty value in Library order."""
    first = members[0]
    sort = next(
        (t.metadata.sort_album_artist for t in members if t.metadata.sort_album_artist),
        "",
    )
    if not sort:
        sort = next(
            (t.metadata.sort_artist for t in members if t.metadata.sort_artist), ""
        )
    return AlbumValues(
        first.album,
        first.album_artist or first.artist,
        sort,
        next(
            (t.metadata.podcast_rss_url for t in members if t.metadata.podcast_rss_url),
            "",
        ),
        first.show,
        first.metadata.compilation,
        first.season_number,
        3
        if any(t.media_kind is MediaKind.PODCAST or t.metadata.podcast for t in members)
        else 2,
    )


def unchanged_podcast_album_fields(
    previous: Sequence[Track], members: Sequence[Track]
) -> frozenset[str]:
    """Unchanged Episode values do not redefine retained show-level metadata."""
    if not previous or not all(
        t.media_kind is MediaKind.PODCAST or t.metadata.podcast
        for t in (*previous, *members)
    ):
        return frozenset()
    before, after = album_values(previous), album_values(members)
    return frozenset(
        f.name
        for f in fields(AlbumValues)
        if f.name != "content_type"
        and getattr(before, f.name) == getattr(after, f.name)
    )
