"""Track identity indexes shared by sync planning stages."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .path_identity import coerce_int, stable_path_key


@dataclass(frozen=True, slots=True)
class ResolvedPlaylistTrack:
    """Resolved identity for one source playlist item."""

    source_path: str
    db_track_id: int = 0
    pending_add: bool = False


@dataclass(frozen=True, slots=True)
class PlaylistTrackIdentityIndex:
    """Canonical source-path to device-track identity resolver.

    Playlist planning should not guess at device membership from raw playlist
    paths.  This index centralizes the three safe states:
    - already-known iPod track: direct ``db_track_id``
    - track being added in this sync: canonical ``source_path`` fallback
    - unresolved: not safe to attach
    """

    source_path_to_db_track_id: Mapping[str, int]
    pending_add_source_paths: frozenset[str]
    valid_source_paths: frozenset[str]
    source_path_aliases: Mapping[str, str]

    @classmethod
    def build(
        cls,
        *,
        source_path_to_db_track_id: Mapping[str, int] | None = None,
        pending_add_source_paths: Iterable[str] = (),
        valid_source_paths: Iterable[str] = (),
        source_path_aliases: Mapping[str, str] | None = None,
    ) -> PlaylistTrackIdentityIndex:
        aliases = {
            stable_path_key(source): stable_path_key(target)
            for source, target in (source_path_aliases or {}).items()
        }
        db_ids = {
            cls._apply_alias(stable_path_key(path), aliases): db_track_id
            for path, raw_db_track_id in (source_path_to_db_track_id or {}).items()
            if (db_track_id := coerce_int(raw_db_track_id))
        }
        pending = frozenset(
            cls._apply_alias(stable_path_key(path), aliases)
            for path in pending_add_source_paths
        )
        valid = frozenset(
            cls._apply_alias(stable_path_key(path), aliases)
            for path in valid_source_paths
        )
        return cls(
            source_path_to_db_track_id=db_ids,
            pending_add_source_paths=pending,
            valid_source_paths=valid,
            source_path_aliases=aliases,
        )

    def canonical_source_path(self, path: str) -> str:
        key = stable_path_key(path)
        return self.source_path_aliases.get(key, key)

    def resolve_playlist_source(self, path: str) -> ResolvedPlaylistTrack | None:
        source_key = self.canonical_source_path(path)
        db_track_id = coerce_int(self.source_path_to_db_track_id.get(source_key))
        if db_track_id:
            return ResolvedPlaylistTrack(source_path=source_key, db_track_id=db_track_id)
        if source_key in self.pending_add_source_paths:
            return ResolvedPlaylistTrack(source_path=source_key, pending_add=True)
        if source_key in self.valid_source_paths:
            return None
        return None

    @staticmethod
    def _apply_alias(path: str, aliases: Mapping[str, str]) -> str:
        return aliases.get(path, path)


@dataclass(slots=True)
class SyncTrackIdentityState:
    """Mutable identity state accumulated during track matching."""

    claimed_db_track_ids: set[int] = field(default_factory=set)
    source_path_to_db_track_id: dict[str, int] = field(default_factory=dict)
    source_path_aliases: dict[str, str] = field(default_factory=dict)

    def claim(self, db_track_id: object) -> None:
        db_id = coerce_int(db_track_id)
        if db_id:
            self.claimed_db_track_ids.add(db_id)

    def is_claimed(self, db_track_id: object) -> bool:
        db_id = coerce_int(db_track_id)
        return bool(db_id and db_id in self.claimed_db_track_ids)

    def record_matched_source(self, source_path: str, db_track_id: object) -> None:
        db_id = coerce_int(db_track_id)
        if not db_id:
            return
        self.source_path_to_db_track_id[stable_path_key(source_path)] = db_id

    def record_duplicate_group_aliases(self, tracks: Sequence[Any]) -> None:
        if len(tracks) < 2:
            return
        representative_path = str(getattr(tracks[0], "path", "") or "")
        if not representative_path:
            return
        representative_key = stable_path_key(representative_path)
        for duplicate_track in tracks[1:]:
            duplicate_path = str(getattr(duplicate_track, "path", "") or "")
            if duplicate_path:
                self.source_path_aliases[stable_path_key(duplicate_path)] = representative_key

    def build_playlist_index(
        self,
        *,
        pending_add_source_paths: Iterable[str],
        valid_source_paths: Iterable[str],
    ) -> PlaylistTrackIdentityIndex:
        return PlaylistTrackIdentityIndex.build(
            source_path_to_db_track_id=self.source_path_to_db_track_id,
            pending_add_source_paths=pending_add_source_paths,
            valid_source_paths=valid_source_paths,
            source_path_aliases=self.source_path_aliases,
        )


@dataclass(frozen=True, slots=True)
class FingerprintIdentityPlan:
    """Fingerprint-plus-album grouping used before collision matching."""

    groups: Mapping[tuple[str, str], tuple[Any, ...]]
    duplicates: Mapping[str, tuple[Any, ...]]

    def sorted_groups_for_matching(
        self,
        *,
        mapping: Any,
        ipod_by_db_track_id: Mapping[int, dict],
    ) -> tuple[tuple[tuple[str, str], tuple[Any, ...]], ...]:
        """Return groups ordered so confident album matches claim db IDs first."""

        def album_match_priority(item: tuple[tuple[str, str], tuple[Any, ...]]) -> int:
            (fingerprint, album_key), _tracks = item
            for entry in mapping.get_entries(fingerprint):
                ipod_track = ipod_by_db_track_id.get(entry.db_track_id)
                if not ipod_track:
                    continue
                ipod_album = (ipod_track.get("Album", "") or "").strip().lower()
                if ipod_album == album_key:
                    return 0
            return 1

        return tuple(sorted(self.groups.items(), key=album_match_priority))


def build_fingerprint_identity_plan(
    pc_by_fp: Mapping[str, Sequence[Any]],
) -> FingerprintIdentityPlan:
    """Group PC tracks by fingerprint and album identity."""

    groups: dict[tuple[str, str], tuple[Any, ...]] = {}
    duplicates: dict[str, tuple[Any, ...]] = {}

    for fingerprint, tracks in pc_by_fp.items():
        by_album: dict[str, list[Any]] = {}
        for track in tracks:
            album_key = (getattr(track, "album", "") or "").strip().lower()
            by_album.setdefault(album_key, []).append(track)

        for album_key, album_tracks in by_album.items():
            group_tracks = tuple(album_tracks)
            groups[(fingerprint, album_key)] = group_tracks
            if len(group_tracks) > 1:
                first = group_tracks[0]
                display_key = (
                    f"{getattr(first, 'artist', '') or 'Unknown'}|"
                    f"{getattr(first, 'album', '') or 'Unknown'}|"
                    f"{getattr(first, 'title', '') or 'Unknown'}"
                )
                duplicates[display_key] = group_tracks

    return FingerprintIdentityPlan(groups=groups, duplicates=duplicates)
