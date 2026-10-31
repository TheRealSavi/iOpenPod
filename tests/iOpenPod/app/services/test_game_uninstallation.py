"""Game removal is isolated, recoverable and tied to a current catalog item."""

import plistlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_game_installation import volume

from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.services import game_uninstallation as removal
from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinationError,
    DeviceCoordinator,
    SyncRecoveryRequiredError,
)
from iOpenPod.app.services.game_library import InstalledGame
from iOpenPod.app.services.phase import INDEX_PATH
from iPodDB.games import PhaseLibrary, build_phase_library
from storage import (
    FilePrecondition,
    FilesystemSession,
    HardwareIdentifiers,
    RecoverableWriteError,
    Storage,
    StorageError,
)
from storage.testing import VirtualStoragePlatform

PARENTS = ("Games_RO", "GameData_RW", "GameStats_WO")


def game_files(
    root: Path,
    identifier: str = "1D000",
    *,
    folder: str | None = None,
    runtime: bool = True,
) -> InstalledGame:
    directory = folder or identifier
    base = root / "iPod_Control/Games_RO" / directory
    (base / "Executables/empty").mkdir(parents=True)
    (base / "Executables/game.bin").write_bytes(b"fixture game")
    (base / "Manifest.plist").write_bytes(
        plistlib.dumps(
            {"Name": f"Game {identifier}", "Version": "1.0", "GUID": identifier}
        )
    )
    if runtime:
        for name in PARENTS[1:]:
            target = root / "iPod_Control" / name / identifier
            (target / "nested/empty").mkdir(parents=True)
            (target / "nested/save.bin").write_bytes(b"saved progress")
    return InstalledGame(directory, f"Game {identifier}", "1.0", identifier=identifier)


def files(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("runtime", [False, True])
@pytest.mark.parametrize("folder", ["1D000", "renamed-game"])
def test_removes_three_game_trees_and_preserves_siblings_and_shared_roots(
    tmp_path: Path, runtime: bool, folder: str
) -> None:
    with volume(tmp_path) as (session, root):
        game = game_files(root, folder=folder, runtime=runtime)
        game_files(root, "ABCDE")
        for parent in PARENTS:
            (root / "iPod_Control" / parent / "shared.dat").write_bytes(
                b"shared root data"
            )
        (root / "iPod_Control/iTunes").mkdir()
        auth = root / "iPod_Control/iTunes/IC-Info.sidb"
        auth.write_bytes(b"authorization stays")
        original = files(root)
        prepared = removal.prepare_uninstallation(
            session, game, dependencies=(), checkpoint=lambda: None
        )
        assert files(root) == original
        assert not prepared.transaction.writes
        assert prepared.transaction.removals[0].path.name == "Manifest.plist"
        result = session.execute_transaction(prepared.transaction)
        for directory in prepared.directories:
            session.remove_empty_directory(directory.path)
        assert session.finalize_committed_transaction(
            result.recovery.journal_path
        ).complete
        assert not (root / "iPod_Control/Games_RO" / folder).exists()
        for parent in PARENTS[1:]:
            assert not (root / "iPod_Control" / parent / "1D000").exists()
        for parent in PARENTS:
            assert (root / "iPod_Control" / parent / "ABCDE").is_dir()
        assert auth.read_bytes() == b"authorization stays"
        assert files(root) == {
            path: data
            for path, data in original.items()
            if "ABCDE" in path or path.endswith(("IC-Info.sidb", "shared.dat"))
        }


@pytest.mark.parametrize("change", ["file", "membership", "appeared"])
def test_changed_files_or_folder_membership_block_removal(
    tmp_path: Path, change: str
) -> None:
    with volume(tmp_path) as (session, root):
        game = game_files(root, runtime=change != "appeared")
        prepared = removal.prepare_uninstallation(
            session, game, dependencies=(), checkpoint=lambda: None
        )
        if change == "file":
            (root / "iPod_Control/Games_RO/1D000/Executables/game.bin").write_bytes(
                b"external changes"
            )
        elif change == "membership":
            (root / "iPod_Control/Games_RO/1D000/new.bin").write_bytes(b"new")
        else:
            (root / "iPod_Control/GameData_RW/1D000").mkdir(parents=True)
        before = files(root)
        with pytest.raises((ValueError, StorageError)):
            removal.recheck_uninstallation(session, prepared, lambda: None)
            session.execute_transaction(prepared.transaction)
        assert files(root) == before


@pytest.mark.parametrize(
    "invalid", ["directory", "guid", "stale", "duplicate", "runtime_file", "bounds"]
)
def test_unsafe_or_stale_targets_fail_without_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    with volume(tmp_path) as (session, root):
        game = game_files(root, runtime=invalid != "runtime_file")
        if invalid == "directory":
            game = replace(game, directory="../Games_RO")
        elif invalid == "guid":
            game = replace(game, identifier="../other")
        elif invalid == "stale":
            game = replace(game, version="old")
        elif invalid == "duplicate":
            game_files(root, folder="other-install", runtime=False)
        elif invalid == "runtime_file":
            target = root / "iPod_Control/GameData_RW/1D000"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"keep file")
        else:
            monkeypatch.setattr(removal, "_MAX_ENTRIES", 1)
        before = files(root)
        with pytest.raises((ValueError, StorageError)):
            removal.prepare_uninstallation(
                session, game, dependencies=(), checkpoint=lambda: None
            )
        assert files(root) == before
        assert not session.host_transaction_journals()


