"""Validation for executable sync plans.

The diff/planning side is allowed to be flexible while it gathers evidence.
The executor is not: by the time a SyncPlan reaches file/database mutation,
every item must have the identities required by the stage that will consume it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from .contracts import SyncAction, SyncItem, SyncPlan
from .path_identity import coerce_int, stable_path_key

IssueLevel = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class PlanValidationIssue:
    level: IssueLevel
    code: str
    message: str
    bucket: str = ""
    item_label: str = ""


@dataclass(frozen=True, slots=True)
class PlanValidationResult:
    issues: tuple[PlanValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[PlanValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.level == "error")

    @property
    def warnings(self) -> tuple[PlanValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.level == "warning")

    @property
    def is_valid(self) -> bool:
        return not self.errors


_BUCKET_ACTIONS: tuple[tuple[str, SyncAction], ...] = (
    ("to_add", SyncAction.ADD_TO_IPOD),
    ("to_remove", SyncAction.REMOVE_FROM_IPOD),
    ("_integrity_removals", SyncAction.REMOVE_FROM_IPOD),
    ("to_update_metadata", SyncAction.UPDATE_METADATA),
    ("to_update_file", SyncAction.UPDATE_FILE),
    ("to_update_artwork", SyncAction.UPDATE_ARTWORK),
    ("to_sync_playcount", SyncAction.SYNC_PLAYCOUNT),
    ("to_sync_rating", SyncAction.SYNC_RATING),
)

_DB_MUTATION_BUCKETS = {
    "to_update_metadata",
    "to_update_file",
    "to_update_artwork",
    "to_sync_playcount",
    "to_sync_rating",
}


def validate_sync_plan(plan: SyncPlan) -> PlanValidationResult:
    """Return all structural problems that would make execution ambiguous."""

    issues: list[PlanValidationIssue] = []
    _validate_bucket_actions(plan, issues)
    _validate_track_identities(plan, issues)
    _validate_conversion_groups(plan, issues)
    _validate_destructive_conflicts(plan, issues)
    _validate_playlist_payloads(plan, issues)
    _validate_stale_mapping_entries(plan, issues)
    return PlanValidationResult(tuple(issues))


def _add_error(
    issues: list[PlanValidationIssue],
    code: str,
    message: str,
    *,
    bucket: str = "",
    item: SyncItem | None = None,
    item_label: str = "",
) -> None:
    issues.append(
        PlanValidationIssue(
            level="error",
            code=code,
            message=message,
            bucket=bucket,
            item_label=item_label or (item.display_label if item else ""),
        )
    )


def _bucket_items(plan: SyncPlan, bucket: str) -> list[SyncItem]:
    value = getattr(plan, bucket, [])
    return list(value or [])


def _validate_bucket_actions(
    plan: SyncPlan,
    issues: list[PlanValidationIssue],
) -> None:
    for bucket, expected_action in _BUCKET_ACTIONS:
        for item in _bucket_items(plan, bucket):
            if item.action == expected_action:
                continue
            _add_error(
                issues,
                "wrong_action_bucket",
                (
                    f"{item.display_label} is in {bucket} with action "
                    f"{item.action.name}; expected {expected_action.name}."
                ),
                bucket=bucket,
                item=item,
            )


def _validate_track_identities(
    plan: SyncPlan,
    issues: list[PlanValidationIssue],
) -> None:
    for item in plan.to_add:
        if item.has_pc_source or _is_downloadable_podcast(item):
            continue
        _add_error(
            issues,
            "add_missing_source",
            f"{item.display_label} is planned for add but has no usable PC source.",
            bucket="to_add",
            item=item,
        )

    for item in plan.to_update_file:
        if item.is_chaptered_aggregate_rebuild:
            _validate_chaptered_rebuild_sources(item, issues, "to_update_file")
            continue
        if not item.has_pc_source:
            _add_error(
                issues,
                "update_missing_source",
                (
                    f"{item.display_label} is planned for file update but has "
                    "no usable PC source."
                ),
                bucket="to_update_file",
                item=item,
            )

    for bucket, _expected_action in _BUCKET_ACTIONS:
        if bucket not in _DB_MUTATION_BUCKETS:
            continue
        for item in _bucket_items(plan, bucket):
            if _sync_item_db_track_id(item):
                continue
            _add_error(
                issues,
                "missing_db_track_id",
                (
                    f"{item.display_label} is in {bucket} but has no db_track_id. "
                    "Database row mutations must target a stable iPod track id."
                ),
                bucket=bucket,
                item=item,
            )

    for bucket in ("to_remove", "_integrity_removals"):
        for item in _bucket_items(plan, bucket):
            if item.is_chaptered_aggregate_rebuild:
                if not _sync_item_db_track_id(item):
                    _add_error(
                        issues,
                        "chapter_rebuild_missing_db_track_id",
                        (
                            f"{item.display_label} rebuilds a chaptered album "
                            "but has no db_track_id."
                        ),
                        bucket=bucket,
                        item=item,
                    )
                _validate_chaptered_rebuild_sources(item, issues, bucket)
                continue

            if item.ipod_location or _sync_item_db_track_id(item):
                continue
            _add_error(
                issues,
                "remove_missing_identity",
                (
                    f"{item.display_label} is planned for removal but has no "
                    "iPod location or db_track_id."
                ),
                bucket=bucket,
                item=item,
            )

    for item in plan.to_update_metadata:
        if item.metadata_changes:
            continue
        _add_error(
            issues,
            "metadata_update_without_changes",
            f"{item.display_label} is planned for metadata update with no fields.",
            bucket="to_update_metadata",
            item=item,
        )

    for item in plan.to_sync_playcount:
        if item.play_count_delta or item.skip_count_delta:
            continue
        _add_error(
            issues,
            "playcount_sync_without_delta",
            f"{item.display_label} is planned for play-count sync with no delta.",
            bucket="to_sync_playcount",
            item=item,
        )


def _validate_chaptered_rebuild_sources(
    item: SyncItem,
    issues: list[PlanValidationIssue],
    bucket: str,
) -> None:
    if not item.aggregate_rebuild_pc_tracks:
        return
    for source in item.aggregate_rebuild_pc_tracks:
        if getattr(source, "path", None):
            continue
        _add_error(
            issues,
            "chapter_rebuild_missing_source",
            (
                f"{item.display_label} rebuilds a chaptered album but one "
                "chapter source has no path."
            ),
            bucket=bucket,
            item=item,
        )
        return


def _validate_conversion_groups(
    plan: SyncPlan,
    issues: list[PlanValidationIssue],
) -> None:
    add_counts = Counter(
        item.conversion_group_key
        for item in plan.to_add
        if item.conversion_group_key
    )
    expected_counts: dict[str, int] = dict(add_counts)
    for item in plan.to_add:
        group_id = item.conversion_group_key
        if not group_id:
            continue
        expected = item.conversion_group_expected_count
        if expected:
            expected_counts[group_id] = max(expected_counts.get(group_id, 0), expected)

    for item in plan.to_remove:
        if not item.is_deferred_removal:
            continue
        group_id = item.conversion_group_key
        if not group_id:
            _add_error(
                issues,
                "deferred_remove_missing_group",
                (
                    f"{item.display_label} is deferred until replacement add "
                    "but has no conversion_group_id."
                ),
                bucket="to_remove",
                item=item,
            )
            continue
        if group_id not in add_counts:
            _add_error(
                issues,
                "deferred_remove_without_add",
                (
                    f"{item.display_label} waits for conversion group {group_id}, "
                    "but that group has no add items in this plan."
                ),
                bucket="to_remove",
                item=item,
            )
            continue
        expected = expected_counts.get(group_id, add_counts[group_id])
        if add_counts[group_id] < expected:
            _add_error(
                issues,
                "incomplete_deferred_conversion_group",
                (
                    f"{item.display_label} waits for conversion group {group_id}, "
                    f"but only {add_counts[group_id]} of {expected} add items are "
                    "present."
                ),
                bucket="to_remove",
                item=item,
            )


def _validate_destructive_conflicts(
    plan: SyncPlan,
    issues: list[PlanValidationIssue],
) -> None:
    normal_remove_ids: dict[int, SyncItem] = {}
    for item in plan.to_remove:
        if item.is_deferred_removal or item.is_chaptered_aggregate_rebuild:
            continue
        db_track_id = _sync_item_db_track_id(item)
        if not db_track_id:
            continue
        previous = normal_remove_ids.get(db_track_id)
        if previous is not None:
            _add_error(
                issues,
                "duplicate_remove_db_track_id",
                (
                    f"{item.display_label} and {previous.display_label} both "
                    f"remove db_track_id {db_track_id}."
                ),
                bucket="to_remove",
                item=item,
            )
            continue
        normal_remove_ids[db_track_id] = item

    for bucket in _DB_MUTATION_BUCKETS:
        for item in _bucket_items(plan, bucket):
            db_track_id = _sync_item_db_track_id(item)
            if not db_track_id or db_track_id not in normal_remove_ids:
                continue
            _add_error(
                issues,
                "update_conflicts_with_remove",
                (
                    f"{item.display_label} updates db_track_id {db_track_id}, "
                    "but the same track is also planned for removal."
                ),
                bucket=bucket,
                item=item,
            )


def _validate_playlist_payloads(
    plan: SyncPlan,
    issues: list[PlanValidationIssue],
) -> None:
    plan_source_keys = _plan_source_keys(plan)
    playlist_sources = (
        ("playlists_to_add", plan.playlists_to_add, True),
        ("playlists_to_edit", plan.playlists_to_edit, True),
    )
    pending_playlist_ids: dict[int, tuple[str, str]] = {}
    for bucket, playlists, require_known_sources in playlist_sources:
        for playlist in playlists or []:
            _validate_playlist_payload(
                bucket,
                playlist,
                issues,
                plan_source_keys=plan_source_keys if require_known_sources else None,
            )
            if playlist.get("master_flag"):
                continue
            playlist_id = coerce_int(playlist.get("playlist_id"))
            if not playlist_id:
                continue
            title = str(playlist.get("Title") or "playlist")
            previous = pending_playlist_ids.get(playlist_id)
            if previous is not None:
                previous_bucket, previous_title = previous
                _add_error(
                    issues,
                    "playlist_duplicate_pending_id",
                    (
                        f"Playlist {title} in {bucket} and {previous_title} "
                        f"in {previous_bucket} both use playlist_id {playlist_id}."
                    ),
                    bucket=bucket,
                    item_label=title,
                )
                continue
            pending_playlist_ids[playlist_id] = (bucket, title)

    for playlist in plan.playlists_to_remove or []:
        if playlist.get("master_flag"):
            _add_error(
                issues,
                "playlist_remove_master",
                "Master playlists cannot be removed by a sync plan.",
                bucket="playlists_to_remove",
                item_label=str(playlist.get("Title") or "playlist"),
            )
            continue
        playlist_id = coerce_int(playlist.get("playlist_id"))
        if playlist_id:
            pending = pending_playlist_ids.get(playlist_id)
            if pending is not None:
                pending_bucket, pending_title = pending
                title = str(playlist.get("Title") or "playlist")
                _add_error(
                    issues,
                    "playlist_remove_conflicts_with_pending_update",
                    (
                        f"Playlist {title} is removed, but {pending_title} "
                        f"in {pending_bucket} also updates playlist_id {playlist_id}."
                    ),
                    bucket="playlists_to_remove",
                    item_label=title,
                )
            continue
        _add_error(
            issues,
            "playlist_remove_missing_id",
            (
                f"Playlist {playlist.get('Title') or 'playlist'} is planned "
                "for removal but has no playlist_id."
            ),
            bucket="playlists_to_remove",
            item_label=str(playlist.get("Title") or "playlist"),
        )


def _validate_playlist_payload(
    bucket: str,
    playlist: dict,
    issues: list[PlanValidationIssue],
    *,
    plan_source_keys: set[str] | None = None,
) -> None:
    if playlist.get("master_flag"):
        return

    playlist_id = coerce_int(playlist.get("playlist_id"))
    title = str(playlist.get("Title") or "playlist")
    if not playlist_id:
        _add_error(
            issues,
            "playlist_missing_id",
            f"Playlist {title} has no playlist_id.",
            bucket=bucket,
            item_label=title,
        )

    items = playlist.get("items", [])
    if items is None:
        return
    if not isinstance(items, list):
        _add_error(
            issues,
            "playlist_items_not_list",
            f"Playlist {title} has malformed items; expected a list.",
            bucket=bucket,
            item_label=title,
        )
        return

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            _add_error(
                issues,
                "playlist_item_not_dict",
                f"Playlist {title} item {index} is malformed.",
                bucket=bucket,
                item_label=title,
            )
            continue
        if _playlist_item_has_identity(item):
            _validate_playlist_item_source_is_planned(
                item,
                plan_source_keys,
                issues,
                bucket=bucket,
                title=title,
                index=index,
            )
            continue
        _add_error(
            issues,
            "playlist_item_missing_identity",
            (
                f"Playlist {title} item {index} has no db_track_id, track_id, "
                "or source_path."
            ),
            bucket=bucket,
            item_label=title,
        )


def _validate_playlist_item_source_is_planned(
    item: dict[str, Any],
    plan_source_keys: set[str] | None,
    issues: list[PlanValidationIssue],
    *,
    bucket: str,
    title: str,
    index: int,
) -> None:
    if plan_source_keys is None:
        return
    if coerce_int(item.get("db_track_id", item.get("db_id", 0))):
        return
    if coerce_int(item.get("track_id", 0)):
        return
    source_path = item.get("source_path") or item.get("_source_path")
    if not source_path:
        return
    source_key = _safe_stable_path_key(str(source_path))
    if source_key and source_key in plan_source_keys:
        return
    _add_error(
        issues,
        "playlist_source_not_planned_or_matched",
        (
            f"Playlist {title} item {index} references {source_path}, but "
            "that source is not in the add plan or matched PC path index."
        ),
        bucket=bucket,
        item_label=title,
    )


def _validate_stale_mapping_entries(
    plan: SyncPlan,
    issues: list[PlanValidationIssue],
) -> None:
    for index, entry in enumerate(getattr(plan, "_stale_mapping_entries", []) or [], start=1):
        if not isinstance(entry, tuple) or len(entry) != 2:
            _add_error(
                issues,
                "stale_mapping_entry_malformed",
                f"Stale mapping entry {index} is malformed.",
                bucket="_stale_mapping_entries",
            )
            continue
        fingerprint, db_track_id = entry
        if fingerprint and coerce_int(db_track_id):
            continue
        _add_error(
            issues,
            "stale_mapping_entry_missing_identity",
            f"Stale mapping entry {index} has no fingerprint or db_track_id.",
            bucket="_stale_mapping_entries",
        )


def _playlist_item_has_identity(item: dict[str, Any]) -> bool:
    if coerce_int(item.get("db_track_id", item.get("db_id", 0))):
        return True
    if coerce_int(item.get("track_id", 0)):
        return True
    return bool(item.get("source_path") or item.get("_source_path"))


def _plan_source_keys(plan: SyncPlan) -> set[str]:
    keys: set[str] = set()
    for item in plan.to_add:
        key = _safe_stable_path_key(item.source_path)
        if key:
            keys.add(key)
    for path in (plan.matched_pc_paths or {}).values():
        key = _safe_stable_path_key(str(path))
        if key:
            keys.add(key)
    return keys


def _safe_stable_path_key(path: str) -> str:
    if not path:
        return ""
    try:
        return stable_path_key(path)
    except (TypeError, ValueError, OSError):
        return ""


def _sync_item_db_track_id(item: SyncItem) -> int:
    return coerce_int(item.db_track_id)


def _is_downloadable_podcast(item: SyncItem) -> bool:
    pc_track = item.pc_track
    if pc_track is None:
        return False
    return bool(
        getattr(pc_track, "is_podcast", False)
        and getattr(pc_track, "podcast_enclosure_url", "")
    )
