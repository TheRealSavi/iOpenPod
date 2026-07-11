from __future__ import annotations

from iopenpod.itunesdb_shared.constants import MEDIA_TYPE_PODCAST
from iopenpod.sync.contracts import SyncAction, SyncPlan
from iopenpod.sync.fingerprint_diff_engine import FingerprintDiffEngine
from iopenpod.sync.mapping import MappingFile
from iopenpod.sync.track_identity import SyncTrackIdentityState


def _mapping(db_track_id: int, *, aggregate_kind: str | None = None) -> dict:
    return {
        "db_track_id": db_track_id,
        "source_format": "mp3",
        "ipod_format": "mp3",
        "source_size": 123,
        "source_mtime": 1.0,
        "last_sync": "2026-01-01T00:00:00+00:00",
        "was_transcoded": False,
        "aggregate_kind": aggregate_kind,
    }


def test_removal_planning_removes_orphaned_mapping_entries() -> None:
    mapping = MappingFile.from_dict({
        "version": 5,
        "tracks": {
            "gone": [_mapping(101)],
            "stale": [_mapping(202)],
            "aggregate": [_mapping(303, aggregate_kind="chaptered_album")],
        },
    })
    plan = SyncPlan()

    FingerprintDiffEngine._plan_removed_tracks(
        plan,
        mapping=mapping,
        seen_fps=set(),
        ipod_by_db_track_id={
            101: {"Artist": "Artist", "Title": "Gone", "size": 55},
            303: {"Artist": "Artist", "Title": "Aggregate", "size": 999},
        },
        track_identity=SyncTrackIdentityState(),
        claimed_aggregate_db_ids={303},
        bootstrap_protected_db_track_ids=set(),
    )

    assert [item.action for item in plan.to_remove] == [SyncAction.REMOVE_FROM_IPOD]
    assert [item.db_track_id for item in plan.to_remove] == [101]
    assert plan.to_remove[0].description == "Removed from PC: Artist - Gone"
    assert plan._stale_mapping_entries == [("stale", 202)]
    assert plan.storage.bytes_to_remove == 55


def test_removal_planning_removes_unclaimed_album_variant() -> None:
    mapping = MappingFile.from_dict({
        "version": 5,
        "tracks": {
            "fp": [
                _mapping(101),
                _mapping(202),
            ],
        },
    })
    track_identity = SyncTrackIdentityState()
    track_identity.claim(101)
    plan = SyncPlan()

    FingerprintDiffEngine._plan_removed_tracks(
        plan,
        mapping=mapping,
        seen_fps={"fp"},
        ipod_by_db_track_id={
            101: {"Artist": "Artist", "Title": "Song", "Album": "Album", "size": 11},
            202: {
                "Artist": "Artist",
                "Title": "Song",
                "Album": "Greatest Hits",
                "size": 22,
            },
        },
        track_identity=track_identity,
        claimed_aggregate_db_ids=set(),
        bootstrap_protected_db_track_ids=set(),
    )

    assert [item.db_track_id for item in plan.to_remove] == [202]
    assert plan.to_remove[0].description == (
        "Album variant removed: Artist - Song [Greatest Hits]"
    )
    assert plan.storage.bytes_to_remove == 22


def test_removal_planning_accounts_for_claimed_protected_stale_and_podcasts() -> None:
    mapping = MappingFile.from_dict({
        "version": 5,
        "tracks": {
            "stale": [_mapping(202)],
        },
    })
    track_identity = SyncTrackIdentityState()
    track_identity.claim(101)
    plan = SyncPlan()

    FingerprintDiffEngine._plan_removed_tracks(
        plan,
        mapping=mapping,
        seen_fps=set(),
        ipod_by_db_track_id={
            101: {"Artist": "Artist", "Title": "Claimed", "size": 11},
            303: {"Artist": "Artist", "Title": "iTunes Only", "size": 33},
            404: {
                "Artist": "Podcast",
                "Title": "Episode",
                "media_type": MEDIA_TYPE_PODCAST,
                "size": 44,
            },
            505: {"Artist": "Bootstrap", "Title": "Protected", "size": 55},
        },
        track_identity=track_identity,
        claimed_aggregate_db_ids=set(),
        bootstrap_protected_db_track_ids={505},
    )

    assert [item.db_track_id for item in plan.to_remove] == [303]
    assert plan.to_remove[0].description == "Not in PC library: Artist - iTunes Only"
    assert plan._stale_mapping_entries == [("stale", 202)]
    assert plan.storage.bytes_to_remove == 33
