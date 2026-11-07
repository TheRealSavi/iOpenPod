"""Small persistent Host game fixtures exercise create-only installation."""

import plistlib
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest

from device_registry import DeviceProfile
from iOpenPod.app.services import game_download
from iOpenPod.app.services import game_installation as installation
from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinationError,
    DeviceCoordinator,
)
from iOpenPod.app.services.game_content import inspect_contents
from storage import (
    AccessMode,
    FilePrecondition,
    FilesystemSession,
    HardwareIdentifiers,
    Storage,
    StorageError,
)
from storage.testing import VirtualStoragePlatform


def package(root: Path, identifier: str = "1D000") -> installation.GamePackage:
    path = root / ("host-" + identifier)
    (path / "Executables/empty").mkdir(parents=True)
    (path / "Manifest.plist").write_bytes(
        plistlib.dumps({"Name": "Fixture game", "Version": "1.0", "GUID": identifier})
    )
    (path / "Executables/game.bin").write_bytes(b"fixture executable")
    (path / "Executables/game.bin.sinf").write_bytes(b"fixture sinf")
    (path / "Manifest.plist.p7b").write_bytes(b"fixture signature")
    return installation.GamePackage(
        identifier, "1.0", path, inspect_contents(path, lambda: None).sha256
    )


@contextmanager
def volume(tmp_path: Path) -> Generator[tuple[FilesystemSession, Path]]:
    root = tmp_path / "device"
    root.mkdir()
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform, transaction_recovery_directory=tmp_path / "recovery")
    with storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        yield session, root


@pytest.mark.parametrize("existing_data", [False, True])
def test_batch_copies_host_files_preserves_support_data_and_creates_empty_folders(
    tmp_path: Path, existing_data: bool
) -> None:
    packages = (package(tmp_path), package(tmp_path, "ABCDE"))
    with volume(tmp_path) as (session, root):
        for name in ("GameData_RW", "GameStats_WO"):
            if existing_data:
                folder = root / "iPod_Control" / name
                folder.mkdir(parents=True)
                (folder / "saved.bin").write_bytes(b"preserve")
        with installation.prepare_installation(
            session, packages, dependencies=(), checkpoint=lambda: None
        ) as prepared:
            assert not (root / str(installation.ROOT)).exists()
            assert len(prepared.transaction.writes) == 8
            assert all(write.expected is None for write in prepared.transaction.writes)
            assert all(
                write.path.name == "Manifest.plist"
                for write in prepared.transaction.writes[-2:]
            )
            for directory in prepared.directories:
                session.create_directory(directory)
            result = session.execute_transaction(prepared.transaction)
            assert session.finalize_committed_transaction(
                result.recovery.journal_path
            ).complete
        for game in packages:
            target = root / str(installation.ROOT) / game.identifier
            assert (target / "Executables/empty").is_dir()
            for source in game.directory.rglob("*"):
                if source.is_file():
                    assert (
                        target / source.relative_to(game.directory)
                    ).read_bytes() == source.read_bytes()
            assert game.directory.is_dir()
        for name in ("GameData_RW", "GameStats_WO"):
            assert (root / "iPod_Control" / name).is_dir()
            if existing_data:
                assert (
                    root / "iPod_Control" / name / "saved.bin"
                ).read_bytes() == b"preserve"


@pytest.mark.parametrize(
    "failure",
    ["changed", "missing_manifest", "identity", "version", "path", "occupied"],
)
def test_invalid_or_changed_host_games_never_publish(
    tmp_path: Path, failure: str
) -> None:
    game = package(tmp_path)
    if failure == "changed":
        (game.directory / "Executables/game.bin").write_bytes(b"changed")
    elif failure == "missing_manifest":
        (game.directory / "Manifest.plist").unlink()
        game = replace(
            game, sha256=inspect_contents(game.directory, lambda: None).sha256
        )
    elif failure == "identity":
        game = replace(game, identifier="ABCDE")
    elif failure == "version":
        game = replace(game, version="2.0")
    elif failure == "path":
        game = replace(game, identifier="../outside")
    with volume(tmp_path) as (session, root):
        if failure == "occupied":
            target = root / str(installation.ROOT) / game.identifier
            target.mkdir(parents=True)
            (target / "keep.bin").write_bytes(b"keep")
        with (
            pytest.raises((ValueError, StorageError)),
            installation.prepare_installation(
                session, (game,), dependencies=(), checkpoint=lambda: None
            ),
        ):
            pytest.fail("invalid game produced a plan")
        assert not (
            root / str(installation.ROOT) / game.identifier / "Manifest.plist"
        ).exists()
        if failure == "occupied":
            assert (
                root / str(installation.ROOT) / game.identifier / "keep.bin"
            ).read_bytes() == b"keep"


