"""Typed Jellyfin accounts, items, and play count outcomes, without I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iOpenPod.app.models.device import ActiveIPod

# Jellyfin stores play counts as signed 32-bit integers.
MAX_PLAY_COUNT = 2**31 - 1


class JellyfinError(Exception):
    """A credential-free message that is safe to show the user."""


@dataclass(frozen=True, slots=True)
class JellyfinAccount:
    server_url: str
    server_id: str
    user_id: str
    username: str
    device_id: str
    token: str = field(repr=False)

    @property
    def identity(self) -> str:
        return f"{self.server_id}:{self.user_id}"


@dataclass(frozen=True, slots=True)
class JellyfinTrack:
    item_id: str
    title: str
    album: str
    artists: tuple[str, ...]
    album_artist: str
    track_number: int
    disc_number: int
    length_ms: int
    play_count: int


@dataclass(frozen=True, slots=True)
class PlayCountResult:
    matched: int = 0
    ipod_updated: int = 0
    jellyfin_updated: int = 0
    unmatched: tuple[str, ...] = ()
    ambiguous: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    cancelled: bool = False
    # The saved Library when this run changed the iPod; otherwise ``None``.
    active: ActiveIPod | None = field(default=None, repr=False)

    @property
    def summary(self) -> str:
        parts = [
            f"Matched {self.matched} songs: updated {self.ipod_updated} on the "
            f"iPod and {self.jellyfin_updated} on Jellyfin."
        ]
        if self.unmatched:
            parts.append(f"{len(self.unmatched)} not found on Jellyfin.")
        if self.ambiguous:
            parts.append(f"{len(self.ambiguous)} with several possible matches.")
        if self.issues:
            parts.append(f"{len(self.issues)} problems.")
        return " ".join(parts)
