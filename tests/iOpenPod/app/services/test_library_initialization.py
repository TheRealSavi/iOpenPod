"""Selection-time recovery on virtual restored iPods, without physical devices."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

from device_registry import DEFAULT_DEVICE_REGISTRY, DeviceProfile
from iOpenPod.app.models.device import DeviceReadiness
from iOpenPod.app.services import library_initialization
from iOpenPod.app.services.device_coordinator import (
    DeviceAccessError,
    DeviceChangedError,
    DeviceCoordinator,
    DeviceLibraryLoadError,
    DeviceNotSelectableError,
    SyncRecoveryRequiredError,
    SyncRecoveryRestoredError,
)
from iPodDB.iTunesDB.cdb import decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.library import IPodLibrary, WriteTarget, create_empty_library
from storage import (
    FilePrecondition,
    FilesystemSession,
    FlushResult,
    HardwareIdentifiers,
    Storage,
    StorageTransaction,
    TransactionActivity,
    TransactionProgress,
    TransactionResult,
    TransactionState,
)
from storage.models import VolumeObservation
from storage.testing import VirtualStoragePlatform

GUID = bytes.fromhex("000A270012345678")


@contextmanager
def restored_device(
    root: Path,
    *,
    model: str = "M9282",
    writable: bool = True,
    signing: bool = True,
) -> Generator[tuple[VirtualStoragePlatform, DeviceCoordinator], None, None]:
    device = root / "iPod_Control" / "Device"
    device.mkdir(parents=True)
    (device / "SysInfo").write_text(f"ModelNumStr: {model}\n")
    if signing:
        (device / "HashInfo").write_bytes(
            b"HASHv0" + GUID + bytes(12) + bytes(range(12)) + bytes(range(16))
        )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root,
        label="Restored iPod",
        writable=writable,
        identifiers=HardwareIdentifiers(transport_serial=GUID.hex() if signing else ""),
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    try:
        yield platform, coordinator
    finally:
        coordinator.close()


def files(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize(
    "model",
    [
        "M8541",
        "M9282",
        "M9802",
        "MA005",
        "MA002",
        "MB565",
        "MB480",
        "MC027",
        "MC525",
        "MD480",
    ],
)
def test_selection_initializes_model_compatible_library_and_is_idempotent(
    tmp_path: Path, model: str
) -> None:
    with restored_device(tmp_path, model=model) as (_, coordinator):
        before = files(tmp_path)
        candidate = coordinator.discover_devices().candidates[0]
        assert candidate.readiness is DeviceReadiness.DATABASE_INITIALIZABLE
        assert candidate.selectable
        assert files(tmp_path) == before
        assert not (tmp_path / "iPod_Control/iTunes").exists()
        active = coordinator.select_device(candidate.id)
        assert coordinator.active_ipod is active
        assert active.library.tracks == ()
        assert active.library.playlists == ()
        assert active.display_name == "Restored iPod"
        profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number(model)
        assert profile is not None
        compressed = profile.capabilities.database.supports_compressed_database
        assert active.database_name == ("iTunesCDB" if compressed else "iTunesDB")
        data = (tmp_path / "iPod_Control/iTunes" / active.database_name).read_bytes()
        logical = decompress_iTunesCDB(data).logical_bytes if compressed else data
        assert (
            parse_iTunesDB(logical).header.version
            == profile.capabilities.database.binary_version
        )
        assert IPodLibrary.parse(data).snapshot == active.library
        for directory in ("Device", "iTunes", "Music", "Artwork"):
            assert (tmp_path / "iPod_Control" / directory).is_dir()
        if profile.capabilities.database.uses_sqlite_database:
            assert (
                len(
                    tuple(
                        (tmp_path / "iPod_Control/iTunes/iTunes Library.itlp").iterdir()
                    )
                )
                == 6
            )
            assert (tmp_path / "iPod_Control/iTunes/iTunesDB").read_bytes() == b""
        assert not list((tmp_path / ".iopenpod-recovery").glob("*/transaction.json"))
        after = files(tmp_path / "iPod_Control/iTunes")
        coordinator.select_device(candidate.id)
        assert files(tmp_path / "iPod_Control/iTunes") == after


@pytest.mark.parametrize("payload", [b"", b"damaged database"])
def test_existing_primary_is_never_replaced(tmp_path: Path, payload: bytes) -> None:
    with restored_device(tmp_path) as (_, coordinator):
        directory = tmp_path / "iPod_Control/iTunes"
        directory.mkdir()
        database = directory / "iTunesDB"
        database.write_bytes(payload)
        candidate = coordinator.discover_devices().candidates[0]
        assert candidate.readiness is not DeviceReadiness.DATABASE_INITIALIZABLE
        with pytest.raises((DeviceNotSelectableError, DeviceLibraryLoadError)):
            coordinator.select_device(candidate.id)
        assert database.read_bytes() == payload
        assert coordinator.active_ipod is None


@pytest.mark.parametrize("model,writable", [("M9282", False), ("not-a-model", True)])
def test_unidentified_or_readonly_volume_is_not_initialized(
    tmp_path: Path, model: str, writable: bool
) -> None:
    with restored_device(tmp_path, model=model, writable=writable) as (_, coordinator):
        before = files(tmp_path)
        candidate = coordinator.discover_devices().candidates[0]
        assert not candidate.selectable
        with pytest.raises(DeviceNotSelectableError):
            coordinator.select_device(candidate.id)
        assert files(tmp_path) == before


@pytest.mark.parametrize("model", ["MB565", "MB480", "MC027", "MC525"])
def test_missing_signing_material_fails_before_creating_layout(
    tmp_path: Path, model: str
) -> None:
    with restored_device(tmp_path, model=model, signing=False) as (_, coordinator):
        before = files(tmp_path)
        candidate = coordinator.discover_devices().candidates[0]
        with pytest.raises(DeviceLibraryLoadError, match="could not be created safely"):
            coordinator.select_device(candidate.id)
        assert files(tmp_path) == before
        assert not (tmp_path / "iPod_Control/iTunes").exists()
        assert coordinator.active_ipod is None


def test_new_database_after_discovery_is_loaded_without_replacement(
    tmp_path: Path,
) -> None:
    with restored_device(tmp_path) as (_, coordinator):
        candidate = coordinator.discover_devices().candidates[0]
        result = create_empty_library(
            "External iPod", WriteTarget(database_version=0x13), supports_podcasts=True
        )
        assert result.prepared is not None
        directory = tmp_path / "iPod_Control/iTunes"
        directory.mkdir()
        database = directory / "iTunesDB"
        database.write_bytes(result.prepared.itunes)
        active = coordinator.select_device(candidate.id)
        assert active.display_name == "External iPod"
        assert database.read_bytes() == result.prepared.itunes


@pytest.mark.parametrize(
    "change", ["database", "alternate", "identity", "disconnect", "readonly", "marker"]
)
def test_changes_after_preparation_block_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    with restored_device(tmp_path) as (platform, coordinator):
        candidate = coordinator.discover_devices().candidates[0]
        original = library_initialization.prepare

        # Keep the production signature for static checking of the test seam.
        def mutate(
            session: FilesystemSession,
            profile: DeviceProfile,
            target: WriteTarget,
            device_name: str,
            dependencies: tuple[FilePrecondition, ...],
        ) -> StorageTransaction:
            plan = original(session, profile, target, device_name, dependencies)
            if change in ("database", "alternate"):
                directory = tmp_path / "iPod_Control/iTunes"
                directory.mkdir()
                (
                    directory / ("iTunesDB" if change == "database" else "iTunesCDB")
                ).write_bytes(b"external")
            elif change == "identity":
                (tmp_path / "iPod_Control/Device/SysInfo").write_text(
                    "ModelNumStr: MA005\n"
                )
            elif change == "disconnect":
                platform.disconnect(tmp_path)
            elif change == "marker":
                (tmp_path / "iPod_Control").rename(tmp_path / "retained")
            else:
                platform.set_writable(tmp_path, False)
            return plan

        monkeypatch.setattr(library_initialization, "prepare", mutate)
        with pytest.raises((DeviceAccessError, DeviceChangedError)):
            coordinator.select_device(candidate.id)
        assert coordinator.active_ipod is None
        database = tmp_path / "iPod_Control/iTunes/iTunesDB"
        if change == "database":
            assert database.read_bytes() == b"external"
        else:
            assert not database.exists()


@pytest.mark.parametrize(
    "obstruction", ["sidecar", "sqlite", "directory_file", "symlink", "wrong_hashinfo"]
)
def test_conflicting_artifacts_fail_without_mutating_files(
    tmp_path: Path, obstruction: str
) -> None:
    with restored_device(tmp_path, model="MC027") as (_, coordinator):
        itunes = tmp_path / "iPod_Control/iTunes"
        itunes.mkdir()
        if obstruction == "sidecar":
            (itunes / "Play Counts").write_bytes(b"retained playback evidence")
        elif obstruction == "sqlite":
            companions = itunes / "iTunes Library.itlp"
            companions.mkdir()
            (companions / "Library.itdb").write_bytes(b"retained SQLite library")
        elif obstruction == "directory_file":
            (tmp_path / "iPod_Control/Music").write_bytes(b"retained file")
        elif obstruction == "symlink":
            (tmp_path / "iPod_Control/Artwork").symlink_to(
                tmp_path, target_is_directory=True
            )
        else:
            (tmp_path / "iPod_Control/Device/HashInfo").write_bytes(
                b"HASHv0" + bytes(20) + bytes(range(12)) + bytes(range(16))
            )
        before = files(tmp_path)
        candidate = coordinator.discover_devices().candidates[0]
        with pytest.raises((DeviceAccessError, DeviceLibraryLoadError)):
            coordinator.select_device(candidate.id)
        assert coordinator.active_ipod is None
        assert files(tmp_path) == before
        assert not (itunes / "iTunesCDB").exists()


def test_late_nano_retains_existing_empty_compatibility_file(tmp_path: Path) -> None:
    with restored_device(tmp_path, model="MC525") as (_, coordinator):
        itunes = tmp_path / "iPod_Control/iTunes"
        itunes.mkdir()
        compatibility = itunes / "iTunesDB"
        compatibility.write_bytes(b"")
        original = compatibility.stat()
        media = tmp_path / "iPod_Control/Music/F00/retained.mp3"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"retained media")
        candidate = coordinator.discover_devices().candidates[0]
        coordinator.select_device(candidate.id)
        assert compatibility.stat().st_ino == original.st_ino
        assert compatibility.stat().st_mtime_ns == original.st_mtime_ns
        assert media.read_bytes() == b"retained media"


def test_unconfirmed_flush_retains_journal_and_never_activates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unconfirmed_flush(_observation: VolumeObservation) -> FlushResult:
        return FlushResult(False, "unconfirmed")

    with restored_device(tmp_path) as (platform, coordinator):
        candidate = coordinator.discover_devices().candidates[0]
        flush = platform.flush
        monkeypatch.setattr(platform, "flush", unconfirmed_flush)
        with pytest.raises(SyncRecoveryRequiredError) as failure:
            coordinator.select_device(candidate.id)
        assert coordinator.active_ipod is None
        assert (tmp_path / failure.value.recovery_path).is_file()
        database = tmp_path / "iPod_Control/iTunes/iTunesDB"
        published = database.read_bytes()
        monkeypatch.setattr(platform, "flush", flush)
        ready = coordinator.discover_devices().candidates[0]
        active = coordinator.select_device(ready.id)
        assert active.library.tracks == ()
        assert database.read_bytes() == published
        assert not (tmp_path / failure.value.recovery_path).exists()


def test_interrupted_publication_remains_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with restored_device(tmp_path, model="MC525") as (platform, coordinator):
        candidate = coordinator.discover_devices().candidates[0]
        execute = FilesystemSession.execute_transaction

        def disconnect(
            session: FilesystemSession,
            plan: StorageTransaction,
            *,
            checkpoint: Callable[[], None] | None = None,
            progress: Callable[[TransactionProgress], None] | None = None,
            activity: Callable[[TransactionActivity], None] | None = None,
        ) -> TransactionResult:
            def interrupt(event: TransactionProgress) -> None:
                if event.state is TransactionState.PUBLISHING and event.completed == 1:
                    platform.disconnect(tmp_path)

            return execute(
                session,
                plan,
                checkpoint=checkpoint,
                progress=interrupt,
                activity=activity,
            )

        monkeypatch.setattr(FilesystemSession, "execute_transaction", disconnect)
        with pytest.raises(SyncRecoveryRequiredError) as failure:
            coordinator.select_device(candidate.id)
        assert coordinator.active_ipod is None
        assert (tmp_path / failure.value.recovery_path).is_file()
        assert not (tmp_path / "iPod_Control/iTunes/iTunesCDB").exists()
        monkeypatch.setattr(FilesystemSession, "execute_transaction", execute)
        platform.reconnect(tmp_path)
        discovery = coordinator.discover_devices()
        assert (
            discovery.candidates[0].readiness is DeviceReadiness.SYNC_RECOVERY_REQUIRED
        )
        with pytest.raises(
            SyncRecoveryRestoredError, match="previous Library was restored"
        ):
            coordinator.recover_sync_journal(failure.value.recovery_path)
        assert coordinator.active_ipod is None
        assert not (tmp_path / "iPod_Control/iTunes/iTunesCDB").exists()
        assert not (tmp_path / failure.value.recovery_path).exists()
        ready = coordinator.discover_devices().candidates[0]
        active = coordinator.select_device(ready.id)
        assert active.library.tracks == ()
