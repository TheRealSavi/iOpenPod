"""Read an installed Games_RO catalog through an identity-bound Storage session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from iPodDB.games import parse_game_manifest
from storage import DeviceEntryKind, DevicePath, StorageError

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage import FilesystemSession

_ROOT = DevicePath("iPod_Control/Games_RO")
_MAX_GAMES = 512
_MAX_ART = 4 * 1024 * 1024
_ART_BUDGET = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class InstalledGame:
    directory: str
    title: str
    version: str
    artwork: bytes = b""
    identifier: str = ""


@dataclass(frozen=True, slots=True)
class GameCatalog:
    games: tuple[InstalledGame, ...] = ()
    issues: tuple[str, ...] = ()


def read_game_catalog(
    session: FilesystemSession, checkpoint: Callable[[], None]
) -> GameCatalog:
    """Enumerate top-level installations; platform executables are not games."""
    checkpoint()
    if not session.exists(_ROOT):
        return GameCatalog()
    entries = session.list_directory(_ROOT)
    if len(entries) > _MAX_GAMES:
        raise ValueError(
            "The installed games directory exceeds the supported entry count."
        )
    games: list[InstalledGame] = []
    issues: list[str] = []
    artwork_bytes = 0
    for entry in entries:
        checkpoint()
        if entry.kind is not DeviceEntryKind.DIRECTORY:
            continue
        folder = entry.path.parts[-1]
        manifest = DevicePath.from_parts((*entry.path.parts, "Manifest.plist"))
        artwork_path = DevicePath.from_parts((*entry.path.parts, "iTunesArtwork"))
        try:
            if not session.exists(manifest):
                continue
            title, version, identifier = folder, "", ""
            try:
                data = session.read_snapshot(manifest, max_bytes=1024 * 1024).data
                metadata = parse_game_manifest(data)
                title, version = metadata.title, metadata.version
                identifier = metadata.identifier
            except (ValueError, StorageError) as error:
                if not session.is_active:
                    raise
                issues.append(f"{folder}: {error}")
            artwork = b""
            try:
                if session.exists(artwork_path):
                    artwork = session.read_snapshot(
                        artwork_path, max_bytes=_MAX_ART
                    ).data
                    if artwork_bytes + len(artwork) > _ART_BUDGET:
                        artwork = b""
                        issues.append(f"{folder}: artwork memory limit reached")
                    artwork_bytes += len(artwork)
            except StorageError as error:
                if not session.is_active:
                    raise
                issues.append(f"{folder}: {error}")
            games.append(InstalledGame(folder, title, version, artwork, identifier))
        except StorageError as error:
            if not session.is_active:
                raise
            issues.append(f"{folder}: {error}")
    checkpoint()
    return GameCatalog(
        tuple(sorted(games, key=lambda game: (game.title.casefold(), game.directory))),
        tuple(issues),
    )
