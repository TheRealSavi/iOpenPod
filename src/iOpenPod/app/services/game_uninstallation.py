"""Capture one installed game's files for recoverable, bounded removal."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from iOpenPod.app.services.game_library import InstalledGame, read_game_catalog
from storage import DeviceEntryKind, DevicePath, StorageTransaction, TransactionRemoval

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage import FilePrecondition, FilesystemSession

_ROOTS = (
    DevicePath("iPod_Control/Games_RO"),
    DevicePath("iPod_Control/GameData_RW"),
    DevicePath("iPod_Control/GameStats_WO"),
)
_MAX_ENTRIES = 30_000


class GameRemovalPhase(StrEnum):
    PREPARING = "preparing"
    REMOVING = "removing"
    VERIFYING = "verifying"
    CLEANING = "cleaning"
    FINALIZING = "finalizing"


@dataclass(frozen=True, slots=True)
class GameRemovalProgress:
    phase: GameRemovalPhase
    current: int = 0
    total: int = 0
    path: DevicePath | None = None


@dataclass(frozen=True, slots=True)
class DirectoryObservation:
    path: DevicePath
    children: tuple[tuple[DevicePath, DeviceEntryKind], ...]


@dataclass(frozen=True, slots=True)
class PreparedGameUninstallation:
    transaction: StorageTransaction
    directories: tuple[DirectoryObservation, ...]
    missing: tuple[DevicePath, ...]


def _component(value: str) -> str:
    if DevicePath(value).parts != (value,):
        raise ValueError("A game folder identifier must be one path component.")
    return value


def prepare_uninstallation(
    session: FilesystemSession,
    game: InstalledGame,
    *,
    dependencies: tuple[FilePrecondition, ...],
    checkpoint: Callable[[], None],
) -> PreparedGameUninstallation:
    """Capture actual RO folder and GUID-owned runtime data, preserving siblings."""
    directory = _component(game.directory)
    identifier = _component(game.identifier or directory)
    checkpoint()
    catalog = read_game_catalog(session, checkpoint)
    current = next(
        (item for item in catalog.games if item.directory == directory), None
    )
    if current is None or (current.identifier, current.title, current.version) != (
        game.identifier,
        game.title,
        game.version,
    ):
        raise ValueError(
            "The selected game changed. Reload the games list before uninstalling."
        )
    if any(
        item.directory != directory
        and (item.identifier or item.directory).casefold() == identifier.casefold()
        for item in catalog.games
    ):
        raise ValueError(
            "Multiple installed games share this identity; their saved data cannot be removed safely."
        )
    removals: list[TransactionRemoval] = []
    observations: list[DirectoryObservation] = []
    missing: list[DevicePath] = []
    count = 0
    for parent, name in zip(_ROOTS, (directory, identifier, identifier), strict=True):
        checkpoint()
        matches = (
            tuple(
                entry
                for entry in session.list_directory(parent)
                if entry.path.name.casefold() == name.casefold()
            )
            if session.exists(parent)
            else ()
        )
        if not matches:
            if parent == _ROOTS[0]:
                raise ValueError(
                    "The selected game folder disappeared during preparation."
                )
            missing.append(parent.joinpath(name))
            continue
        if len(matches) != 1:
            raise ValueError("A game's folder identity is ambiguous.")
        if matches[0].kind is not DeviceEntryKind.DIRECTORY:
            raise ValueError("A game's folder is not a plain directory.")
        pending = list(matches)
        while pending:
            checkpoint()
            entry = pending.pop()
            count += 1
            if count > _MAX_ENTRIES:
                raise ValueError(
                    "The game folders exceed the supported removal entry count."
                )
            if entry.kind is DeviceEntryKind.FILE:
                removals.append(
                    TransactionRemoval(entry.path, session.fingerprint(entry.path))
                )
            elif entry.kind is DeviceEntryKind.DIRECTORY:
                children = session.list_directory(entry.path)
                observations.append(
                    DirectoryObservation(
                        entry.path,
                        tuple((child.path, child.kind) for child in children),
                    )
                )
                pending.extend(children)
            else:
                raise ValueError("A game folder contains an unsafe filesystem entry.")
    # Stop advertising the game before removing executables and resources.
    removals.sort(key=lambda item: item.path.name.casefold() != "manifest.plist")
    prepared = PreparedGameUninstallation(
        StorageTransaction(
            (), tuple(removals), dependencies=dependencies, host_recovery=True
        ),
        tuple(
            sorted(observations, key=lambda item: len(item.path.parts), reverse=True)
        ),
        tuple(missing),
    )
    recheck_uninstallation(session, prepared, checkpoint)
    session.validate_transaction(prepared.transaction)
    return prepared


def recheck_uninstallation(
    session: FilesystemSession,
    prepared: PreparedGameUninstallation,
    checkpoint: Callable[[], None],
) -> None:
    """Reject changed membership before any captured file is removed."""
    for path in prepared.missing:
        checkpoint()
        parent = path.parent
        assert parent is not None
        if session.exists(parent) and any(
            entry.path.name.casefold() == path.name.casefold()
            for entry in session.list_directory(parent)
        ):
            raise ValueError("A game folder appeared during removal preparation.")
    for observed in prepared.directories:
        checkpoint()
        if (
            tuple(
                (entry.path, entry.kind)
                for entry in session.list_directory(observed.path)
            )
            != observed.children
        ):
            raise ValueError("A game folder changed during removal preparation.")
