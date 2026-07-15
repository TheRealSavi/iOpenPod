"""UI-specific sync plan builders."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def build_removal_sync_plan(tracks: Sequence[dict]) -> Any:
    """Build a removal-only SyncPlan for tracks selected in the UI."""

    from iopenpod.sync.contracts import (
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

    from iopenpod.sync.contracts import (
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

