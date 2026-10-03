"""Typed boundary for channel detection and nonblocking update providers."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from iOpenPod.app.display_text import source_text


class InstallChannel(StrEnum):
    MICROSOFT_STORE = "microsoft-store"
    WINDOWS_PACKAGE = "windows-package"
    UNPACKAGED = "unpackaged"
    FROZEN = "frozen"
    SOURCE = "source"
    MAC_APP_STORE = "mac-app-store"
    APP_STORE_TEST = "app-store-test"
    FLATPAK = "flatpak"
    SNAP = "snap"
    UNKNOWN = "unknown"

    @property
    def display_name(self) -> str:
        """Shared source copy for startup diagnostics and translated presentation."""
        return {
            InstallChannel.MICROSOFT_STORE: source_text("Microsoft Store"),
            InstallChannel.WINDOWS_PACKAGE: source_text("Windows package (sideloaded)"),
            InstallChannel.UNPACKAGED: source_text("Unpackaged"),
            InstallChannel.FROZEN: source_text("Standalone executable"),
            InstallChannel.SOURCE: source_text("Python / source"),
            InstallChannel.MAC_APP_STORE: source_text(
                "Mac App Store (receipt detected)"
            ),
            InstallChannel.APP_STORE_TEST: source_text("App Store testing"),
            InstallChannel.FLATPAK: source_text("Flatpak"),
            InstallChannel.SNAP: source_text("Snap"),
            InstallChannel.UNKNOWN: source_text("Unknown source"),
        }[self]


class UpdateOutcome(StrEnum):
    AVAILABLE = "available"
    CURRENT = "current"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class UpdateResult:
    outcome: UpdateOutcome
    detail: str = ""


@dataclass(frozen=True, slots=True)
class UpdateProgress:
    """Progress for one package, never falsely presented as the whole request."""

    package: str
    fraction: float
    installing: bool


class UpdateBackend(Protocol):
    """All methods run on the GUI thread and must return without waiting.

    A successful check retains the channel's opaque update selection. Installation
    uses that selection. Poll returns immutable progress or one terminal result.
    """

    def check(self) -> None: ...

    def install(self) -> None: ...

    def poll(self) -> UpdateResult | UpdateProgress | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class UpdateProvider:
    channel: InstallChannel
    backend: UpdateBackend | None = None
    display_name: str = "installation source"
