"""Bounded USB control transfers on retained handles with a Host writer lease."""

from __future__ import annotations

import struct
import threading
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

from storage.errors import StorageError
from storage.models import ConnectionGeneration

if TYPE_CHECKING:
    from types import TracebackType

    from storage._writer_lock import VolumeWriterLease


class UsbControlError(StorageError):
    """A control transfer failed; its completion may be uncertain."""


class UsbControlAuthorizationError(UsbControlError):
    """Device access was denied. Another OS prompt requires a new user action."""


class UsbControlDriverError(UsbControlError):
    """No installed driver could open the selected USB control interface."""


def _validate_endpoint_identity(
    interface_class: object, interface_path: object, instance_id: object
) -> None:
    """Validate values from runtime callers independently of their annotations."""
    if not isinstance(interface_class, uuid.UUID):
        raise ValueError("USB interface class must be a UUID")
    if any(
        not isinstance(value, str) or not 0 < len(value) <= 32768 or "\0" in value
        for value in (interface_path, instance_id)
    ):
        raise ValueError("USB interface identities must be bounded nonempty text")


def _validate_data_out(value: object) -> None:
    if not isinstance(value, bytes) or len(value) > 65535:
        raise ValueError("USB output must be bounded immutable bytes")


@dataclass(frozen=True)
class UsbControlEndpoint:
    """Opaque Host interface identity; protocol identity is checked by its caller."""

    interface_class: uuid.UUID
    interface_path: str
    instance_id: str
    vendor_id: int
    product_id: int

    def __post_init__(self) -> None:
        _validate_endpoint_identity(
            self.interface_class, self.interface_path, self.instance_id
        )
        if any(
            type(value) is not int or not 0 <= value <= 65535
            for value in (self.vendor_id, self.product_id)
        ):
            raise ValueError("USB identifiers must fit unsigned 16 bits")


@dataclass(frozen=True)
class UsbControlRequest:
    request_type: int
    request: int
    value: int = 0
    index: int = 0
    data_out: bytes = b""
    data_in_length: int = 0
    allow_short_read: bool = False
    timeout_ms: int = 2000

    def __post_init__(self) -> None:
        for value, maximum in (
            (self.request_type, 255),
            (self.request, 255),
            (self.value, 65535),
            (self.index, 65535),
            (self.data_in_length, 65535),
        ):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError("USB setup field is outside its unsigned width")
        _validate_data_out(self.data_out)
        if (self.is_read and self.data_out) or (
            not self.is_read and (self.data_in_length or self.allow_short_read)
        ):
            raise ValueError("USB data direction disagrees with the setup packet")
        if type(self.timeout_ms) is not int or not 1 <= self.timeout_ms <= 60000:
            raise ValueError("USB timeout must be between 1 and 60000 milliseconds")

    @property
    def is_read(self) -> bool:
        return bool(self.request_type & 0x80)

    @property
    def transfer_length(self) -> int:
        return self.data_in_length if self.is_read else len(self.data_out)

    def setup_packet(self) -> bytes:
        return struct.pack(
            "<BBHHH",
            self.request_type,
            self.request,
            self.value,
            self.index,
            self.transfer_length,
        )


@dataclass(frozen=True)
class UsbControlResponse:
    data: bytes
    transferred: int


class UsbControlChannel(Protocol):
    def execute(self, request: UsbControlRequest) -> UsbControlResponse: ...
    def close(self) -> None: ...


@runtime_checkable
class UsbControlProvider(Protocol):
    def discover_usb_control(
        self,
        interface_class: uuid.UUID,
        vendor_id: int,
        product_id: int,
    ) -> tuple[UsbControlEndpoint, ...]: ...

    def open_usb_control_channel(
        self,
        endpoint: UsbControlEndpoint,
    ) -> UsbControlChannel: ...


class UsbControlSession:
    """No reconnect, retry, reset, eject, or protocol cleanup on failure/close."""

    def __init__(
        self,
        endpoint: UsbControlEndpoint,
        channel: UsbControlChannel,
        lease: VolumeWriterLease,
    ) -> None:
        self._endpoint = endpoint
        self._generation = ConnectionGeneration(uuid.uuid4().hex)
        self._channel = channel
        self._lease = lease
        self._active = True
        self._lock = threading.RLock()

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def endpoint(self) -> UsbControlEndpoint:
        return self._endpoint

    @property
    def connection_generation(self) -> ConnectionGeneration:
        return self._generation

    def execute(self, request: UsbControlRequest) -> UsbControlResponse:
        with self._lock:
            if not self._active:
                raise UsbControlError("The USB Control Session is closed")
            try:
                response = self._channel.execute(request)
                valid = (
                    0 <= response.transferred <= request.transfer_length
                    if request.allow_short_read
                    else response.transferred == request.transfer_length
                )
                if not valid or len(response.data) != (
                    response.transferred if request.is_read else 0
                ):
                    raise UsbControlError("Incomplete or invalid USB control transfer")
                return response
            except BaseException as error:
                try:
                    self.close()
                except Exception as cleanup_error:
                    error.add_note(f"USB handle cleanup failed: {cleanup_error}")
                raise

    def close(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            try:
                self._channel.close()
            finally:
                self._lease.__exit__(None, None, None)

    def __enter__(self) -> Self:
        if not self._active:
            raise UsbControlError("The USB Control Session is closed")
        return self

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()
