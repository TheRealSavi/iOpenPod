from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from iopenpod.sync.contracts import SyncAction, SyncItem, SyncPlan


def _pc_track(**kwargs: object) -> Any:
    defaults: dict[str, object] = {
        "path": "/music/song.flac",
        "relative_path": "song.flac",
        "filename": "song.flac",
        "title": "Song",
        "size": 1234,
    }
    defaults.update(kwargs)
    return cast(Any, SimpleNamespace(**defaults))


def test_sync_item_source_and_label_helpers() -> None:
    item = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        pc_track=_pc_track(title="", filename="fallback.mp3"),
    )

    assert item.has_pc_source
    assert item.source_path == "/music/song.flac"
    assert item.source_relative_path == "song.flac"
    assert item.display_label == "fallback.mp3"


def test_sync_item_size_helpers_coerce_bad_values() -> None:
    add = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        pc_track=_pc_track(size="bad"),
        estimated_size="2048",  # type: ignore[arg-type]
    )
    remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        ipod_track={"Location": ":iPod_Control:Music:F00:Song.mp3", "size": "512"},
    )
    update = SyncItem(
        action=SyncAction.UPDATE_FILE,
        pc_track=_pc_track(size=300),
        estimated_size=900,
        ipod_track={"size": 500},
    )

    assert add.planned_add_size == 2048
    assert remove.planned_remove_size == 512
    assert remove.ipod_location == ":iPod_Control:Music:F00:Song.mp3"
    assert update.planned_update_growth == 400


def test_sync_item_conversion_and_aggregate_helpers() -> None:
    item = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        conversion_group_id="group-1",
        conversion_group_add_count="3",  # type: ignore[arg-type]
        defer_removal_until_after_add=True,
        aggregate_kind="chaptered_album",
        aggregate_rebuild_pc_tracks=(_pc_track(),),
        db_track_id=101,
    )

    assert item.conversion_group_key == "group-1"
    assert item.conversion_group_expected_count == 3
    assert item.is_deferred_removal
    assert item.is_deferred_replacement_removal
    assert item.is_chaptered_aggregate_rebuild


def test_sync_plan_summary_uses_item_size_helpers() -> None:
    plan = SyncPlan(
        to_add=[
            SyncItem(
                action=SyncAction.ADD_TO_IPOD,
                pc_track=_pc_track(size=100),
                estimated_size=250,
            )
        ],
        to_remove=[
            SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                ipod_track={"Title": "Gone", "size": 75},
            )
        ],
        to_update_file=[
            SyncItem(
                action=SyncAction.UPDATE_FILE,
                pc_track=_pc_track(size=90),
            )
        ],
    )

    summary = plan.summary

    assert "1 tracks to add (250.0 B)" in summary
    assert "1 tracks to remove (75.0 B)" in summary
    assert "1 tracks to re-sync (90.0 B)" in summary
