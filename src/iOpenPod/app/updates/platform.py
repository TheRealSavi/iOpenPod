"""Platform infrastructure selects only an evidenced installation channel."""

import logging
import os
import sys
from configparser import ConfigParser
from dataclasses import replace
from importlib import import_module
from pathlib import Path

from .backend import InstallChannel, UpdateProvider

logger = logging.getLogger(__name__)
_runtime_error = ""
_runtime_initialized = False
_FLATPAK_INFO = Path("/.flatpak-info")


def _unpackaged_channel() -> InstallChannel:
    return (
        InstallChannel.FROZEN
        if getattr(sys, "frozen", False)
        else InstallChannel.SOURCE
    )


def _linux_channel() -> InstallChannel:
    metadata = ConfigParser(interpolation=None)
    metadata.read(_FLATPAK_INFO, encoding="utf-8")
    if (
        metadata.get("Application", "name", fallback="")
        == "io.github.therealsavi.iOpenPod"
    ):
        return InstallChannel.FLATPAK
    if os.environ.get("SNAP_NAME") == "iopenpod" and os.environ.get("SNAP"):
        return InstallChannel.SNAP
    return _unpackaged_channel()


def _macos_channel() -> InstallChannel:
    if not getattr(sys, "frozen", False):
        return InstallChannel.SOURCE
    foundation = import_module("Foundation")
    receipt_url = foundation.NSBundle.mainBundle().appStoreReceiptURL()
    if receipt_url is not None:
        receipt = Path(str(receipt_url.path()))
        if receipt.is_file():
            if receipt.name == "sandboxReceipt":
                return InstallChannel.APP_STORE_TEST
            return InstallChannel.MAC_APP_STORE
    return InstallChannel.FROZEN


def initialize_update_runtime() -> None:
    """Establish the UI STA before Qt or native projections initialize COM."""
    global _runtime_error, _runtime_initialized
    if sys.platform == "win32" and not _runtime_initialized:
        try:
            runtime = import_module("winrt.runtime")
            runtime.init_apartment(runtime.ApartmentType.SINGLE_THREADED)
            _runtime_initialized = True
            _runtime_error = ""
        except Exception as error:
            _runtime_error = str(error)
            logger.exception("Could not initialize the update UI apartment")


def close_update_runtime() -> None:
    global _runtime_initialized
    if _runtime_initialized:
        import_module("winrt.runtime").uninit_apartment()
        _runtime_initialized = False


def create_update_provider(window_id: int) -> UpdateProvider:
    if sys.platform == "linux":
        return UpdateProvider(_linux_channel())
    if sys.platform == "darwin":
        return UpdateProvider(_macos_channel())
    if sys.platform != "win32":
        return UpdateProvider(_unpackaged_channel())
    if _runtime_error:
        raise RuntimeError(_runtime_error)
    from .windows import create_store_provider

    provider = create_store_provider(window_id)
    if provider.channel is InstallChannel.UNPACKAGED:
        return replace(provider, channel=_unpackaged_channel())
    return provider
