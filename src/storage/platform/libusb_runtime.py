"""Pinned bundled libusb ABI, loaded without discovering or opening devices."""

from __future__ import annotations

import ctypes
from importlib import import_module
from typing import Any

from storage.usb_control import UsbControlError


def load_library() -> Any:
    """Require the wheel's library instead of resolving a Host installation."""
    try:
        package = import_module("libusb_package")
        path = package.get_library_path()
        if path is None:
            raise FileNotFoundError("libusb package resource")
        library = ctypes.CDLL(str(path))
    except (ImportError, OSError) as error:
        raise UsbControlError(
            "The bundled libusb library is missing; reinstall iOpenPod"
        ) from error
    pointer = ctypes.c_void_p
    signatures: dict[str, tuple[list[Any], Any]] = {
        "libusb_get_version": ([], pointer),
        "libusb_init": ([ctypes.POINTER(pointer)], ctypes.c_int),
        "libusb_exit": ([pointer], None),
        "libusb_wrap_sys_device": (
            [pointer, ctypes.c_ssize_t, ctypes.POINTER(pointer)],
            ctypes.c_int,
        ),
        "libusb_close": ([pointer], None),
        "libusb_get_device_list": (
            [pointer, ctypes.POINTER(ctypes.POINTER(pointer))],
            ctypes.c_ssize_t,
        ),
        "libusb_free_device_list": ([ctypes.POINTER(pointer), ctypes.c_int], None),
        "libusb_ref_device": ([pointer], pointer),
        "libusb_unref_device": ([pointer], None),
        "libusb_get_device_descriptor": ([pointer, pointer], ctypes.c_int),
        "libusb_get_bus_number": ([pointer], ctypes.c_uint8),
        "libusb_get_device_address": ([pointer], ctypes.c_uint8),
        "libusb_open": ([pointer, ctypes.POINTER(pointer)], ctypes.c_int),
        "libusb_get_configuration": (
            [pointer, ctypes.POINTER(ctypes.c_int)],
            ctypes.c_int,
        ),
        "libusb_set_auto_detach_kernel_driver": ([pointer, ctypes.c_int], ctypes.c_int),
        "libusb_set_configuration": ([pointer, ctypes.c_int], ctypes.c_int),
        "libusb_kernel_driver_active": ([pointer, ctypes.c_int], ctypes.c_int),
        "libusb_detach_kernel_driver": ([pointer, ctypes.c_int], ctypes.c_int),
        "libusb_attach_kernel_driver": ([pointer, ctypes.c_int], ctypes.c_int),
        "libusb_claim_interface": ([pointer, ctypes.c_int], ctypes.c_int),
        "libusb_release_interface": ([pointer, ctypes.c_int], ctypes.c_int),
        "libusb_control_transfer": (
            [
                pointer,
                ctypes.c_uint8,
                ctypes.c_uint8,
                ctypes.c_uint16,
                ctypes.c_uint16,
                pointer,
                ctypes.c_uint16,
                ctypes.c_uint,
            ],
            ctypes.c_int,
        ),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result
    return library


def check_runtime() -> None:
    """Exercise the included library without enumerating or opening devices."""
    library = load_library()
    # Initializing a libusb context also starts native device discovery.
    if not library.libusb_get_version():
        raise UsbControlError("The bundled libusb runtime could not report its version")
