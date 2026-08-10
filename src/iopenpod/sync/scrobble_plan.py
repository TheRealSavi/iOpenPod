"""Build a minimal sync plan that submits only pending iPod scrobbles."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import SyncAction, SyncItem, SyncPlan


def build_pending_scrobble_plan(
    tracks: Iterable[Mapping[str, Any]],
) -> SyncPlan:
    """Return a database-only plan for tracks with pending scrobbles.

    ``play_count_2`` is the durable pending-scrobble queue. The plan copies
    each track dictionary so running it cannot mutate the live GUI cache while
    the device write is in progress.
    """
    plan = SyncPlan()
    for raw_track in tracks:
        track = dict(raw_track)
        try:
            pending_count = max(0, int(track.get("play_count_2", 0) or 0))
            db_track_id = int(track.get("db_track_id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if pending_count <= 0 or db_track_id <= 0:
            continue

        title = str(track.get("Title") or "Unknown Title")
        artist = str(track.get("Artist") or "Unknown Artist")
        play_word = "play" if pending_count == 1 else "plays"
        plan.to_sync_playcount.append(
            SyncItem(
                action=SyncAction.SYNC_PLAYCOUNT,
                db_track_id=db_track_id,
                ipod_track=track,
                play_count_delta=pending_count,
                description=f"{pending_count} pending {play_word}: {artist} - {title}",
            )
        )
    return plan
