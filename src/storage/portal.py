"""The Storage portal for discovery and Filesystem Session creation."""

from __future__ import annotations

import os
import threading
import uuid
import weakref
from pathlib import Path
from typing import TYPE_CHECKING

from storage.errors import (
    EjectError,
    HostPathOnPhysicalDeviceError,
    MountInspectionError,
    NotVolumeRootError,
    ReadOnlyFilesystemError,
    VolumeDisconnectedError,
    VolumeIdentityChangedError,
)
from storage.host_files import (
    AtomicHostFile,
    application_cache_file,
    application_config_file,
)
from storage.models import (
    AccessMode,
    ConnectionGeneration,
    DiscoveryResult,
    EjectResult,
    HardwareProbeResult,
    MountedVolume,
    ScsiVpdPagePlan,
    VolumeObservation,
)
from storage.platform.native import native_platform_adapter
from storage.session import FilesystemSession

if TYPE_CHECKING:
    from collections.abc import Mapping

    from storage.paths import HostPath
    from storage.platform.base import PlatformAdapter


class Storage:
    """Discover Volumes and open identity-bound filesystem portals."""

    def __init__(
        self,
        platform: PlatformAdapter | None = None,
        *,
        writer_lock_directory: Path | None = None,
    ) -> None:
        self._platform = platform or native_platform_adapter()
        self._writer_lock_directory = writer_lock_directory
        self._state_lock = threading.Lock()
        self._generations: dict[str, ConnectionGeneration] = {}
        self._sessions: list[weakref.ReferenceType[FilesystemSession]] = []

    @property
    def platform_name(self) -> str:
        return self._platform.name

    def host_config_file(
        self,
        application_name: str,
        filename: str,
        *,
        environment: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> AtomicHostFile:
        """Open one application-owned file in the Host's config location."""

        path = application_config_file(
            application_name,
            filename,
            platform_name=self.platform_name,
            environment=environment,
            home=home,
        )
        return AtomicHostFile(path)

    def host_cache_file(
        self,
        application_name: str,
        filename: str,
        *,
        environment: Mapping[str, str] | None = None,
        home: Path | None = None,
    ) -> AtomicHostFile:
        """Open one application-owned file in the Host's cache location."""

        path = application_cache_file(
            application_name,
            filename,
            platform_name=self.platform_name,
            environment=environment,
            home=home,
        )
        return AtomicHostFile(path)

    def discover(self) -> DiscoveryResult:
        """Return all currently mounted removable Volumes known to the Host."""

        result = self._platform.discover()
        current_keys = {item.connection_key for item in result.observations}
        with self._state_lock:
            missing_keys = set(self._generations) - current_keys
            for key in missing_keys:
                del self._generations[key]
            mounted = tuple(
                self._mounted_volume(observation) for observation in result.observations
            )
            session_references = tuple(self._sessions)

        remaining_references: list[weakref.ReferenceType[FilesystemSession]] = []
        for reference in session_references:
            session = reference()
            if session is None:
                continue
            remaining_references.append(reference)
            if session.connection_key in missing_keys:
                session.invalidate("The Volume disappeared during discovery refresh")
        with self._state_lock:
            self._sessions = remaining_references

        return DiscoveryResult(volumes=mounted, issues=result.issues)

    def inspect(self, mount_point: Path) -> MountedVolume:
        """Inspect a user-selected Mount Point without assigning domain meaning."""

        if not mount_point.is_absolute():
            raise MountInspectionError("A Mount Point must be an absolute Host path")
        observation = self._platform.inspect(mount_point)
        requested = _canonical_path(mount_point)
        observed = _canonical_path(observation.mount_point.path)
        if requested != observed:
            raise NotVolumeRootError(
                f"The selected path is inside the Volume mounted at {observed}"
            )
        with self._state_lock:
            return self._mounted_volume(observation)

    def open_session(
        self,
        mounted_volume: MountedVolume,
        *,
        access: AccessMode = AccessMode.READ_ONLY,
    ) -> FilesystemSession:
        """Open one connection-bound Filesystem Session after reinspection."""

        with self._state_lock:
            retained_generation = self._generations.get(
                mounted_volume.observation.connection_key
            )
        if retained_generation != mounted_volume.connection_generation:
            raise VolumeIdentityChangedError(
                "The selected Connection Generation is no longer current"
            )

        current = self._platform.reinspect(mounted_volume.observation)
        if not _same_connection(mounted_volume.observation, current):
            self._forget_generation(mounted_volume)
            raise VolumeIdentityChangedError(
                "The Mount Point changed before its Filesystem Session opened"
            )
        capabilities = current.volume.capabilities
        if not capabilities.readable:
            raise MountInspectionError("The mounted Volume is not readable")
        if access is AccessMode.READ_WRITE and not capabilities.safe_for_writes:
            reasons = capabilities.unsafe_write_reasons
            detail = reasons[0] if reasons else "the mounted Volume is read-only"
            raise ReadOnlyFilesystemError(detail)

        try:
            session = FilesystemSession(
                mounted_volume=MountedVolume(
                    observation=current,
                    connection_generation=mounted_volume.connection_generation,
                ),
                access=access,
                platform=self._platform,
                on_invalidate=self._forget_connection,
                writer_lock_directory=self._writer_lock_directory,
            )
        except OSError as error:
            self._forget_generation(mounted_volume)
            raise VolumeDisconnectedError(
                "The Volume disappeared before its Filesystem Session opened"
            ) from error
        with self._state_lock:
            retained_generation = self._generations.get(
                mounted_volume.observation.connection_key
            )
            if retained_generation != mounted_volume.connection_generation:
                session.close()
                raise VolumeIdentityChangedError(
                    "The selected Connection Generation expired while opening"
                )
            self._sessions.append(weakref.ref(session))
        return session

    def probe_hardware(
        self,
        mounted_volume: MountedVolume,
        *,
        page_plan: ScsiVpdPagePlan | None = None,
    ) -> HardwareProbeResult:
        """Probe the exact current Physical Device through its native adapter."""

        with self._state_lock:
            retained_generation = self._generations.get(
                mounted_volume.observation.connection_key
            )
        if retained_generation != mounted_volume.connection_generation:
            raise VolumeIdentityChangedError(
                "The selected Connection Generation is no longer current"
            )
        current = self._platform.reinspect(mounted_volume.observation)
        if not _same_connection(mounted_volume.observation, current):
            self._forget_generation(mounted_volume)
            raise VolumeIdentityChangedError(
                "The Mount Point changed before its hardware probe"
            )
        result = self._platform.probe(current, page_plan)
        after = self._platform.reinspect(current)
        if not _same_connection(current, after):
            self._forget_generation(mounted_volume)
            raise VolumeIdentityChangedError(
                "The Mount Point changed during its hardware probe"
            )
        return result

    def eject(self, mounted_volume: MountedVolume) -> EjectResult:
        """Safely eject the exact retained Physical Device through the Host OS."""

        with self._state_lock:
            retained_generation = self._generations.get(
                mounted_volume.observation.connection_key
            )
        if retained_generation != mounted_volume.connection_generation:
            raise VolumeIdentityChangedError(
                "The selected Connection Generation is no longer current"
            )

        current = self._platform.reinspect(mounted_volume.observation)
        if not _same_connection(mounted_volume.observation, current):
            self._forget_generation(mounted_volume)
            raise VolumeIdentityChangedError(
                "The Mount Point changed before safe eject could begin"
            )
        if not current.physical_device.removable:
            raise MountInspectionError(
                "The Host no longer reports this Physical Device as removable"
            )

        try:
            result = self._platform.eject(current)
        except EjectError as error:
            if error.volume_unmounted:
                self._forget_generation(mounted_volume)
            raise
        self._forget_generation(mounted_volume)
        return result

    def require_host_path_off_physical_device(
        self,
        path: HostPath,
        device: MountedVolume,
    ) -> None:
        """Reject a Host path placed on the retained Physical Device."""

        with self._state_lock:
            retained_generation = self._generations.get(
                device.observation.connection_key
            )
        if retained_generation != device.connection_generation:
            raise VolumeIdentityChangedError(
                "The selected Connection Generation is no longer current"
            )
        current = self._platform.reinspect(device.observation)
        if not _same_connection(device.observation, current):
            self._forget_generation(device)
            raise VolumeIdentityChangedError(
                "The Mount Point changed before Host path validation"
            )

        ancestor = _nearest_existing_ancestor(Path(os.fspath(path)))
        protected_id = None
        candidate_id = None
        try:
            protected_id = self._platform.physical_device_id_for_path(
                current.mount_point.path
            )
            candidate_id = self._platform.physical_device_id_for_path(ancestor)
        finally:
            after = self._platform.reinspect(current)
            if not _same_connection(current, after):
                self._forget_generation(device)
                raise VolumeIdentityChangedError(
                    "The Mount Point changed during Host path validation"
                )
        if (
            protected_id is None
            or protected_id != current.physical_device.id
            or candidate_id is None
        ):
            raise MountInspectionError(
                f"Storage could not identify comparable Physical Devices for {ancestor}"
            )
        if candidate_id == current.physical_device.id:
            raise HostPathOnPhysicalDeviceError(
                "The Host path is on the selected Physical Device"
            )

    def close_all_sessions(self) -> None:
        with self._state_lock:
            references = tuple(self._sessions)
            self._sessions = []
        for reference in references:
            session = reference()
            if session is not None:
                session.close()

    def _mounted_volume(self, observation: VolumeObservation) -> MountedVolume:
        generation = self._generations.get(observation.connection_key)
        if generation is None:
            generation = ConnectionGeneration(uuid.uuid4().hex)
            self._generations[observation.connection_key] = generation
        return MountedVolume(
            observation=observation,
            connection_generation=generation,
        )

    def _forget_generation(self, mounted_volume: MountedVolume) -> None:
        self._forget_connection(
            mounted_volume.observation.connection_key,
            mounted_volume.connection_generation,
        )

    def _forget_connection(
        self,
        connection_key: str,
        generation: ConnectionGeneration,
    ) -> None:
        with self._state_lock:
            retained = self._generations.get(connection_key)
            if retained == generation:
                self._generations.pop(connection_key, None)
            references = tuple(self._sessions)
            self._sessions = [
                reference for reference in references if reference() is not None
            ]

        for reference in references:
            session = reference()
            if session is None:
                continue
            session_volume = session.mounted_volume
            if (
                session.connection_key == connection_key
                and session_volume.connection_generation == generation
            ):
                session.invalidate_from_storage(
                    "Another session detected that this connection is no longer safe"
                )


def _same_connection(
    retained: VolumeObservation,
    current: VolumeObservation,
) -> bool:
    return (
        retained.physical_device.id == current.physical_device.id
        and retained.volume.id == current.volume.id
        and retained.mount_instance == current.mount_instance
        and _canonical_path(retained.mount_point.path)
        == _canonical_path(current.mount_point.path)
    )


def _canonical_path(path: Path) -> str:
    return os.path.normcase(os.path.realpath(path))


def _nearest_existing_ancestor(path: Path) -> Path:
    current = path
    while True:
        try:
            current.stat()
            return current.resolve(strict=True)
        except (FileNotFoundError, NotADirectoryError):
            parent = current.parent
            if parent == current:
                raise MountInspectionError(
                    f"No existing Host path contains {path}"
                ) from None
            current = parent
        except OSError as error:
            raise MountInspectionError(
                f"Could not inspect the Host path containing {path}: {error}"
            ) from error
