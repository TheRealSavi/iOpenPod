"""Recovery hints must not lock an unrelated, usable Library."""

from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.sync_test_support import (
    DATABASE_PATH,
    PARTIAL_DATABASE_BYTES,
    SyncExecutionStub,
    create_transaction_journal,
)
from tests.iOpenPod.app.test_library_write_controller import session as session
from tests.iOpenPod.app.test_library_write_controller import track_model as track_model
from tests.iOpenPod.app.test_library_write_controller import wait_for

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.device_controller import DeviceController
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.device import ActiveIPod, DeviceReadiness
from iOpenPod.app.models.track_table_model import TrackTableModel
from iOpenPod.app.services.device_coordinator import (
    DeviceChangedError,
    DeviceCoordinator,
    SyncRecoveryDeclinedError,
    SyncRecoveryRequiredError,
)
from iOpenPod.app.sync_controller import SyncController
from storage import (
    DevicePath,
    FileFingerprint,
    FilePreconditionError,
    FilesystemSession,
    HardwareIdentifiers,
    StorageOperationError,
    TransactionState,
    WriteResult,
)


def test_stale_host_recovery_hint_does_not_lock_a_usable_ipod(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    store = GlobalSettingsStore()
    settings = SettingsService(store, DeviceSettingsStore())
    store.set(
        "sync/pending-recovery-journal",
        ".iopenpod-recovery/" + "a" * 32 + "/transaction.json",
    )
    controller = SyncController(SyncExecutionStub(), workspace, devices, settings)
    try:
        assert not workspace.locked
        assert devices.device_writes_allowed
        assert not controller.needs_recovery
    finally:
        controller.shutdown()


@pytest.mark.parametrize("corrupt", [False, True])
def test_keep_current_contents_retires_journal_without_changing_library_or_recovery_copies(
    tmp_path: Path,
    corrupt: bool,
) -> None:
    device = build_device(tmp_path)
    path = create_transaction_journal(device, TransactionState.PREPARED)
    journal = device.root / path
    if corrupt:
        journal.write_bytes(b"incomplete journal")
    before = {
        p.relative_to(device.root): p.read_bytes()
        for p in device.root.rglob("*")
        if p.is_file()
    }
    coordinator = DeviceCoordinator(device.storage)
    try:
        candidate = coordinator.discover_devices().candidates[0]
        with pytest.raises(SyncRecoveryRequiredError):
            coordinator.select_device(candidate.id)
        kept = coordinator.keep_sync_contents(path)
        assert kept.library.tracks
        assert not journal.exists()
        retired = journal.with_name("declined-transaction.json")
        after = {
            p.relative_to(device.root): p.read_bytes()
            for p in device.root.rglob("*")
            if p.is_file()
        }
        before[retired.relative_to(device.root)] = before.pop(
            journal.relative_to(device.root)
        )
        assert after == before
        coordinator.close()
        restarted = DeviceCoordinator(device.storage)
        try:
            candidate = restarted.discover_devices().candidates[0]
            assert candidate.readiness is DeviceReadiness.READY
            assert restarted.select_device(candidate.id).library == kept.library
        finally:
            restarted.close()
    finally:
        coordinator.close()
        device.coordinator.close()


def test_keep_incomplete_database_reports_load_failure_without_recovery_lock(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    path = create_transaction_journal(device, TransactionState.PUBLISHING)
    try:
        with pytest.raises(SyncRecoveryDeclinedError, match="could not be loaded"):
            device.coordinator.keep_sync_contents(path)
        assert (device.root / str(DATABASE_PATH)).read_bytes() == PARTIAL_DATABASE_BYTES
        assert not (device.root / path).exists()
        assert (device.root / path).with_name("declined-transaction.json").exists()
        assert all(
            c.readiness is not DeviceReadiness.SYNC_RECOVERY_REQUIRED
            for c in device.coordinator.discover_devices().candidates
        )
    finally:
        device.coordinator.close()


def test_keep_refuses_changed_journal_after_choice_was_presented(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    path = create_transaction_journal(device, TransactionState.PREPARED)
    try:
        device.coordinator.discover_devices()
        (device.root / path).write_bytes(b"changed after discovery")
        with pytest.raises(FilePreconditionError):
            device.coordinator.keep_sync_contents(path)
        assert (device.root / path).exists()
        device.assert_original()
    finally:
        device.coordinator.close()


def test_keep_refuses_replacement_volume(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    path = create_transaction_journal(device, TransactionState.PREPARED)
    try:
        device.coordinator.discover_devices()
        device.platform.replace_identity(
            device.root, device_id="other", volume_id="other"
        )
        with pytest.raises(DeviceChangedError):
            device.coordinator.keep_sync_contents(path)
        assert (device.root / path).exists()
        device.assert_original()
    finally:
        device.coordinator.close()


def test_missing_journal_can_be_dismissed_on_its_observed_device(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    path = create_transaction_journal(device, TransactionState.PREPARED)
    try:
        device.coordinator.discover_devices()
        (device.root / path).unlink()
        assert device.coordinator.keep_sync_contents(path).library.tracks
        device.assert_original()
    finally:
        device.coordinator.close()


def test_recovery_on_one_ipod_does_not_hide_or_lock_another(tmp_path: Path) -> None:
    device = build_device(tmp_path / "broken")
    healthy = build_device(tmp_path / "healthy")
    healthy.coordinator.close()
    device.platform.add_volume(
        healthy.root,
        device_id="healthy-device",
        volume_id="healthy-volume",
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1261,
            transport_serial="000A270012345678",
        ),
    )
    create_transaction_journal(device, TransactionState.PUBLISHING)
    devices = DeviceController(
        device.coordinator,
        TrackTableModel(),
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    workspace = LibraryWorkspace()
    controller = SyncController(
        SyncExecutionStub(),
        workspace,
        devices,
        SettingsService(GlobalSettingsStore(), DeviceSettingsStore()),
    )
    try:
        devices.refresh_devices()
        wait_for(lambda: not devices.busy)
        assert len(devices.discovery.candidates) == 2
        broken = next(
            c
            for c in devices.discovery.candidates
            if c.readiness is DeviceReadiness.SYNC_RECOVERY_REQUIRED
        )
        ready = next(
            c
            for c in devices.discovery.candidates
            if c.readiness is DeviceReadiness.READY
        )
        devices.select_device(broken.id.value)
        wait_for(lambda: not devices.busy)
        assert controller.needs_recovery and workspace.locked
        devices.select_device(ready.id.value)
        wait_for(lambda: not devices.busy)
        assert not controller.needs_recovery and not workspace.locked
        assert devices.device_writes_allowed
    finally:
        controller.shutdown()
        devices.shutdown()


@pytest.mark.parametrize("reload_fails", [False, True])
def test_keep_choice_unlocks_controller_and_never_runs_restoration(
    session: tuple[DeviceCoordinator, DeviceController, LibraryWorkspace, Path],
    reload_fails: bool,
) -> None:
    coordinator, devices, workspace, _ = session
    active = coordinator.active_ipod
    assert active is not None
    workspace.load(active.library)
    calls: list[str] = []
    path = ".iopenpod-recovery/" + "a" * 32 + "/transaction.json"

    def keep(journal: str) -> ActiveIPod:
        calls.append(journal)
        if reload_fails:
            raise SyncRecoveryDeclinedError(
                "Current contents kept; Library needs repair."
            )
        return active

    def forbidden_restore(create_transaction_journal: str) -> ActiveIPod:
        pytest.fail("Keeping current contents must not restore the Library")

    store = GlobalSettingsStore()
    controller = SyncController(
        SyncExecutionStub(),
        workspace,
        devices,
        SettingsService(store, DeviceSettingsStore()),
        recovery=forbidden_restore,
        keep_contents=keep,
    )
    try:
        devices.recoveryRequired.emit(path)
        assert controller.keep_current_contents()
        wait_for(lambda: not controller.busy)
        assert calls == [path]
        assert not controller.needs_recovery and not workspace.locked
        assert devices.device_writes_allowed is not reload_fails
        assert not store.has("sync/pending-recovery-journal")
        assert not store.has("sync/pending-cleanup-journal")
    finally:
        controller.shutdown()


def test_keep_one_journal_still_offers_the_next_interrupted_transaction(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    first = create_transaction_journal(device, TransactionState.PREPARED)
    second = create_transaction_journal(device, TransactionState.PREPARED)
    try:
        with pytest.raises(SyncRecoveryRequiredError) as error:
            device.coordinator.keep_sync_contents(first)
        assert error.value.recovery_path == second
        assert not (device.root / first).exists()
        assert (device.root / second).exists()
        device.assert_original()
    finally:
        device.coordinator.close()


def test_keep_can_retry_after_journal_move_succeeded_but_reported_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = build_device(tmp_path)
    path = create_transaction_journal(device, TransactionState.PREPARED)
    move = FilesystemSession.move

    def interrupted_move(
        session: FilesystemSession,
        source: DevicePath,
        destination: DevicePath,
        *,
        expected_source: FileFingerprint,
    ) -> WriteResult:
        move(session, source, destination, expected_source=expected_source)
        raise StorageOperationError("Device interrupted after the rename")

    try:
        monkeypatch.setattr(FilesystemSession, "move", interrupted_move)
        with pytest.raises(StorageOperationError):
            device.coordinator.keep_sync_contents(path)
        assert not (device.root / path).exists()
        monkeypatch.setattr(FilesystemSession, "move", move)
        assert device.coordinator.keep_sync_contents(path).library.tracks
        device.assert_original()
    finally:
        device.coordinator.close()


def test_terminal_cleanup_is_rediscovered_from_device_without_host_settings(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    path = create_transaction_journal(device, TransactionState.RESTORED)
    store = GlobalSettingsStore()
    settings = SettingsService(store, DeviceSettingsStore())
    coordinator = DeviceCoordinator(device.storage)
    devices = DeviceController(coordinator, TrackTableModel(), settings)
    controller = SyncController(
        SyncExecutionStub(),
        LibraryWorkspace(),
        devices,
        settings,
        keep_contents=coordinator.keep_sync_contents,
    )
    try:
        devices.refresh_devices()
        wait_for(lambda: not devices.busy)
        devices.select_device(devices.discovery.candidates[0].id.value)
        wait_for(lambda: not devices.busy)
        assert controller.needs_cleanup and not controller.needs_recovery
        assert controller.result is not None and controller.result.recovery_path == path
        assert devices.device_writes_allowed
        assert controller.keep_current_contents()
        wait_for(lambda: not controller.busy)
        assert not controller.needs_cleanup and not controller.needs_recovery
        assert not store.has("sync/pending-cleanup-journal")
        assert not (device.root / path).exists()
        device.assert_original()
    finally:
        controller.shutdown()
        devices.shutdown()
        device.coordinator.close()
