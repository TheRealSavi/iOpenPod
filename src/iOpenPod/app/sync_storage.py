"""Provisional Sync storage projections from captured file sizes, without I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.sync_plan import SyncPlanAction, SyncPlanMediaKind, host_path_identity

if TYPE_CHECKING:
    from iOpenPod.app.host_media_library import HostMediaLibrary
    from iOpenPod.app.library_sync_helper import IPodMediaLibrary
    from iOpenPod.app.models.device import DeviceCandidate
    from iOpenPod.app.sync_plan import SyncPlan


@dataclass(frozen=True, slots=True)
class SyncStorageEstimate:
    """Source-size arithmetic, never an output-size or transaction-space guarantee."""

    total_bytes: int
    current_used_bytes: int
    incoming_bytes: int
    outgoing_bytes: int
    unknown_items: int

    @property
    def net_bytes(self) -> int:
        return self.incoming_bytes - self.outgoing_bytes

    @property
    def projected_used_bytes(self) -> int:
        return max(0, self.current_used_bytes + self.net_bytes)

    @property
    def free_bytes(self) -> int:
        """Negative values preserve how far the provisional projection exceeds capacity."""

        return self.total_bytes - self.projected_used_bytes


class SyncStorageProjection:
    """Index scan facts once and project only the selected plan's proposed changes.

    Incoming media uses Host source bytes until transcoder output estimates exist.
    Outgoing bytes use scanned iPod files, including replaced files. Shared files
    are credited once, only when every scanned reference leaves the iPod. Packed
    Photo representations, artwork, databases, and transaction overhead are outside
    this provisional projection. Attention and missing facts remain explicit.
    """

    def __init__(
        self,
        host: HostMediaLibrary,
        ipod: IPodMediaLibrary,
        candidate: DeviceCandidate,
    ) -> None:
        self._total = max(0, candidate.total_bytes)
        self._used = min(self._total, max(0, candidate.used_bytes))
        self._host_sizes = {
            host_path_identity(str(source.path)): source.size_bytes
            for source in host.sources
            if source.size_bytes >= 0
        }
        self._ipod_files = {
            (SyncPlanMediaKind.TRACK, track.track_id): (
                str(track.path),
                track.size_bytes,
            )
            for track in ipod.tracks
        }
        self._ipod_files.update(
            {
                (SyncPlanMediaKind.PHOTO, photo.image_id): (
                    str(photo.path),
                    photo.size_bytes,
                )
                for photo in ipod.images
            }
        )

    def estimate(self, plan: SyncPlan) -> SyncStorageEstimate:
        incoming = 0
        unknown = 0
        outgoing: dict[str, int] = {}
        released: set[tuple[SyncPlanMediaKind, int]] = set()
        for item in plan.items:
            if item.action is SyncPlanAction.ATTENTION:
                unknown += 1
                continue
            missing_size = False
            incoming_size = 0
            if item.action in {SyncPlanAction.ADD, SyncPlanAction.UPDATE}:
                size = (
                    self._host_sizes.get(host_path_identity(item.host_path))
                    if item.host_path is not None
                    else None
                )
                if size is None:
                    missing_size = True
                else:
                    incoming_size = size
            key = (item.media_kind, item.ipod_id) if item.ipod_id is not None else None
            file = None
            if item.action in {SyncPlanAction.REMOVE, SyncPlanAction.UPDATE}:
                file = self._ipod_files.get(key) if key is not None else None
                if file is None:
                    missing_size = True
            if missing_size:
                unknown += 1
                continue
            incoming += incoming_size
            if file is not None and key is not None:
                released.add(key)
                path, size = file
                outgoing[path] = size

        # A retained Track or Photo may still reference the same physical file.
        for key, (path, _size) in self._ipod_files.items():
            if key not in released:
                outgoing.pop(path, None)
        return SyncStorageEstimate(
            self._total,
            self._used,
            incoming,
            sum(outgoing.values()),
            unknown,
        )


__all__ = ["SyncStorageEstimate", "SyncStorageProjection"]
