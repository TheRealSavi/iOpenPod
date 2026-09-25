"""Restart detection and terminal cleanup preserve the Library's recovery state."""

import hashlib
from collections.abc import Callable
from pathlib import Path
from time import monotonic, sleep

import pytest
from PySide6.QtTest import QTest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.test_device_controller import APPLICATION

from iOpenPod.app.core.settings.definitions import PENDING_SYNC_RECOVERY
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.device_controller import DeviceController
from iOpenPod.app.models.track_table_model import TrackTableModel
from iOpenPod.app.services.device_coordinator import (
    DeviceChangedError,
    DeviceCoordinator,
    SyncCleanupCompletedError,
    SyncRecoveryRequiredError,
    SyncRecoveryRestoredError,
)
from storage import (
    AccessMode,
    DevicePath,
    FileContent,
    FilesystemSession,
    FlushResult,
    RecoverableWriteError,
    StorageTransaction,
    TransactionDurabilityPendingError,
    TransactionFailureFacts,
    TransactionProgress,
    TransactionRecovery,
    TransactionState,
    TransactionWrite,
    VolumeIdentityChangedError,
)

_DATABASE = DevicePath("iPod_Control/iTunes/iTunesDB")
_PARTIAL = b"partially published database"


def _wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while monotonic() < deadline:
        APPLICATION.processEvents()
        if predicate():
            return
        QTest.qWait(10)
        sleep(0.005)
    assert predicate(), "Timed out waiting for asynchronous device work"


def _journal(device: Device, state: TransactionState) -> str:
    """Leave an actual Storage journal at a selected durable transaction boundary."""
    with device.storage.open_session(
        device.storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        plan = StorageTransaction(
            (
                TransactionWrite(
                    _DATABASE,
                    _PARTIAL,
                    FileContent(len(_PARTIAL), hashlib.sha256(_PARTIAL).hexdigest()),
                    session.fingerprint(_DATABASE),
                ),
            )
        )

        def interrupt(event: TransactionProgress) -> None:
            if event.state is state and (
                state is not TransactionState.PUBLISHING or event.completed == 1
            ):
                raise InterruptedError("Simulated application interruption")

        if state is TransactionState.COMMITTED:
            result = session.execute_transaction(plan)
            return str(result.recovery.journal_path)
        if state is TransactionState.RESTORED:
            result = session.execute_transaction(plan)
            return str(
                session.restore_transaction(result.recovery).recovery.journal_path
            )
        with pytest.raises(RecoverableWriteError) as caught:
            session.execute_transaction(plan, progress=interrupt)
        return caught.value.recovery_path


@pytest.mark.parametrize("fresh_coordinator", [False, True])
def test_discovery_finds_crash_journal_before_loading_partial_database(
    tmp_path: Path, fresh_coordinator: bool
) -> None:
    device = build_device(tmp_path)
    path = _journal(device, TransactionState.PUBLISHING)
    coordinator = (
        DeviceCoordinator(device.storage) if fresh_coordinator else device.coordinator
    )
    try:
        with pytest.raises(SyncRecoveryRequiredError) as caught:
            coordinator.discover_devices(refresh_known=False)
        assert caught.value.recovery_path == path
        assert (device.root / str(_DATABASE)).read_bytes() == _PARTIAL
    finally:
        coordinator.close()
        device.coordinator.close()


def test_selection_detects_pending_journal_before_metadata_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    candidate = device.active.candidate.id
    path = _journal(device, TransactionState.PREPARED)

    def forbidden_repair(*_args: object) -> None:
        pytest.fail("Selection must not repair metadata before pending recovery")

    monkeypatch.setattr(
        device.coordinator, "_reconcile_device_metadata", forbidden_repair
    )
    try:
        with pytest.raises(SyncRecoveryRequiredError) as caught:
            device.coordinator.select_device(candidate)
        assert caught.value.recovery_path == path
        device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("settings_writable", [False, True])
def test_discovery_propagates_recovery_and_blocks_writes_without_a_prior_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings_writable: bool
) -> None:
    device = build_device(tmp_path)
    path = _journal(device, TransactionState.PREPARED)
    store = GlobalSettingsStore()
    settings = SettingsService(store, DeviceSettingsStore())
    if not settings_writable:

        def failed_sync() -> None:
            raise OSError("Host settings disk is full")

        monkeypatch.setattr(store, "sync", failed_sync)
    controller = DeviceController(device.coordinator, TrackTableModel(), settings)
    recoveries: list[str] = []
    failures: list[object] = []
    controller.recoveryRequired.connect(recoveries.append)
    controller.operationFailed.connect(failures.append)
    try:
        controller.refresh_devices()
        _wait_until(lambda: not controller.busy)
        assert recoveries == [path]
        assert settings.get(PENDING_SYNC_RECOVERY) == path
        assert not controller.device_writes_allowed
        assert not controller.begin_exclusive_operation()
        assert failures == []
    finally:
        controller.shutdown()


