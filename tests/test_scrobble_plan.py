from iopenpod.sync.contracts import SyncAction
from iopenpod.sync.scrobble_plan import build_pending_scrobble_plan


def test_pending_scrobble_plan_uses_only_durable_queue() -> None:
    source_tracks = [
        {"db_track_id": 1, "play_count_1": 10, "play_count_2": 3, "Title": "Song", "Artist": "Artist"},
        {"db_track_id": 2, "play_count_1": 8, "play_count_2": 0, "Title": "Other"},
        {"db_track_id": 0, "play_count_2": 7, "Title": "Missing ID"},
    ]

    plan = build_pending_scrobble_plan(source_tracks)

    assert len(plan.to_sync_playcount) == 1
    item = plan.to_sync_playcount[0]
    assert item.action is SyncAction.SYNC_PLAYCOUNT
    assert item.db_track_id == 1
    assert item.play_count_delta == 3
    assert item.ipod_track is not source_tracks[0]
    assert item.description == "3 pending plays: Artist - Song"
