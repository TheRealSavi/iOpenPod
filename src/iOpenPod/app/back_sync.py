"""Post-commit rating updates to the Host files paired by the reviewed Sync."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial
from typing import TYPE_CHECKING

import mutagen

from iOpenPod.app.display_text import source_text
from iOpenPod.app.library_sync_helper import SyncedTrack
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

    from iOpenPod.app.library_sync_helper import SyncDetails
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.sync_execution import SyncExecutionRequest
    from iOpenPod.app.sync_plan import SyncPlanItem


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


@dataclass(frozen=True, slots=True)
class RatingDecision:
    """Ratings observed during Review and the targets to apply after selection."""

    host_rating: int
    ipod_rating: int
    ipod_target: int
    host_target: int | None = None


def review_rating(
    host: int, ipod: int, sync: SyncDetails, policy: str
) -> RatingDecision | None:
    """Resolve one established pair, including a retry or baseline-only update."""
    if not 0 <= ipod <= 100:
        return None
    if sync.host_rating is None or sync.ipod_rating is None:
        return RatingDecision(host, ipod, ipod)

    pending = sync.pending_rating
    if pending is not None and pending.matches(host, ipod):
        target = pending.target_rating
    elif (host, ipod) == (sync.host_rating, sync.ipod_rating):
        return None if pending is None else RatingDecision(host, ipod, ipod)
    else:
        target = resolved_rating(host, ipod, sync.host_rating, sync.ipod_rating, policy)
    host_target = whole_star_rating(target)
    return RatingDecision(
        host, ipod, target, host_target if host_target != host else None
    )


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
    for item in completed:
        if (
            item.media_kind is not SyncPlanMediaKind.TRACK
            or item.host_path is None
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
        decision = item.rating
        if not source.metadata_complete or (decision is None and prior is not None):
            continue
        host_target = decision.host_target if decision is not None else None
        needs_write = host_target is not None
        try:
            validate_device()
            observation = LocalHostFile.observe(source.path)
            if not source.matches(observation):
                raise ValueError(
                    "The paired Host file changed after scanning; rescan before retrying."
                )
            rating = host.rating if decision is None else decision.host_rating
            if decision is not None and track.rating != decision.ipod_target:
                raise ValueError("The saved iPod rating differs from Review.")
            if host_target is not None:
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
                        expected_rating=rating,
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