def test_restored_but_reload_failed_reports_completion_without_missing_journal_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    path = _journal(device, TransactionState.PUBLISHING)

    def fail_discovery() -> None:
        raise OSError("The restored iPod was disconnected during reload")

    monkeypatch.setattr(device.coordinator, "discover_devices", fail_discovery)
    try:
        with pytest.raises(
            SyncRecoveryRestoredError, match="previous Library was restored"
        ):
            device.coordinator.recover_sync_journal(path)
        device.assert_original()
        assert device.coordinator.active_ipod is None
        assert not (device.root / path).exists()
    finally:
        device.coordinator.close()


def test_recovery_reports_another_pending_journal_after_finishing_the_first(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    first = _journal(device, TransactionState.PREPARED)
    second = _journal(device, TransactionState.PREPARED)
    try:
        with pytest.raises(SyncRecoveryRequiredError) as caught:
            device.coordinator.recover_sync_journal(first)
        assert caught.value.recovery_path == second
        assert not (device.root / first).exists()
        assert (device.root / second).exists()
        device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("after_restart", [False, True])
def test_restoration_final_flush_failure_reports_removed_recovery_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_restart: bool
) -> None:
    device = build_device(tmp_path)
    path = _journal(device, TransactionState.PUBLISHING)
    original_finalize = FilesystemSession.finalize_transaction

    def failed_flush(
        session: FilesystemSession, recovery: TransactionRecovery
    ) -> FlushResult:
        original_finalize(session, recovery)
        raise TransactionDurabilityPendingError(
            "Final device flush failed",
            TransactionFailureFacts(
                recovery.journal_path, TransactionState.RESTORED, True, True
            ),
        )

    monkeypatch.setattr(FilesystemSession, "finalize_transaction", failed_flush)
    try:
        if after_restart:
            with pytest.raises(SyncRecoveryRestoredError, match="Safely eject"):
                device.coordinator.recover_sync_journal(path)
        else:
            with pytest.raises(SyncCleanupCompletedError, match="Safely eject"):
                device.coordinator.recover_failed_sync(device.active, path)
        assert not (device.root / path).exists()
        device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "state", [TransactionState.COMMITTED, TransactionState.RESTORED]
)
def test_retry_cleanup_preserves_terminal_library_and_requires_connected_journal(
    tmp_path: Path, state: TransactionState
) -> None:
    device = build_device(tmp_path)
    path = _journal(device, state)
    expected = (device.root / str(_DATABASE)).read_bytes()
    try:
        device.coordinator.cleanup_sync_journal(path)
        assert (device.root / str(_DATABASE)).read_bytes() == expected
        assert not (device.root / path).exists()
        with pytest.raises(DeviceChangedError, match="Reconnect the original iPod"):
            device.coordinator.cleanup_sync_journal(path)
        assert (device.root / str(_DATABASE)).read_bytes() == expected
    finally:
        device.coordinator.close()


def test_cleanup_after_final_flush_failure_does_not_require_missing_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    path = _journal(device, TransactionState.COMMITTED)
    original_finalize = FilesystemSession.finalize_committed_transaction

    def failed_flush(session: FilesystemSession, journal_path: DevicePath) -> None:
        original_finalize(session, journal_path)
        raise TransactionDurabilityPendingError(
            "Final device flush failed",
            TransactionFailureFacts(
                journal_path, TransactionState.COMMITTED, True, True
            ),
        )

    monkeypatch.setattr(
        FilesystemSession, "finalize_committed_transaction", failed_flush
    )
    try:
        with pytest.raises(SyncCleanupCompletedError, match="Safely eject"):
            device.coordinator.cleanup_sync_journal(path)
        assert not (device.root / path).exists()
        assert (device.root / str(_DATABASE)).read_bytes() == _PARTIAL
    finally:
        device.coordinator.close()


def test_retry_cleanup_refuses_pending_recovery(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    path = _journal(device, TransactionState.PUBLISHING)
    try:
        with pytest.raises(SyncRecoveryRequiredError):
            device.coordinator.cleanup_sync_journal(path)
        assert (device.root / path).exists()
        assert (device.root / str(_DATABASE)).read_bytes() == _PARTIAL
    finally:
        device.coordinator.close()


def test_retry_cleanup_refuses_journal_from_another_device(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    path = _journal(device, TransactionState.COMMITTED)
    device.platform.replace_identity(
        device.root, device_id="other-device", volume_id="other-volume"
    )
    try:
        with pytest.raises(VolumeIdentityChangedError):
            device.coordinator.cleanup_sync_journal(path)
        assert (device.root / path).exists()
        assert (device.root / str(_DATABASE)).read_bytes() == _PARTIAL
    finally:
        device.coordinator.close()
