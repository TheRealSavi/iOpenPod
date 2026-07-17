"""Merge additional sync plans into an existing review plan."""

from __future__ import annotations

from typing import Final

from iopenpod.sync.contracts import SyncPlan
from iopenpod.sync.photos import PhotoSyncPlan

_SYNC_PLAN_LIST_FIELDS: Final[tuple[str, ...]] = (
    "to_add",
    "to_remove",
    "to_update_metadata",
    "to_update_file",
    "to_update_artwork",
    "to_sync_playcount",
    "to_sync_rating",
    "fingerprint_errors",
    "unresolved_collisions",
    "_stale_mapping_entries",
    "_integrity_removals",
    "playlists_to_add",
    "playlists_to_edit",
    "playlists_to_remove",
)

_SYNC_PLAN_DICT_FIELDS: Final[tuple[str, ...]] = (
    "matched_pc_paths",
    "duplicates",
)

_SYNC_PLAN_COUNT_FIELDS: Final[tuple[str, ...]] = (
    "total_pc_tracks",
    "matched_tracks",
)

_SYNC_PLAN_FIRST_VALUE_FIELDS: Final[tuple[str, ...]] = (
    "mapping",
    "integrity_report",
    "_refreshed_podcast_feeds",
)

_SYNC_PLAN_MERGED_FIELDS: Final[frozenset[str]] = frozenset(
    (
        *_SYNC_PLAN_LIST_FIELDS,
        *_SYNC_PLAN_DICT_FIELDS,
        *_SYNC_PLAN_COUNT_FIELDS,
        *_SYNC_PLAN_FIRST_VALUE_FIELDS,
        "total_ipod_tracks",
        "storage",
        "photo_plan",
        "removals_pre_checked",
        "_mapping_requires_persistence",
    )
)

_PHOTO_PLAN_LIST_FIELDS: Final[tuple[str, ...]] = (
    "albums_to_add",
    "albums_to_remove",
    "photos_to_add",
    "photos_to_remove",
    "photos_to_update",
    "album_membership_adds",
    "album_membership_removes",
    "skipped_files",
)

_PHOTO_PLAN_FIRST_VALUE_FIELDS: Final[tuple[str, ...]] = (
    "current_db",
    "desired_library",
)

_PHOTO_PLAN_MERGED_FIELDS: Final[frozenset[str]] = frozenset(
    (
        *_PHOTO_PLAN_LIST_FIELDS,
        *_PHOTO_PLAN_FIRST_VALUE_FIELDS,
        "thumb_bytes_to_add",
        "thumb_bytes_to_remove",
    )
)


def merge_additional_sync_plan(
    base_plan: SyncPlan,
    incoming_plan: SyncPlan,
) -> SyncPlan:
    """Merge an additional sync plan into an existing review plan in place."""

    for field_name in _SYNC_PLAN_LIST_FIELDS:
        getattr(base_plan, field_name).extend(getattr(incoming_plan, field_name))

    for field_name in _SYNC_PLAN_DICT_FIELDS:
        getattr(base_plan, field_name).update(getattr(incoming_plan, field_name))

    base_plan.storage.bytes_to_add += incoming_plan.storage.bytes_to_add
    base_plan.storage.bytes_to_remove += incoming_plan.storage.bytes_to_remove
    base_plan.storage.bytes_to_update += incoming_plan.storage.bytes_to_update

    for field_name in _SYNC_PLAN_COUNT_FIELDS:
        setattr(
            base_plan,
            field_name,
            getattr(base_plan, field_name) + getattr(incoming_plan, field_name),
        )

    base_plan.total_ipod_tracks = max(
        base_plan.total_ipod_tracks,
        incoming_plan.total_ipod_tracks,
    )

    for field_name in _SYNC_PLAN_FIRST_VALUE_FIELDS:
        if getattr(base_plan, field_name) is None:
            setattr(base_plan, field_name, getattr(incoming_plan, field_name))

    base_plan.photo_plan = merge_additional_photo_plan(
        base_plan.photo_plan,
        incoming_plan.photo_plan,
    )
    base_plan.removals_pre_checked = (
        base_plan.removals_pre_checked or incoming_plan.removals_pre_checked
    )
    base_plan._mapping_requires_persistence = (
        base_plan._mapping_requires_persistence
        or incoming_plan._mapping_requires_persistence
    )
    return base_plan


def merge_additional_photo_plan(
    base_plan: PhotoSyncPlan | None,
    incoming_plan: PhotoSyncPlan | None,
) -> PhotoSyncPlan | None:
    """Merge an additional photo plan into an existing photo plan in place."""

    if incoming_plan is None:
        return base_plan
    if base_plan is None:
        return incoming_plan

    for field_name in _PHOTO_PLAN_LIST_FIELDS:
        getattr(base_plan, field_name).extend(getattr(incoming_plan, field_name))

    base_plan.thumb_bytes_to_add += incoming_plan.thumb_bytes_to_add
    base_plan.thumb_bytes_to_remove += incoming_plan.thumb_bytes_to_remove

    for field_name in _PHOTO_PLAN_FIRST_VALUE_FIELDS:
        if getattr(base_plan, field_name) is None:
            setattr(base_plan, field_name, getattr(incoming_plan, field_name))

    return base_plan