def test_partial_removal_can_restore_original_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with volume(tmp_path) as (session, root):
        game = game_files(root)
        original = files(root)
        prepared = removal.prepare_uninstallation(
            session, game, dependencies=(), checkpoint=lambda: None
        )
        target = root / "iPod_Control/Games_RO/1D000/Manifest.plist"
        native_unlink = Path.unlink

        def interrupt(path: Path, missing_ok: bool = False) -> None:
            native_unlink(path, missing_ok=missing_ok)
            if path == target:
                raise OSError("Interrupted removal")

        with monkeypatch.context() as fault:
            fault.setattr(Path, "unlink", interrupt)
            with pytest.raises(RecoverableWriteError):
                session.execute_transaction(prepared.transaction)
        journals = session.host_transaction_journals()
        assert len(journals) == 1
        session.restore_transaction(session.inspect_transaction(journals[0]))
        assert session.finalize_restored_transaction(journals[0]).complete
        assert files(root) == original


@pytest.mark.parametrize("change", ["", "metadata", "cancel", "disconnect", "cleanup"])
def test_coordinator_binds_removal_and_preserves_library_and_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    sysinfo = metadata / "SysInfo"
    sysinfo.write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    game = game_files(root)
    index = root / str(INDEX_PATH)
    index.parent.mkdir(parents=True)
    index.write_bytes(build_phase_library(PhaseLibrary(0)))
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform, transaction_recovery_directory=tmp_path / "recovery"),
        volume_presentation_enabled=False,
    )
    original_prepare = removal.prepare_uninstallation
    cancelled = Event()
    progress: list[removal.GameRemovalProgress] = []

    def prepare(
        session: FilesystemSession,
        game: InstalledGame,
        *,
        dependencies: tuple[FilePrecondition, ...],
        checkpoint: Callable[[], None],
    ) -> removal.PreparedGameUninstallation:
        result = original_prepare(
            session, game, dependencies=dependencies, checkpoint=checkpoint
        )
        if change == "metadata":
            sysinfo.write_text("changed")
        elif change == "cancel":
            cancelled.set()
        elif change == "disconnect":
            platform.disconnect(root)
        return result

    monkeypatch.setattr(removal, "prepare_uninstallation", prepare)
    if change == "cleanup":

        def refuse(_session: FilesystemSession, _path: object) -> None:
            raise OSError("folder cleanup failed")

        monkeypatch.setattr(FilesystemSession, "remove_empty_directory", refuse)
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        auth = root / "iPod_Control/iTunes/IC-Info.sidb"
        auth.write_bytes(b"authorization stays")
        database = root / "iPod_Control/iTunes/iTunesDB"
        original_db = database.read_bytes()
        if change:
            with pytest.raises((DeviceCoordinationError, StorageError)) as caught:
                coordinator.uninstall_game(
                    active, game, cancelled, progress=progress.append
                )
            if change == "cleanup":
                assert isinstance(caught.value, SyncRecoveryRequiredError)
            else:
                assert (root / "iPod_Control/Games_RO/1D000/Manifest.plist").is_file()
        else:
            result = coordinator.uninstall_game(
                active, game, cancelled, progress=progress.append
            )
            assert not result.games and not index.exists()
            assert all(
                not (root / "iPod_Control" / parent / "1D000").exists()
                for parent in PARENTS
            )
            assert all((root / "iPod_Control" / parent).is_dir() for parent in PARENTS)
            assert {event.phase for event in progress} == set(removal.GameRemovalPhase)
            assert any(
                event.phase is removal.GameRemovalPhase.REMOVING
                and 0 < event.current <= event.total
                for event in progress
            )
            assert progress[-1].phase is removal.GameRemovalPhase.FINALIZING
            # Removing Phase's index must update the cached source precondition.
            coordinator.prepare_library(
                LibraryPreparationRequest(active.library, active, 1, 1),
                lambda _: None,
                Event(),
                allow_unchanged=True,
            )
        assert auth.read_bytes() == b"authorization stays"
        assert database.read_bytes() == original_db
    finally:
        coordinator.close()
