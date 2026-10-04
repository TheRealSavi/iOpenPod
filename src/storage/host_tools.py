"""Host executable discovery, child environments, and package-manager observations."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


def host_tool_environment() -> dict[str, str]:
    """Keep frozen Linux libraries out of system tools without changing the app."""
    environment = dict(os.environ)
    if sys.platform == "linux" and getattr(sys, "frozen", False):
        # PyInstaller prepends its libraries and retains the Host's original path.
        original = environment.get("LD_LIBRARY_PATH_ORIG")
        if original is None:
            environment.pop("LD_LIBRARY_PATH", None)
        else:
            environment["LD_LIBRARY_PATH"] = original
    return environment


def executable_directories() -> tuple[Path, ...]:
    """Known native install locations, including GUI sessions with a stale PATH."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return (
            (
                Path(local) / "Microsoft/WinGet/Links",
                Path(local) / "Microsoft/WindowsApps",
            )
            if local
            else ()
        )
    if sys.platform == "darwin":
        prefixes = (
            ("/opt/homebrew", "/usr/local")
            if platform.machine().lower() in {"arm64", "aarch64"}
            else ("/usr/local", "/opt/homebrew")
        )
        return (*(Path(prefix) / "bin" for prefix in prefixes), Path("/usr/bin"))
    return (Path("/usr/local/bin"), Path("/usr/bin"), Path("/bin"))


def find_host_executable(name: str) -> str | None:
    """Prefer the user's PATH, then known package-manager executable locations."""
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError("Expected an executable name, not a path")
    found = shutil.which(name)
    if found is not None:
        return str(Path(found).absolute())
    filename = name + ".exe" if sys.platform == "win32" else name
    for directory in executable_directories():
        candidate = directory / filename
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


@dataclass(frozen=True, slots=True)
class HostToolEnvironment:
    system: str
    architecture: str
    distribution_ids: frozenset[str] = frozenset()
    managers: tuple[tuple[str, str], ...] = ()
    confined: bool = False
    administrator: bool = False

    def executable(self, name: str) -> str | None:
        return next((path for key, path in self.managers if key == name), None)


def inspect_tool_environment() -> HostToolEnvironment:
    """Observe the Host without installing anything or changing its environment."""
    ids: frozenset[str] = frozenset()
    if sys.platform.startswith("linux"):
        try:
            release = platform.freedesktop_os_release()
        except OSError:
            pass
        else:
            ids = frozenset(
                (release.get("ID", "") + " " + release.get("ID_LIKE", "")).split()
            )
    architecture = platform.machine().lower()
    managers: list[tuple[str, str]] = []
    if sys.platform == "darwin":
        # A universal app may run under Rosetta. A native ARM Homebrew is preferred
        # when available; arch explicitly selects the matching interpreter slice.
        for prefix in ("/opt/homebrew", "/usr/local"):
            brew = Path(prefix) / "bin/brew"
            if brew.is_file() and os.access(brew, os.X_OK):
                managers.append(("brew", str(brew)))
                architecture = "arm64" if prefix == "/opt/homebrew" else "x86_64"
                break
    names = (
        ("winget",)
        if sys.platform == "win32"
        else ("apt-get", "dnf", "pacman", "zypper", "pkexec")
        if sys.platform.startswith("linux")
        else ()
    )
    managers.extend(
        (name, path)
        for name in names
        if (path := find_host_executable(name)) is not None
    )
    confined = bool(
        os.environ.get("FLATPAK_ID")
        or os.environ.get("SNAP")
        or os.environ.get("APP_SANDBOX_CONTAINER_ID")
        or (sys.platform.startswith("linux") and Path("/.flatpak-info").exists())
    )
    return HostToolEnvironment(
        sys.platform,
        architecture,
        ids,
        tuple(managers),
        confined,
        getattr(os, "geteuid", lambda: -1)() == 0,
    )
