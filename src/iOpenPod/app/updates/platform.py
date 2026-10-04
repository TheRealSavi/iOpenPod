"""Platform infrastructure selects only an evidenced installation channel."""

import logging
import os
import sys
from configparser import ConfigParser
from importlib import import_module
from pathlib import Path

from .backend import InstallChannel, UpdateProvider

logger = logging.getLogger(__name__)
_runtime_error = ""
_runtime_initialized = False
_FLATPAK_INFO = Path("/.flatpak-info")


def _unpackaged_channel() -> InstallChannel:
    if getattr(sys, "frozen", False):
        return InstallChannel.FROZEN
    from .python_installation import running_python_installation

    return (
        InstallChannel.PYPI if running_python_installation() else InstallChannel.SOURCE
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
        return _unpackaged_channel()
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


def detect_install_channel() -> InstallChannel:
    """Inspect installation evidence without creating an updater or requiring a window."""
    if sys.platform == "linux":
        return _linux_channel()
    if sys.platform == "darwin":
        return _macos_channel()
    if sys.platform == "win32":
        initialize_update_runtime()
        if _runtime_error:
            raise RuntimeError(_runtime_error)
        from .windows import detect_channel

        channel = detect_channel()
        if channel is not InstallChannel.UNPACKAGED:
            return channel
    return _unpackaged_channel()


def create_update_provider(window_id: int) -> UpdateProvider:
    if sys.platform != "win32":
        channel = detect_install_channel()
        return _standalone_provider(channel)
    if _runtime_error:
        raise RuntimeError(_runtime_error)
    from .windows import create_store_provider

    provider = create_store_provider(window_id)
    if provider.channel is InstallChannel.UNPACKAGED:
        return _standalone_provider(_unpackaged_channel())
    return provider


def _standalone_provider(channel: InstallChannel) -> UpdateProvider:
    if channel is InstallChannel.PYPI:
        from .pypi import PyPIBackend
        from .python_helper import PythonInstaller
        from .python_installation import running_python_installation

        python_installation = running_python_installation()
        if python_installation is None:
            raise ValueError("The Python installation changed during detection")
        python_installer: PythonInstaller | None = None
        restriction = ""
        try:
            python_installer = PythonInstaller(python_installation)
        except (OSError, ValueError) as error:
            restriction = str(error)
        return UpdateProvider(
            channel,
            PyPIBackend(python_installation, python_installer, restriction=restriction),
            "PyPI",
            staged_download=True,
        )
    if channel is not InstallChannel.FROZEN:
        return UpdateProvider(channel)
    from .github import GitHubBackend, ReleaseInstaller
    from .installation import running_installation

    installation = running_installation()
    if installation is None:
        return UpdateProvider(channel)
    installer: ReleaseInstaller | None = None
    if installation.public_keys:
        if sys.platform == "darwin":
            from .sparkle import SparkleInstaller

            installer = SparkleInstaller(installation)
        else:
            from .portable import PortableInstaller

            try:
                installer = PortableInstaller(installation)
            except (ValueError, OSError):
                logger.info("This installation requires a manual update", exc_info=True)
    return UpdateProvider(
        channel,
        GitHubBackend(installation, installer),
        "GitHub",
        staged_download=sys.platform != "darwin",
        native_restart=sys.platform == "darwin",
    )
