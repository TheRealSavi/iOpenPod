"""macOS IOKit SCSI tasks for identity probes and exclusive update sessions."""

from __future__ import annotations

import ctypes
import re
import sys
from contextlib import contextmanager, suppress
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_int32,
    c_uint8,
    c_uint32,
    c_uint64,
    c_void_p,
)
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from storage.errors import DeviceBusyError, VolumeIdentityChangedError
from storage.models import (
    HardwareProbeIssue,
    HardwareProbeIssueCode,
    HardwareProbeObservation,
    HardwareProbeResult,
    ScsiVpdPagePlan,
)
from storage.platform.macos_iokit import (
    UTF8_ENCODING as _UTF8,
)
from storage.platform.macos_iokit import (
    MacFrameworks as _MacFrameworks,
)
from storage.platform.macos_iokit import (
    registry_int as _property_int,
)
from storage.platform.macos_iokit import (
    vtable_call as _vtable_call,
)
from storage.scsi import (
    ScsiCommand,
    ScsiCommandError,
    ScsiIdentity,
    ScsiResponse,
    ScsiSessionError,
    checked_response,
    require_scsi_identity,
)
from storage.scsi_vpd import collect_scsi_vpd

if TYPE_CHECKING:
    from collections.abc import Callable, Generator


class _UuidBytes(Structure):
    _fields_ = [("data", c_uint8 * 16)]


_IO_SERVICE_PLANE = b"IOService"
_DATA_FROM_TARGET = 2


class _IoVirtualRange(Structure):
    _fields_ = [("address", c_uint64), ("length", c_uint64)]


class _ScsiSenseData(Structure):
    _fields_ = [("data", c_uint8 * 18)]


def probe_macos_scsi(
    *,
    usb_product_id: int | None,
    transport_serial: str,
    target_bsd_name: str,
    page_plan: ScsiVpdPagePlan | None = None,
) -> HardwareProbeResult:
    """Probe one matching SCSI peripheral without unmounting its Volume."""

    if sys.platform != "darwin":
        return HardwareProbeResult()
    try:
        frameworks = _MacFrameworks()
        observations = _matching_observations(
            frameworks,
            usb_product_id=usb_product_id,
            transport_serial=transport_serial,
            target_bsd_name=target_bsd_name,
            page_plan=page_plan,
        )
    except (OSError, ValueError) as error:
        return _failed(f"macOS could not start its IOKit SCSI probe: {error}")
    if len(observations) == 1:
        return HardwareProbeResult(observations=observations)
    if len(observations) > 1:
        return _failed(
            "More than one device matched the macOS hardware probe; reconnect one "
            "device at a time so observations cannot be assigned to the wrong one."
        )
    return _failed("The selected macOS device did not return SCSI identity data.")


def _matching_observations(
    frameworks: _MacFrameworks,
    *,
    usb_product_id: int | None,
    transport_serial: str,
    target_bsd_name: str,
    page_plan: ScsiVpdPagePlan | None,
) -> tuple[HardwareProbeObservation, ...]:
    observations: list[HardwareProbeObservation] = []
    with _matching_services(
        frameworks, usb_product_id, transport_serial, target_bsd_name
    ) as matches:
        for service, serial in matches:
            with _ScsiSession(frameworks, service) as session:
                if not session.open():
                    continue
                observation = collect_scsi_vpd(
                    session.inquiry, source="iokit", page_plan=page_plan
                )
            observations.append(replace(observation, transport_serial=serial))
    return tuple(observations)


@contextmanager
def _matching_services(
    frameworks: _MacFrameworks,
    product: int | None,
    serial: str,
    bsd_name: str,
) -> Generator[list[tuple[int, str]], None, None]:
    """Keep the matching registry objects alive across a non-forced unmount."""
    matches: list[tuple[int, str]] = []
    iterator = c_uint32()
    match = frameworks.iokit.IOServiceMatching(b"com_apple_driver_iPodSBCNub")
    if not match or frameworks.iokit.IOServiceGetMatchingServices(
        0, match, byref(iterator)
    ):
        yield matches
        return
    try:
        while service := int(frameworks.iokit.IOIteratorNext(iterator.value)):
            keep = False
            try:
                pid, usb_serial = _usb_info(frameworks, service)
                if product is not None and pid != product:
                    continue
                if serial and usb_serial.casefold() != serial.casefold():
                    continue
                names = (
                    _descendant_property_values(frameworks, service, "BSD Name")
                    if bsd_name
                    else ()
                )
                if (
                    bsd_name
                    and bsd_name not in names
                    and not (
                        re.fullmatch(r"disk[0-9]+", bsd_name)
                        and any(
                            re.fullmatch(bsd_name + r"s[0-9]+", name) for name in names
                        )
                    )
                ):
                    continue
                matches.append((service, usb_serial))
                keep = True
            finally:
                if not keep:
                    frameworks.iokit.IOObjectRelease(service)
        yield matches
    finally:
        for service, _ in matches:
            frameworks.iokit.IOObjectRelease(service)
        frameworks.iokit.IOObjectRelease(iterator.value)


