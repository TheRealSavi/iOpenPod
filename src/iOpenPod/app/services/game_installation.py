"""Create-only Storage plans from persistent Host game files."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from iOpenPod.app.services.game_content import inspect_contents
from iOpenPod.app.services.game_library import read_game_catalog
from iPodDB.games import parse_game_manifest
from storage import DeviceEntryKind, DevicePath, StorageTransaction, TransactionWrite

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from storage import FilePrecondition, FilesystemSession
ROOT = DevicePath("iPod_Control/Games_RO")
_MAX_MEMBERS = 20_000


class GameInstallationPhase(StrEnum):
    DOWNLOADING = "downloading"
    PREPARING = "preparing"
    EXTRACTING = "extracting"
    INSTALLING = "installing"
    VERIFYING = "verifying"
    FINALIZING = "finalizing"


@dataclass(frozen=True, slots=True)
class GameInstallationProgress:
    phase: GameInstallationPhase
    current: int = 0
    total: int = 0
    path: DevicePath | None = None
    title: str = ""


@dataclass(frozen=True, slots=True)
class GamePackage:
    identifier: str
    version: str
    directory: Path
    sha256: str
    title: str = ""


@dataclass(frozen=True, slots=True)
class PreparedGameInstallation:
    transaction: StorageTransaction
    directories: tuple[DevicePath, ...]


@contextmanager
def prepare_installation(
    session: FilesystemSession,
    packages: tuple[GamePackage, ...],
    *,
    dependencies: tuple[FilePrecondition, ...],
    checkpoint: Callable[[], None],
    progress: Callable[[GameInstallationProgress], None] = lambda _: None,
) -> Generator[PreparedGameInstallation]:
    checkpoint()
    if not packages or len({game.identifier.casefold() for game in packages}) != len(
        packages
    ):
        raise ValueError("Invalid game installation selection.")
    validate_destinations(session, packages, checkpoint)
    writes: list[TransactionWrite] = []
    directories = [
        DevicePath("iPod_Control/GameStats_WO"),
        DevicePath("iPod_Control/GameData_RW"),
    ]
    for index, game in enumerate(packages):
        checkpoint()
        if DevicePath(game.identifier).parts != (game.identifier,):
            raise ValueError("Invalid game folder identity.")
        progress(
            GameInstallationProgress(
                GameInstallationPhase.PREPARING, index, len(packages), title=game.title
            )
        )
        contents = inspect_contents(game.directory, checkpoint)
        if contents.sha256 != game.sha256:
            raise ValueError("The cached game files failed verification.")
        manifest = next(
            (item for item in contents.files if item.relative == "Manifest.plist"), None
        )
        if manifest is None or manifest.content.size > 1024 * 1024:
            raise ValueError("The game manifest is missing or exceeds its size limit.")
        metadata = parse_game_manifest(Path(str(manifest.source)).read_bytes())
        if (
            metadata.identifier.casefold() != game.identifier.casefold()
            or metadata.version != game.version
        ):
            raise ValueError("The cached game does not match its catalog identity.")
        destination = ROOT.joinpath(game.identifier)
        directories.append(destination)
        directories.extend(
            DevicePath.from_parts((*destination.parts, *DevicePath(relative).parts))
            for relative in contents.directories
        )
        writes.extend(
            TransactionWrite(
                DevicePath.from_parts(
                    (*destination.parts, *DevicePath(item.relative).parts)
                ),
                item.source,
                item.content,
            )
            for item in contents.files
        )
    writes.sort(key=lambda item: item.path.name.casefold() == "manifest.plist")
    transaction = StorageTransaction(
        tuple(writes), dependencies=dependencies, host_recovery=True
    )
    session.validate_transaction(transaction)
    yield PreparedGameInstallation(transaction, tuple(directories))


def validate_destinations(
    session: FilesystemSession,
    packages: tuple[GamePackage, ...],
    checkpoint: Callable[[], None],
) -> None:
    installed = read_game_catalog(session, checkpoint)
    occupied = {
        value.strip().casefold()
        for game in installed.games
        for value in (game.identifier, game.directory)
        if value
    }
    if any(game.identifier.casefold() in occupied for game in packages):
        raise ValueError(
            "A selected game is already on this iPod. Reload the games list."
        )
    if not session.exists(ROOT):
        return
    selected = {game.identifier.casefold() for game in packages}
    for entry in session.list_directory(ROOT):
        if entry.path.name.casefold() not in selected:
            continue
        pending = [entry]
        count = 0
        while pending:
            checkpoint()
            current = pending.pop()
            count += 1
            if current.kind is not DeviceEntryKind.DIRECTORY or count > _MAX_MEMBERS:
                raise ValueError(
                    "A selected game's destination folder is already occupied."
                )
            pending.extend(session.list_directory(current.path))
