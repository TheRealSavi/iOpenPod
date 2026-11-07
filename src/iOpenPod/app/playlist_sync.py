"""Pure, reviewable Host Playlist matching and membership reconciliation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace

from iOpenPod.app.display_text import source_text
from iPodDB.library import Playlist, PlaylistKind, playlist_entries


@dataclass(frozen=True, slots=True)
class PlaylistAssociation:
    """A successful Host source identity paired with a persistent iPod identity."""

    host_playlist_id: int
    ipod_playlist_id: int


@dataclass(frozen=True, slots=True)
class PlaylistSyncChoice:
    host_playlist_id: int
    included: bool = True
    automatic: bool = True
    target_id: int | None = None


@dataclass(frozen=True, slots=True)
class PlaylistSyncChange:
    name: str
    action: str
    added_count: int
    removed_count: int
    order_changed: bool
    renamed: bool = False


@dataclass(frozen=True, slots=True)
class PlaylistSyncReviewItem:
    host_playlist_id: int
    name: str
    choice: PlaylistSyncChoice
    target_id: int | None = None
    target_name: str = ""
    match_detail: str = ""
    change: PlaylistSyncChange | None = None
    issue_code: str = ""
    detail: str = ""
    needs_association: bool = False
    source_path: str = ""

    @property
    def actionable(self) -> bool:
        return (
            self.choice.included
            and not self.issue_code
            and (self.change is not None or self.needs_association)
        )


def playlist_sync_target(playlist: Playlist) -> bool:
    return (
        playlist.kind is PlaylistKind.PLAYLIST
        and playlist.parent_id is None
        and not playlist.system_managed
    )


def playlist_changes(
    before: tuple[Playlist, ...], after: tuple[Playlist, ...]
) -> tuple[PlaylistSyncChange, ...]:
    by_id = {playlist.playlist_id: playlist for playlist in before}
    changes: list[PlaylistSyncChange] = []
    for playlist in after:
        previous = by_id.get(playlist.playlist_id)
        if previous is not None and (
            previous.track_ids == playlist.track_ids and previous.name == playlist.name
        ):
            continue
        original = () if previous is None else previous.track_ids
        old_counts, new_counts = Counter(original), Counter(playlist.track_ids)
        common = old_counts & new_counts

        def retained_order(
            identities: tuple[int, ...], counts: Counter[int]
        ) -> tuple[int, ...]:
            remaining = counts.copy()
            result: list[int] = []
            for identity in identities:
                if remaining[identity]:
                    remaining[identity] -= 1
                    result.append(identity)
            return tuple(result)

        changes.append(
            PlaylistSyncChange(
                playlist.name,
                "create" if previous is None else "update",
                sum((new_counts - old_counts).values()),
                sum((old_counts - new_counts).values()),
                retained_order(original, common)
                != retained_order(playlist.track_ids, common),
                previous is not None and previous.name != playlist.name,
            )
        )
    return tuple(changes)


def reconcile_playlist_sync(
    hosts: tuple[Playlist, ...],
    baseline: tuple[Playlist, ...],
    mapping: dict[int, int],
    *,
    selected: set[int],
    unresolved: set[int],
    incomplete: frozenset[int],
    associations: tuple[PlaylistAssociation, ...] = (),
    choices: tuple[PlaylistSyncChoice, ...] = (),
    source_paths: dict[int, str] | None = None,
) -> tuple[
    tuple[Playlist, ...],
    tuple[PlaylistSyncReviewItem, ...],
    tuple[PlaylistAssociation, ...],
]:
    """Match first, reject competing targets, then apply each complete selection.

    An unchecked Playlist never changes Track selection. The supplied baseline
    already excludes references to explicitly removed iPod Tracks.
    """
    by_id = {playlist.playlist_id: playlist for playlist in baseline}
    saved = {item.host_playlist_id: item.ipod_playlist_id for item in associations}
    by_choice = {item.host_playlist_id: item for item in choices}
    host_names = Counter(item.name.casefold() for item in hosts)
    by_name: dict[str, list[Playlist]] = {}
    for playlist in baseline:
        if playlist.parent_id is None:
            by_name.setdefault(playlist.name.casefold(), []).append(playlist)
    rows: list[PlaylistSyncReviewItem] = []
    supported_hosts = tuple(item for item in hosts if playlist_sync_target(item))
    for host in supported_hosts:
        choice = by_choice.get(host.playlist_id, PlaylistSyncChoice(host.playlist_id))
        target_id = choice.target_id
        detail = source_text("Chosen in Review")
        problem = ""
        if choice.automatic:
            if host.playlist_id in saved:
                target_id = saved[host.playlist_id]
                detail = source_text("Saved match")
            else:
                matches = by_name.get(host.name.casefold(), [])
                if host_names[host.name.casefold()] > 1 or len(matches) > 1:
                    problem = source_text(
                        "More than one Playlist has this name. Choose an iPod Playlist or create a new one."
                    )
                elif matches:
                    target_id = matches[0].playlist_id
                detail = (
                    source_text("Same name") if matches else source_text("New Playlist")
                )
        target = by_id.get(target_id) if target_id is not None else None
        if target_id is not None and (
            target is None or not playlist_sync_target(target)
        ):
            problem = source_text(
                "The matched Playlist is missing or cannot be synced. Choose another iPod Playlist or create a new one."
            )
        rows.append(
            PlaylistSyncReviewItem(
                host.playlist_id,
                host.name,
                choice,
                target_id,
                target.name if target is not None else "",
                detail,
                issue_code="sync.playlist_ambiguous" if problem else "",
                detail=problem,
                source_path=(source_paths or {}).get(host.playlist_id, ""),
            )
        )
    claims = Counter(
        row.target_id
        for row in rows
        if row.choice.included and row.target_id is not None and not row.issue_code
    )
    applied: list[PlaylistAssociation] = []
    next_id = min((0, *by_id)) - 1
    for index, (host, row) in enumerate(zip(supported_hosts, rows, strict=True)):
        problem, code = row.detail, row.issue_code
        if row.target_id is not None and claims[row.target_id] > 1:
            code = "sync.playlist_ambiguous"
            problem = source_text(
                "Another selected Host Playlist uses this iPod Playlist. Choose a different target or uncheck one."
            )
        if unresolved.intersection(host.track_ids):
            code = "sync.playlist_unresolved_matches"
            problem = source_text(
                "Resolve the unmatched Tracks in this Playlist before syncing it."
            )
        elif host.playlist_id in incomplete:
            code = "sync.playlist_incomplete"
            problem = source_text(
                "Some source entries could not be read or were declined. Resolve them and rescan."
            )
        elif any(
            identity in selected and identity not in mapping
            for identity in host.track_ids
        ):
            code = "sync.playlist_incomplete"
            problem = source_text(
                "A selected Track failed. Retry it before syncing this Playlist."
            )
        desired = tuple(
            mapping[identity] for identity in host.track_ids if identity in mapping
        )
        if not code and not desired and host.entries:
            code = "sync.playlist_no_tracks"
            problem = source_text(
                "Select Tracks from this Playlist to add them to the iPod."
            )
        if code:
            rows[index] = replace(row, issue_code=code, detail=problem)
            continue
        current = by_id.get(row.target_id) if row.target_id is not None else None
        identity = next_id if current is None else current.playlist_id
        wanted = (
            Playlist(identity, host.name, entries=playlist_entries(desired))
            if current is None
            else replace(
                current,
                name=host.name,
                entries=playlist_entries(desired, current.entries),
            )
        )
        changes = playlist_changes(() if current is None else (current,), (wanted,))
        rows[index] = replace(
            row,
            change=changes[0] if changes else None,
            needs_association=saved.get(host.playlist_id) != identity,
        )
        if row.choice.included:
            by_id[identity] = wanted
            applied.append(PlaylistAssociation(host.playlist_id, identity))
            if current is None:
                next_id -= 1
    return tuple(by_id.values()), tuple(rows), tuple(applied)
