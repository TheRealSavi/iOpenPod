"""
PyUSB backend resolution helpers.

PyUSB is pure Python, but on Windows it still needs a native
``libusb-1.0.dll``.  The app vendors the official 64-bit libusb DLL under
``vendor/libusb/windows/x64`` and falls back to system/package locations.
"""

from __future__ import annotations

import ctypes.util
import logging
import os
import platform
import sys
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


def get_libusb_backend():
    """Return a PyUSB libusb1 backend, or ``None`` if no backend can load."""
    try:
        import usb.backend.libusb1
    except ImportError:
        return None

    backend = usb.backend.libusb1.get_backend()
    if backend is not None:
        return backend

    for candidate in _candidate_libusb_paths():
        backend = _backend_from_path(usb.backend.libusb1.get_backend, candidate)
        if backend is not None:
            logger.debug("PyUSB libusb backend loaded from %s", candidate)
            return backend

    return None


def backend_diagnostic() -> str:
    """Return a short human-readable backend diagnostic string."""
    try:
        import usb.backend.libusb1
    except ImportError:
        return "pyusb is not installed"

    if usb.backend.libusb1.get_backend() is not None:
        return "system libusb backend available"

    candidates = list(_candidate_libusb_paths())
    if not candidates:
        return "no libusb-1.0 library candidates found"

    existing = [str(path) for path in candidates if path.exists()]
    if existing:
        return "libusb candidates exist but failed to load: " + ", ".join(existing)
    return "libusb candidates missing: " + ", ".join(str(path) for path in candidates)


def _backend_from_path(get_backend: Callable, path: Path):
    if not path.exists():
        return None

    def _find_library(_name: str) -> str:
        return str(path)

    try:
        return get_backend(find_library=_find_library)
    except Exception as exc:
        logger.debug("PyUSB backend load failed from %s: %s", path, exc)
        return None


def _candidate_libusb_paths() -> list[Path]:
    candidates: list[Path] = []

    for env_name in ("IOPENPOD_LIBUSB_DLL", "PYUSB_LIBUSB_DLL"):
        env_path = os.environ.get(env_name, "").strip()
        if env_path:
            candidates.append(Path(env_path))

    # Optional helper from the ``libusb-package`` wheel when available.
    try:
        import libusb_package  # type: ignore

        path = libusb_package.find_library()
        if path:
            candidates.append(Path(path))
    except Exception:
        pass

    system_path = ctypes.util.find_library("usb-1.0")
    if system_path:
        candidates.append(Path(system_path))

    root = Path(__file__).resolve().parent.parent
    exe_dir = Path(sys.executable).resolve().parent
    if sys.platform == "win32":
        arch = platform.architecture()[0]
        if arch == "64bit":
            candidates.extend([
                root / "vendor" / "libusb" / "windows" / "x64" / "libusb-1.0.dll",
                exe_dir / "libusb-1.0.dll",
                exe_dir / "vendor" / "libusb" / "windows" / "x64" / "libusb-1.0.dll",
            ])
        else:
            candidates.extend([
                root / "vendor" / "libusb" / "windows" / "x86" / "libusb-1.0.dll",
                exe_dir / "libusb-1.0.dll",
                exe_dir / "vendor" / "libusb" / "windows" / "x86" / "libusb-1.0.dll",
            ])
    elif sys.platform == "darwin":
        candidates.extend([
            root / "vendor" / "libusb" / "macos" / "libusb-1.0.dylib",
            exe_dir / "libusb-1.0.dylib",
        ])
    else:
        candidates.extend([
            root / "vendor" / "libusb" / "linux" / "libusb-1.0.so",
            exe_dir / "libusb-1.0.so",
        ])

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique
