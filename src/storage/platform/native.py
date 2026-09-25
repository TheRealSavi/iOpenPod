"""Select the native Host adapter without leaking platform checks to callers."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from storage.errors import UnsupportedStorageOperationError

if TYPE_CHECKING:
    from storage.platform.base import PlatformAdapter


def native_platform_adapter() -> PlatformAdapter:
    if sys.platform == "win32":
        from storage.platform.windows import WindowsPlatformAdapter

        return WindowsPlatformAdapter()
    if sys.platform == "darwin":
        from storage.platform.macos import MacOSPlatformAdapter

        return MacOSPlatformAdapter()
    if sys.platform.startswith("linux"):
        from storage.platform.linux import LinuxPlatformAdapter

        return LinuxPlatformAdapter()
    raise UnsupportedStorageOperationError(
        f"Storage does not support the Host platform {sys.platform!r}"
    )