@pytest.mark.parametrize(
    "change",
    [
        "",
        "metadata",
        "authorization",
        "cancel",
        "disconnect",
        "blocked_game_data",
        "blocked_game_stats",
    ],
)
def test_coordinator_binds_installation_to_current_device_and_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    sysinfo = metadata / "SysInfo"
    sysinfo.write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform, transaction_recovery_directory=tmp_path / "recovery"),
        volume_presentation_enabled=False,
    )
    game = package(tmp_path)

    def bundled(
        _profile: DeviceProfile, _identifiers: tuple[str, ...]
    ) -> tuple[installation.GamePackage, ...]:
        return (game,)

    monkeypatch.setattr(game_download, "resolve_packages", bundled)
    original = installation.prepare_installation
    cancelled = Event()
    updates: list[installation.GameInstallationProgress] = []

    @contextmanager
    def prepare(
        session: FilesystemSession,
        archives: tuple[installation.GamePackage, ...],
        *,
        dependencies: tuple[FilePrecondition, ...],
        checkpoint: Callable[[], None],
        progress: Callable[[installation.GameInstallationProgress], None],
    ) -> Generator[installation.PreparedGameInstallation]:
        with original(
            session,
            archives,
            dependencies=dependencies,
            checkpoint=checkpoint,
            progress=progress,
        ) as prepared:
            if change == "metadata":
                sysinfo.write_text("changed identity")
            elif change == "authorization":
                (root / "iPod_Control/iTunes/IC-Info.sidb").write_bytes(b"changed")
            elif change == "cancel":
                cancelled.set()
            elif change == "disconnect":
                platform.disconnect(root)
            yield prepared

    monkeypatch.setattr(installation, "prepare_installation", prepare)
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        (root / "iPod_Control/iTunes/IC-Info.sidb").write_bytes(
            b"fixture authorization"
        )
        blocked = None
        if change in {"blocked_game_data", "blocked_game_stats"}:
            blocked = (
                root
                / "iPod_Control"
                / ("GameData_RW" if change == "blocked_game_data" else "GameStats_WO")
            )
            blocked.write_bytes(b"preserve conflicting file")
        database = root / "iPod_Control/iTunes/iTunesDB"
        before = database.read_bytes()
        if change:
            with pytest.raises((DeviceCoordinationError, ValueError, StorageError)):
                coordinator.install_games(
                    active, ("1D000",), cancelled, progress=updates.append
                )
            assert not (root / str(installation.ROOT)).exists()
            if blocked is not None:
                assert blocked.read_bytes() == b"preserve conflicting file"
        else:
            result = coordinator.install_games(
                active, ("1D000",), cancelled, progress=updates.append
            )
            assert [game.identifier for game in result.games] == ["1D000"]
            assert (root / str(installation.ROOT) / "1D000/Executables/empty").is_dir()
            assert (root / "iPod_Control/GameStats_WO").is_dir()
            assert (root / "iPod_Control/GameData_RW").is_dir()
            assert {event.phase for event in updates} == {
                installation.GameInstallationPhase.PREPARING,
                installation.GameInstallationPhase.INSTALLING,
                installation.GameInstallationPhase.VERIFYING,
                installation.GameInstallationPhase.FINALIZING,
            }
            assert updates[-1].phase is installation.GameInstallationPhase.FINALIZING
        assert database.read_bytes() == before
    finally:
        coordinator.close()
