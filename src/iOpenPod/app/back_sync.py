"""Post-commit rating updates to the Host files paired by the reviewed Sync."""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from typing import TYPE_CHECKING

import mutagen

from iOpenPod.app.display_text import source_text
from iOpenPod.app.library_sync_helper import PendingRatingWrite, SyncedTrack
from iOpenPod.app.media.ratings import (
    rating_supported,
    rewrite_rating_stream,
    whole_star_rating,
)
from iPodDB.library import IssueSeverity, WriteIssue
from storage import StorageError
from storage.host_input import LocalHostFile
from storage.host_replacement import replace_host_file

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.sync_execution import SyncExecutionRequest
    from iOpenPod.app.sync_plan import SyncPlanItem
    from iPodDB.library import LibrarySnapshot


def resolved_rating(
    host: int,
    ipod: int,
    baseline_host: int | None,
    baseline_ipod: int | None,
    policy: str = "host",
) -> int:
    """Resolve captured rating changes; unknown pairs retain the iPod value."""
    if policy not in {"host", "ipod", "average"}:
        raise ValueError("Unknown rating conflict policy")
    if baseline_host is None or baseline_ipod is None:
        return ipod
    host_changed = host != baseline_host
    ipod_changed = ipod != baseline_ipod
    if host_changed and ipod_changed and host != ipod:
        return (
            host
            if policy == "host"
            else ipod
            if policy == "ipod"
            else min(100, int((host + ipod) / 40 + 0.5) * 20)
        )
    return host if host_changed else ipod


def rating_needs_back_sync(
    host: int, ipod: int, baseline_host: int | None, baseline_ipod: int | None
) -> bool:
    return (
        baseline_host is not None
        and baseline_ipod is not None
        and (host != baseline_host or ipod != baseline_ipod)
        and resolved_rating(host, ipod, baseline_host, baseline_ipod) != host
    )


def pending_rating_writes(
    request: SyncExecutionRequest,
    desired: LibrarySnapshot,
    completed: tuple[SyncPlanItem, ...],
) -> dict[int, PendingRatingWrite]:
    """Capture a retryable write only for a reviewed, established Host pair."""
    from iOpenPod.app.sync_plan import host_path_identity

    if not (request.options.back_sync_ratings and request.plan.sync_ratings):
        return {}
    hosts = {
        host_path_identity(track.metadata.location): track
        for track in request.host.snapshot.tracks
    }
    readable = {
        host_path_identity(str(source.path))
        for source in request.host.sources
        if source.metadata_complete
    }
    baselines = {record.track_id: record.sync for record in request.ipod.tracks}
    targets = {track.track_id: track.rating for track in desired.tracks}
    original = {track.track_id: track.rating for track in request.source.library.tracks}
    pending: dict[int, PendingRatingWrite] = {}
    for item in completed:
        if item.host_path is None or item.ipod_id is None:
            continue
        key = host_path_identity(item.host_path)
        host = hosts.get(key)
        prior = baselines.get(item.ipod_id)
        target = targets.get(item.ipod_id)
        before = original.get(item.ipod_id)
        if (
            host is None
            or key not in readable
            or prior is None
            or prior.host_rating is None
            or prior.ipod_rating is None
            or host_path_identity(prior.host_path_hint) != key
            or target is None
            or before is None
            or not 0 <= target <= 100
            or whole_star_rating(target) == host.rating
            or (
                prior.pending_rating is None
                and host.rating == prior.host_rating
                and before == prior.ipod_rating
            )
        ):
            continue
        pending[item.ipod_id] = PendingRatingWrite(host.rating, target)
    return pending


