"""User intent stays separate from duplicate matching and final Review exclusions."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from iOpenPod.app.host_media_library import (
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaSource,
)
from iOpenPod.app.library_sync_helper import (
    IPodMediaCacheStats,
    IPodMediaLibrary,
    IPodTrackFingerprint,
    SyncDetails,
)
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_plan import (
    SyncDuplicatePair,
    SyncDuplicateResolution,
    SyncPlan,
    SyncPlanAction,
    prepare_sync_plan,
)
from iPodDB.library import LibrarySnapshot, Track, TrackMetadata
from storage import DevicePath, HostPath


def _comparison(
    tmp_path: Path, *, known_pair: bool = False, separate_groups: bool = False
) -> tuple[HostMediaLibrary, SyncPlan]:
    paths = tuple(tmp_path / f"song-{identity}.mp3" for identity in (1, 2))
    host = HostMediaLibrary(
        LibrarySnapshot(
            tracks=tuple(
                Track(
                    identity,
                    "Song",
                    "Artist",
                    "Album",
                    180_000,
                    metadata=TrackMetadata(location=str(path)),
                )
                for identity, path in enumerate(paths, 1)
            )
        ),
        tuple(
            HostMediaSource(
                HostPath(path),
                HostMediaFileKind.AUDIO,
                100,
                1000,
                acoustic_fingerprint="4,5,6" if separate_groups and index else "1,2,3",
            )
            for index, path in enumerate(paths)
        ),
        (),
        HostMediaCacheStats(),
    )
    identities = (10, 11, 20, 21) if separate_groups else (10, 11)
    ipod_snapshot = LibrarySnapshot(
        tracks=tuple(
            Track(
                identity,
                "Song",
                "Artist",
                "Album",
                180_000,
                metadata=TrackMetadata(
                    location=f"iPod_Control/Music/F00/{identity}.mp3"
                ),
            )
            for identity in identities
        )
    )
    ipod = IPodMediaLibrary(
        tuple(
            IPodTrackFingerprint(
                identity + 1000,
                identity,
                DevicePath(f"iPod_Control/Music/F00/{identity}.mp3"),
                90,
                900,
                "4,5,6" if identity >= 20 else "1,2,3",
                SyncDetails(
                    "2026-10-07T12:00:00Z",
                    str(paths[0]),
                    100,
                    1000,
                    "mp3",
                    "mp3",
                    False,
                )
                if known_pair and identity == 10
                else None,
            )
            for identity in identities
        ),
        (),
        (),
        IPodMediaCacheStats(),
        None,
        False,
    )
    return host, prepare_sync_plan(host, ipod, ipod_snapshot)


def _selection(host: HostMediaLibrary, comparison: SyncPlan) -> SyncSelection:
    selection = SyncSelection()
    selection.reset(host, comparison)
    return selection


def test_changing_pair_drops_old_removal_and_does_not_remove_previous_target(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    path = group.hosts[0].host_path
    first = SyncDuplicateResolution(
        group.group_id,
        pairs=(SyncDuplicatePair(path, 10),),
        removed_ipod_ids=frozenset({11}),
    )
    assert selection.set_duplicate_resolution(first)
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 1
    second = SyncDuplicateResolution(
        group.group_id, pairs=(SyncDuplicatePair(path, 11),)
    )
    assert selection.set_duplicate_resolution(second)
    (item,) = selection.selected_plan.items
    assert item.ipod_id == 11
    assert item.action is SyncPlanAction.UPDATE
    assert (
        selection.review_check_state(selection.potential_removals[0])
        is Qt.CheckState.Unchecked
    )
    assert selection.duplicate_resolutions == (second,)


def test_matching_preserves_other_copies_and_skipped_host_is_still_selectable(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    resolution = SyncDuplicateResolution(
        group.group_id, pairs=(SyncDuplicatePair(group.hosts[0].host_path, 10),)
    )
    selection.set_duplicate_resolution(resolution)
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 0
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 0
    selection.set_tracks_checked((2,), True)
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 1
    selection.set_tracks_checked((2,), False)
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 0
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 0


def test_reapplying_add_choice_after_browser_deselection_restores_host_intent(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    resolution = SyncDuplicateResolution(
        group.group_id, added_host_paths=frozenset({group.hosts[0].host_path})
    )
    selection.set_duplicate_resolution(resolution)
    selection.set_tracks_checked((1,), False)
    assert selection.selected_plan.change_count == 0
    assert selection.set_duplicate_resolution(resolution)
    assert selection.track_check_state(1) is Qt.CheckState.Checked
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 1


def test_reapplying_cleanup_choice_after_review_uncheck_restores_explicit_removal(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    resolution = SyncDuplicateResolution(
        group.group_id, removed_ipod_ids=frozenset({11})
    )
    selection.set_duplicate_resolution(resolution)
    (removed,) = selection.selected_plan.items
    assert selection.set_removal_checked(removed, False)
    assert selection.selected_plan.change_count == 0
    assert selection.set_duplicate_resolution(resolution)
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 1


def test_unchanged_choices_do_not_emit_selection_changes(tmp_path: Path) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    resolution = SyncDuplicateResolution(
        group.group_id, pairs=(SyncDuplicatePair(group.hosts[0].host_path, 10),)
    )
    selection.set_duplicate_resolution(resolution)
    changes: list[bool] = []
    selection.changed.connect(lambda: changes.append(True))
    assert not selection.set_duplicate_resolution(resolution)
    assert changes == []


@pytest.mark.parametrize("invalid", ("group", "pair", "remove"))
def test_malformed_choices_leave_all_selection_and_review_state_unchanged(
    tmp_path: Path, invalid: str
) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    resolution = SyncDuplicateResolution(
        group.group_id, pairs=(SyncDuplicatePair(group.hosts[0].host_path, 10),)
    )
    selection.set_duplicate_resolution(resolution)
    (paired,) = selection.selected_plan.items
    selection.set_review_items_checked((paired,), False)
    before = (
        selection.selected_plan,
        selection.review_plan,
        selection.resolved_comparison,
    )
    changes: list[bool] = []
    selection.changed.connect(lambda: changes.append(True))
    malformed = (
        replace(resolution, group_id="stale-group")
        if invalid == "group"
        else replace(
            resolution,
            pairs=(*resolution.pairs, SyncDuplicatePair(group.hosts[1].host_path, 10)),
        )
        if invalid == "pair"
        else replace(resolution, removed_ipod_ids=frozenset({10}))
    )
    with pytest.raises(ValueError):
        selection.set_duplicate_resolution(malformed)
    assert (
        selection.selected_plan,
        selection.review_plan,
        selection.resolved_comparison,
    ) == before
    assert selection.duplicate_resolutions == (resolution,)
    assert selection.track_check_state(1) is Qt.CheckState.Checked
    assert changes == []


def test_review_exclusion_skips_update_keeps_link_and_expires_when_pair_changes(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    first = SyncDuplicateResolution(
        group.group_id, pairs=(SyncDuplicatePair(group.hosts[0].host_path, 10),)
    )
    selection.set_duplicate_resolution(first)
    (paired,) = selection.selected_plan.items
    selection.set_review_items_checked((paired,), False)
    assert not selection.selected_plan.items
    assert selection.track_check_state(1) is Qt.CheckState.Checked
    assert selection.resolved_comparison.count(SyncPlanAction.UPDATE) == 1
    assert selection.duplicate_resolutions == (first,)
    second = replace(first, pairs=(SyncDuplicatePair(group.hosts[0].host_path, 11),))
    selection.set_duplicate_resolution(second)
    (replacement,) = selection.selected_plan.items
    assert replacement.ipod_id == 11
    assert selection.review_check_state(paired) is None


def test_changing_cleanup_preserves_review_exclusion_of_same_match(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    first = SyncDuplicateResolution(
        group.group_id, pairs=(SyncDuplicatePair(group.hosts[0].host_path, 10),)
    )
    selection.set_duplicate_resolution(first)
    (paired,) = selection.selected_plan.items
    selection.set_review_items_checked((paired,), False)
    selection.set_duplicate_resolution(
        replace(first, removed_ipod_ids=frozenset({11})),
        preserved_host_paths=frozenset({group.hosts[0].host_path}),
    )
    (removal,) = selection.selected_plan.items
    assert removal.action is SyncPlanAction.REMOVE
    assert removal.ipod_id == 11
    assert selection.review_check_state(paired) is Qt.CheckState.Unchecked


def test_other_group_choices_preserve_browser_selection_and_review_exclusions(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path, separate_groups=True)
    selection = _selection(host, comparison)
    first, second = comparison.duplicate_groups
    resolution1 = SyncDuplicateResolution(
        first.group_id, added_host_paths=frozenset({first.hosts[0].host_path})
    )
    selection.set_duplicate_resolution(resolution1)
    (added,) = tuple(
        item
        for item in selection.selected_plan.items
        if item.action is SyncPlanAction.ADD
    )
    selection.set_review_items_checked((added,), False)
    resolution2 = SyncDuplicateResolution(
        second.group_id,
        pairs=(SyncDuplicatePair(second.hosts[0].host_path, second.ipods[0].ipod_id),),
    )
    selection.set_duplicate_resolution(resolution2)
    assert selection.review_check_state(added) is Qt.CheckState.Unchecked
    assert selection.selected_host_count == 2
    assert selection.selected_plan.count(SyncPlanAction.UPDATE) == 1
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 0


@pytest.mark.parametrize("clear", (False, True))
def test_new_scan_or_clear_retires_duplicate_choices_and_removals(
    tmp_path: Path, clear: bool
) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    selection.set_duplicate_resolution(
        SyncDuplicateResolution(
            group.group_id,
            added_host_paths=frozenset({group.hosts[0].host_path}),
            removed_ipod_ids=frozenset({11}),
        )
    )
    if clear:
        selection.clear()
    else:
        selection.reset(host, comparison)
    assert selection.duplicate_resolutions == ()
    assert selection.selected_host_count == 0
    assert selection.selected_plan.change_count == 0
    assert selection.selected_plan.duplicate_resolutions == ()


def test_review_duplicate_choices_preserve_established_host_deselection(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path, known_pair=True)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    selection.set_tracks_checked((1,), False)
    known_removal = next(
        item for item in selection.selected_plan.items if item.ipod_id == 10
    )
    assert known_removal.action is SyncPlanAction.REMOVE
    selection.set_duplicate_resolution(SyncDuplicateResolution(group.group_id))
    assert known_removal in selection.selected_plan.items
    assert selection.track_check_state(1) is Qt.CheckState.Unchecked


def test_editing_other_host_preserves_manual_pair_deselection(tmp_path: Path) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    first = SyncDuplicateResolution(
        group.group_id, pairs=(SyncDuplicatePair(group.hosts[0].host_path, 10),)
    )
    selection.set_duplicate_resolution(first)
    selection.set_tracks_checked((1,), False)
    selection.set_duplicate_resolution(
        replace(first, added_host_paths=frozenset({group.hosts[1].host_path})),
        preserved_host_paths=frozenset({group.hosts[0].host_path}),
    )
    assert selection.track_check_state(1) is Qt.CheckState.Unchecked
    assert selection.track_check_state(2) is Qt.CheckState.Checked
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 1
    removal = next(
        item
        for item in selection.selected_plan.items
        if item.action is SyncPlanAction.REMOVE
    )
    assert removal.ipod_id == 10


def test_explicitly_rechoosing_same_pair_restores_excluded_update(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    choice = SyncDuplicateResolution(
        group.group_id, pairs=(SyncDuplicatePair(group.hosts[0].host_path, 10),)
    )
    selection.set_duplicate_resolution(choice)
    (paired,) = selection.selected_plan.items
    selection.set_review_items_checked((paired,), False)
    assert not selection.selected_plan.items
    assert selection.set_duplicate_resolution(choice)
    assert selection.review_check_state(paired) is Qt.CheckState.Checked
    assert selection.selected_plan.count(SyncPlanAction.UPDATE) == 1


def test_untouched_ambiguous_checked_host_does_not_become_unrequested_add(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    selection.set_tracks_checked((1, 2), True)
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 0
    selection.set_duplicate_resolution(
        SyncDuplicateResolution(
            group.group_id, pairs=(SyncDuplicatePair(group.hosts[0].host_path, 10),)
        ),
        preserved_host_paths=frozenset({group.hosts[1].host_path}),
    )
    assert selection.track_check_state(2) is Qt.CheckState.Unchecked
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 0


def test_foreign_preserved_path_is_rejected_without_changing_selection(
    tmp_path: Path,
) -> None:
    host, comparison = _comparison(tmp_path)
    selection = _selection(host, comparison)
    (group,) = comparison.duplicate_groups
    before = selection.selected_plan
    with pytest.raises(ValueError, match="Untouched Host paths"):
        selection.set_duplicate_resolution(
            SyncDuplicateResolution(group.group_id),
            preserved_host_paths=frozenset({str(tmp_path / "unrelated.mp3")}),
        )
    assert selection.selected_plan == before
    assert selection.duplicate_resolutions == ()
