"""Shared CoreFoundation and IOKit bindings for native Storage adapters."""

from __future__ import annotations

import ctypes
from ctypes import (
    POINTER,
    byref,
    c_char_p,
    c_int32,
    c_uint8,
    c_uint32,
    c_uint64,
    c_void_p,
    cast,
)
from typing import Any

UTF8_ENCODING = 0x08000100


class MacFrameworks:
    def __init__(self) -> None:
        self.cf = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        self.iokit = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/IOKit.framework/IOKit"
        )
        self._configure()
        self.task_client_uuid = self.uuid_from_bytes(
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
        self.plugin_uuid = self.uuid_from_bytes(
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

    def uuid_from_bytes(self, *values: int) -> c_void_p:
        return c_void_p(
            self.cf.CFUUIDGetConstantUUIDWithBytes(
                None,
                *[c_uint8(value) for value in values],
            )
        )


def registry_int(frameworks: MacFrameworks, entry: int, key: str) -> int | None:
    cf_key = frameworks.cf.CFStringCreateWithCString(
        None,
        key.encode(),
        UTF8_ENCODING,
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


def vtable_call(
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