def open_macos_scsi(
    *,
    product: int | None,
    serial: str,
    bsd_partition: str,
    expected: ScsiIdentity,
    unmount: Callable[[], None],
) -> _ScsiSession:
    if (
        not serial
        or product is None
        or not re.fullmatch(r"disk[0-9]+s[0-9]+", bsd_partition)
    ):
        raise ScsiSessionError("Could not identify the selected USB partition")
    frameworks = _MacFrameworks()
    with _matching_services(frameworks, product, serial, bsd_partition) as matches:
        if len(matches) != 1:
            raise VolumeIdentityChangedError(
                "Could not match the selected partition to one IOKit SCSI service"
            )
        session = _ScsiSession(frameworks, matches[0][0])
        try:
            if not session.connect():
                raise ScsiSessionError(
                    "The selected IOKit service did not provide a SCSI interface"
                )
            unmount()
            if not session.obtain_exclusive():
                raise DeviceBusyError(
                    "macOS could not obtain exclusive access to the selected device"
                )
            require_scsi_identity(session, expected)
            return session
        except BaseException:
            session.close()
            raise


class _ScsiSession:
    def __init__(self, frameworks: _MacFrameworks, service: int) -> None:
        self._frameworks = frameworks
        self._service = service
        self._plugin: c_void_p | None = None
        self._device: c_void_p | None = None
        self._task: c_void_p | None = None
        self._exclusive = False

    def open(self) -> bool:
        return self.connect() and self.obtain_exclusive()

    def connect(self) -> bool:
        plugin = c_void_p()
        score = c_int32()
        result = self._frameworks.iokit.IOCreatePlugInInterfaceForService(
            self._service,
            self._frameworks.task_client_uuid,
            self._frameworks.plugin_uuid,
            byref(plugin),
            byref(score),
        )
        if result != 0 or not plugin:
            return False
        self._plugin = plugin

        interface_uuid = bytes(
            (
                0x1B,
                0xBC,
                0x41,
                0x32,
                0x08,
                0xA5,
                0x11,
                0xD5,
                0x90,
                0xED,
                0x00,
                0x30,
                0x65,
                0x7D,
                0x05,
                0x2A,
            )
        )
        uuid = _UuidBytes.from_buffer_copy(interface_uuid)
        device = c_void_p()
        if _vtable_call(
            plugin,
            1,
            c_uint32,
            [_UuidBytes, POINTER(c_void_p)],
            uuid,
            byref(device),
        ):
            return False
        self._device = device
        return bool(device)

    def obtain_exclusive(self) -> bool:
        device = self._device
        if not device or _vtable_call(device, 8, c_int32, []):
            return False
        self._exclusive = True
        task = _vtable_call(device, 10, c_void_p, [])
        if not task:
            return False
        self._task = c_void_p(task)
        return True

    def inquiry(self, *, evpd: bool, page: int, alloc_len: int) -> bytes:
        command = ScsiCommand(
            bytes((0x12, int(evpd), page, 0, alloc_len, 0)),
            data_in_length=alloc_len,
            allow_short_read=True,
        )
        try:
            return checked_response(command, self.execute(command)).data
        except ScsiSessionError as error:
            raise OSError(str(error)) from error

    def execute(self, command: ScsiCommand) -> ScsiResponse:
        task = self._task
        if task is None:
            raise ScsiSessionError("The IOKit SCSI task is closed")
        if _vtable_call(task, 24, c_int32, []):
            raise ScsiSessionError("IOKit could not prepare a new SCSI task")
        cdb = (c_uint8 * 16)(*command.cdb)
        if _vtable_call(
            task,
            8,
            c_int32,
            [POINTER(c_uint8), c_uint8],
            cdb,
            c_uint8(len(command.cdb)),
        ):
            raise ScsiSessionError("IOKit rejected the SCSI command descriptor")

        length = command.transfer_length
        data = ctypes.create_string_buffer(command.data_out, max(1, length))
        if length:
            data_range = _IoVirtualRange(ctypes.addressof(data), length)
            direction = 1 if command.data_out else _DATA_FROM_TARGET
            if _vtable_call(
                task,
                11,
                c_int32,
                [POINTER(_IoVirtualRange), c_uint8, c_uint64, c_uint8],
                byref(data_range),
                c_uint8(1),
                c_uint64(length),
                c_uint8(direction),
            ):
                raise ScsiSessionError("IOKit rejected the SCSI transfer buffer")
        if _vtable_call(
            task, 12, c_int32, [c_uint32], c_uint32(command.timeout_seconds * 1000)
        ):
            raise ScsiSessionError("IOKit rejected the SCSI command timeout")
        sense = _ScsiSenseData()
        status = c_uint32()
        realized = c_uint64()
        result = _vtable_call(
            task,
            16,
            c_int32,
            [POINTER(_ScsiSenseData), POINTER(c_uint32), POINTER(c_uint64)],
            byref(sense),
            byref(status),
            byref(realized),
        )
        response = ScsiResponse(
            data.raw[: realized.value] if command.data_in_length else b"",
            realized.value,
            status.value,
            bytes(sense.data) if any(sense.data) else b"",
        )
        if result:
            if (
                result & 0xFFFFFFFF == 0xE00002C0 and not status.value
            ):  # kIOReturnNoDevice
                raise ScsiCommandError(
                    "The device disconnected during the SCSI command"
                )
            raise ScsiCommandError(
                f"IOKit SCSI execution failed (0x{result & 0xFFFFFFFF:08x})", response
            )
        return response

    def close(self) -> None:
        if self._task is not None:
            _safe_vtable_call(self._task, 3, c_uint32, [])
            self._task = None
        if self._exclusive and self._device is not None:
            _safe_vtable_call(self._device, 9, c_int32, [])
            self._exclusive = False
        if self._device is not None:
            _safe_vtable_call(self._device, 3, c_uint32, [])
            self._device = None
        if self._plugin is not None:
            _safe_vtable_call(self._plugin, 3, c_uint32, [])
            self._plugin = None

    def __enter__(self) -> _ScsiSession:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _usb_info(frameworks: _MacFrameworks, service: int) -> tuple[int | None, str]:
    product_id: int | None = None
    serial = ""
    entry = service
    try:
        for _ in range(10):
            parent = c_uint32()
            result = frameworks.iokit.IORegistryEntryGetParentEntry(
                entry,
                _IO_SERVICE_PLANE,
                byref(parent),
            )
            if result != 0:
                break
            if product_id is None:
                product_id = _property_int(frameworks, parent.value, "idProduct")
            if not serial:
                serial = _property_text(
                    frameworks,
                    parent.value,
                    "USB Serial Number",
                )
            if entry != service:
                frameworks.iokit.IOObjectRelease(entry)
            entry = parent.value
            if product_id is not None and serial:
                break
    finally:
        if entry != service:
            frameworks.iokit.IOObjectRelease(entry)
    return product_id, serial


