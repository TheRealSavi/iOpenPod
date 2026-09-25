"""Virtual mounted-volume adapter for deterministic Storage verification."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from storage.errors import EjectError, MountInspectionError
from storage.models import (
    DeviceBus,
    DiscoveryIssue,
    EjectResult,
    FlushResult,
    HardwareIdentifiers,
    HardwareProbeResult,
    MountPoint,
    PhysicalDevice,
    PhysicalDeviceId,
    ScsiVpdPagePlan,
    StorageCapabilities,
    Volume,
    VolumeId,
    VolumeObservation,
)
from storage.platform.base import ObservationDiscoveryResult

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(slots=True)
class _VirtualVolumeState:
    observation: VolumeObservation
    probe_result: HardwareProbeResult = field(default_factory=HardwareProbeResult)
    connected: bool = True
    flush_count: int = 0
    eject_count: int = 0
    eject_error: EjectError | None = None


class VirtualStoragePlatform:
    """Controllable Adapter backed by ordinary temporary directories."""

    def __init__(self) -> None:
        self._volumes: dict[Path, _VirtualVolumeState] = {}
        self._connection_counter = 0

    @property
    def name(self) -> str:
        return "virtual"

    def add_volume(
        self,
        root: Path,
        *,
        device_id: str = "virtual-device-1",
        volume_id: str = "virtual-volume-1",
        label: str = "Virtual Volume",
        filesystem_type: str = "virtual",
        writable: bool = True,
        max_file_size_bytes: int | None = None,
        max_component_length: int | None = 255,
        allocation_unit_size: int | None = 4096,
        identifiers: HardwareIdentifiers | None = None,
        probe_result: HardwareProbeResult | None = None,
    ) -> VolumeObservation:
        canonical = root.resolve(strict=True)
        if not canonical.is_dir():
            raise ValueError("A virtual Volume root must be a directory")
        self._connection_counter += 1
        usage = shutil.disk_usage(canonical)
        physical_id = PhysicalDeviceId(device_id)
        observation = VolumeObservation(
            physical_device=PhysicalDevice(
                id=physical_id,
                display_name=label,
                bus=DeviceBus.VIRTUAL,
                removable=True,
                identifiers=identifiers or HardwareIdentifiers(),
            ),
            volume=Volume(
                id=VolumeId(volume_id),
                physical_device_id=physical_id,
                label=label,
                filesystem_type=filesystem_type,
                total_bytes=usage.total,
                available_bytes=usage.free,
                capabilities=StorageCapabilities(
                    readable=True,
                    writable=writable,
                    case_sensitive=(os.path.normcase("A") != os.path.normcase("a")),
                    max_file_size_bytes=max_file_size_bytes,
                    max_component_length=max_component_length,
                    allocation_unit_size=allocation_unit_size,
                ),
            ),
            mount_point=MountPoint(canonical),
            mount_instance=f"virtual-{self._connection_counter}",
        )
        self._volumes[canonical] = _VirtualVolumeState(
            observation=observation,
            probe_result=probe_result or HardwareProbeResult(),
        )
        return observation

    def discover(self) -> ObservationDiscoveryResult:
        observations = tuple(
            state.observation for state in self._volumes.values() if state.connected
        )
        return ObservationDiscoveryResult(observations=observations)

    def inspect(self, mount_point: Path) -> VolumeObservation:
        canonical = mount_point.resolve(strict=False)
        matching = tuple(
            (root, state)
            for root, state in self._volumes.items()
            if canonical == root or canonical.is_relative_to(root)
        )
        if not matching or not canonical.exists():
            raise MountInspectionError(
                f"The virtual Volume is not connected at {mount_point}"
            )
        _, state = max(matching, key=lambda item: len(os.fspath(item[0])))
        if not state.connected:
            raise MountInspectionError(
                f"The virtual Volume is not connected at {mount_point}"
            )
        usage = shutil.disk_usage(canonical)
        return replace(
            state.observation,
            volume=replace(
                state.observation.volume,
                total_bytes=usage.total,
                available_bytes=usage.free,
            ),
        )

    def reinspect(self, retained: VolumeObservation) -> VolumeObservation:
        return self.inspect(retained.mount_point.path)

    def physical_device_id_for_path(self, path: Path) -> PhysicalDeviceId | None:
        canonical = path.resolve(strict=True)
        matching = tuple(
            (root, state)
            for root, state in self._volumes.items()
            if canonical == root or canonical.is_relative_to(root)
        )
        if matching:
            _, state = max(matching, key=lambda item: len(os.fspath(item[0])))
            if not state.connected:
                raise MountInspectionError(
                    f"The virtual Volume is not connected at {path}"
                )
            return state.observation.physical_device.id
        try:
            return PhysicalDeviceId(f"virtual-host:{canonical.stat().st_dev}")
        except OSError:
            return None

    def flush(self, observation: VolumeObservation) -> FlushResult:
        canonical = observation.mount_point.path.resolve(strict=False)
        state = self._volumes.get(canonical)
        if state is None or not state.connected:
            raise MountInspectionError("The virtual Volume disconnected before flush")
        state.flush_count += 1
        return FlushResult(complete=True, detail="virtual filesystem flushed")

    def eject(self, observation: VolumeObservation) -> EjectResult:
        canonical = observation.mount_point.path.resolve(strict=False)
        state = self._volumes.get(canonical)
        if state is None or not state.connected:
            raise MountInspectionError("The virtual Volume disconnected before eject")
        state.eject_count += 1
        if state.eject_error is not None:
            if state.eject_error.volume_unmounted:
                state.connected = False
            raise state.eject_error
        state.connected = False
        return EjectResult("virtual Physical Device safely ejected")

    def probe(
        self,
        observation: VolumeObservation,
        page_plan: ScsiVpdPagePlan | None = None,
    ) -> HardwareProbeResult:
        del page_plan
        state = self._volumes.get(observation.mount_point.path.resolve(strict=False))
        if state is None or not state.connected:
            raise MountInspectionError(
                "The virtual Volume disconnected before its hardware probe"
            )
        return state.probe_result

    def disconnect(self, root: Path) -> None:
        state = self._state(root)
        state.connected = False

    def reconnect(self, root: Path) -> VolumeObservation:
        state = self._state(root)
        self._connection_counter += 1
        state.connected = True
        state.observation = replace(
            state.observation,
            mount_instance=f"virtual-{self._connection_counter}",
        )
        return state.observation

    def replace_identity(
        self,
        root: Path,
        *,
        device_id: str,
        volume_id: str,
    ) -> VolumeObservation:
        state = self._state(root)
        physical_id = PhysicalDeviceId(device_id)
        state.observation = replace(
            state.observation,
            physical_device=replace(
                state.observation.physical_device,
                id=physical_id,
            ),
            volume=replace(
                state.observation.volume,
                id=VolumeId(volume_id),
                physical_device_id=physical_id,
            ),
        )
        return state.observation

    def set_writable(self, root: Path, writable: bool) -> None:
        state = self._state(root)
        state.observation = replace(
            state.observation,
            volume=replace(
                state.observation.volume,
                capabilities=replace(
                    state.observation.volume.capabilities,
                    writable=writable,
                ),
            ),
        )

    def flush_count(self, root: Path) -> int:
        return self._state(root).flush_count

    def eject_count(self, root: Path) -> int:
        return self._state(root).eject_count

    def fail_eject(
        self,
        root: Path,
        message: str,
        *,
        volume_unmounted: bool = False,
    ) -> None:
        self._state(root).eject_error = EjectError(
            message,
            volume_unmounted=volume_unmounted,
        )

    def issues(self) -> tuple[DiscoveryIssue, ...]:
        return ()

    def _state(self, root: Path) -> _VirtualVolumeState:
        canonical = root.resolve(strict=False)
        try:
            return self._volumes[canonical]
        except KeyError as error:
            raise KeyError(f"No virtual Volume is registered at {root}") from error
