"""Small view-model helpers for rendering and selecting sync plan items."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from iTunesDB_Shared.constants import (
    MEDIA_TYPE_AUDIO,
    MEDIA_TYPE_AUDIO_VIDEO,
    MEDIA_TYPE_AUDIOBOOK,
    MEDIA_TYPE_MUSIC_VIDEO,
    MEDIA_TYPE_PODCAST,
    MEDIA_TYPE_TV_SHOW,
    MEDIA_TYPE_VIDEO,
)

ACTION_ADD_TO_IPOD = "ADD_TO_IPOD"
ACTION_REMOVE_FROM_IPOD = "REMOVE_FROM_IPOD"
ACTION_UPDATE_METADATA = "UPDATE_METADATA"
ACTION_UPDATE_FILE = "UPDATE_FILE"
ACTION_UPDATE_ARTWORK = "UPDATE_ARTWORK"
ACTION_SYNC_PLAYCOUNT = "SYNC_PLAYCOUNT"
ACTION_SYNC_RATING = "SYNC_RATING"

MEDIA_TYPE_ORDER = (
    "music",
    "podcast",
    "audiobook",
    "video",
    "music_video",
    "tv_show",
    "other",
)


@dataclass(frozen=True)
class SyncActionCounts:
    """Counts of selected sync actions for confirmation copy."""

    add_to_ipod: int = 0
    remove_from_ipod: int = 0
    update_metadata: int = 0
    update_file: int = 0
    update_artwork: int = 0
    sync_playcount: int = 0
    sync_rating: int = 0


def sync_action_key(item: Any) -> str:
    """Return a stable action name without exposing engine enums to the GUI."""

    action = getattr(item, "action", "")
    enum_name = getattr(action, "name", None)
    if isinstance(enum_name, str):
        return enum_name
    return str(action).rsplit(".", 1)[-1]


def is_sync_action(item: Any, action_key: str) -> bool:
    return sync_action_key(item) == action_key


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


def classify_media_type(item: Any) -> str:
    """Classify a sync item into a stable media type bucket."""

    track = getattr(item, "pc_track", None)
    ipod = _ipod_track(item)

    if track is not None:
        if getattr(track, "is_podcast", False):
            return "podcast"
        if getattr(track, "is_audiobook", False):
            return "audiobook"
        if getattr(track, "is_video", False):
            video_kind = getattr(track, "video_kind", "")
            if video_kind == "tv_show":
                return "tv_show"
            if video_kind == "music_video":
                return "music_video"
            return "video"
        return "music"

    if ipod is not None:
        media_type = _int_value(ipod.get("media_type", MEDIA_TYPE_AUDIO))
        if media_type & MEDIA_TYPE_PODCAST:
            return "podcast"
        if media_type & MEDIA_TYPE_AUDIOBOOK:
            return "audiobook"
        if media_type & MEDIA_TYPE_TV_SHOW:
            return "tv_show"
        if media_type & MEDIA_TYPE_MUSIC_VIDEO:
            return "music_video"
        if media_type & MEDIA_TYPE_VIDEO:
            return "video"
        if media_type == MEDIA_TYPE_AUDIO_VIDEO or media_type & MEDIA_TYPE_AUDIO:
            return "music"

    return "music"


def group_by_media_type(items: Iterable[Any]) -> list[tuple[str, list[Any]]]:
    """Group sync items by media type using the sync review display order."""

    groups: dict[str, list[Any]] = {}
    for item in items:
        groups.setdefault(classify_media_type(item), []).append(item)

    return [(key, groups[key]) for key in MEDIA_TYPE_ORDER if key in groups]


def sync_item_size_delta(item: Any) -> tuple[int, int]:
    """Return ``(bytes_to_add, bytes_to_remove)`` for a selected sync item."""

    action = sync_action_key(item)
    if action in {ACTION_ADD_TO_IPOD, ACTION_UPDATE_FILE}:
        estimated_size = getattr(item, "estimated_size", None)
        if estimated_size is not None:
            return _int_value(estimated_size), 0

        track = getattr(item, "pc_track", None)
        return _int_value(getattr(track, "size", 0)), 0

    if action == ACTION_REMOVE_FROM_IPOD:
        ipod = _ipod_track(item)
        return 0, _int_value(ipod.get("size", 0) if ipod is not None else 0)

    return 0, 0


def count_sync_actions(items: Iterable[Any]) -> SyncActionCounts:
    """Count selected sync items by action."""

    counts: dict[str, int] = {
        ACTION_ADD_TO_IPOD: 0,
        ACTION_REMOVE_FROM_IPOD: 0,
        ACTION_UPDATE_METADATA: 0,
        ACTION_UPDATE_FILE: 0,
        ACTION_UPDATE_ARTWORK: 0,
        ACTION_SYNC_PLAYCOUNT: 0,
        ACTION_SYNC_RATING: 0,
    }
    for item in items:
        action = sync_action_key(item)
        if action in counts:
            counts[action] += 1

    return SyncActionCounts(
        add_to_ipod=counts[ACTION_ADD_TO_IPOD],
        remove_from_ipod=counts[ACTION_REMOVE_FROM_IPOD],
        update_metadata=counts[ACTION_UPDATE_METADATA],
        update_file=counts[ACTION_UPDATE_FILE],
        update_artwork=counts[ACTION_UPDATE_ARTWORK],
        sync_playcount=counts[ACTION_SYNC_PLAYCOUNT],
        sync_rating=counts[ACTION_SYNC_RATING],
    )
