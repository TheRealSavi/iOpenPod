"""Local candidates and native spacing for Track-seeded Genius Playlists.

The firmware owns Playlist selection and playback. This policy supplies bounded
audio-ranked candidates, metadata neighborhoods, and a connected fallback graph.
Artist and album keys support native spacing; acoustic vectors stay on the Host.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from hashlib import blake2b
from itertools import zip_longest
from typing import TYPE_CHECKING

from iOpenPod.app.genius_audio import rank_genius_candidates
from iPodDB.library import MediaKind, is_video_track
from iPodDB.library.genius import (
    GeniusConfigRow,
    GeniusData,
    GeniusMetadata,
    GeniusMetadataRow,
    GeniusSimilarities,
    GeniusSimilaritiesRow,
    GeniusSpacingRule,
    GeniusTrack,
    GeniusUpdate,
    make_no_rule_genius_config,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from iOpenPod.app.genius_audio import GeniusAudioProfile
    from iPodDB.library import LibrarySnapshot, Track


MAX_GENIUS_CANDIDATES = 32
_MAX_ID = (1 << 64) - 1
_ARTIST_CANDIDATES = 16
_ALBUM_CANDIDATES = 8
_GENRE_CANDIDATES = 128
type _GroupKey = str | tuple[str, str]


@dataclass(slots=True)
class _GroupIndex:
    """Shared membership and positions avoid rescanning large metadata groups."""

    members: dict[_GroupKey, list[int]] = field(
        default_factory=dict[_GroupKey, list[int]]
    )
    positions: dict[int, tuple[_GroupKey, int]] = field(
        default_factory=dict[int, tuple[_GroupKey, int]]
    )

    def add(self, track_id: int, key: _GroupKey) -> None:
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


def _album_labels(track: Track) -> tuple[str, str] | None:
    artist = track.effective_album_artist
    album = track.album.casefold()
    return (artist, album) if artist.strip() and album.strip() else None


def _metadata_key(kind: str, labels: tuple[str, ...], genius_id: int) -> int:
    """Hash semantic labels independently of Track order and Python hash seeds.

    Missing labels use the stable Genius identity, so unrelated unknown artists
    or albums do not become one spacing group. Length framing distinguishes
    arbitrary label contents, including separators embedded in tags.
    """
    digest = blake2b(digest_size=8, person=b"iOpenPodGKeys")
    values = (kind, "known", *labels) if labels else (kind, "missing", str(genius_id))
    for value in values:
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return int.from_bytes(digest.digest(), "big") or 1


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
    ranked: tuple[int, ...],
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
    for candidate in ranked:
        capacity = limit if successor in seen or candidate == successor else limit - 1
        if candidate not in seen and len(chosen) < capacity:
            chosen.append(candidate)
            seen.add(candidate)
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
    profiles: Mapping[int, GeniusAudioProfile] | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> GeniusUpdate:
    """Prepare every music Track for native Genius without creating any Mixes.

    Existing unique, nonzero unsigned 64-bit Genius IDs survive. New identities
    depend on persistent iPod identity where available, or the semantic Track ID
    (including temporary negative IDs), with deterministic collision handling.
    The write preparation persists these assignments for the next Sync.

    Optional Host audio profiles rank candidates first. Missing profiles fall
    back to metadata neighborhoods and the Library-wide ring. Both paths use
    bounded candidate pools; metadata groups share indexed membership instead of
    scanning whole groups. Ordering is independent of Snapshot order, Python
    hash randomization, and the current time.

    Metadata slots 1 and 2 carry stable artist and album labels for two opcode-3
    spacing rules. Their distance/jitter parameters are firmware counters, not
    guaranteed song gaps. A floor of 1 allows the first-used key's documented
    counter of 1 to pass after relaxation, including single-group Libraries;
    this does not establish native playability. Acoustic vectors are never
    encoded as native metadata keys.

    The previously tested result thresholds remain 25 desired and 10 minimum.
    Smaller Libraries still receive complete valid graphs, but firmware may
    decline to create a Playlist. This function does not lower those thresholds.
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
    metadata: list[GeniusMetadataRow] = []
    eligible_profiles: dict[int, GeniusAudioProfile] = {}
    for track in tracks:
        check()
        genius_id = assignments[track.track_id]
        # Match native/Common Library identity (ADR-0172). Case and whitespace
        # remain significant for artists; only blank labels count as missing.
        artist = track.artist if track.artist.strip() else ""
        album = _album_labels(track)
        artists.add(track.track_id, artist)
        if album is not None:
            albums.add(track.track_id, album)
        genres.add(track.track_id, track.genre.strip().casefold())
        metadata.append(
            GeniusMetadataRow(
                genius_id,
                2,
                GeniusMetadata(
                    (
                        1,
                        _metadata_key("artist", (artist,) if artist else (), genius_id),
                        _metadata_key("album", album or (), genius_id),
                        genius_id,
                    )
                ),
            )
        )
        if (
            profiles is not None
            and (profile := profiles.get(track.track_id)) is not None
        ):
            eligible_profiles[track.track_id] = profile
    ranked = (
        rank_genius_candidates(
            eligible_profiles, limit=MAX_GENIUS_CANDIDATES, checkpoint=check
        )
        if eligible_profiles
        else {}
    )
    track_ids = tuple(track.track_id for track in tracks)
    similarities: list[GeniusSimilaritiesRow] = []
    for position, track_id in enumerate(track_ids):
        check()
        genius_id = assignments[track_id]
        candidates = _candidates(
            position, track_ids, artists, albums, genres, ranked.get(track_id, ())
        )
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
            (
                GeniusConfigRow(
                    1,
                    2,
                    25,
                    10,
                    replace(
                        make_no_rule_genius_config(),
                        entries=(
                            GeniusSpacingRule(1, 1, 6, 2),
                            GeniusSpacingRule(2, 1, 10, 2),
                        ),
                    ),
                ),
            ),
            tuple(metadata),
            tuple(similarities),
        ),
        tuple(GeniusTrack(track_id, assignments[track_id]) for track_id in track_ids),
        mixes=None,
    )


__all__ = ["MAX_GENIUS_CANDIDATES", "generate_genius_update"]