def back_sync_ratings(
    request: SyncExecutionRequest,
    active: ActiveIPod,
    completed: tuple[SyncPlanItem, ...],
    provenance: tuple[SyncedTrack, ...],
    *,
    validate_device: Callable[[], None] = lambda: None,
) -> tuple[tuple[SyncedTrack, ...], tuple[WriteIssue, ...]]:
    """Write ratings only for successfully completed, explicitly selected items.

    The caller has already verified device publication. Failures retain previous
    rating baselines, so another reviewed Sync can retry without undoing the iPod.
    """
    from iOpenPod.app.sync_plan import (
        SyncPlanAction,
        SyncPlanMediaKind,
        host_path_identity,
    )

    hosts = {
        host_path_identity(t.metadata.location): t for t in request.host.snapshot.tracks
    }
    sources = {host_path_identity(str(s.path)): s for s in request.host.sources}
    scanned = {t.track_id: t for t in request.ipod.tracks}
    tracks = {t.track_id: t for t in active.library.tracks}
    paths = {t.metadata.location: t for t in active.library.tracks}
    updated = {(t.track_id, str(t.path)): t for t in provenance}
    linked = {
        host_path_identity(t.sync.host_path_hint): t
        for t in provenance
        if t.sync is not None
    }
    issues: list[WriteIssue] = []
    selected = set(completed)
    for item in request.plan.items:
        if (
            item.media_kind is not SyncPlanMediaKind.TRACK
            or item.host_path is None
            or item not in selected
            or item.action in (SyncPlanAction.REMOVE, SyncPlanAction.ATTENTION)
        ):
            continue
        key = host_path_identity(item.host_path)
        new = linked.get(key)
        old = scanned.get(item.ipod_id) if item.ipod_id is not None else None
        prior = old.sync if old is not None else None
        if prior is not None and host_path_identity(prior.host_path_hint) != key:
            prior = None
        record = new or (
            SyncedTrack(
                old.path, old.acoustic_fingerprint, prior, track_id=old.track_id
            )
            if old is not None
            else None
        )
        if record is None or record.sync is None:
            continue
        track = (
            tracks.get(item.ipod_id)
            if item.ipod_id is not None
            else paths.get(str(record.path))
        )
        host = hosts.get(key)
        source = sources.get(key)
        if track is None or host is None or source is None:
            continue
        sync = replace(
            record.sync,
            host_rating=prior.host_rating if prior is not None else None,
            ipod_rating=prior.ipod_rating if prior is not None else None,
            pending_rating=prior.pending_rating if prior is not None else None,
        )
        record = replace(record, sync=sync)
        record_key = (record.track_id, str(record.path))
        updated[record_key] = record
        enabled = request.options.back_sync_ratings and request.plan.sync_ratings
        if not source.metadata_complete or (not enabled and prior is not None):
            continue
        if (
            sync.pending_rating is None
            and host.rating == sync.host_rating
            and track.rating == sync.ipod_rating
        ):
            continue
        host_target = whole_star_rating(track.rating)
        needs_write = (
            enabled
            and sync.pending_rating is not None
            and sync.pending_rating.matches(host.rating, track.rating)
            and host_target != host.rating
        )
        try:
            validate_device()
            observation = LocalHostFile.observe(source.path)
            if not source.matches(observation):
                raise ValueError(
                    "The paired Host file changed after scanning; rescan before retrying."
                )
            rating = host.rating
            if needs_write:
                if not rating_supported(item.host_path):
                    raise ValueError(
                        "This Host media format does not support rating Back Sync."
                    )
                observation = replace_host_file(
                    observation,
                    partial(
                        rewrite_rating_stream,
                        file_name=item.host_path,
                        rating=host_target,
                        expected_rating=host.rating,
                    ),
                    checkpoint=validate_device,
                )
                issues.append(
                    WriteIssue(
                        "sync.rating_written",
                        source_text(
                            "Updated Host rating from {old} to {new} stars.",
                            old=str(rating // 20),
                            new=str(host_target // 20),
                        ),
                        severity=IssueSeverity.INFO,
                        artifact=item.host_path,
                    )
                )
                rating = host_target
            updated[record_key] = replace(
                record,
                sync=replace(
                    sync,
                    host_rating=rating,
                    ipod_rating=track.rating,
                    pending_rating=None,
                    host_size_bytes=observation.size_bytes,
                    host_modified_ns=observation.modified_ns,
                ),
            )
        except (OSError, ValueError, StorageError, mutagen.MutagenError) as error:
            issues.append(
                WriteIssue(
                    "sync.rating_back_sync_failed",
                    "The iPod Sync completed, but its Host rating update could not finish. Rescan and retry Sync."
                    if needs_write
                    else "The paired Host file was unavailable; its rating baseline was kept. Rescan before the next Sync.",
                    detail=str(error),
                    artifact=item.host_path,
                    severity=IssueSeverity.ERROR
                    if needs_write
                    else IssueSeverity.WARNING,
                )
            )
    return tuple(updated.values()), tuple(issues)
