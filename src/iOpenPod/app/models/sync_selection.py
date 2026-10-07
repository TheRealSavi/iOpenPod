"""Mutable user intent layered over one immutable Sync comparison."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal

from iOpenPod.app.sync_plan import (
    SyncDuplicateResolution,
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
    host_path_identity,
    resolve_sync_duplicates,
    select_sync_plan,
)
from iPodDB.library import PhotoRepresentationKind

if TYPE_CHECKING:
    from collections.abc import Iterable

    from iOpenPod.app.host_media_library import HostMediaLibrary
    from iOpenPod.app.sync_plan import SyncDuplicateGroup


class SyncSelection(QObject):
    """Own desired iPod membership without mutating a Library Snapshot or plan."""

    hostSelectionChanged = Signal()
    removalSelectionChanged = Signal()
    reviewSelectionChanged = Signal()
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._comparison = SyncPlan(())
        self._duplicate_resolutions: tuple[SyncDuplicateResolution, ...] = ()
        self._resolved_comparison: SyncPlan | None = None
        self._track_paths: dict[int, str] = {}
        self._photo_paths: dict[int, str] = {}
        self._selected_host_paths: set[str] = set()
        self._selected_ipod_removals: set[tuple[SyncPlanMediaKind, int]] = set()
        self._excluded_review_items: set[SyncPlanItem] = set()
        self._review_plan: SyncPlan | None = None
        self._review_items: frozenset[SyncPlanItem] = frozenset()

    @property
    def comparison(self) -> SyncPlan:
        return self._comparison

    @property
    def duplicate_resolutions(self) -> tuple[SyncDuplicateResolution, ...]:
        return self._duplicate_resolutions

    @property
    def resolved_comparison(self) -> SyncPlan:
        """Return the scan comparison with validated, explicit matching choices."""

        if self._resolved_comparison is None:
            self._resolved_comparison = resolve_sync_duplicates(
                self._comparison, self._duplicate_resolutions
            )
        return self._resolved_comparison

    def set_duplicate_resolution(
        self,
        resolution: SyncDuplicateResolution,
        *,
        preserved_host_paths: frozenset[str] = frozenset(),
    ) -> bool:
        """Apply explicit choices atomically, preserving untouched dialog rows.

        Callers editing part of a group name its untouched Host paths so browser
        membership and Review exclusions remain independent of the changed rows.
        Reapplying an explicitly chosen pair or Add restores its selected action.
        """

        choices = {item.group_id: item for item in self._duplicate_resolutions}
        choices[resolution.group_id] = resolution
        # Validate the complete choices before changing any visible selection.
        resolutions = tuple(choices.values())
        resolved = resolve_sync_duplicates(self._comparison, resolutions)
        group = next(
            item
            for item in self._comparison.duplicate_groups
            if item.group_id == resolution.group_id
        )
        established_hosts = {
            host_path_identity(pair.host_path) for pair in group.established_pairs
        }
        established_ipods = {pair.ipod_id for pair in group.established_pairs}
        preserved = {host_path_identity(path) for path in preserved_host_paths}
        group_paths = {host_path_identity(host.host_path) for host in group.hosts}
        if not preserved <= group_paths:
            raise ValueError("Untouched Host paths must belong to the duplicate group")
        # Checked ambiguous sources do not yet authorize an Add. An untouched
        # Skip row must not become an Add when another row resolves the group.
        preserved.intersection_update(
            host_path_identity(item.host_path)
            for item in self.resolved_comparison.items
            if item.host_path is not None
            and item.action is not SyncPlanAction.ATTENTION
        )
        selected_hosts = self._selected_host_paths.copy()
        selected_hosts.difference_update(
            host_path_identity(host.host_path)
            for host in group.hosts
            if host_path_identity(host.host_path) not in established_hosts
            and host_path_identity(host.host_path) not in preserved
        )
        explicitly_selected = {
            host_path_identity(path) for path in resolution.added_host_paths
        } | {host_path_identity(pair.host_path) for pair in resolution.pairs}
        explicitly_selected.difference_update(preserved)
        selected_hosts.update(explicitly_selected)
        selected_removals = self._selected_ipod_removals.copy()
        selected_removals.difference_update(
            (group.media_kind, ipod.ipod_id)
            for ipod in group.ipods
            if ipod.ipod_id not in established_ipods
        )
        selected_removals.update(
            (group.media_kind, identity) for identity in resolution.removed_ipod_ids
        )
        selected = select_sync_plan(
            resolved,
            selected_host_paths=frozenset(selected_hosts),
            selected_ipod_removals=frozenset(),
        )
        review_items = frozenset(
            (
                *selected.items,
                *(item for item in resolved.items if _removal_key(item) is not None),
            )
        )
        exclusions = {
            item
            for item in self._excluded_review_items
            if item in review_items
            and not (
                item.host_path is not None
                and host_path_identity(item.host_path) in explicitly_selected
            )
        }
        if (
            resolutions == self._duplicate_resolutions
            and selected_hosts == self._selected_host_paths
            and selected_removals == self._selected_ipod_removals
            and exclusions == self._excluded_review_items
        ):
            return False
        self._selected_host_paths = selected_hosts
        self._selected_ipod_removals = selected_removals
        self._duplicate_resolutions = resolutions
        self._resolved_comparison = resolved
        self._review_plan = None
        self._excluded_review_items = exclusions
        self.hostSelectionChanged.emit()
        self.removalSelectionChanged.emit()
        self.reviewSelectionChanged.emit()
        self.changed.emit()
        return True

    @property
    def selected_host_count(self) -> int:
        return len(self._selected_host_paths)

    @property
    def unresolved_selected_host_paths(self) -> frozenset[str]:
        """Selected ambiguous sources still need an explicit Match, Add, or Skip."""

        return frozenset(
            host_path_identity(item.host_path)
            for item in self.resolved_comparison.items
            if item.action is SyncPlanAction.ATTENTION
            and item.basis is SyncPlanBasis.AMBIGUOUS_IDENTITY
            and item.host_path is not None
            and host_path_identity(item.host_path) in self._selected_host_paths
        )

    @property
    def pending_duplicate_groups(self) -> tuple[SyncDuplicateGroup, ...]:
        """Return the duplicate groups blocking the user's selected Host intent."""

        paths = self.unresolved_selected_host_paths
        return tuple(
            group
            for group in self._comparison.duplicate_groups
            if any(host_path_identity(host.host_path) in paths for host in group.hosts)
        )

    @property
    def potential_removals(self) -> tuple[SyncPlanItem, ...]:
        return tuple(
            item
            for item in self.resolved_comparison.items
            if item.action is SyncPlanAction.REMOVE
            and item.basis is SyncPlanBasis.IPOD_ONLY
            and item.host_path is None
            and item.ipod_id is not None
        )

    @property
    def selected_plan(self) -> SyncPlan:
        return replace(
            self.review_plan,
            items=tuple(
                item
                for item in self.review_plan.items
                if self.review_check_state(item) is not Qt.CheckState.Unchecked
            ),
        )

    @property
    def review_plan(self) -> SyncPlan:
        """Return selected actions plus every opt-in iPod-only removal candidate."""

        if self._review_plan is None:
            selected = select_sync_plan(
                self.resolved_comparison,
                selected_host_paths=frozenset(self._selected_host_paths),
                selected_ipod_removals=frozenset(),
            )
            self._review_plan = replace(
                selected,
                items=(*selected.items, *self.potential_removals),
            )
            self._review_items = frozenset(self._review_plan.items)
        return self._review_plan

    def review_check_state(self, item: SyncPlanItem) -> Qt.CheckState | None:
        """Review includes actions independently of desired Host membership."""

        if self._review_plan is None:
            _ = self.review_plan  # Populate the cached candidate identities.
        if item not in self._review_items or item.action in {
            SyncPlanAction.UNCHANGED,
            SyncPlanAction.ATTENTION,
        }:
            return None
        removal = self.removal_check_state(item)
        if removal is not None:
            return removal
        return (
            Qt.CheckState.Unchecked
            if item in self._excluded_review_items
            else Qt.CheckState.Checked
        )

    def set_review_items_checked(
        self, items: Iterable[SyncPlanItem], checked: bool
    ) -> bool:
        """Toggle captured candidates in one update, never inventing a new action."""

        changed = False
        removals_changed = False
        for item in items:
            state = self.review_check_state(item)
            if state is None or (state is Qt.CheckState.Checked) == checked:
                continue
            key = _removal_key(item)
            if key is not None:
                if checked:
                    self._selected_ipod_removals.add(key)
                else:
                    self._selected_ipod_removals.discard(key)
                removals_changed = True
            elif checked:
                self._excluded_review_items.discard(item)
            else:
                self._excluded_review_items.add(item)
            changed = True
        if changed:
            if removals_changed:
                self.removalSelectionChanged.emit()
            self.reviewSelectionChanged.emit()
            self.changed.emit()
        return changed

    def reset(self, library: HostMediaLibrary, comparison: SyncPlan) -> None:
        """Adopt a completed scan; only already-correlated Host media starts checked."""

        self._comparison = comparison
        self._duplicate_resolutions = ()
        self._resolved_comparison = None
        self._track_paths = {
            track.track_id: host_path_identity(track.metadata.location)
            for track in library.snapshot.tracks
            if track.metadata.location
        }
        self._photo_paths = {}
        if library.snapshot.photos is not None:
            for photo in library.snapshot.photos.photos:
                path = next(
                    (
                        representation.relative_path
                        for representation in photo.representations
                        if representation.kind
                        is PhotoRepresentationKind.FULL_RESOLUTION
                    ),
                    None,
                )
                if path is None and photo.representations:
                    path = photo.representations[0].relative_path
                if path:
                    self._photo_paths[photo.photo_id] = host_path_identity(path)

        self._selected_host_paths = {
            host_path_identity(item.host_path)
            for item in comparison.items
            if item.host_path is not None and item.ipod_id is not None
        }
        self._selected_ipod_removals.clear()
        self._excluded_review_items.clear()
        self._review_plan = None
        self._review_items = frozenset()
        self.hostSelectionChanged.emit()
        self.removalSelectionChanged.emit()
        self.reviewSelectionChanged.emit()
        self.changed.emit()

    def clear(self) -> None:
        self._comparison = SyncPlan(())
        self._duplicate_resolutions = ()
        self._resolved_comparison = None
        self._track_paths.clear()
        self._photo_paths.clear()
        self._selected_host_paths.clear()
        self._selected_ipod_removals.clear()
        self._excluded_review_items.clear()
        self._review_plan = None
        self._review_items = frozenset()
        self.hostSelectionChanged.emit()
        self.removalSelectionChanged.emit()
        self.reviewSelectionChanged.emit()
        self.changed.emit()

    def track_check_state(self, track_id: int) -> Qt.CheckState:
        return self._path_check_state(self._track_paths.get(track_id))

    def photo_check_state(self, photo_id: int) -> Qt.CheckState:
        return self._path_check_state(self._photo_paths.get(photo_id))

    def track_group_check_state(self, track_ids: Iterable[int]) -> Qt.CheckState:
        return self._aggregate_paths(
            self._track_paths.get(track_id) for track_id in track_ids
        )

    def set_tracks_checked(self, track_ids: Iterable[int], checked: bool) -> bool:
        return self._set_paths(
            (self._track_paths.get(track_id) for track_id in track_ids),
            checked,
        )

    def set_photos_checked(self, photo_ids: Iterable[int], checked: bool) -> bool:
        return self._set_paths(
            (self._photo_paths.get(photo_id) for photo_id in photo_ids),
            checked,
        )

    def removal_check_state(self, item: SyncPlanItem) -> Qt.CheckState | None:
        key = _removal_key(item)
        if key is None:
            return None
        return (
            Qt.CheckState.Checked
            if key in self._selected_ipod_removals
            else Qt.CheckState.Unchecked
        )

    def set_removal_checked(self, item: SyncPlanItem, checked: bool) -> bool:
        if _removal_key(item) is None:
            return False
        return self.set_review_items_checked((item,), checked)

    def _path_check_state(self, path: str | None) -> Qt.CheckState:
        return (
            Qt.CheckState.Checked
            if path is not None and path in self._selected_host_paths
            else Qt.CheckState.Unchecked
        )

    def _aggregate_paths(self, paths: Iterable[str | None]) -> Qt.CheckState:
        retained = tuple(path for path in paths if path is not None)
        selected = sum(path in self._selected_host_paths for path in retained)
        if selected == 0:
            return Qt.CheckState.Unchecked
        if selected == len(retained):
            return Qt.CheckState.Checked
        return Qt.CheckState.PartiallyChecked

    def _set_paths(self, paths: Iterable[str | None], checked: bool) -> bool:
        retained = {path for path in paths if path is not None}
        before = len(self._selected_host_paths)
        if checked:
            self._selected_host_paths.update(retained)
        else:
            self._selected_host_paths.difference_update(retained)
        if before == len(self._selected_host_paths):
            return False
        self._review_plan = None
        self._excluded_review_items.intersection_update(self.review_plan.items)
        self.hostSelectionChanged.emit()
        self.changed.emit()
        return True


def _removal_key(
    item: SyncPlanItem,
) -> tuple[SyncPlanMediaKind, int] | None:
    if (
        item.action is not SyncPlanAction.REMOVE
        or item.basis is not SyncPlanBasis.IPOD_ONLY
        or item.host_path is not None
        or item.ipod_id is None
    ):
        return None
    return item.media_kind, item.ipod_id


__all__ = ["SyncSelection"]
