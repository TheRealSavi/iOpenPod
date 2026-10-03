"""Configure native playback and caches for the read-only application bundle."""

import ctypes
import os
import sys
from functools import cache
from pathlib import Path


def configure_frozen_runtime() -> None:
    """Prepare the frozen runtime without changing the user's PATH."""
    if not getattr(sys, "frozen", False):
        return
    # Installed bundles may be read-only. Keep compiled analysis code in Numba's
    # per-user cache even when a developer's unpacked bundle happens to be writable.
    os.environ.setdefault("NUMBA_CACHE_LOCATOR_CLASSES", "UserWideCacheLocator")
    if sys.platform == "win32":
        bundle_root = getattr(sys, "_MEIPASS", None)
        if not isinstance(bundle_root, str):
            raise RuntimeError("The frozen runtime directory is unavailable")
        _load_windows_playback_libraries(Path(bundle_root))


@cache
def _load_windows_playback_libraries(bundle_root: Path) -> tuple[ctypes.CDLL, ...]:
    """Retain Qt's bundled FFmpeg libraries for the lifetime of the process."""
    qt_directory = bundle_root.resolve() / "PySide6"
    libraries: list[Path] = []
    for name in ("avutil", "swresample", "swscale", "avcodec", "avformat"):
        matches = tuple(qt_directory.glob(f"{name}-*.dll"))
        if len(matches) != 1:
            raise RuntimeError(
                f"Expected one bundled Qt playback library: {name}-*.dll"
            )
        libraries.append(matches[0])
    # MSIX ignores PATH when resolving a plugin's dependencies. PySide6's PATH
    # setup therefore works in a portable build but can leave its FFmpeg plugin
    # unloadable in the Store app. Preload only our bundled DLLs, by absolute path,
    # before the first QMediaPlayer chooses a backend. ctypes' default Windows
    # loading flags also search the DLL's own directory for its dependencies.
    return tuple(ctypes.WinDLL(str(library)) for library in libraries)


def configure_bundled_tools() -> None:
    """Compatibility name for launchers installed before the runtime rename.

    Older editable installs imported this symbol while the application was
    renamed from its bundled-media-tools setup. Keep that launcher usable while
    the environment refreshes; the current runtime contract is the frozen-cache
    configuration above and does not add anything to ``PATH``.
    """
    configure_frozen_runtime()
