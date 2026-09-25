"""Public QWidget behavior for the Backup Archive v4 page."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
)

from iOpenPod.app.backup_controller import (
    BackupController,
    BackupOperation,
    BackupOperationFailure,
)
from iOpenPod.app.backups.models import (
    ArchiveKey,
    BackupCatalog,
    BackupDeviceIdentity,
    BackupDeviceInfo,
    BackupIdentityClaim,
    BackupIdentityClaimKind,
    BackupInventory,
    BackupProgress,
    BackupReason,
    BackupStage,
    LegacyIdentityClaim,
    RestoreRecoveryOutcome,
    RestoreRecoveryPhase,
    RestoreRecoveryRecord,
    SnapshotIdentityState,
    SnapshotInfo,
)
from iOpenPod.app.backups.outcomes import (
    BackupFailure,
    BackupFailureCode,
    DeviceWritePolicy,
    RestoreIncomplete,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.GUI.pages.backup_page import BackupPage, BackupSnapshotCard
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.browser_chrome import PageHeader, SourceListPanel
from storage import DevicePath

if TYPE_CHECKING:
    import pytest

    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.GUI.presentation.backup_messages import BackupMessage


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


class _Controller(QObject):
    inventoryChanged = Signal(object)
    catalogChanged = Signal(object)
    progressChanged = Signal(object)
    busyChanged = Signal(bool)
    operationFailed = Signal(object)
    operationCancelled = Signal(object)
    operationCompleted = Signal(object, object)
    deviceWritePolicyChanged = Signal(object)

    def __init__(
        self,
        backup_root: Path,
        *,
        inventory: BackupInventory | None = None,
        catalog: BackupCatalog | None = None,
    ) -> None:
        super().__init__()
        self.backup_root = backup_root
        self.inventory = inventory or BackupInventory(())
        self.catalog = catalog
        self.busy = False
        self.device_write_policy = DeviceWritePolicy.ALLOWED
        self.imported_sources: list[str] = []
        self.restore_calls: list[tuple[str, str, bool]] = []
        self.recovery_calls: list[str] = []

    def refresh(self) -> None:
        pass

    def create_snapshot(self) -> None:
        pass

    def archive_path(self, device_id: str = "") -> Path:
        return self.backup_root / "resolved-archive" / device_id

    def cancel(self) -> None:
        pass

    def load_catalog(self, _device_id: str) -> None:
        if self.catalog is not None:
            self.catalogChanged.emit(self.catalog)

    def import_original(self, source: str) -> bool:
        self.imported_sources.append(source)
        return True

    def restore_snapshot(
        self,
        device_id: str,
        snapshot_id: str,
        *,
        legacy_confirmed: bool = False,
    ) -> bool:
        self.restore_calls.append((device_id, snapshot_id, legacy_confirmed))
        return True

    def recover_restore(self, recovery_id: str) -> bool:
        self.recovery_calls.append(recovery_id)
        return True

    def export_snapshot(self, *_args: object) -> None:
        pass

    def delete_snapshot(self, *_args: object) -> None:
        pass

    def update_note(self, *_args: object) -> None:
        pass


class _Devices(QObject):
    activeIPodChanged = Signal(object)
    busyChanged = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.active_ipod = object()
        self.busy = False


def build_backup_page(
    tmp_path: Path,
    *,
    inventory: BackupInventory | None = None,
    catalog: BackupCatalog | None = None,
) -> tuple[BackupPage, _Controller]:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    controller = _Controller(
        tmp_path / "native",
        inventory=inventory,
        catalog=catalog,
    )
    devices = _Devices()
    page = BackupPage(
        cast("BackupController", controller),
        cast("DeviceController", devices),
        settings,
        ThemeManager(APPLICATION, settings),
    )
    return page, controller


def _pending_recovery() -> RestoreRecoveryRecord:
    identity = BackupDeviceIdentity(
        (
            BackupIdentityClaim.from_hardware(
                BackupIdentityClaimKind.PRODUCT_SERIAL,
                "SERIAL-ONE",
            ),
        )
    )
    return RestoreRecoveryRecord(
        id="1" * 32,
        target_archive_key=ArchiveKey("ipod--target"),
        safety_archive_key=ArchiveKey("ipod--safety"),
        current_identity=identity,
        target_snapshot_id="target-snapshot",
        safety_snapshot_id="safety-snapshot",
        operation_journal=DevicePath(f".iopenpod-recovery/{'2' * 32}/transaction.json"),
        recovery_material_identity="3" * 64,
        phase=RestoreRecoveryPhase.RECOVERY_REQUIRED,
        outcome=RestoreRecoveryOutcome.UNRESOLVED,
        created_at="2026-09-12T12:00:00+00:00",
        updated_at="2026-09-12T12:01:00+00:00",
    )


def test_page_uses_shared_compact_header_and_source_list(tmp_path: Path) -> None:
    inventory = BackupInventory(
        (BackupDeviceInfo("roadpod", "RoadPod", snapshot_count=1),)
    )
    page, _controller = build_backup_page(tmp_path, inventory=inventory)

    try:
        page.resize(1180, 900)
        page.show()
        APPLICATION.processEvents()
        header = page.findChild(PageHeader, "backupsToolbar")
        source_list = page.findChild(SourceListPanel, "backupDeviceRail")

        assert header is not None and header.height() == LAYOUT.page_header_height
        assert source_list is not None
        assert source_list.title_label.text() == "Your iPods"
        assert source_list.count_label.text() == "1"
        splitter = page.findChild(QSplitter, "backupBrowserSplitter")
        assert splitter is not None
        assert splitter.count() == 2
        assert splitter.handleWidth() == LAYOUT.source_list_splitter_handle_width
        assert not splitter.childrenCollapsible()
        assert all(
            not splitter.isCollapsible(index) for index in range(splitter.count())
        )
        original_rail_width = splitter.sizes()[0]
        splitter.moveSplitter(original_rail_width + 40, 1)
        APPLICATION.processEvents()
        assert splitter.sizes()[0] > original_rail_width
    finally:
        page.close()
        page.deleteLater()


def test_pending_recovery_banner_explains_and_starts_bounded_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _pending_recovery()
    page, controller = build_backup_page(
        tmp_path,
        inventory=BackupInventory((), pending_recoveries=(record,)),
    )
    questions: list[str] = []

    def answer(
        _parent: object,
        _title: str,
        text: str,
        *_args: object,
        **_kwargs: object,
    ) -> QMessageBox.StandardButton:
        questions.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", answer)

    try:
        page.show()
        APPLICATION.processEvents()
        text = page.findChild(QLabel, "backupRecoveryText")
        recover = page.findChild(QPushButton, "backupRecoverRestore")

        assert text is not None and "safety-snapshot" in text.text()
        assert recover is not None and recover.isEnabled()
        recover.click()

        assert controller.recovery_calls == [record.id]
        assert "return the iPod" in questions[-1]
        assert "Safety Snapshot" in questions[-1]
    finally:
        page.close()
        page.deleteLater()


def test_import_button_explains_read_only_conversion_before_starting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, controller = build_backup_page(tmp_path)
    source = tmp_path / "Original Backups"
    questions: list[tuple[str, str]] = []

    def choose_source(*_args: object, **_kwargs: object) -> str:
        return str(source)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", choose_source)

    def answer(
        _parent: object,
        title: str,
        text: str,
        *_args: object,
        **_kwargs: object,
    ) -> QMessageBox.StandardButton:
        questions.append((title, text))
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", answer)

    try:
        button = page.findChild(QPushButton, "backupImportOriginal")
        assert button is not None
        button.click()

        assert controller.imported_sources == [str(source)]
        assert "Original iOpenPod" in questions[-1][1]
        assert "will not be changed" in questions[-1][1]
        assert "saved backups" in questions[-1][1]
        empty_detail = page.findChild(QLabel, "backupEmptyDetail")
        assert empty_detail is not None
        assert "Import Backups" in empty_detail.text()
        assert "in Settings" not in empty_detail.text()
    finally:
        page.close()
        page.deleteLater()


def test_worker_failure_is_presented_for_backup_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, _controller = build_backup_page(tmp_path)
    failure = BackupFailure(
        BackupFailureCode.ARCHIVE_UNAVAILABLE,
        "The backup location is unavailable.",
        "Reconnect it and retry.",
        "permission denied",
    )
    messages: list[object] = []
    monkeypatch.setattr(page, "_show_backup_message", messages.append)

    try:
        page.show()
        APPLICATION.processEvents()
        page._operation_failed(  # pyright: ignore[reportPrivateUsage]
            BackupOperationFailure(
                BackupOperation.CREATE,
                failure.summary,
                "OSError",
                failure=failure,
            )
        )

        assert len(messages) == 1
        message = cast("BackupMessage", messages[0])
        assert message.title == "Backup Operation Failed"
        assert message.next_step == failure.action
        assert "permission denied" in message.diagnostic_detail
    finally:
        page.close()
        page.deleteLater()


def test_capture_progress_bar_uses_bytes_instead_of_file_count(
    tmp_path: Path,
) -> None:
    page, controller = build_backup_page(tmp_path)

    try:
        controller.progressChanged.emit(
            BackupProgress(
                BackupStage.CAPTURING,
                current=1,
                total=2,
                message="Capturing 2 of 2 files…",
                completed_bytes=75,
                total_bytes=100,
            )
        )
        APPLICATION.processEvents()
        bar = page.findChild(QProgressBar, "backupProgressBar")

        assert bar is not None
        assert bar.maximum() == 10_000
        assert bar.value() == 7_500
    finally:
        page.close()
        page.deleteLater()


def test_note_edit_remains_retryable_until_a_refreshed_catalog_confirms_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = SnapshotInfo(
        "snapshot-1",
        "2026-09-12T12:00:00+00:00",
        "ipod--opaque",
        "RoadPod",
        note="old note",
    )
    card = BackupSnapshotCard(snapshot, can_restore=False, restore_hint="")
    changes: list[tuple[str, str]] = []

    def record_change(snapshot_id: str, note: str) -> None:
        changes.append((snapshot_id, note))

    card.noteChanged.connect(record_change)
    edit = card.findChild(QAction, "backupEditNote")
    assert edit is not None

    def edit_note(dialog: QInputDialog) -> int:
        assert dialog.textValue() == "old note"
        editor = dialog.findChild(QLineEdit)
        assert editor is not None and editor.maxLength() == 4_000
        dialog.setTextValue("new note")
        return QInputDialog.DialogCode.Accepted

    monkeypatch.setattr(QInputDialog, "exec", edit_note)
    edit.trigger()
    edit.trigger()

    assert changes == [
        ("snapshot-1", "new note"),
        ("snapshot-1", "new note"),
    ]
    card.deleteLater()


def test_imported_snapshot_card_labels_reason_as_import() -> None:
    snapshot = SnapshotInfo(
        "snapshot-1",
        "2026-09-12T12:00:00+00:00",
        "ipod--opaque",
        "RoadPod",
        reason=BackupReason.IMPORT,
    )
    card = BackupSnapshotCard(snapshot, can_restore=False, restore_hint="")

    reason = card.findChild(QLabel, "backupSnapshotSummary")

    assert reason is not None
    assert "Imported backup" in reason.text()
    card.deleteLater()


def test_open_folder_uses_the_controller_resolved_archive_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = BackupDeviceInfo("ipod--opaque", "RoadPod", snapshot_count=1)
    page, controller = build_backup_page(tmp_path, inventory=BackupInventory((device,)))
    archive = controller.archive_path(device.device_id)
    archive.mkdir(parents=True)
    opened: list[Path] = []

    def open_url(url: object) -> bool:
        opened.append(Path(cast("QUrl", url).toLocalFile()))
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)

    try:
        page.show()
        APPLICATION.processEvents()
        button = page.findChild(QPushButton, "backupOpenFolder")
        assert button is not None and button.isEnabled()

        button.click()

        assert opened == [archive]
    finally:
        page.close()
        page.deleteLater()


def test_legacy_snapshot_requires_explicit_confirmation_for_each_restore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_key = "ORIGINAL-ROADPOD"
    device = BackupDeviceInfo(
        ArchiveKey.for_legacy(original_key).value,
        "RoadPod",
        snapshot_count=1,
        has_backup_identifier=True,
        connected=True,
    )
    snapshot = SnapshotInfo(
        "legacy-snapshot",
        "2026-09-12T12:00:00+00:00",
        device.device_id,
        device.device_name,
        identity_state=SnapshotIdentityState.LEGACY_UNKNOWN,
        legacy_identity_claim=LegacyIdentityClaim.from_original_key(original_key),
    )
    catalog = BackupCatalog(device, (snapshot,), stored_size=128)
    page, controller = build_backup_page(
        tmp_path,
        inventory=BackupInventory((device,), connected_device_id=device.device_id),
        catalog=catalog,
    )
    questions: list[tuple[str, str]] = []
    answers = iter([QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes])

    def answer(
        _parent: object,
        title: str,
        text: str,
        *_args: object,
        **_kwargs: object,
    ) -> QMessageBox.StandardButton:
        questions.append((title, text))
        return next(answers)

    monkeypatch.setattr(QMessageBox, "question", answer)

    try:
        APPLICATION.processEvents()
        restore = page.findChild(QPushButton, "backupRestoreSnapshot")
        assert restore is not None and restore.isEnabled()
        restore.click()

        assert controller.restore_calls == []

        restore.click()

        assert "Imported Backup" in questions[-1][0]
        assert "Original iOpenPod" in questions[-1][1]
        assert "connected iPod is the one this backup belongs to" in questions[-1][1]
        assert "removing files" in questions[-1][1]
        assert "safety backup" in questions[-1][1]
        assert controller.restore_calls == [(device.device_id, snapshot.id, True)]
    finally:
        page.close()
        page.deleteLater()


def test_incomplete_restore_outcome_shows_recovery_material_and_blocks_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page, controller = build_backup_page(tmp_path)
    dialogs: list[QMessageBox] = []

    def capture_dialog(dialog: QMessageBox) -> int:
        dialogs.append(dialog)
        return int(QMessageBox.StandardButton.Ok)

    monkeypatch.setattr(QMessageBox, "exec", capture_dialog)
    outcome = RestoreIncomplete(
        "target-snapshot",
        "safety-snapshot",
        DevicePath(".iopenpod-recovery/restore.json"),
        BackupFailure(
            BackupFailureCode.VERIFICATION_FAILED,
            "Restored content could not be verified.",
            "Recover the interrupted restore.",
            detail="hash mismatch in file 14",
        ),
    )

    try:
        page.show()
        controller.operationCompleted.emit(BackupOperation.RESTORE, outcome)

        assert len(dialogs) == 1
        dialog = dialogs[0]
        assert dialog.windowTitle() == "Restore Incomplete — Recovery Required"
        assert "safety-snapshot" in dialog.text()
        assert ".iopenpod-recovery/restore.json" in dialog.text()
        assert "Keep the iPod connected" in dialog.informativeText()
        assert "Do not use, sync, or write to it" in dialog.informativeText()
        assert "hash mismatch" in dialog.detailedText()
    finally:
        page.close()
        page.deleteLater()


def test_restore_write_block_disables_restore_but_keeps_read_only_export(
    tmp_path: Path,
) -> None:
    device = BackupDeviceInfo(
        "roadpod",
        "RoadPod",
        snapshot_count=1,
        has_backup_identifier=True,
        connected=True,
    )
    snapshot = SnapshotInfo(
        "snapshot-1",
        "2026-09-12T12:00:00+00:00",
        device.device_id,
        device.device_name,
        identity_state=SnapshotIdentityState.NATIVE,
    )
    page, controller = build_backup_page(
        tmp_path,
        inventory=BackupInventory((device,), connected_device_id=device.device_id),
        catalog=BackupCatalog(device, (snapshot,), stored_size=128),
    )

    try:
        APPLICATION.processEvents()
        restore = page.findChild(QPushButton, "backupRestoreSnapshot")
        export = page.findChild(QAction, "backupExportSnapshot")
        assert restore is not None and restore.isEnabled()
        assert export is not None and export.isEnabled()

        controller.device_write_policy = DeviceWritePolicy.BLOCKED_UNTIL_RECOVERY
        controller.deviceWritePolicyChanged.emit(controller.device_write_policy)

        assert not restore.isEnabled()
        assert export.isEnabled()
    finally:
        page.close()
        page.deleteLater()


def test_explicitly_unstable_imported_snapshot_cannot_start_restore(
    tmp_path: Path,
) -> None:
    device = BackupDeviceInfo(
        "legacy--unstable",
        "Unknown iPod",
        snapshot_count=1,
        has_backup_identifier=True,
        connected=True,
    )
    snapshot = SnapshotInfo(
        "unstable-snapshot",
        "2026-09-12T12:00:00+00:00",
        device.device_id,
        device.device_name,
        identity_state=SnapshotIdentityState.UNSTABLE,
    )
    page, _controller = build_backup_page(
        tmp_path,
        inventory=BackupInventory((device,), connected_device_id=device.device_id),
        catalog=BackupCatalog(device, (snapshot,), stored_size=128),
    )

    try:
        APPLICATION.processEvents()
        restore = page.findChild(QPushButton, "backupRestoreSnapshot")

        assert restore is not None and not restore.isEnabled()
        assert "can't confirm which iPod" in restore.toolTip()
    finally:
        page.close()
        page.deleteLater()


def test_card_keeps_secondary_actions_in_menu_and_details_on_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = SnapshotInfo(
        "snapshot-1",
        "2026-09-12T12:00:00+00:00",
        "roadpod",
        "RoadPod",
        file_count=1_234,
        total_size=2_048,
        files_added=12,
        files_removed=3,
        files_changed=4,
        note="<b>Before the road trip</b>",
    )
    card = BackupSnapshotCard(snapshot, can_restore=True, restore_hint="")
    restored: list[str] = []
    exported: list[str] = []
    deleted: list[str] = []
    dialogs: list[QMessageBox] = []
    card.restoreRequested.connect(restored.append)
    card.exportRequested.connect(exported.append)
    card.deleteRequested.connect(deleted.append)

    def capture_dialog(dialog: QMessageBox) -> int:
        dialogs.append(dialog)
        return int(QMessageBox.StandardButton.Ok)

    monkeypatch.setattr(QMessageBox, "exec", capture_dialog)
    try:
        card.resize(600, 140)
        card.show()
        APPLICATION.processEvents()
        assert {button.text() for button in card.findChildren(QPushButton)} == {
            "Restore…",
            "More",
        }
        assert card.findChild(QLineEdit) is None
        note = card.findChild(QLabel, "backupSnapshotNote")
        assert note is not None and note.isVisible()
        assert note.textFormat() == Qt.TextFormat.PlainText
        assert note.text() == snapshot.note
        assert not any("added" in label.text() for label in card.findChildren(QLabel))
        more = card.findChild(QPushButton, "backupSnapshotMore")
        assert more is not None
        actions = more.menu().actions()
        assert [action.text() for action in actions] == [
            "Edit Note…",
            "Export to Folder…",
            "Details…",
            "",
            "Delete Backup…",
        ]
        assert actions[3].isSeparator()
        actions[1].trigger()
        actions[4].trigger()
        restore = card.findChild(QPushButton, "backupRestoreSnapshot")
        assert restore is not None
        restore.click()
        assert restored == exported == deleted == [snapshot.id]
        actions[2].trigger()
        assert len(dialogs) == 1
        assert "1,234 files" in dialogs[0].informativeText()
        assert "12 added · 3 removed · 4 changed" in dialogs[0].informativeText()
        assert snapshot.id in dialogs[0].detailedText()
    finally:
        card.close()
        card.deleteLater()


def test_invalid_card_keeps_diagnostics_available_and_mutations_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = BackupSnapshotCard(
        SnapshotInfo(
            "broken",
            "2026-09-12",
            "roadpod",
            "RoadPod",
            is_valid=False,
            validation_error="Catalog checksum mismatch",
        ),
        can_restore=True,
        restore_hint="",
    )
    diagnostics: list[str] = []

    def capture_dialog(dialog: QMessageBox) -> int:
        diagnostics.append(dialog.detailedText())
        return int(QMessageBox.StandardButton.Ok)

    monkeypatch.setattr(QMessageBox, "exec", capture_dialog)
    try:
        for name in ("backupEditNote", "backupExportSnapshot", "backupDeleteSnapshot"):
            action = card.findChild(QAction, name)
            assert action is not None and not action.isEnabled()
        restore = card.findChild(QPushButton, "backupRestoreSnapshot")
        assert restore is not None and not restore.isEnabled()
        details = card.findChild(QAction, "backupSnapshotDetails")
        assert details is not None and details.isEnabled()
        details.trigger()
        assert diagnostics == ["Backup ID: broken\n\nCatalog checksum mismatch"]
        note = card.findChild(QLabel, "backupSnapshotNote")
        assert note is not None and note.isHidden()
    finally:
        card.deleteLater()


def test_busy_card_disables_actions_and_keeps_details_available() -> None:
    card = BackupSnapshotCard(
        SnapshotInfo("snapshot-1", "2026-09-12", "roadpod", "RoadPod"),
        can_restore=True,
        restore_hint="",
    )
    try:
        card.set_actions_enabled(False)
        for name in ("backupEditNote", "backupExportSnapshot", "backupDeleteSnapshot"):
            action = card.findChild(QAction, name)
            assert action is not None and not action.isEnabled()
        details = card.findChild(QAction, "backupSnapshotDetails")
        assert details is not None and details.isEnabled()
        restore = card.findChild(QPushButton, "backupRestoreSnapshot")
        assert restore is not None and not restore.isEnabled()
        card.set_actions_enabled(True)
        assert restore.isEnabled()
    finally:
        card.deleteLater()


def test_cancelled_or_unchanged_note_does_not_request_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    card = BackupSnapshotCard(
        SnapshotInfo("snapshot-1", "2026-09-12", "roadpod", "RoadPod", note="Keep"),
        can_restore=False,
        restore_hint="",
    )
    changes: list[tuple[str, str]] = []

    def record_change(key: str, note: str) -> None:
        changes.append((key, note))

    card.noteChanged.connect(record_change)
    edit = card.findChild(QAction, "backupEditNote")
    assert edit is not None
    replies = iter(
        [
            ("Different", QInputDialog.DialogCode.Rejected),
            (" Keep ", QInputDialog.DialogCode.Accepted),
            ("", QInputDialog.DialogCode.Accepted),
        ]
    )

    def edit_note(dialog: QInputDialog) -> int:
        value, result = next(replies)
        dialog.setTextValue(value)
        return result

    monkeypatch.setattr(QInputDialog, "exec", edit_note)
    try:
        edit.trigger()
        edit.trigger()
        assert changes == []
        edit.trigger()
        assert changes == [("snapshot-1", "")]
    finally:
        card.deleteLater()


def test_browsing_disconnected_ipod_does_not_offer_backup_of_another_ipod(
    tmp_path: Path,
) -> None:
    device = BackupDeviceInfo("roadpod", "RoadPod", snapshot_count=0)
    page, _controller = build_backup_page(
        tmp_path,
        inventory=BackupInventory((device,), connected_device_id="another-ipod"),
        catalog=BackupCatalog(device, (), stored_size=0),
    )
    try:
        APPLICATION.processEvents()
        create = page.findChild(QPushButton, "backupCreate")
        assert create is not None and not create.isEnabled()
        hint = page.findChild(QLabel, "backupDeviceSummary")
        assert hint is not None and "Connect this iPod" in hint.text()
    finally:
        page.close()
        page.deleteLater()


def test_empty_page_gives_wrapped_instructions_without_clipping(tmp_path: Path) -> None:
    page, _controller = build_backup_page(tmp_path)
    try:
        page.resize(704, 620)
        page.show()
        APPLICATION.processEvents()
        detail = page.findChild(QLabel, "backupEmptyDetail")
        assert detail is not None and detail.isVisible()
        assert detail.height() >= detail.heightForWidth(detail.width())
    finally:
        page.close()
        page.deleteLater()
