"""Planner for playlist files managed by media-folder sync."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from .path_identity import coerce_int
from .sync_playlist_files import (
    SYNC_PLAYLIST_SOURCE,
    SyncPlaylistDiscovery,
    SyncPlaylistFile,
    is_managed_sync_playlist_id,
    normalize_sync_playlist_path,
)
from .track_identity import PlaylistTrackIdentityIndex


@dataclass(frozen=True, slots=True)
class SyncPlaylistPlan:
    """Playlist actions emitted by media-folder playlist planning."""

    to_add: tuple[dict, ...] = ()
    to_edit: tuple[dict, ...] = ()
    to_remove: tuple[dict, ...] = ()


def build_sync_playlist_changes(
    discovery: SyncPlaylistDiscovery,
    existing_playlists: Iterable[dict],
    ipod_tracks: Iterable[dict],
    *,
    source_path_to_db_track_id: dict[str, int],
    pending_add_source_paths: set[str],
    valid_source_paths: set[str],
    source_path_aliases: dict[str, str] | None = None,
    selected_playlist_source_paths: AbstractSet[str] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return playlist add/edit/remove payloads for discovered sync playlists."""

    identity_index = PlaylistTrackIdentityIndex.build(
        source_path_to_db_track_id=source_path_to_db_track_id,
        pending_add_source_paths=pending_add_source_paths,
        valid_source_paths=valid_source_paths,
        source_path_aliases=source_path_aliases,
    )
    plan = SyncPlaylistPlanner(
        identity_index=identity_index,
        ipod_tracks=ipod_tracks,
    ).plan(
        discovery,
        existing_playlists,
        selected_playlist_source_paths=selected_playlist_source_paths,
    )
    return list(plan.to_add), list(plan.to_edit), list(plan.to_remove)


class SyncPlaylistPlanner:
    """Build add/edit/remove payloads for discovered sync playlist files."""

    def __init__(
        self,
        *,
        identity_index: PlaylistTrackIdentityIndex,
        ipod_tracks: Iterable[dict],
    ) -> None:
        self.identity_index = identity_index
        self.old_tid_to_db_track_id = _old_tid_to_db_track_id(ipod_tracks)

    def plan(
        self,
        discovery: SyncPlaylistDiscovery,
        existing_playlists: Iterable[dict],
        *,
        selected_playlist_source_paths: AbstractSet[str] | None = None,
    ) -> SyncPlaylistPlan:
        selected_playlist_keys = selected_playlist_source_paths
        existing_by_id: dict[int, dict] = {}
        managed_existing: dict[int, dict] = {}
        for existing_playlist in existing_playlists:
            if existing_playlist.get("master_flag"):
                continue
            playlist_id = coerce_int(existing_playlist.get("playlist_id"))
            if not playlist_id:
                continue
            existing_by_id.setdefault(playlist_id, existing_playlist)
            if is_managed_sync_playlist_id(playlist_id):
                managed_existing.setdefault(playlist_id, existing_playlist)

        current_ids = set(discovery.source_playlist_ids)
        to_add: list[dict] = []
        to_edit: list[dict] = []

        for source_playlist in discovery.playlists:
            if (
                selected_playlist_keys is not None
                and normalize_sync_playlist_path(source_playlist.source_path)
                not in selected_playlist_keys
            ):
                continue
            payload = self._playlist_payload(source_playlist)
            existing = existing_by_id.get(source_playlist.playlist_id)
            if existing is None:
                to_add.append(payload)
                continue

            payload["_isNew"] = False
            if self._playlist_needs_update(existing, payload):
                to_edit.append(payload)

        to_remove = [
            {
                **dict(playlist),
                "_source": SYNC_PLAYLIST_SOURCE,
                "_sync_playlist_deleted": True,
            }
            for playlist_id, playlist in sorted(managed_existing.items())
            if playlist_id not in current_ids
        ]

        return SyncPlaylistPlan(
            to_add=tuple(to_add),
            to_edit=tuple(to_edit),
            to_remove=tuple(to_remove),
        )

    def _playlist_payload(self, playlist: SyncPlaylistFile) -> dict:
        items: list[dict[str, str | int]] = []
        unresolved = 0
        for item in playlist.items:
            resolved = self.identity_index.resolve_playlist_source(item["source_path"])
            if resolved is None:
                unresolved += 1
                continue
            payload_item: dict[str, str | int] = {"source_path": resolved.source_path}
            if resolved.db_track_id:
                payload_item["db_track_id"] = resolved.db_track_id
            items.append(payload_item)

        skipped = playlist.skipped_entries + unresolved
        return {
            "Title": playlist.title,
            "playlist_id": playlist.playlist_id,
            "_isNew": True,
            "_source": SYNC_PLAYLIST_SOURCE,
            "_mhsd_dataset_type": 2,
            "_mhsd_result_key": "mhlp",
            "_sync_playlist_path": playlist.source_path,
            "_sync_playlist_total_entries": playlist.total_entries,
            "_sync_playlist_skipped_count": skipped,
            "items": items,
            "mhip_child_count": len(items),
        }

    def _playlist_needs_update(self, existing: dict, desired: dict) -> bool:
        if existing.get("Title") != desired.get("Title"):
            return True

        desired_ids: list[int] = []
        has_pending_add = False
        for item in desired.get("items", []):
            db_track_id = coerce_int(item.get("db_track_id", item.get("db_id", 0)))
            if db_track_id:
                desired_ids.append(db_track_id)
                continue
            source_path = item.get("source_path") or item.get("_source_path")
            if source_path and self.identity_index.resolve_playlist_source(source_path):
                has_pending_add = True
                continue
            return True

        if has_pending_add:
            return True

        existing_ids = _playlist_db_track_ids(
            existing.get("items", []),
            self.old_tid_to_db_track_id,
        )
        return existing_ids != desired_ids


def _playlist_db_track_ids(
    items: Iterable[dict],
    old_tid_to_db_track_id: dict[int, int],
) -> list[int]:
    result: list[int] = []
    for item in items:
        db_track_id = coerce_int(item.get("db_track_id", item.get("db_id", 0)))
        if not db_track_id:
            db_track_id = old_tid_to_db_track_id.get(coerce_int(item.get("track_id")), 0)
        if db_track_id:
            result.append(db_track_id)
    return result


def _old_tid_to_db_track_id(ipod_tracks: Iterable[dict]) -> dict[int, int]:
    result: dict[int, int] = {}
    for track in ipod_tracks:
        track_id = coerce_int(track.get("track_id"))
        db_track_id = coerce_int(track.get("db_track_id", track.get("db_id", 0)))
        if track_id and db_track_id:
            result[track_id] = db_track_id
    return result
