"""Internal platform seam for mounted-volume discovery and revalidation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from storage.models import (
        DiscoveryIssue,
        EjectResult,
        FlushResult,
        HardwareProbeResult,
        PhysicalDeviceId,
        ScsiVpdPagePlan,
        VolumeObservation,
    )


@dataclass(frozen=True, slots=True)
class ObservationDiscoveryResult:
    observations: tuple[VolumeObservation, ...]
    issues: tuple[DiscoveryIssue, ...] = ()


class PlatformAdapter(Protocol):
    """Behavior that genuinely differs between native and virtual Hosts.

    ``inspect`` describes a caller-supplied Host path. ``reinspect`` validates an
    already retained mounted connection and may use a narrower native fast path.
    """

    @property
    def name(self) -> str: ...

    def discover(self) -> ObservationDiscoveryResult: ...

    def inspect(self, mount_point: Path) -> VolumeObservation: ...

    def reinspect(self, retained: VolumeObservation) -> VolumeObservation: ...

    def physical_device_id_for_path(self, path: Path) -> PhysicalDeviceId | None: ...

    def probe(
        self,
        observation: VolumeObservation,
        page_plan: ScsiVpdPagePlan | None = None,
    ) -> HardwareProbeResult: ...

    def flush(self, observation: VolumeObservation) -> FlushResult: ...

    def eject(self, observation: VolumeObservation) -> EjectResult: ...
