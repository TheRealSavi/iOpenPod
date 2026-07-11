from __future__ import annotations

from iopenpod.sync.contracts import SyncAction, SyncItem, SyncPlan
from iopenpod.sync.fingerprint_diff_engine import FingerprintDiffEngine


def test_gui_rating_edit_replaces_existing_rating_plan_item() -> None:
    plan = SyncPlan(
        to_sync_rating=[
            SyncItem(
                action=SyncAction.SYNC_RATING,
                db_track_id=101,
                ipod_rating=40,
                pc_rating=60,
                new_rating=60,
                description="Rating: Artist - Song",
            )
        ]
    )
    ipod_track = {"Artist": "Artist", "Title": "Song", "rating": 40}

    FingerprintDiffEngine._apply_gui_edit_overlay(
        plan,
        ipod_by_db_track_id={101: ipod_track},
        gui_edits={101: {"rating": (40, 100)}},
    )

    assert len(plan.to_sync_rating) == 1
    item = plan.to_sync_rating[0]
    assert item.new_rating == 100
    assert item.pc_rating == 100
    assert item.description == "Rating (edited in iOpenPod): Artist - Song"


def test_gui_metadata_edit_merges_with_existing_metadata_item() -> None:
    ipod_track = {"Artist": "Artist", "Title": "Old Title"}
    plan = SyncPlan(
        to_update_metadata=[
            SyncItem(
                action=SyncAction.UPDATE_METADATA,
                db_track_id=101,
                ipod_track=ipod_track,
                metadata_changes={"artist": ("PC Artist", "Artist")},
                description="Metadata: Artist - Old Title (artist)",
            )
        ]
    )

    FingerprintDiffEngine._apply_gui_edit_overlay(
        plan,
        ipod_by_db_track_id={101: ipod_track},
        gui_edits={101: {"Title": ("Old Title", "New Title")}},
    )

    assert len(plan.to_update_metadata) == 1
    item = plan.to_update_metadata[0]
    assert item.metadata_changes == {
        "artist": ("PC Artist", "Artist"),
        "title": ("New Title", "Old Title"),
    }
    assert item.description == "Metadata: Artist - Old Title (artist, title)"


def test_gui_metadata_edit_creates_item_for_ipod_only_field() -> None:
    ipod_track = {"Artist": "Artist", "Title": "Song", "bookmark_time_ms": 0}
    plan = SyncPlan()

    FingerprintDiffEngine._apply_gui_edit_overlay(
        plan,
        ipod_by_db_track_id={101: ipod_track},
        gui_edits={101: {"bookmark_time_ms": (0, 30_000)}},
    )

    assert len(plan.to_update_metadata) == 1
    item = plan.to_update_metadata[0]
    assert item.metadata_changes == {"bookmark_time_ms": (30_000, 0)}
    assert item.description == (
        "Metadata (edited in iOpenPod): Artist - Song (bookmark_time_ms)"
    )


def test_restore_gui_edit_values_restores_visible_track_values() -> None:
    ipod_track = {"Artist": "Artist", "Title": "Old Title", "rating": 40}

    FingerprintDiffEngine._restore_gui_edit_values(
        ipod_by_db_track_id={101: ipod_track},
        gui_edits={101: {"Title": ("Old Title", "New Title"), "rating": (40, 80)}},
    )

    assert ipod_track["Title"] == "New Title"
    assert ipod_track["rating"] == 80
