"""Build executable sync plans from sync-review selections."""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import StorageSummary, SyncAction, SyncPlan


def build_filtered_sync_plan(
    original_plan: Any | None,
    selected_items: Iterable[Any],
    *,
    include_playlists: bool = True,
    selected_playlists: Mapping[str, Iterable[dict]] | None = None,
    selected_photo_plan: Any | None = None,
) -> SyncPlan:
    """Build the executable plan from checked sync-review items."""

    selected_items = tuple(selected_items)

    grouped: dict[SyncAction, list[Any]] = {
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

    original_adds = original_plan.to_add if original_plan else ()
    original_conversion_counts = Counter(
        getattr(item, "conversion_group_id", None)
        for item in original_adds
        if getattr(item, "conversion_group_id", None)
    )
    for item in original_adds:
        group_id = getattr(item, "conversion_group_id", None)
        if not group_id:
            continue
        expected = int(getattr(item, "conversion_group_add_count", 0) or 0)
        if expected:
            original_conversion_counts[group_id] = max(
                original_conversion_counts[group_id],
                expected,
            )

    selected_conversion_counts = Counter(
        getattr(item, "conversion_group_id", None)
        for item in grouped[SyncAction.ADD_TO_IPOD]
        if getattr(item, "conversion_group_id", None)
    )
    complete_conversion_groups = {
        group_id
        for group_id, selected_count in selected_conversion_counts.items()
        if selected_count >= original_conversion_counts.get(group_id, selected_count)
    }
    grouped[SyncAction.REMOVE_FROM_IPOD] = [
        item
        for item in grouped[SyncAction.REMOVE_FROM_IPOD]
        if (
            not getattr(item, "defer_removal_until_after_add", False)
            or getattr(item, "conversion_group_id", None) in complete_conversion_groups
        )
    ]

    bytes_to_add = 0
    bytes_to_remove = 0
    bytes_to_update = 0
    filtered_items = tuple(item for bucket in grouped.values() for item in bucket)
    for item in filtered_items:
        add_delta, remove_delta = _sync_item_size_delta(item)
        if item.action == SyncAction.UPDATE_FILE:
            bytes_to_update += add_delta
        else:
            bytes_to_add += add_delta
        bytes_to_remove += remove_delta

    if selected_photo_plan is not None:
        bytes_to_add += int(getattr(selected_photo_plan, "thumb_bytes_to_add", 0) or 0)
        bytes_to_remove += int(
            getattr(selected_photo_plan, "thumb_bytes_to_remove", 0) or 0
        )

    if selected_playlists is not None:
        playlists_to_add = list(selected_playlists.get("playlists_to_add", ()))
        playlists_to_edit = list(selected_playlists.get("playlists_to_edit", ()))
        playlists_to_remove = list(selected_playlists.get("playlists_to_remove", ()))
    else:
        playlists_to_add = (
            original_plan.playlists_to_add if original_plan and include_playlists else []
        )
        playlists_to_edit = (
            original_plan.playlists_to_edit if original_plan and include_playlists else []
        )
        playlists_to_remove = (
            original_plan.playlists_to_remove
            if original_plan and include_playlists
            else []
        )

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
        _integrity_removals=(
            original_plan._integrity_removals if original_plan else []
        ),
        _mapping_requires_persistence=(
            original_plan._mapping_requires_persistence if original_plan else False
        ),
        _refreshed_podcast_feeds=(
            original_plan._refreshed_podcast_feeds if original_plan else None
        ),
        mapping=original_plan.mapping if original_plan else None,
        integrity_report=original_plan.integrity_report if original_plan else None,
        storage=StorageSummary(
            bytes_to_add=bytes_to_add,
            bytes_to_remove=bytes_to_remove,
            bytes_to_update=bytes_to_update,
        ),
        playlists_to_add=playlists_to_add,
        playlists_to_edit=playlists_to_edit,
        playlists_to_remove=playlists_to_remove,
        photo_plan=selected_photo_plan if original_plan else None,
    )


def build_selected_photo_plan(
    original_photo_plan: Any | None,
    included_keys: Iterable[str],
    selected_items_by_key: Mapping[str, Iterable[Any]] | None = None,
) -> Any | None:
    """Build a filtered PhotoSyncPlan from checked sync-review photo rows."""

    if original_photo_plan is None:
        return None

    from .photos import PhotoSyncPlan

    included = set(included_keys)
    selected_by_key = (
        {key: list(items) for key, items in selected_items_by_key.items()}
        if selected_items_by_key is not None
        else None
    )
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
        if selected_by_key is not None:
            value = copy.deepcopy(selected_by_key.get(key, []))
        else:
            value = (
                copy.deepcopy(getattr(original_photo_plan, key))
                if key in included
                else []
            )
        setattr(selected, key, value)

    if selected_by_key is None:
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
    else:
        selected.thumb_bytes_to_add = sum(
            int(getattr(item, "estimated_size", 0) or getattr(item, "size", 0) or 0)
            for item in selected.photos_to_add
        )
        selected.thumb_bytes_to_remove = sum(
            int(getattr(item, "size", 0) or 0)
            for item in selected.photos_to_remove
        )
    return selected if selected.has_changes else None


def _sync_item_size_delta(item: Any) -> tuple[int, int]:
    """Return ``(bytes_to_add, bytes_to_remove)`` for a selected sync item."""

    action = _sync_action_key(item)
    if action in {"ADD_TO_IPOD", "UPDATE_FILE"}:
        estimated_size = getattr(item, "estimated_size", None)
        if estimated_size is not None:
            return _int_value(estimated_size), 0

        track = getattr(item, "pc_track", None)
        return _int_value(getattr(track, "size", 0)), 0

    if action == "REMOVE_FROM_IPOD":
        ipod = _ipod_track(item)
        return 0, _int_value(ipod.get("size", 0) if ipod is not None else 0)

    return 0, 0


def _sync_action_key(item: Any) -> str:
    action = getattr(item, "action", "")
    enum_name = getattr(action, "name", None)
    if isinstance(enum_name, str):
        return enum_name
    return str(action).rsplit(".", 1)[-1]


def _ipod_track(item: Any) -> Mapping[str, Any] | None:
    value = getattr(item, "ipod_track", None)
    if isinstance(value, Mapping):
        return value
    return None


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
