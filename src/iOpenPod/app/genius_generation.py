"""A basic local candidate graph for native, Track-seeded Genius Playlists.

The firmware owns Playlist selection and playback. This policy supplies bounded
metadata neighborhoods and a connected fallback graph; it is not an acoustic
similarity model. Its compact configuration and four-key metadata follow the
Classic 6.5G and nano 7G experiments in the native Genius research record.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from hashlib import blake2b
from itertools import zip_longest
from typing import TYPE_CHECKING

from iPodDB.library import MediaKind, is_video_track
from iPodDB.library.genius import (
    GeniusConfigRow,
    GeniusData,
    GeniusMetadata,
    GeniusMetadataRow,
    GeniusSimilarities,
    GeniusSimilaritiesRow,
    GeniusTrack,
    GeniusUpdate,
    make_no_rule_genius_config,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from iPodDB.library import LibrarySnapshot, Track


MAX_GENIUS_CANDIDATES = 256
_MAX_ID = (1 << 64) - 1
_ARTIST_CANDIDATES = 16
_ALBUM_CANDIDATES = 8
_GENRE_CANDIDATES = 128


@dataclass(slots=True)
class _GroupIndex:
    """Shared membership and positions avoid rescanning large metadata groups."""

    members: dict[str, list[int]] = field(default_factory=dict[str, list[int]])
    positions: dict[int, tuple[str, int]] = field(
        default_factory=dict[int, tuple[str, int]]
    )

    def add(self, track_id: int, key: str) -> None:
        if key:
            group = self.members.setdefault(key, [])
            self.positions[track_id] = (key, len(group))
            group.append(track_id)

    def neighbors(self, track_id: int, limit: int) -> Iterator[int]:
        position = self.positions.get(track_id)
        if position is None:
            return
        key, start = position
        group = self.members[key]
        for distance in range(1, min(limit, len(group) - 1) + 1):
            yield group[(start + distance) % len(group)]


def _valid_id(value: int) -> bool:
    return type(value) is int and 0 < value <= _MAX_ID


def _track_order(track: Track) -> tuple[int, int, int]:
    if track.ipod is not None and _valid_id(track.ipod.db_track_id):
        return (0, track.ipod.db_track_id, track.track_id)
    return (1, track.track_id, track.track_id)


def _initial_genius_id(track: Track) -> int:
    namespace, identity, _ = _track_order(track)
    digest = blake2b(
        f"{namespace}:{identity}".encode("ascii"),
        digest_size=8,
        person=b"iOpenPodGenius",
    ).digest()
    return int.from_bytes(digest, "big") or 1


def _assign_ids(tracks: list[Track], checkpoint: Callable[[], None]) -> dict[int, int]:
    existing: Counter[int] = Counter()
    for track in tracks:
        checkpoint()
        if track.ipod is not None and _valid_id(track.ipod.genius_id):
            existing[track.ipod.genius_id] += 1
    # Even an ambiguous old ID stays reserved, so none of its former owners can
    # accidentally inherit another Track's old relationships by allocation.
    occupied = set(existing)
    assigned: dict[int, int] = {}
    for track in tracks:
        checkpoint()
        old = 0 if track.ipod is None else track.ipod.genius_id
        if _valid_id(old) and existing[old] == 1:
            assigned[track.track_id] = old
            continue
        genius_id = _initial_genius_id(track)
        while genius_id in occupied:
            checkpoint()
            genius_id = genius_id % _MAX_ID + 1
        assigned[track.track_id] = genius_id
        occupied.add(genius_id)
    return assigned


def _candidates(
    position: int,
    track_ids: tuple[int, ...],
    artist: _GroupIndex,
    album: _GroupIndex,
    genre: _GroupIndex,
) -> tuple[int, ...]:
    size = len(track_ids)
    if size < 2:
        return ()
    track_id = track_ids[position]
    limit = min(MAX_GENIUS_CANDIDATES, size - 1)
    successor = track_ids[(position + 1) % size]
    chosen: list[int] = []
    seen = {track_id}
    # Reserve one place for the global successor. Every Track can therefore
    # reach the whole music Library even when its metadata group is enormous.
    for group in zip_longest(
        artist.neighbors(track_id, _ARTIST_CANDIDATES),
        genre.neighbors(track_id, _GENRE_CANDIDATES),
        album.neighbors(track_id, _ALBUM_CANDIDATES),
    ):
        for candidate in group:
            capacity = (
                limit if successor in seen or candidate == successor else limit - 1
            )
            if (
                candidate is not None
                and candidate not in seen
                and len(chosen) < capacity
            ):
                chosen.append(candidate)
                seen.add(candidate)
    # At most `limit` ring steps suffice: those distinct positions plus any
    # existing metadata choices already supply `limit` distinct candidates.
    for distance in range(1, limit + 1):
        candidate = track_ids[(position + distance) % size]
        if len(chosen) == limit:
            break
        if candidate not in seen:
            chosen.append(candidate)
            seen.add(candidate)
    return tuple(chosen)


def generate_genius_update(
    snapshot: LibrarySnapshot,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> GeniusUpdate:
    """Prepare every music Track for native Genius without creating any Mixes.

    Existing unique, nonzero unsigned 64-bit Genius IDs survive. New identities
    depend on persistent iPod identity where available, or the semantic Track ID
    (including temporary negative IDs), with deterministic collision handling.
    The write preparation persists these assignments for the next Sync.

    Candidate construction takes O(N log N + N * K) work and O(N * K) space,
    where K is the fixed candidate cap. Metadata groups share indexed membership;
    no Track scans an entire large group. Ordering is independent of Snapshot
    order, Python hash randomization, and the current time.

    The proven configuration requests 25 results with a minimum of 10. Smaller
    Libraries still receive complete valid graphs, but firmware may decline to
    create a Playlist. This function does not lower those untested thresholds.
    """
    check = checkpoint if checkpoint is not None else lambda: None
    check()
    tracks: list[Track] = []
    for track in snapshot.tracks:
        check()
        if (
            track.media_kind is MediaKind.MUSIC
            and not track.metadata.podcast
            and not is_video_track(track)
        ):
            tracks.append(track)
    tracks.sort(key=_track_order)
    assignments = _assign_ids(tracks, check)
    artists, albums, genres = _GroupIndex(), _GroupIndex(), _GroupIndex()
    for track in tracks:
        check()
        artists.add(track.track_id, track.artist.strip().casefold())
        album = track.album.strip().casefold()
        if album:
            albums.add(
                track.track_id,
                "\x1f".join((track.effective_album_artist.strip().casefold(), album)),
            )
        genres.add(track.track_id, track.genre.strip().casefold())
    track_ids = tuple(track.track_id for track in tracks)
    metadata: list[GeniusMetadataRow] = []
    similarities: list[GeniusSimilaritiesRow] = []
    for position, track_id in enumerate(track_ids):
        check()
        genius_id = assignments[track_id]
        metadata.append(
            GeniusMetadataRow(
                genius_id, 2, GeniusMetadata((1, genius_id, genius_id, genius_id))
            )
        )
        candidates = _candidates(position, track_ids, artists, albums, genres)
        similarities.append(
            GeniusSimilaritiesRow(
                genius_id,
                2,
                GeniusSimilarities(tuple(assignments[member] for member in candidates)),
            )
        )
    check()
    return GeniusUpdate(
        GeniusData(
            (GeniusConfigRow(1, 2, 25, 10, make_no_rule_genius_config()),),
            tuple(metadata),
            tuple(similarities),
        ),
        tuple(GeniusTrack(track_id, assignments[track_id]) for track_id in track_ids),
        mixes=None,
    )


__all__ = ["MAX_GENIUS_CANDIDATES", "generate_genius_update"]
