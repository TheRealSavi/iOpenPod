"""Small Qt runtime helpers that must run before selected Qt modules load."""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import os
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass

_QT_FFMPEG_QUIET_RULES = (
    "qt.multimedia.ffmpeg*.debug=false",
    "qt.multimedia.ffmpeg*.info=false",
    "qt.multimedia.ffmpeg*.warning=false",
)


@dataclass(frozen=True)
class LinuxQtRuntimeDependency:
    """A shared library needed by Qt's Linux xcb platform plugin."""

    label: str
    find_names: tuple[str, ...]
    sonames: tuple[str, ...]
    debian_package: str
    fedora_package: str
    arch_package: str


_LINUX_QT_XCB_RUNTIME_DEPS = (
    LinuxQtRuntimeDependency(
        label="xcb-cursor",
        find_names=("xcb-cursor",),
        sonames=("libxcb-cursor.so.0",),
        debian_package="libxcb-cursor0",
        fedora_package="xcb-util-cursor",
        arch_package="xcb-util-cursor",
    ),
    LinuxQtRuntimeDependency(
        label="xcb-icccm",
        find_names=("xcb-icccm",),
        sonames=("libxcb-icccm.so.4",),
        debian_package="libxcb-icccm4",
        fedora_package="xcb-util-wm",
        arch_package="xcb-util-wm",
    ),
    LinuxQtRuntimeDependency(
        label="xcb-image",
        find_names=("xcb-image",),
        sonames=("libxcb-image.so.0",),
        debian_package="libxcb-image0",
        fedora_package="xcb-util-image",
        arch_package="xcb-util-image",
    ),
    LinuxQtRuntimeDependency(
        label="xcb-keysyms",
        find_names=("xcb-keysyms",),
        sonames=("libxcb-keysyms.so.1",),
        debian_package="libxcb-keysyms1",
        fedora_package="xcb-util-keysyms",
        arch_package="xcb-util-keysyms",
    ),
    LinuxQtRuntimeDependency(
        label="xcb-xkb",
        find_names=("xcb-xkb",),
        sonames=("libxcb-xkb.so.1",),
        debian_package="libxcb-xkb1",
        fedora_package="libxcb",
        arch_package="libxcb",
    ),
    LinuxQtRuntimeDependency(
        label="xcb-render-util",
        find_names=("xcb-render-util",),
        sonames=("libxcb-render-util.so.0",),
        debian_package="libxcb-render-util0",
        fedora_package="xcb-util-renderutil",
        arch_package="xcb-util-renderutil",
    ),
    LinuxQtRuntimeDependency(
        label="xkbcommon-x11",
        find_names=("xkbcommon-x11",),
        sonames=("libxkbcommon-x11.so.0",),
        debian_package="libxkbcommon-x11-0",
        fedora_package="libxkbcommon-x11",
        arch_package="libxkbcommon-x11",
    ),
    LinuxQtRuntimeDependency(
        label="xkbcommon",
        find_names=("xkbcommon",),
        sonames=("libxkbcommon.so.0",),
        debian_package="libxkbcommon0",
        fedora_package="libxkbcommon",
        arch_package="libxkbcommon",
    ),
)

_NON_XCB_QPA_PLATFORMS = (
    "eglfs",
    "linuxfb",
    "minimal",
    "minimalegl",
    "offscreen",
    "vkkhrdisplay",
    "vnc",
    "wayland",
)


def configure_qt_multimedia_logging() -> None:
    """Suppress Qt/FFmpeg probe chatter while leaving other Qt logs alone."""

    existing = os.environ.get("QT_LOGGING_RULES", "").strip()
    parts = [part.strip() for part in existing.replace("\n", ";").split(";") if part.strip()]
    for rule in _QT_FFMPEG_QUIET_RULES:
        if rule not in parts:
            parts.append(rule)
    os.environ["QT_LOGGING_RULES"] = ";".join(parts)


configure_qt_multimedia_logging()


def _linux_qt_uses_xcb(environ: Mapping[str, str]) -> bool:
    requested_platform = environ.get("QT_QPA_PLATFORM", "").strip().lower()
    if not requested_platform:
        return True

    platform_name = requested_platform.split(";", 1)[0].split(":", 1)[0]
    return not any(
        platform_name == non_xcb_platform
        or platform_name.startswith(f"{non_xcb_platform}-")
        for non_xcb_platform in _NON_XCB_QPA_PLATFORMS
    )


def _library_is_loadable(
    dependency: LinuxQtRuntimeDependency,
    *,
    find_library: Callable[[str], str | None],
    load_library: Callable[[str], object],
) -> bool:
    candidates: list[str] = []
    for find_name in dependency.find_names:
        found = find_library(find_name)
        if found:
            candidates.append(found)
    candidates.extend(dependency.sonames)

    for candidate in candidates:
        try:
            load_library(candidate)
        except OSError:
            continue
        return True

    return False


def linux_qt_dependency_error(
    *,
    platform: str = sys.platform,
    environ: Mapping[str, str] | None = None,
    find_library: Callable[[str], str | None] = ctypes.util.find_library,
    load_library: Callable[[str], object] = ctypes.CDLL,
) -> str | None:
    """Return an actionable Linux Qt dependency error before QApplication aborts."""

    environ = os.environ if environ is None else environ
    if platform != "linux" or not _linux_qt_uses_xcb(environ):
        return None

    missing = [
        dependency
        for dependency in _LINUX_QT_XCB_RUNTIME_DEPS
        if not _library_is_loadable(
            dependency,
            find_library=find_library,
            load_library=load_library,
        )
    ]
    if not missing:
        return None

    debian_packages = " ".join(dict.fromkeys(dep.debian_package for dep in missing))
    fedora_packages = " ".join(dict.fromkeys(dep.fedora_package for dep in missing))
    arch_packages = " ".join(dict.fromkeys(dep.arch_package for dep in missing))
    missing_labels = ", ".join(dep.label for dep in missing)

    return "\n".join(
        (
            "iOpenPod cannot start because Qt is missing Linux desktop libraries.",
            "",
            f"Missing Qt xcb runtime libraries: {missing_labels}",
            "",
            "Install the missing packages for your distribution, then run iopenpod again.",
            "",
            "Debian / Ubuntu:",
            f"  sudo apt install {debian_packages}",
            "",
            "Fedora / RPM-based Linux:",
            f"  sudo dnf install {fedora_packages}",
            "",
            "Arch Linux:",
            f"  sudo pacman -S {arch_packages}",
            "",
            "If you are running a Wayland-only desktop, you can also try:",
            "  QT_QPA_PLATFORM=wayland iopenpod",
        )
    )


@contextlib.contextmanager
def quiet_native_stderr() -> Iterator[None]:
    """Temporarily mute native stderr writes from C/C++ libraries."""

    try:
        sys.stderr.flush()
    except (AttributeError, OSError, ValueError):
        yield
        return

    stderr_fd = 2
    try:
        saved_fd = os.dup(stderr_fd)
    except OSError:
        yield
        return

    try:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            os.dup2(sink.fileno(), stderr_fd)
            yield
    finally:
        try:
            os.dup2(saved_fd, stderr_fd)
        finally:
            os.close(saved_fd)
