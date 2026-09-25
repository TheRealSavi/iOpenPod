"""macOS IOKit SCSITask transport for generic SCSI VPD observations."""

from __future__ import annotations

import ctypes
import struct
import sys
from contextlib import suppress
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_char_p,
    c_int32,
    c_uint8,
    c_uint32,
    c_uint64,
    c_void_p,
    cast,
)
from dataclasses import replace
from typing import Any

from storage.models import (
    HardwareProbeIssue,
    HardwareProbeIssueCode,
    HardwareProbeObservation,
    HardwareProbeResult,
    ScsiVpdPagePlan,
)
from storage.scsi_vpd import collect_scsi_vpd

_IO_SERVICE_PLANE = b"IOService"
_UTF8 = 0x08000100
_DATA_FROM_TARGET = 2


class _IoVirtualRange(Structure):
    _fields_ = [("address", c_uint64), ("length", c_uint64)]


class _ScsiSenseData(Structure):
    _fields_ = [("data", c_uint8 * 18)]


class _MacFrameworks:
    def __init__(self) -> None:
        self.cf = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        self.iokit = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/IOKit.framework/IOKit"
        )
        self._configure()
        self.task_client_uuid = self._uuid(
            0x7D,
            0x66,
            0x67,
            0x8E,
            0x08,
            0xA2,
            0x11,
            0xD5,
            0xA1,
            0xB8,
            0x00,
            0x30,
            0x65,
            0x7D,
            0x05,
            0x2A,
        )
        self.plugin_uuid = self._uuid(
            0xC2,
            0x44,
            0xE8,
            0x58,
            0x10,
            0x9C,
            0x11,
            0xD4,
            0x91,
            0xD4,
            0x00,
            0x50,
            0xE4,
            0xC6,
            0x42,
            0x6F,
        )

    def _configure(self) -> None:
        self.cf.CFStringGetCString.argtypes = [
            c_void_p,
            c_char_p,
            c_int32,
            c_uint32,
        ]
        self.cf.CFStringGetCString.restype = ctypes.c_bool
        self.cf.CFRelease.argtypes = [c_void_p]
        self.cf.CFGetTypeID.argtypes = [c_void_p]
        self.cf.CFGetTypeID.restype = c_uint64
        self.cf.CFStringGetTypeID.restype = c_uint64
        self.cf.CFNumberGetTypeID.restype = c_uint64
        self.cf.CFNumberGetValue.argtypes = [c_void_p, c_int32, c_void_p]
        self.cf.CFNumberGetValue.restype = ctypes.c_bool
        self.cf.CFUUIDGetConstantUUIDWithBytes.restype = c_void_p
        self.cf.CFUUIDGetConstantUUIDWithBytes.argtypes = [c_void_p] + [c_uint8] * 16
        self.cf.CFStringCreateWithCString.argtypes = [
            c_void_p,
            c_char_p,
            c_uint32,
        ]
        self.cf.CFStringCreateWithCString.restype = c_void_p

        self.iokit.IOServiceMatching.argtypes = [c_char_p]
        self.iokit.IOServiceMatching.restype = c_void_p
        self.iokit.IOServiceGetMatchingServices.argtypes = [
            c_uint32,
            c_void_p,
            POINTER(c_uint32),
        ]
        self.iokit.IOServiceGetMatchingServices.restype = c_int32
        self.iokit.IOIteratorNext.argtypes = [c_uint32]
        self.iokit.IOIteratorNext.restype = c_uint32
        self.iokit.IOObjectRelease.argtypes = [c_uint32]
        self.iokit.IORegistryEntryGetParentEntry.argtypes = [
            c_uint32,
            c_char_p,
            POINTER(c_uint32),
        ]
        self.iokit.IORegistryEntryGetParentEntry.restype = c_int32
        self.iokit.IORegistryEntryGetChildIterator.argtypes = [
            c_uint32,
            c_char_p,
            POINTER(c_uint32),
        ]
        self.iokit.IORegistryEntryGetChildIterator.restype = c_int32
        self.iokit.IORegistryEntryCreateCFProperty.argtypes = [
            c_uint32,
            c_void_p,
            c_void_p,
            c_uint32,
        ]
        self.iokit.IORegistryEntryCreateCFProperty.restype = c_void_p
        self.iokit.IOCreatePlugInInterfaceForService.argtypes = [
            c_uint32,
            c_void_p,
            c_void_p,
            POINTER(c_void_p),
            POINTER(c_int32),
        ]
        self.iokit.IOCreatePlugInInterfaceForService.restype = c_int32

    def _uuid(self, *values: int) -> c_void_p:
        return c_void_p(
            self.cf.CFUUIDGetConstantUUIDWithBytes(
                None,
                *[c_uint8(value) for value in values],
            )
        )


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
    match = frameworks.iokit.IOServiceMatching(b"com_apple_driver_iPodSBCNub")
    if not match:
        return ()
    iterator = c_uint32()
    if frameworks.iokit.IOServiceGetMatchingServices(0, match, byref(iterator)) != 0:
        return ()
    observations: list[HardwareProbeObservation] = []
    try:
        while service := int(frameworks.iokit.IOIteratorNext(iterator.value)):
            try:
                usb_info = _usb_info(frameworks, service)
                if usb_product_id is not None and usb_info[0] != usb_product_id:
                    continue
                if (
                    transport_serial
                    and usb_info[1].casefold() != transport_serial.casefold()
                ):
                    continue
                if target_bsd_name:
                    bsd_names = _descendant_property_values(
                        frameworks,
                        service,
                        "BSD Name",
                    )
                    if not any(
                        name == target_bsd_name
                        or name.startswith(f"{target_bsd_name}s")
                        for name in bsd_names
                    ):
                        continue
                with _ScsiSession(frameworks, service) as session:
                    if not session.open():
                        continue
                    observation = collect_scsi_vpd(
                        session.inquiry,
                        source="iokit",
                        page_plan=page_plan,
                    )
                observations.append(replace(observation, transport_serial=usb_info[1]))
            finally:
                frameworks.iokit.IOObjectRelease(service)
    finally:
        frameworks.iokit.IOObjectRelease(iterator.value)
    return tuple(observations)


class _ScsiSession:
    def __init__(self, frameworks: _MacFrameworks, service: int) -> None:
        self._frameworks = frameworks
        self._service = service
        self._plugin: c_void_p | None = None
        self._device: c_void_p | None = None
        self._task: c_void_p | None = None
        self._exclusive = False

    def open(self) -> bool:
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
        uuid_low, uuid_high = struct.unpack("<QQ", interface_uuid)
        device = c_void_p()
        if _vtable_call(
            plugin,
            1,
            c_uint32,
            [c_uint64, c_uint64, POINTER(c_void_p)],
            c_uint64(uuid_low),
            c_uint64(uuid_high),
            byref(device),
        ):
            return False
        self._device = device
        if _vtable_call(device, 8, c_int32, []):
            return False
        self._exclusive = True
        task = _vtable_call(device, 10, c_void_p, [])
        if not task:
            return False
        self._task = c_void_p(task)
        return True

    def inquiry(self, *, evpd: bool, page: int, alloc_len: int) -> bytes:
        if self._task is None:
            raise OSError("The IOKit SCSI task is not open")
        task = self._task
        _vtable_call(task, 24, c_int32, [])
        command = (c_uint8 * 16)(
            0x12,
            0x01 if evpd else 0,
            page & 0xFF,
            0,
            alloc_len & 0xFF,
            0,
            *([0] * 10),
        )
        if _vtable_call(
            task,
            8,
            c_int32,
            [POINTER(c_uint8), c_uint8],
            cast(command, POINTER(c_uint8)),
            c_uint8(6),
        ):
            raise OSError(f"IOKit rejected the SCSI command for page 0x{page:02X}")

        data = ctypes.create_string_buffer(alloc_len)
        data_range = _IoVirtualRange(ctypes.addressof(data), alloc_len)
        if _vtable_call(
            task,
            11,
            c_int32,
            [POINTER(_IoVirtualRange), c_uint8, c_uint64, c_uint8],
            byref(data_range),
            c_uint8(1),
            c_uint64(alloc_len),
            c_uint8(_DATA_FROM_TARGET),
        ):
            raise OSError(f"IOKit rejected the buffer for page 0x{page:02X}")
        _vtable_call(task, 12, c_int32, [c_uint32], c_uint32(10_000))
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
        if result or status.value or not realized.value:
            raise OSError(status.value or result, f"SCSI page 0x{page:02X} failed")
        return bytes(data.raw[: realized.value])

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


def _property_int(frameworks: _MacFrameworks, entry: int, key: str) -> int | None:
    cf_key = frameworks.cf.CFStringCreateWithCString(
        None,
        key.encode(),
        _UTF8,
    )
    if not cf_key:
        return None
    try:
        value = frameworks.iokit.IORegistryEntryCreateCFProperty(
            entry,
            cf_key,
            None,
            0,
        )
        if not value:
            return None
        try:
            if frameworks.cf.CFGetTypeID(value) != frameworks.cf.CFNumberGetTypeID():
                return None
            number = c_int32()
            if not frameworks.cf.CFNumberGetValue(value, 3, byref(number)):
                return None
            return int(number.value)
        finally:
            frameworks.cf.CFRelease(value)
    finally:
        frameworks.cf.CFRelease(cf_key)


def _vtable_call(
    instance: c_void_p,
    slot: int,
    result_type: Any,
    argument_types: list[Any],
    *arguments: Any,
) -> Any:
    table = cast(instance, POINTER(c_void_p))[0]
    function_pointer = cast(table, POINTER(c_void_p))[slot]
    function = ctypes.CFUNCTYPE(result_type, c_void_p, *argument_types)(
        function_pointer
    )
    return function(instance, *arguments)


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
