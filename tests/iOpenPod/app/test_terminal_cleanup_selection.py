"""Selected iPods quietly reclaim finished transactions without restoring media."""

import hashlib
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iOpenPod.app.sync_test_support import (
    SyncExecutionStub,
    create_transaction_journal,
)
from tests.iOpenPod.app.test_library_write_controller import wait_for

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.device_controller import DeviceController
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.device import DeviceCandidateIssueCode
from iOpenPod.app.models.track_table_model import TrackTableModel
from iOpenPod.app.services.device_coordinator import SyncRecoveryRequiredError
from iOpenPod.app.sync_controller import SyncController
from storage import (
    AccessMode,
    DevicePath,
    FileContent,
    FilesystemSession,
    FlushResult,
    StorageOperationError,
    StorageTransaction,
    TransactionDurabilityPendingError,
    TransactionFailureFacts,
    TransactionState,
    TransactionWrite,
)


def _terminal_journal(device: Device, state: TransactionState) -> DevicePath:
    with device.storage.open_session(
        device.storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        path = DevicePath("iPod_Control/Music/F00/cleanup-test.bin")
        payload = b"verified media"
        result = session.execute_transaction(
            StorageTransaction(
                (
                    TransactionWrite(
                        path,
                        payload,
                        FileContent(len(payload), hashlib.sha256(payload).hexdigest()),
                        session.fingerprint(path) if session.exists(path) else None,
                    ),
                )
            )
        )
        if state is TransactionState.RESTORED:
            session.restore_transaction(result.recovery)
        return result.recovery.journal_path


def test_selection_cleans_every_terminal_journal_without_media_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    journals = (
        _terminal_journal(device, TransactionState.COMMITTED),
        _terminal_journal(device, TransactionState.RESTORED),
        _terminal_journal(device, TransactionState.COMMITTED),
    )

    def forbidden_inspect(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Terminal cleanup must not inspect or hash transaction media")

    monkeypatch.setattr(FilesystemSession, "inspect_transaction", forbidden_inspect)
    try:
        discovery = device.coordinator.discover_devices()
        assert all((device.root / str(path)).exists() for path in journals)
        active = device.coordinator.select_device(discovery.candidates[0].id)
        assert active.library.tracks
        assert not device.coordinator.sync_cleanup_path
        assert all(not (device.root / str(path.parent)).exists() for path in journals)
        assert not any("cleanup" in issue.code for issue in active.candidate.issues)
        device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("corrupt", [False, True])
def test_selection_checks_every_journal_before_cleaning_terminal_files(
    tmp_path: Path, corrupt: bool
) -> None:
    device = build_device(tmp_path)
    terminal = _terminal_journal(device, TransactionState.COMMITTED)
    interrupted = create_transaction_journal(device, TransactionState.PREPARED)
    if corrupt:
        (device.root / interrupted).write_bytes(b"invalid journal")
    try:
        candidate = device.coordinator.discover_devices().candidates[0]
        with pytest.raises(SyncRecoveryRequiredError):
            device.coordinator.select_device(candidate.id)
        assert (device.root / str(terminal)).exists()
        assert (device.root / interrupted).exists()
        device.assert_original()
    finally:
        device.coordinator.close()


def test_selection_preserves_foreign_and_declined_terminal_journals(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    foreign = _terminal_journal(device, TransactionState.COMMITTED)
    declined = _terminal_journal(device, TransactionState.RESTORED)
    declined_file = device.root / str(declined)
    declined_file.rename(declined_file.with_name("declined-transaction.json"))
    foreign_data = (device.root / str(foreign)).read_bytes()
    device.platform.replace_identity(
        device.root, device_id="another-device", volume_id="another-volume"
    )
    try:
        candidate = device.coordinator.discover_devices().candidates[0]
        active = device.coordinator.select_device(candidate.id)
        assert active.library.tracks
        assert not device.coordinator.sync_cleanup_path
        assert (device.root / str(foreign)).read_bytes() == foreign_data
        assert declined_file.with_name("declined-transaction.json").exists()
        device.assert_original()
    finally:
        device.coordinator.close()


def test_selection_cleanup_failure_keeps_its_reason_and_continues_other_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    blocked = _terminal_journal(device, TransactionState.COMMITTED)
    other = _terminal_journal(device, TransactionState.COMMITTED)
    finalize = FilesystemSession.finalize_committed_transaction

    def blocked_cleanup(session: FilesystemSession, path: DevicePath) -> FlushResult:
        if path == blocked:
            raise StorageOperationError("Recovery file is in use")
        return finalize(session, path)

    monkeypatch.setattr(
        FilesystemSession, "finalize_committed_transaction", blocked_cleanup
    )
    try:
        candidate = device.coordinator.discover_devices().candidates[0]
        active = device.coordinator.select_device(candidate.id)
        assert device.coordinator.sync_cleanup_path == str(blocked)
        assert (device.root / str(blocked)).exists()
        assert not (device.root / str(other)).exists()
        issue = next(
            issue
            for issue in active.candidate.issues
            if issue.code is DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING
        )
        assert "Recovery file is in use" in issue.detail
        monkeypatch.setattr(
            FilesystemSession, "finalize_committed_transaction", finalize
        )
        reloaded = device.coordinator.select_device(candidate.id)
        assert not (device.root / str(blocked)).exists()
        assert not device.coordinator.sync_cleanup_path
        assert not any("cleanup" in issue.code for issue in reloaded.candidate.issues)
        device.assert_original()
    finally:
        device.coordinator.close()


def test_selection_post_cleanup_flush_failure_does_not_offer_missing_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    journal = _terminal_journal(device, TransactionState.COMMITTED)
    finalize = FilesystemSession.finalize_committed_transaction

    def incomplete_flush(session: FilesystemSession, path: DevicePath) -> FlushResult:
        result = finalize(session, path)
        if path == journal:
            raise TransactionDurabilityPendingError(
                "Final device flush failed",
                TransactionFailureFacts(path, TransactionState.COMMITTED, True, True),
            )
        return result

    monkeypatch.setattr(
        FilesystemSession, "finalize_committed_transaction", incomplete_flush
    )
    try:
        candidate = device.coordinator.discover_devices().candidates[0]
        active = device.coordinator.select_device(candidate.id)
        assert not (device.root / str(journal)).exists()
        assert not device.coordinator.sync_cleanup_path
        issue = next(
            issue
            for issue in active.candidate.issues
            if issue.code is DeviceCandidateIssueCode.TRANSACTION_CLEANUP_FLUSH_PENDING
        )
        assert "Safely eject" in issue.detail
        device.assert_original()
    finally:
        device.coordinator.close()


def test_keep_current_contents_reload_does_not_clean_other_recovery_copies(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    journal = _terminal_journal(device, TransactionState.COMMITTED)
    interrupted = create_transaction_journal(device, TransactionState.PREPARED)
    try:
        active = device.coordinator.keep_sync_contents(interrupted)
        assert active.library.tracks
        assert (device.root / str(journal)).exists()
        assert not (device.root / interrupted).exists()
        device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("automatic", [False, True])
def test_discovery_preserves_cleanup_choice_until_journal_is_actually_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, automatic: bool
) -> None:
    device = build_device(tmp_path)
    journal = _terminal_journal(device, TransactionState.COMMITTED)
    finalize = FilesystemSession.finalize_committed_transaction

    def blocked_cleanup(session: FilesystemSession, path: DevicePath) -> FlushResult:
        if path == journal:
            raise StorageOperationError("Recovery file is in use")
        return finalize(session, path)

    monkeypatch.setattr(
        FilesystemSession, "finalize_committed_transaction", blocked_cleanup
    )
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    devices = DeviceController(device.coordinator, TrackTableModel(), settings)
    controller = SyncController(
        SyncExecutionStub(), LibraryWorkspace(), devices, settings
    )
    busy_events: list[bool] = []
    devices.busyChanged.connect(busy_events.append)

    def refresh() -> None:
        if automatic:
            before = len(busy_events)
            devices.start_auto_refresh()
            wait_for(lambda: len(busy_events) >= before + 2 and not devices.busy)
            devices.stop_auto_refresh()
        else:
            devices.refresh_devices()
            wait_for(lambda: not devices.busy)

    try:
        devices.refresh_devices()
        wait_for(lambda: not devices.busy)
        devices.select_device(devices.discovery.candidates[0].id.value)
        wait_for(lambda: not devices.busy)
        assert controller.needs_cleanup
        refresh()
        assert controller.needs_cleanup
        assert controller.result is not None
        assert "Recovery file is in use" in controller.result.issues[-1].detail
        assert (device.root / str(journal)).exists()
        if automatic:
            result = controller.result
            refresh()
            assert controller.result is result

        monkeypatch.setattr(
            FilesystemSession, "finalize_committed_transaction", finalize
        )
        device.coordinator.cleanup_sync_journal(str(journal))
        refresh()
        assert not controller.needs_cleanup
        assert not device.coordinator.sync_cleanup_path
        assert devices.active_ipod is not None
        assert not any(
            issue.code is DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING
            for issue in devices.active_ipod.candidate.issues
        )
    finally:
        controller.shutdown()
        devices.shutdown()
