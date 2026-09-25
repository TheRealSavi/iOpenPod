from __future__ import annotations

import sys
from types import ModuleType

import usb.backend.libusb1

from iopenpod.device import usb_backend


def test_packaged_libusb_library_supplies_pyusb_backend(monkeypatch, tmp_path) -> None:
    packaged_library = tmp_path / "libusb-1.0.dylib"
    packaged_library.touch()
    expected_backend = object()

    def get_backend(*, find_library=None):
        if find_library is None:
            return None
        assert find_library("usb-1.0") == str(packaged_library)
        return expected_backend

    monkeypatch.setattr(usb_backend.sys, "platform", "darwin")
    monkeypatch.setattr(
        usb_backend.ctypes.util,
        "find_library",
        lambda _name: None,
    )
    monkeypatch.setattr(
        usb.backend.libusb1,
        "get_backend",
        get_backend,
    )
    libusb_package = ModuleType("libusb_package")
    monkeypatch.setattr(
        libusb_package,
        "get_library_path",
        lambda: packaged_library,
        raising=False,
    )
    monkeypatch.setitem(sys.modules, "libusb_package", libusb_package)

    assert usb_backend.get_libusb_backend() is expected_backend
