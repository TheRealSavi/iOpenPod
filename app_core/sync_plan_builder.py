"""Helpers for building executable sync plans from UI/user selections."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from typing import Any


def build_removal_sync_plan(tracks: Sequence[dict]) -> Any:
    """Build a removal-only SyncPlan for tracks selected in the UI."""

    from SyncEngine.fingerprint_diff_engine import (
        StorageSummary,
        SyncAction,
        SyncItem,
        SyncPlan,
    )

    to_remove = []
    bytes_to_remove = 0
    for track in tracks:
        db_track_id = track.get("db_track_id", track.get("db_id"))
        title = track.get("Title", "Unknown")
        artist = track.get("Artist", "")
        size = track.get("size", track.get("Size", 0)) or 0
        to_remove.append(
            SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                db_track_id=db_track_id,
                ipod_track=track,
                description=(
                    f"Remove: {artist} - {title}"
                    if artist
                    else f"Remove: {title}"
                ),
            )
        )
        bytes_to_remove += int(size)

    return SyncPlan(
        to_remove=to_remove,
        storage=StorageSummary(bytes_to_remove=bytes_to_remove),
        removals_pre_checked=True,
    )


def build_podcast_removal_sync_plan(
    episodes: Sequence[Any],
    ipod_tracks: Sequence[dict],
    feed_title: str,
) -> Any | None:
    """Build a removal-only SyncPlan for podcast episodes already on the iPod."""

    from SyncEngine.fingerprint_diff_engine import (
        StorageSummary,
        SyncAction,
        SyncItem,
        SyncPlan,
    )

    tracks_by_db_track_id = {
        track.get("db_track_id", track.get("db_id", 0)): track
        for track in ipod_tracks
        if track.get("db_track_id", track.get("db_id", 0))
    }

    to_remove = []
    bytes_to_remove = 0
    for episode in episodes:
        db_track_id = getattr(episode, "ipod_db_track_id", None)
        ipod_track = tracks_by_db_track_id.get(db_track_id)
        if not ipod_track:
            continue

        to_remove.append(
            SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                db_track_id=db_track_id,
                ipod_track=ipod_track,
                description=(
                    f"\U0001f399 {feed_title} \u2014 "
                    f"{getattr(episode, 'title', 'Unknown')}"
                ),
            )
        )
        bytes_to_remove += int(ipod_track.get("size", 0) or 0)

    if not to_remove:
        return None

    return SyncPlan(
        to_remove=to_remove,
        storage=StorageSummary(bytes_to_remove=bytes_to_remove),
    )


def build_filtered_sync_plan(
    original_plan: Any | None,
    selected_items: Iterable[Any],
    *,
    include_playlists: bool = True,
    selected_photo_plan: Any | None = None,
) -> Any:
    """Build the executable plan from checked sync-review items."""

    from SyncEngine.fingerprint_diff_engine import StorageSummary, SyncAction, SyncPlan

    from .sync_review_model import sync_item_size_delta

    selected_items = tuple(selected_items)

    grouped: dict[Any, list[Any]] = {
        SyncAction.ADD_TO_IPOD: [],
        SyncAction.REMOVE_FROM_IPOD: [],
        SyncAction.UPDATE_METADATA: [],
        SyncAction.UPDATE_FILE: [],
        SyncAction.UPDATE_ARTWORK: [],
        SyncAction.SYNC_PLAYCOUNT: [],
        SyncAction.SYNC_RATING: [],
    }

    for item in selected_items:
        bucket = grouped.get(item.action)
        if bucket is not None:
            bucket.append(item)

    bytes_to_add = 0
    bytes_to_remove = 0
    bytes_to_update = 0
    for item in selected_items:
        add_delta, remove_delta = sync_item_size_delta(item)
        if item.action == SyncAction.UPDATE_FILE:
            bytes_to_update += add_delta
        else:
            bytes_to_add += add_delta
        bytes_to_remove += remove_delta

    if selected_photo_plan is not None:
        bytes_to_add += int(getattr(selected_photo_plan, "thumb_bytes_to_add", 0) or 0)
        bytes_to_remove += int(getattr(selected_photo_plan, "thumb_bytes_to_remove", 0) or 0)

    return SyncPlan(
        to_add=grouped[SyncAction.ADD_TO_IPOD],
        to_remove=grouped[SyncAction.REMOVE_FROM_IPOD],
        to_update_metadata=grouped[SyncAction.UPDATE_METADATA],
        to_update_file=grouped[SyncAction.UPDATE_FILE],
        to_update_artwork=grouped[SyncAction.UPDATE_ARTWORK],
        to_sync_playcount=grouped[SyncAction.SYNC_PLAYCOUNT],
        to_sync_rating=grouped[SyncAction.SYNC_RATING],
        matched_pc_paths=original_plan.matched_pc_paths if original_plan else {},
        _stale_mapping_entries=(
            original_plan._stale_mapping_entries if original_plan else []
        ),
        _integrity_removals=original_plan._integrity_removals
        if original_plan
        else [],
        mapping=original_plan.mapping if original_plan else None,
        storage=StorageSummary(
            bytes_to_add=bytes_to_add,
            bytes_to_remove=bytes_to_remove,
            bytes_to_update=bytes_to_update,
        ),
        playlists_to_add=(
            original_plan.playlists_to_add
            if original_plan and include_playlists
            else []
        ),
        playlists_to_edit=(
            original_plan.playlists_to_edit
            if original_plan and include_playlists
            else []
        ),
        playlists_to_remove=(
            original_plan.playlists_to_remove
            if original_plan and include_playlists
            else []
        ),
        photo_plan=selected_photo_plan if original_plan else None,
    )


def build_selected_photo_plan(
    original_photo_plan: Any | None,
    included_keys: Iterable[str],
) -> Any | None:
    """Build a filtered PhotoSyncPlan from checked sync-review photo groups."""

    if original_photo_plan is None:
        return None

    from SyncEngine.photos import PhotoSyncPlan

    included = set(included_keys)
    selected = PhotoSyncPlan(
        skipped_files=list(original_photo_plan.skipped_files),
        current_db=original_photo_plan.current_db,
        desired_library=original_photo_plan.desired_library,
    )
    selected.photos_to_update = list(original_photo_plan.photos_to_update)

    for key in (
        "albums_to_add",
        "albums_to_remove",
        "photos_to_add",
        "photos_to_remove",
        "photos_to_update",
        "album_membership_adds",
        "album_membership_removes",
    ):
        setattr(
            selected,
            key,
            copy.deepcopy(getattr(original_photo_plan, key)) if key in included else [],
        )

    selected.thumb_bytes_to_add = (
        original_photo_plan.thumb_bytes_to_add
        if "photos_to_add" in included
        else 0
    )
    selected.thumb_bytes_to_remove = (
        original_photo_plan.thumb_bytes_to_remove
        if "photos_to_remove" in included
        else 0
    )
    return selected if selected.has_changes else None
