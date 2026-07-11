from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from iopenpod.sync.contracts import SyncAction, SyncItem, SyncPlan
from iopenpod.sync.plan_validator import validate_sync_plan


def _pc_track(path: str = "/music/song.mp3", **kwargs: object) -> Any:
    values: dict[str, object] = {
        "path": path,
        "relative_path": Path(path).name if path else "",
        "filename": Path(path).name if path else "",
        "title": "Song",
        "size": 100,
        "is_podcast": False,
        "podcast_enclosure_url": "",
    }
    values.update(kwargs)
    return cast(Any, SimpleNamespace(**values))


def _codes(plan: SyncPlan) -> set[str]:
    result = validate_sync_plan(plan)
    return {issue.code for issue in result.errors}


def test_valid_add_and_playlist_payload_pass() -> None:
    plan = SyncPlan(
        to_add=[
            SyncItem(
                action=SyncAction.ADD_TO_IPOD,
                pc_track=_pc_track(),
            )
        ],
        playlists_to_add=[
            {
                "Title": "Road",
                "playlist_id": 123,
                "_isNew": True,
                "items": [{"source_path": "/music/song.mp3"}],
            }
        ],
    )

    assert validate_sync_plan(plan).is_valid


def test_add_without_source_is_rejected() -> None:
    plan = SyncPlan(to_add=[SyncItem(action=SyncAction.ADD_TO_IPOD)])

    assert "add_missing_source" in _codes(plan)


def test_downloadable_podcast_add_without_local_source_is_allowed() -> None:
    plan = SyncPlan(
        to_add=[
            SyncItem(
                action=SyncAction.ADD_TO_IPOD,
                pc_track=_pc_track(
                    path="",
                    is_podcast=True,
                    podcast_enclosure_url="https://example.test/episode.mp3",
                ),
            )
        ]
    )

    assert validate_sync_plan(plan).is_valid


def test_downloadable_podcast_update_without_local_source_is_rejected() -> None:
    plan = SyncPlan(
        to_update_file=[
            SyncItem(
                action=SyncAction.UPDATE_FILE,
                db_track_id=42,
                pc_track=_pc_track(
                    path="",
                    is_podcast=True,
                    podcast_enclosure_url="https://example.test/episode.mp3",
                ),
            )
        ]
    )

    assert "update_missing_source" in _codes(plan)


def test_database_mutations_require_db_track_id() -> None:
    plan = SyncPlan(
        to_update_metadata=[
            SyncItem(
                action=SyncAction.UPDATE_METADATA,
                ipod_track={"db_track_id": 42, "Title": "Loose dict is not enough"},
            )
        ]
    )

    assert "missing_db_track_id" in _codes(plan)


def test_metadata_update_without_changes_is_rejected() -> None:
    plan = SyncPlan(
        to_update_metadata=[
            SyncItem(
                action=SyncAction.UPDATE_METADATA,
                db_track_id=42,
                metadata_changes={},
            )
        ]
    )

    assert "metadata_update_without_changes" in _codes(plan)


def test_playcount_sync_without_delta_is_rejected() -> None:
    plan = SyncPlan(
        to_sync_playcount=[
            SyncItem(
                action=SyncAction.SYNC_PLAYCOUNT,
                db_track_id=42,
                play_count_delta=0,
                skip_count_delta=0,
            )
        ]
    )

    assert "playcount_sync_without_delta" in _codes(plan)


def test_deferred_replacement_remove_requires_complete_add_group() -> None:
    add = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        pc_track=_pc_track("/music/a.mp3"),
        conversion_group_id="album-1",
        conversion_group_add_count=2,
    )
    remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        db_track_id=10,
        ipod_track={"Location": ":iPod_Control:Music:F00:old.mp3"},
        conversion_group_id="album-1",
        defer_removal_until_after_add=True,
    )
    plan = SyncPlan(to_add=[add], to_remove=[remove])

    assert "incomplete_deferred_conversion_group" in _codes(plan)


def test_deferred_replacement_remove_without_add_group_is_rejected() -> None:
    remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        db_track_id=10,
        ipod_track={"Location": ":iPod_Control:Music:F00:old.mp3"},
        conversion_group_id="album-1",
        defer_removal_until_after_add=True,
    )
    plan = SyncPlan(to_remove=[remove])

    assert "deferred_remove_without_add" in _codes(plan)


def test_remove_update_conflict_is_rejected() -> None:
    plan = SyncPlan(
        to_remove=[
            SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                db_track_id=10,
                ipod_track={"Location": ":iPod_Control:Music:F00:old.mp3"},
            )
        ],
        to_update_metadata=[
            SyncItem(
                action=SyncAction.UPDATE_METADATA,
                db_track_id=10,
                metadata_changes={"title": ("New", "Old")},
            )
        ],
    )

    assert "update_conflicts_with_remove" in _codes(plan)


def test_fingerprint_only_removal_is_rejected() -> None:
    plan = SyncPlan(
        to_remove=[
            SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                fingerprint="123,456,789",
            )
        ]
    )

    assert "remove_missing_identity" in _codes(plan)


def test_playlist_items_need_resolvable_track_identity() -> None:
    plan = SyncPlan(
        playlists_to_add=[
            {
                "Title": "Broken",
                "playlist_id": 123,
                "_isNew": True,
                "items": [{"name": "not enough"}],
            }
        ]
    )

    assert "playlist_item_missing_identity" in _codes(plan)


def test_plan_playlist_source_only_item_must_be_planned_or_matched() -> None:
    plan = SyncPlan(
        playlists_to_add=[
            {
                "Title": "Missing Source",
                "playlist_id": 123,
                "_isNew": True,
                "items": [{"source_path": "/music/not-selected.mp3"}],
            }
        ]
    )

    assert "playlist_source_not_planned_or_matched" in _codes(plan)


def test_plan_playlist_source_only_item_can_use_matched_pc_path() -> None:
    plan = SyncPlan(
        matched_pc_paths={42: "/music/already-on-ipod.mp3"},
        playlists_to_add=[
            {
                "Title": "Matched Source",
                "playlist_id": 123,
                "_isNew": True,
                "items": [{"source_path": "/music/already-on-ipod.mp3"}],
            }
        ],
    )

    assert validate_sync_plan(plan).is_valid


def test_playlist_removals_need_playlist_id() -> None:
    plan = SyncPlan(playlists_to_remove=[{"Title": "No id"}])

    assert "playlist_remove_missing_id" in _codes(plan)


def test_duplicate_pending_playlist_ids_are_rejected() -> None:
    plan = SyncPlan(
        playlists_to_add=[
            {
                "Title": "One",
                "playlist_id": 123,
                "_isNew": True,
                "items": [{"db_track_id": 1}],
            }
        ],
        playlists_to_edit=[
            {
                "Title": "Two",
                "playlist_id": 123,
                "_isNew": False,
                "items": [{"db_track_id": 2}],
            }
        ],
    )

    assert "playlist_duplicate_pending_id" in _codes(plan)


def test_playlist_remove_conflicting_with_update_is_rejected() -> None:
    plan = SyncPlan(
        playlists_to_edit=[
            {
                "Title": "Updated",
                "playlist_id": 123,
                "_isNew": False,
                "items": [{"db_track_id": 1}],
            }
        ],
        playlists_to_remove=[{"Title": "Removed", "playlist_id": 123}],
    )

    assert "playlist_remove_conflicts_with_pending_update" in _codes(plan)


def test_empty_plan_has_no_playlist_side_channel() -> None:
    assert validate_sync_plan(SyncPlan()).is_valid
