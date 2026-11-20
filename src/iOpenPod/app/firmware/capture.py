"""Capture optional installed-build metadata through an identity-bound session."""

from dataclasses import dataclass
from enum import StrEnum

from iOpenPod.app.firmware.registry import (
    MAX_REGISTRY_BYTES,
    FirmwareRegistry,
    read_registry,
)
from storage import (
    DevicePath,
    FilesystemSession,
    MountInspectionError,
    SessionClosedError,
    SessionInvalidatedError,
    StorageError,
)

REGISTRY_PATH = DevicePath("iPod_Control/iOpenPod/Firmware/installed.json")


class RegistryStatus(StrEnum):
    NOT_INSPECTED = "not_inspected"
    MISSING = "missing"
    AVAILABLE = "available"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class RegistryObservation:
    status: RegistryStatus = RegistryStatus.NOT_INSPECTED
    registry: FirmwareRegistry | None = None


def capture_registry(session: FilesystemSession) -> RegistryObservation:
    """Missing/bad optional records do not break Library loading; disconnects do."""
    try:
        if not session.exists(REGISTRY_PATH):
            return RegistryObservation(RegistryStatus.MISSING)
        snapshot = session.read_snapshot(REGISTRY_PATH, max_bytes=MAX_REGISTRY_BYTES)
        registry = read_registry(snapshot.data)
        if session.fingerprint(REGISTRY_PATH) != snapshot.fingerprint:
            return RegistryObservation(RegistryStatus.UNREADABLE)
        return RegistryObservation(RegistryStatus.AVAILABLE, registry)
    except (MountInspectionError, SessionClosedError, SessionInvalidatedError):
        raise
    except (StorageError, ValueError):
        return RegistryObservation(RegistryStatus.UNREADABLE)