def _descendant_property_values(
    frameworks: _MacFrameworks,
    service: int,
    key: str,
) -> frozenset[str]:
    values: set[str] = set()
    pending: list[tuple[int, bool]] = [(service, False)]
    visited = 0
    while pending and visited < 64:
        entry, owned = pending.pop()
        visited += 1
        try:
            if value := _property_text(frameworks, entry, key):
                values.add(value)
            iterator = c_uint32()
            result = frameworks.iokit.IORegistryEntryGetChildIterator(
                entry,
                _IO_SERVICE_PLANE,
                byref(iterator),
            )
            if result == 0:
                try:
                    while child := int(frameworks.iokit.IOIteratorNext(iterator.value)):
                        pending.append((child, True))
                finally:
                    frameworks.iokit.IOObjectRelease(iterator.value)
        finally:
            if owned:
                frameworks.iokit.IOObjectRelease(entry)
    for entry, owned in pending:
        if owned:
            frameworks.iokit.IOObjectRelease(entry)
    return frozenset(values)


def _property_text(frameworks: _MacFrameworks, entry: int, key: str) -> str:
    cf_key = frameworks.cf.CFStringCreateWithCString(
        None,
        key.encode(),
        _UTF8,
    )
    if not cf_key:
        return ""
    try:
        value = frameworks.iokit.IORegistryEntryCreateCFProperty(
            entry,
            cf_key,
            None,
            0,
        )
        if not value:
            return ""
        try:
            if frameworks.cf.CFGetTypeID(value) != frameworks.cf.CFStringGetTypeID():
                return ""
            buffer = ctypes.create_string_buffer(512)
            if frameworks.cf.CFStringGetCString(value, buffer, len(buffer), _UTF8):
                return buffer.value.decode("utf-8", errors="replace")
            return ""
        finally:
            frameworks.cf.CFRelease(value)
    finally:
        frameworks.cf.CFRelease(cf_key)


def _safe_vtable_call(
    instance: c_void_p,
    slot: int,
    result_type: Any,
    argument_types: list[Any],
) -> None:
    with suppress(OSError, ValueError):
        _vtable_call(instance, slot, result_type, argument_types)


def _failed(detail: str) -> HardwareProbeResult:
    return HardwareProbeResult(
        issues=(HardwareProbeIssue(HardwareProbeIssueCode.FAILED, detail),)
    )
