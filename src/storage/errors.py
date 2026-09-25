"""Typed failures raised by the Storage module."""

from __future__ import annotations


class StorageError(Exception):
    """Base class for failures crossing the Storage interface."""


class InvalidDevicePathError(StorageError, ValueError):
    """A Device Path was absolute, traversing, malformed, or unsupported."""


class InvalidHostPathError(StorageError, ValueError):
    """An explicitly supplied Host path was not absolute or otherwise usable."""


class HostPathOnPhysicalDeviceError(StorageError):
    """A Host destination resolves to the protected Physical Device."""


class DevicePathNotFoundError(StorageError, FileNotFoundError):
    """A required Device Path does not exist in the authorized Volume."""


class MountInspectionError(StorageError):
    """Storage could not establish a trustworthy mounted-volume description."""


class NotVolumeRootError(MountInspectionError):
    """The selected path is inside a Volume rather than its Mount Point."""


class FilesystemSessionError(StorageError):
    """Base class for a Filesystem Session lifecycle failure."""


class SessionClosedError(FilesystemSessionError):
    """A caller attempted to reuse an intentionally closed session."""


class SessionInvalidatedError(FilesystemSessionError):
    """A caller attempted to reuse a permanently invalidated session."""


class VolumeDisconnectedError(SessionInvalidatedError):
    """The session's Volume is no longer mounted."""


class VolumeIdentityChangedError(SessionInvalidatedError):
    """The Mount Point now refers to a different device, Volume, or mount."""


class ReadOnlyFilesystemError(StorageError):
    """A mutating operation was requested without writable authorization."""


class UnsafeFilesystemPathError(StorageError):
    """A path traversed a symbolic link, reparse point, or unsafe file kind."""


class StorageCapacityError(StorageError):
    """A write cannot fit while retaining the requested free-space reserve."""


class FileSizeLimitError(StorageError):
    """A file exceeds the mounted filesystem's known per-file limit."""


class FilePreconditionError(StorageError):
    """A destination changed or did not have the expected prior state."""


class ConcurrentModificationError(StorageError):
    """A file changed while Storage was reading or verifying it."""


class DeviceBusyError(StorageError):
    """Another writer owns the Host-side lease for the same Volume."""


class StorageOperationError(StorageError):
    """An operating-system filesystem operation failed safely."""


class UnsupportedStorageOperationError(StorageError):
    """The current Host adapter cannot safely perform an operation."""


class EjectError(StorageOperationError):
    """The Host did not confirm that a Physical Device was safely ejected.

    ``volume_unmounted`` distinguishes a retryable refusal from the important
    partial state where filesystem access has ended but native physical removal
    or power-off was not confirmed.
    """

    def __init__(self, message: str, *, volume_unmounted: bool = False) -> None:
        super().__init__(message)
        self.volume_unmounted = volume_unmounted


class RecoverableWriteError(StorageError):
    """Replacement failed; retained journal and original bytes allow reconciliation."""

    def __init__(
        self, message: str, recovery_path: str, publication_started: bool
    ) -> None:
        super().__init__(message)
        self.recovery_path = recovery_path
        self.publication_started = publication_started
