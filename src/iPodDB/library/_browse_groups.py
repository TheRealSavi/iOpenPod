"""Semantic inputs to native browse groups, independent of candidate documents."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from iPodDB.library.models import Track


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


@dataclass(frozen=True, slots=True)
class AlbumValues:
    title: str
    artist: str
    sort_artist: str
    podcast_url: str
    show: str
    compilation: bool
    season: int


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
    )
