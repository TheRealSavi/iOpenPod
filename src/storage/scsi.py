"""Exclusive, connection-bound SCSI access without device-specific protocols."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

from storage.errors import StorageError

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

    from storage._writer_lock import VolumeWriterLease
    from storage.models import ConnectionGeneration, MountedVolume, VolumeObservation

MAX_TRANSFER_BYTES = 1024 * 1024


def _require_bytes(value: object, message: str) -> bytes:
    """Validate runtime input even when a caller bypasses type checking."""
    if not isinstance(value, bytes):
        raise ValueError(message)
    return value


class ScsiSessionError(StorageError):
    """A SCSI Session is closed, invalidated, or could not be established."""


class ScsiCommandError(ScsiSessionError):
    """Command completion is uncertain; callers must not automatically retry."""

    def __init__(self, message: str, response: ScsiResponse | None = None) -> None:
        super().__init__(message)
        self.response = response


@dataclass(frozen=True)
class ScsiIdentity:
    """Exact standard INQUIRY vendor/product and VPD unit serial."""

    vendor: str
    product: str
    serial: str

    def __post_init__(self) -> None:
        for value, maximum in (
            (self.vendor, 8),
            (self.product, 16),
            (self.serial, 251),
        ):
            if (
                not value
                or value != value.strip()
                or len(value) > maximum
                or any(ord(char) < 32 or ord(char) > 126 for char in value)
            ):
                raise ValueError("SCSI identity fields must contain bounded ASCII text")


@dataclass(frozen=True)
class ScsiCommand:
    """One bounded command, with at most one data direction and no retry policy."""

    cdb: bytes
    data_out: bytes = b""
    data_in_length: int = 0
    allow_short_read: bool = False
    timeout_seconds: int = 10

    def __post_init__(self) -> None:
        cdb_error = "SCSI CDB must be immutable bytes of length 6, 10, 12 or 16"
        if len(_require_bytes(self.cdb, cdb_error)) not in (6, 10, 12, 16):
            raise ValueError(cdb_error)
        _require_bytes(self.data_out, "SCSI output data must be immutable bytes")
        if type(self.data_in_length) is not int or not (
            0 <= self.data_in_length <= MAX_TRANSFER_BYTES
        ):
            raise ValueError("SCSI input length exceeds the bounded transfer size")
        if len(self.data_out) > MAX_TRANSFER_BYTES:
            raise ValueError("SCSI output exceeds the bounded transfer size")
        if self.data_out and self.data_in_length:
            raise ValueError("Bidirectional SCSI commands are not supported")
        if self.allow_short_read and not self.data_in_length:
            raise ValueError("Only data-in commands can permit a short response")
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 60:
            raise ValueError("SCSI timeout must be between 1 and 60 seconds")

    @property
    def transfer_length(self) -> int:
        return len(self.data_out) or self.data_in_length


@dataclass(frozen=True)
class ScsiResponse:
    data: bytes
    transferred: int
    status: int = 0
    sense: bytes = b""


class ScsiChannel(Protocol):
    """Native handle held under an exclusive volume lock until close."""

    def execute(self, command: ScsiCommand) -> ScsiResponse: ...

    def close(self) -> None: ...


@runtime_checkable
class ScsiChannelProvider(Protocol):
    def open_scsi_channel(
        self, observation: VolumeObservation, expected_identity: ScsiIdentity
    ) -> ScsiChannel: ...


def checked_response(command: ScsiCommand, response: ScsiResponse) -> ScsiResponse:
    """Treat failed status and ambiguous lengths as terminal, including writes."""

    if response.status:
        raise ScsiCommandError(
            f"SCSI command returned status 0x{response.status:02x}", response
        )
    valid_length = (
        0 <= response.transferred <= command.transfer_length
        if command.allow_short_read
        else response.transferred == command.transfer_length
    )
    expected_data_length = response.transferred if command.data_in_length else 0
    if not valid_length or len(response.data) != expected_data_length:
        raise ScsiCommandError(
            "SCSI transfer length was incomplete or invalid", response
        )
    return response


class ScsiSession:
    """Serialize commands; a failed command permanently invalidates the session.

    Construction is owned by Storage. Use as a context manager or explicitly
    close it; closing only releases the native handle and Host writer lease.
    """

    def __init__(
        self,
        mounted_volume: MountedVolume,
        channel: ScsiChannel,
        lease: VolumeWriterLease,
        *,
        check_connection: Callable[[], None],
        on_invalidate: Callable[[str, ConnectionGeneration], None],
        on_close: Callable[[], None],
    ) -> None:
        self._mounted_volume = mounted_volume
        self._channel = channel
        self._lease = lease
        self._check_connection = check_connection
        self._on_invalidate = on_invalidate
        self._on_close = on_close
        self._lock = threading.RLock()
        self._active = True
        self._reason = "The SCSI Session is closed"

    @property
    def mounted_volume(self) -> MountedVolume:
        return self._mounted_volume

    @property
    def connection_key(self) -> str:
        return self._mounted_volume.observation.connection_key

    @property
    def is_active(self) -> bool:
        return self._active

    def execute(self, command: ScsiCommand) -> ScsiResponse:
        with self._lock:
            if not self._active:
                raise ScsiSessionError(self._reason)
            try:
                self._check_connection()
                return checked_response(command, self._channel.execute(command))
            except BaseException as error:
                try:
                    self.invalidate(
                        "A SCSI command failed; completion may be uncertain"
                    )
                except Exception as cleanup_error:
                    error.add_note(f"SCSI cleanup also failed: {cleanup_error}")
                raise

    def invalidate(self, reason: str) -> None:
        with self._lock:
            self._reason = reason
            try:
                self._on_invalidate(
                    self.connection_key, self._mounted_volume.connection_generation
                )
            finally:
                self.close()

    def invalidate_from_storage(self, reason: str) -> None:
        with self._lock:
            self._reason = reason
            self.close()

    def close(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            try:
                self._channel.close()
            finally:
                try:
                    self._lease.__exit__(None, None, None)
                finally:
                    self._on_close()

    def __enter__(self) -> Self:
        if not self._active:
            raise ScsiSessionError(self._reason)
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.close()
        except Exception as error:
            if exception is None:
                raise
            exception.add_note(f"SCSI cleanup also failed: {error}")
