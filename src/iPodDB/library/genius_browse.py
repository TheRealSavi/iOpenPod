"""Read-only native Genius collections, separate from the editable Library.

Saved Playlists contain an ordered playback collection. A Mix's members are
possible starting Tracks; the firmware chooses its eventual playback queue.
Every input is already-captured data, without filesystem or persistence authority.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from iPodDB.library.playlists import PlaylistKind
from iPodDB.sidecars import genius_playlist_number, parse_genius_playlist

if TYPE_CHECKING:
    from iPodDB.library.models import LibrarySnapshot
    from iPodDB.sidecars import PlaybackSidecar

_U64 = (1 << 64) - 1


class GeniusCollectionKind(StrEnum):
    PLAYLIST = "playlist"
    MIX = "mix"


@dataclass(frozen=True, slots=True)
class GeniusCollection:
    """Native collection using semantic Track IDs solely for read-only display.

    ``track_ids`` retain ordered occurrences for Playlists and ordered possible
    starting Tracks for Mixes. A Mix's optional ``seed_track_id`` is only its
    compatibility seed, never evidence of the seed chosen during playback.
    ``native_playlist_id`` permits presentation deduplication with a CDB Playlist.
    """

    collection_id: str
    name: str
    kind: GeniusCollectionKind
    track_ids: tuple[int, ...]
    seed_track_id: int | None
    native_playlist_id: int | None = None


@dataclass(frozen=True, slots=True)
class GeniusBrowseIssue:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class GeniusBrowse:
    collections: tuple[GeniusCollection, ...] = ()
    issues: tuple[GeniusBrowseIssue, ...] = ()


class _ProjectionError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _identity(value: object) -> int:
    if type(value) is not int or not -(1 << 63) <= value <= _U64 or not value:
        raise _ProjectionError("genius.invalid_identity", "Invalid persistent identity")
    return value & _U64


def _track_index(snapshot: LibrarySnapshot) -> tuple[dict[int, int], frozenset[int]]:
    pairs = tuple(
        (track.ipod.db_track_id, track.track_id)
        for track in snapshot.tracks
        if track.ipod is not None and track.ipod.db_track_id
    )
    counts = Counter(pid for pid, _ in pairs)
    ambiguous = frozenset(pid for pid, count in counts.items() if count > 1)
    return {pid: tid for pid, tid in pairs if pid not in ambiguous}, ambiguous


def _track(pid: int, tracks: dict[int, int], ambiguous: frozenset[int]) -> int:
    if pid in ambiguous:
        raise _ProjectionError(
            "genius.ambiguous_track",
            "A persistent identity matches multiple Library Tracks",
        )
    if pid not in tracks:
        raise _ProjectionError(
            "genius.missing_track",
            "A referenced Track is absent from the captured Library",
        )
    return tracks[pid]


def _saved_playlists(
    snapshot: LibrarySnapshot,
    sidecars: tuple[PlaybackSidecar, ...],
    tracks: dict[int, int],
    ambiguous: frozenset[int],
) -> tuple[list[GeniusCollection], list[GeniusBrowseIssue]]:
    collections: list[GeniusCollection] = []
    issues: list[GeniusBrowseIssue] = []
    relevant = tuple(
        sidecar
        for sidecar in sidecars
        if genius_playlist_number(sidecar.name) is not None
    )
    counts = Counter(sidecar.name.casefold() for sidecar in relevant)
    for sidecar in relevant:
        try:
            if counts[sidecar.name.casefold()] > 1:
                raise _ProjectionError(
                    "genius.duplicate_source",
                    "Multiple captures have the same filename",
                )
            playlist = parse_genius_playlist(sidecar.data).playlist
            if playlist is None:
                raise _ProjectionError(
                    "genius.unsupported_playlist",
                    "The saved Playlist version is not supported",
                )
            members = tuple(
                _track(pid, tracks, ambiguous) for pid in playlist.track_persistent_ids
            )
            seed = _track(playlist.seed_track_persistent_id, tracks, ambiguous)
            if playlist.track_master_indexes is not None:
                for position, pid in zip(
                    playlist.track_master_indexes,
                    playlist.track_persistent_ids,
                    strict=True,
                ):
                    details = (
                        snapshot.tracks[position].ipod
                        if position < len(snapshot.tracks)
                        else None
                    )
                    if details is None or details.db_track_id != pid:
                        raise _ProjectionError(
                            "genius.position_mismatch",
                            "Saved Track positions disagree with their persistent identities",
                        )
            native_id = playlist.playlist_persistent_id
            identity = (
                f"{native_id:016x}"
                if native_id is not None
                else sidecar.name.casefold()
            )
            collections.append(
                GeniusCollection(
                    f"genius-playlist:{identity}",
                    playlist.name,
                    GeniusCollectionKind.PLAYLIST,
                    members,
                    seed,
                    native_id,
                )
            )
        except _ProjectionError as error:
            issues.append(GeniusBrowseIssue(error.code, f"{sidecar.name}: {error}"))
        except ValueError as error:
            issues.append(
                GeniusBrowseIssue("genius.invalid_playlist", f"{sidecar.name}: {error}")
            )
    return collections, issues


def _canonical_playlists(
    snapshot: LibrarySnapshot,
    tracks: dict[int, int],
    ambiguous: frozenset[int],
) -> tuple[list[GeniusCollection], list[GeniusBrowseIssue]]:
    collections: list[GeniusCollection] = []
    issues: list[GeniusBrowseIssue] = []
    live_track_ids = frozenset(track.track_id for track in snapshot.tracks)
    for playlist in snapshot.playlists:
        if playlist.kind is not PlaylistKind.GENIUS:
            continue
        try:
            native_id = _identity(playlist.playlist_id)
            if not set(playlist.track_ids) <= live_track_ids:
                raise _ProjectionError(
                    "genius.missing_track",
                    "A referenced Track is absent from the captured Library",
                )
        except _ProjectionError as error:
            issues.append(GeniusBrowseIssue(error.code, f"{playlist.name}: {error}"))
            continue
        seed = None
        try:
            if not playlist.genius_seed_persistent_id:
                raise _ProjectionError(
                    "genius.unavailable_seed",
                    "The native seed identity could not be interpreted",
                )
            seed = _track(playlist.genius_seed_persistent_id, tracks, ambiguous)
        except _ProjectionError as error:
            # A retained unknown seed does not prevent browsing this canonical
            # Playlist's independently known ordered membership.
            issues.append(GeniusBrowseIssue(error.code, f"{playlist.name}: {error}"))
        collections.append(
            GeniusCollection(
                f"genius-playlist:{native_id:016x}",
                playlist.name,
                GeniusCollectionKind.PLAYLIST,
                playlist.track_ids,
                seed,
                native_id,
            )
        )
    return collections, issues


def _mixes(
    data: bytes,
    tracks: dict[int, int],
    ambiguous: frozenset[int],
) -> tuple[list[GeniusCollection], list[GeniusBrowseIssue]]:
    collections: list[GeniusCollection] = []
    issues: list[GeniusBrowseIssue] = []
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.deserialize(data)
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA query_only=ON")
            if tuple(
                row[0] for row in connection.execute("PRAGMA integrity_check")
            ) != ("ok",):
                raise ValueError("SQLite integrity check failed")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not {"container", "item_to_container"} <= tables:
                raise ValueError("Required Mix tables are absent")
            for pid, name in connection.execute(
                "SELECT pid,name FROM container WHERE distinguished_kind=32 ORDER BY name_order,pid"
            ):
                try:
                    native_id = _identity(pid)
                    if name is not None and not isinstance(name, str):
                        raise _ProjectionError(
                            "genius.invalid_mix", "Mix name is not text"
                        )
                    rows = tuple(
                        connection.execute(
                            "SELECT item_pid,physical_order FROM item_to_container WHERE container_pid=? ORDER BY physical_order,rowid",
                            (pid,),
                        )
                    )
                    positions = tuple(row[1] for row in rows)
                    if any(
                        type(position) is not int or position < 0
                        for position in positions
                    ) or len(set(positions)) != len(positions):
                        raise _ProjectionError(
                            "genius.invalid_mix",
                            "Mix seed ordering is invalid or ambiguous",
                        )
                    members = tuple(
                        _track(_identity(row[0]), tracks, ambiguous) for row in rows
                    )
                    seeds = (
                        tuple(
                            connection.execute(
                                "SELECT item_pid FROM container_seed WHERE container_pid=? ORDER BY seed_order,rowid",
                                (pid,),
                            )
                        )
                        if "container_seed" in tables
                        else ()
                    )
                    seed = None
                    if len(seeds) > 1:
                        issues.append(
                            GeniusBrowseIssue(
                                "genius.multiple_mix_seeds",
                                f"Mix {native_id:016x}: multiple compatibility seeds; no single seed is selected for display",
                            )
                        )
                    elif seeds:
                        try:
                            seed = _track(_identity(seeds[0][0]), tracks, ambiguous)
                        except _ProjectionError as error:
                            # Compatibility seeds do not define the independently
                            # known ordered starting Tracks of a native Mix.
                            issues.append(
                                GeniusBrowseIssue(
                                    error.code, f"Mix {native_id:016x}: {error}"
                                )
                            )
                    collections.append(
                        GeniusCollection(
                            f"genius-mix:{native_id:016x}",
                            name or "",
                            GeniusCollectionKind.MIX,
                            members,
                            seed,
                            native_id,
                        )
                    )
                except _ProjectionError as error:
                    issues.append(GeniusBrowseIssue(error.code, f"Mix {pid}: {error}"))
    except (sqlite3.DatabaseError, ValueError, OverflowError) as error:
        return [], [
            GeniusBrowseIssue("genius.invalid_sqlite", f"Library.itdb: {error}")
        ]
    return collections, issues


def project_genius_browse(
    snapshot: LibrarySnapshot,
    sidecars: tuple[PlaybackSidecar, ...] = (),
    *,
    sqlite_library: bytes | None = None,
) -> GeniusBrowse:
    """Project captured firmware collections without importing or consuming them.

    A malformed or unresolvable collection is omitted with an issue, rather than
    displaying a misleading partial Playlist. Other valid collections survive.
    SQLite is consulted only for native Mix metadata, never semantic Track facts.
    """

    tracks, ambiguous = _track_index(snapshot)
    collections, issues = _canonical_playlists(snapshot, tracks, ambiguous)
    canonical = {
        collection.native_playlist_id: collection for collection in collections
    }
    saved, saved_issues = _saved_playlists(snapshot, sidecars, tracks, ambiguous)
    issues.extend(saved_issues)
    for collection in saved:
        existing = canonical.get(collection.native_playlist_id)
        if existing is None:
            collections.append(collection)
        elif collection != existing:
            issues.append(
                GeniusBrowseIssue(
                    "genius.playlist_shadowed",
                    f"{collection.name}: a saved sidecar differs from its canonical Library Playlist; the canonical collection is shown",
                )
            )
    if sqlite_library is not None:
        mixes, mix_issues = _mixes(sqlite_library, tracks, ambiguous)
        collections.extend(mixes)
        issues.extend(mix_issues)
    counts = Counter(collection.collection_id for collection in collections)
    duplicates = frozenset(identity for identity, count in counts.items() if count > 1)
    issues.extend(
        GeniusBrowseIssue(
            "genius.duplicate_collection", f"Multiple collections claim {identity}"
        )
        for identity in sorted(duplicates)
    )
    return GeniusBrowse(
        tuple(
            collection
            for collection in collections
            if collection.collection_id not in duplicates
        ),
        tuple(issues),
    )
