"""Defer optional cover changes while retaining the rest of reviewed Sync intent."""

from dataclasses import replace

from iOpenPod.app.library_sync_helper import SyncedTrack
from iOpenPod.app.library_write import LibraryPreparationRequest


def without_cover_changes(
    request: LibraryPreparationRequest,
) -> LibraryPreparationRequest | None:
    """Keep saved cover links; incoming Tracks can be published without a cover."""
    originals = {t.track_id: t for t in request.source.library.tracks}
    tracks = tuple(
        replace(
            track,
            artwork_id=originals[track.track_id].artwork_id
            if track.track_id in originals
            else 0,
        )
        for track in request.snapshot.tracks
    )
    if tracks == request.snapshot.tracks and not request.artwork:
        return None
    # Embedded file artwork is independent of ArtworkDB/iTHMB generation, so
    # keep explicitly requested Rockbox updates and media payloads intact.
    return replace(
        request, snapshot=replace(request.snapshot, tracks=tracks), artwork=()
    )


def pending_cover_provenance(track: SyncedTrack) -> SyncedTrack:
    """Allow the next scan to retry a cover that this Sync did not publish."""
    if track.sync is None:
        return track
    # Empty is an explicit uncommitted cover fingerprint. Unlike None (legacy
    # provenance), it also keeps a deferred cover removal eligible for retry.
    return replace(track, sync=replace(track.sync, host_artwork_sha256=""))
