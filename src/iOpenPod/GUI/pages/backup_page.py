"""Two-pane browser for Backup Archive v4 and explicit legacy import."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.backup_controller import (
    BackupController,
    BackupOperation,
    BackupOperationFailure,
)
from iOpenPod.app.backups import (
    BackupCatalog,
    BackupExportResult,
    BackupInventory,
    BackupProgress,
    BackupRestoreResult,
    BackupStage,
    SnapshotIdentityState,
    SnapshotInfo,
)
from iOpenPod.app.backups.outcomes import (
    BackupTerminalOutcome,
    BrowseCancelled,
    BrowseCompleted,
    BrowseFailed,
    CaptureCancelled,
    CaptureCreated,
    CaptureFailed,
    CaptureUnchanged,
    DeviceWritePolicy,
    ExportCancelled,
    ExportCompleted,
    ExportFailed,
    ImportCancelled,
    ImportCompleted,
    ImportFailed,
    RestoreCancelled,
    RestoreCompleted,
    RestoreDurabilityPending,
    RestoreIncomplete,
    RestorePreMutationFailure,
    RestoreRecovered,
    RestoreUnchanged,
)
from iOpenPod.app.core.settings.definitions import BACKUP_LOCATION
from iOpenPod.GUI.presentation.backup_messages import (
    BackupMessage,
    BackupMessageSeverity,
    backup_message_for,
)
from iOpenPod.GUI.presentation.device_images import device_pixmap
from iOpenPod.GUI.presentation.theme.backup_styles import render_backup_page_style
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.browser_chrome import PageHeader, SourceListPanel
from iOpenPod.GUI.widgets.eta_label import EtaLabel
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager

_DEVICE_ART_SIZE = 84


def _format_size(size: int) -> str:
    value = float(max(0, size))
    units = ("bytes", "KB", "MB", "GB", "TB")
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "bytes":
        return f"{int(value):,} {unit}"
    return f"{value:.1f} {unit}"


def _terminal_outcome(value: object) -> BackupTerminalOutcome | None:
    match value:
        case (
            BrowseCompleted()
            | BrowseCancelled()
            | BrowseFailed()
            | CaptureCreated()
            | CaptureUnchanged()
            | CaptureCancelled()
            | CaptureFailed()
            | ExportCompleted()
            | ExportCancelled()
            | ExportFailed()
            | ImportCompleted()
            | ImportCancelled()
            | ImportFailed()
            | RestoreCompleted()
            | RestoreUnchanged()
            | RestoreRecovered()
            | RestoreDurabilityPending()
            | RestoreCancelled()
            | RestorePreMutationFailure()
            | RestoreIncomplete()
        ):
            return value
        case _:
            return None


class _BackupDeviceArt(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._image_name = "iPodGeneric.png"
        self.setObjectName("backupDeviceArt")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(_DEVICE_ART_SIZE, _DEVICE_ART_SIZE)
        self._refresh()

    def set_image(self, image_name: str) -> None:
        resolved = image_name or "iPodGeneric.png"
        if resolved != self._image_name:
            self._image_name = resolved
            self._refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in {
            QEvent.Type.DevicePixelRatioChange,
            QEvent.Type.ScreenChangeInternal,
        }:
            self._refresh()
        super().changeEvent(event)

    def _refresh(self) -> None:
        self.setPixmap(
            device_pixmap(
                self._image_name,
                _DEVICE_ART_SIZE,
                self.devicePixelRatioF(),
            )
        )


class BackupSnapshotCard(QFrame):
    """One snapshot summary with independently gated archive actions."""

    restoreRequested = Signal(str)
    exportRequested = Signal(str)
    deleteRequested = Signal(str)
    noteChanged = Signal(str, str)

    def __init__(
        self,
        snapshot: SnapshotInfo,
        *,
        can_restore: bool,
        restore_hint: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.snapshot = snapshot
        self._stored_note = snapshot.note
        self._can_restore = can_restore and snapshot.is_valid
        self.setObjectName("backupSnapshotCard")

        title = QLabel(snapshot.display_date, self)
        title.setObjectName("backupSnapshotDate")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)

        summary = QLabel(
            self.tr("%1 · %2")
            .replace("%1", self._reason_label(snapshot))
            .replace("%2", _format_size(snapshot.total_size)),
            self,
        )
        summary.setObjectName("backupSnapshotSummary")
        summary.setWordWrap(True)
        self._note = QLabel(snapshot.note, self)
        self._note.setObjectName("backupSnapshotNote")
        self._note.setTextFormat(Qt.TextFormat.PlainText)
        self._note.setWordWrap(True)
        self._note.setVisible(bool(snapshot.note))

        details = QVBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(LAYOUT.space_2xs)
        details.addWidget(title)
        details.addWidget(summary)
        if not snapshot.is_valid:
            invalid = QLabel(
                self.tr(
                    "This backup can't be read. Open Details for more information."
                ),
                self,
            )
            invalid.setObjectName("backupSnapshotInvalid")
            invalid.setWordWrap(True)
            invalid.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByKeyboard
                | Qt.TextInteractionFlag.TextSelectableByMouse
            )
            details.addWidget(invalid)

        self._restore = ActionButton(
            self.tr("Restore…"), self, kind=ActionButtonKind.SECONDARY
        )
        self._restore.setObjectName("backupRestoreSnapshot")
        self._restore.setToolTip(restore_hint)
        self._restore.clicked.connect(
            lambda: self.restoreRequested.emit(self.snapshot.id)
        )

        self._more = ActionButton(self.tr("More"), self, kind=ActionButtonKind.QUIET)
        self._more.setObjectName("backupSnapshotMore")
        self._more.setAccessibleName(
            self.tr("More actions for backup from %1").replace(
                "%1", snapshot.display_date
            )
        )
        menu = QMenu(self._more)
        self._edit_note = menu.addAction(
            self.tr("Edit Note…") if snapshot.note else self.tr("Add Note…")
        )
        self._edit_note.setObjectName("backupEditNote")
        self._edit_note.triggered.connect(self._edit_snapshot_note)
        self._export = menu.addAction(self.tr("Export to Folder…"))
        self._export.setObjectName("backupExportSnapshot")
        self._export.triggered.connect(
            lambda: self.exportRequested.emit(self.snapshot.id)
        )
        show_details = menu.addAction(self.tr("Details…"))
        show_details.setObjectName("backupSnapshotDetails")
        show_details.triggered.connect(self._show_details)
        menu.addSeparator()
        self._delete = menu.addAction(self.tr("Delete Backup…"))
        self._delete.setObjectName("backupDeleteSnapshot")
        self._delete.triggered.connect(
            lambda: self.deleteRequested.emit(self.snapshot.id)
        )
        self._more.setMenu(menu)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(LAYOUT.space_xs)
        actions.addWidget(self._restore)
        actions.addWidget(self._more)

        heading = QHBoxLayout()
        heading.setSpacing(LAYOUT.space_md)
        heading.addLayout(details, 1)
        heading.addLayout(actions)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_md,
            LAYOUT.space_md,
            LAYOUT.space_md,
            LAYOUT.space_md,
        )
        layout.setSpacing(LAYOUT.space_xs)
        layout.addLayout(heading)
        layout.addWidget(self._note)
        self.set_actions_enabled(True)

    def set_actions_enabled(
        self,
        enabled: bool,
        *,
        restore_writes_allowed: bool = True,
    ) -> None:
        valid = self.snapshot.is_valid
        self._edit_note.setEnabled(enabled and valid)
        self._export.setEnabled(enabled and valid)
        self._delete.setEnabled(enabled and valid)
        self._restore.setEnabled(
            enabled and restore_writes_allowed and self._can_restore
        )

    def _reason_label(self, snapshot: SnapshotInfo) -> str:
        labels = {
            "manual": self.tr("Saved backup"),
            "import": self.tr("Imported backup"),
            "pre-sync": self.tr("Before Sync"),
            "pre_restore_safety": self.tr("Before restore"),
        }
        return labels.get(snapshot.reason.value, snapshot.reason.value)

    def _delta_label(self, snapshot: SnapshotInfo) -> str:
        if not snapshot.is_valid:
            return self.tr("This backup could not be checked.")
        changes = snapshot.files_added + snapshot.files_removed + snapshot.files_changed
        if changes == 0:
            return self.tr("No file changes recorded.")
        return (
            self.tr("%1 added · %2 removed · %3 changed")
            .replace("%1", str(snapshot.files_added))
            .replace("%2", str(snapshot.files_removed))
            .replace("%3", str(snapshot.files_changed))
        )

    @Slot()
    def _edit_snapshot_note(self) -> None:
        dialog = QInputDialog(self)
        dialog.setWindowTitle(self.tr("Backup Note"))
        dialog.setLabelText(self.tr("Add a reminder about this backup:"))
        dialog.setTextValue(self._stored_note)
        dialog.setOkButtonText(self.tr("Save Note"))
        editor = dialog.findChild(QLineEdit)
        if editor is not None:
            editor.setMaxLength(4_000)
        if dialog.exec() == QInputDialog.DialogCode.Accepted:
            value = dialog.textValue().strip()
            if value != self._stored_note:
                self.noteChanged.emit(self.snapshot.id, value)
        dialog.deleteLater()

    @Slot()
    def _show_details(self) -> None:
        snapshot = self.snapshot
        dialog = QMessageBox(self)
        dialog.setWindowTitle(self.tr("Backup Details"))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(snapshot.display_date)
        dialog.setInformativeText(
            self.tr("%1\n%2 files · %3\n%4")
            .replace("%1", self._reason_label(snapshot))
            .replace("%2", f"{snapshot.file_count:,}")
            .replace("%3", _format_size(snapshot.total_size))
            .replace("%4", self._delta_label(snapshot))
        )
        diagnostic = self.tr("Backup ID: %1").replace("%1", snapshot.id)
        if snapshot.validation_error:
            diagnostic += "\n\n" + snapshot.validation_error
        dialog.setDetailedText(diagnostic)
        dialog.exec()
        dialog.deleteLater()


class BackupPage(QWidget):
    """Browse archives and run safe, asynchronous Backup Snapshot workflows."""

    def __init__(
        self,
        controller: BackupController,
        devices: DeviceController,
        settings: SettingsService,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._devices = devices
        self._settings = settings
        self._theme_manager = theme_manager
        self._inventory = controller.inventory
        self._catalog: BackupCatalog | None = controller.catalog
        self._selected_device_id = ""
        self._pending_catalog_id = ""
        self._cards: list[BackupSnapshotCard] = []
        self._pending_recovery_id = ""
        self._has_loaded = False
        self.setObjectName("backupsPage")

        toolbar = PageHeader(self)
        toolbar.setObjectName("backupsToolbar")
        self._page_header = toolbar
        self._title = toolbar.title_label
        self._title.setObjectName("backupsTitle")
        self._page_header.set_title(self.tr("Backups"))
        self._refresh = ActionButton(
            self.tr("Refresh"), toolbar, kind=ActionButtonKind.QUIET
        )
        self._refresh.setObjectName("backupRefresh")
        self._import_button = ActionButton(
            self.tr("Import Backups…"),
            toolbar,
            kind=ActionButtonKind.SECONDARY,
        )
        self._import_button.setObjectName("backupImportOriginal")
        self._import_button.setToolTip(self.tr("Import backups from Original iOpenPod"))
        toolbar.add_action(self._import_button)
        toolbar.add_action(self._refresh)

        self._recovery_banner = QFrame(self)
        self._recovery_banner.setObjectName("backupRecoveryBanner")
        self._recovery_text = QLabel(self._recovery_banner)
        self._recovery_text.setObjectName("backupRecoveryText")
        self._recovery_text.setWordWrap(True)
        self._recover_button = ActionButton(
            self.tr("Recover iPod"),
            self._recovery_banner,
            kind=ActionButtonKind.PRIMARY,
        )
        self._recover_button.setObjectName("backupRecoverRestore")
        recovery_layout = QHBoxLayout(self._recovery_banner)
        recovery_layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_sm,
            LAYOUT.space_lg,
            LAYOUT.space_sm,
        )
        recovery_layout.setSpacing(LAYOUT.space_md)
        recovery_layout.addWidget(self._recovery_text, 1)
        recovery_layout.addWidget(self._recover_button)
        self._recovery_banner.hide()

        self._content = QStackedWidget(self)
        self._content.setObjectName("backupContent")
        self._empty = self._build_empty()
        self._browser = self._build_browser()
        self._content.addWidget(self._empty)
        self._content.addWidget(self._browser)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self._recovery_banner)
        layout.addWidget(self._content, 1)

        self._refresh.clicked.connect(controller.refresh)
        self._recover_button.clicked.connect(self._recover_restore)
        self._import_button.clicked.connect(self._import_original)
        self._backup_now.clicked.connect(controller.create_snapshot)
        self._open_folder.clicked.connect(self._open_archive)
        self._cancel.clicked.connect(controller.cancel)
        self._devices_list.currentItemChanged.connect(self._device_selected)
        controller.inventoryChanged.connect(self._inventory_changed)
        controller.catalogChanged.connect(self._catalog_changed)
        controller.progressChanged.connect(self._progress_changed)
        controller.busyChanged.connect(self._busy_changed)
        controller.operationFailed.connect(self._operation_failed)
        controller.operationCancelled.connect(self._operation_cancelled)
        controller.operationCompleted.connect(self._operation_completed)
        controller.deviceWritePolicyChanged.connect(self._device_write_policy_changed)
        devices.activeIPodChanged.connect(self._active_ipod_changed)
        devices.busyChanged.connect(self._device_busy_changed)
        settings.settingChanged.connect(self._setting_changed)
        theme_manager.effectiveThemeChanged.connect(self._theme_changed)
        self._apply_styles()
        self._render_inventory()
        self._availability_changed()

    def _build_empty(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("backupEmptyPage")
        art = _BackupDeviceArt(page)
        self._empty_title = QLabel(self.tr("Your first backup starts here"), page)
        self._empty_title.setObjectName("backupEmptyTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_title.setWordWrap(True)
        self._empty_detail = QLabel(
            self.tr(
                "Connect your iPod to save a copy you can restore later. "
                "Have backups from Original iOpenPod? Choose Import Backups."
            ),
            page,
        )
        self._empty_detail.setObjectName("backupEmptyDetail")
        self._empty_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_detail.setWordWrap(True)
        self._empty_detail.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        self._empty_detail.setMaximumWidth(500)
        self._empty_backup = ActionButton(
            self.tr("Back Up Now"),
            page,
            kind=ActionButtonKind.PRIMARY,
        )
        self._empty_backup.setObjectName("backupEmptyCreate")
        self._empty_backup.clicked.connect(self._controller.create_snapshot)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(
            LAYOUT.space_3xl,
            LAYOUT.space_3xl,
            LAYOUT.space_3xl,
            LAYOUT.space_3xl,
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addStretch(1)
        layout.addWidget(art, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._empty_title)
        explanation = QHBoxLayout()
        explanation.addStretch(1)
        explanation.addWidget(self._empty_detail, 2)
        explanation.addStretch(1)
        layout.addLayout(explanation)
        layout.addSpacing(LAYOUT.space_xs)
        layout.addWidget(self._empty_backup, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        return page

    def _build_browser(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("backupBrowserPage")
        rail = SourceListPanel(parent=page)
        rail.setObjectName("backupDeviceRail")
        rail.title_label.setObjectName("backupRailLabel")
        rail.count_label.setObjectName("backupRailCount")
        self._device_rail = rail
        self._device_rail.set_title(self.tr("Your iPods"))
        self._devices_list = QListWidget(rail)
        self._devices_list.setObjectName("backupDeviceList")
        rail.set_view(self._devices_list)

        detail = QWidget(page)
        detail.setObjectName("backupDetail")
        hero = QFrame(detail)
        hero.setObjectName("backupHero")
        self._device_art = _BackupDeviceArt(hero)
        self._device_name = QLabel(hero)
        self._device_name.setObjectName("backupDeviceName")
        self._device_name.setTextFormat(Qt.TextFormat.PlainText)
        self._device_name.setWordWrap(True)
        self._device_model = QLabel(hero)
        self._device_model.setObjectName("backupDeviceModel")
        self._device_model.setWordWrap(True)
        self._device_summary = QLabel(hero)
        self._device_summary.setObjectName("backupDeviceSummary")
        self._device_summary.setWordWrap(True)
        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(LAYOUT.space_2xs)
        identity.addWidget(self._device_name)
        identity.addWidget(self._device_model)
        identity.addWidget(self._device_summary)
        self._open_folder = ActionButton(
            self.tr("Open Folder"), detail, kind=ActionButtonKind.QUIET
        )
        self._open_folder.setObjectName("backupOpenFolder")
        self._backup_now = ActionButton(
            self.tr("Back Up Now"), hero, kind=ActionButtonKind.PRIMARY
        )
        self._backup_now.setObjectName("backupCreate")
        hero_actions = QVBoxLayout()
        hero_actions.setContentsMargins(0, 0, 0, 0)
        hero_actions.setSpacing(LAYOUT.space_xs)
        hero_actions.addWidget(self._backup_now)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        hero_layout.setSpacing(LAYOUT.space_md)
        hero_layout.addWidget(self._device_art)
        hero_layout.addLayout(identity, 1)
        hero_layout.addLayout(hero_actions)

        snapshot_heading = QHBoxLayout()
        snapshot_heading.setContentsMargins(0, 0, 0, 0)
        self._snapshots_label = QLabel(self.tr("Saved backups"), detail)
        self._snapshots_label.setObjectName("backupSnapshotsLabel")
        self._snapshots_count = QLabel("0", detail)
        self._snapshots_count.setObjectName("backupSnapshotsCount")
        snapshot_heading.addWidget(self._snapshots_label)
        snapshot_heading.addWidget(self._snapshots_count)
        snapshot_heading.addStretch(1)
        snapshot_heading.addWidget(self._open_folder)

        self._snapshot_host = QWidget(detail)
        self._snapshot_host.setObjectName("backupSnapshotHost")
        self._snapshot_layout = QVBoxLayout(self._snapshot_host)
        self._snapshot_layout.setContentsMargins(0, 0, 0, 0)
        self._snapshot_layout.setSpacing(LAYOUT.space_sm)
        self._snapshot_layout.addStretch(1)
        scroll = QScrollArea(detail)
        scroll.setObjectName("backupSnapshotScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._snapshot_host)

        self._progress_panel = QFrame(detail)
        self._progress_panel.setObjectName("backupProgressPanel")
        self._progress_title = QLabel(self.tr("Working…"), self._progress_panel)
        self._progress_title.setObjectName("backupProgressTitle")
        self._progress_file = QLabel(self._progress_panel)
        self._progress_file.setObjectName("backupProgressFile")
        self._progress_file.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._progress_bar = QProgressBar(self._progress_panel)
        self._progress_bar.setObjectName("backupProgressBar")
        self._progress_eta = EtaLabel(self._progress_panel)
        self._progress_eta.setObjectName("backupProgressEta")
        self._cancel = ActionButton(
            self.tr("Cancel"), self._progress_panel, kind=ActionButtonKind.SECONDARY
        )
        progress_copy = QVBoxLayout()
        progress_copy.setContentsMargins(0, 0, 0, 0)
        progress_copy.setSpacing(LAYOUT.space_2xs)
        progress_copy.addWidget(self._progress_title)
        progress_copy.addWidget(self._progress_file)
        progress_copy.addWidget(self._progress_bar)
        progress_copy.addWidget(self._progress_eta)
        progress_layout = QHBoxLayout(self._progress_panel)
        progress_layout.setContentsMargins(
            LAYOUT.space_md,
            LAYOUT.space_sm,
            LAYOUT.space_md,
            LAYOUT.space_sm,
        )
        progress_layout.setSpacing(LAYOUT.space_md)
        progress_layout.addLayout(progress_copy, 1)
        progress_layout.addWidget(self._cancel)
        self._progress_panel.hide()

        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(0)
        detail_layout.addWidget(hero)
        snapshots = QWidget(detail)
        snapshots_layout = QVBoxLayout(snapshots)
        snapshots_layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_md,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        snapshots_layout.setSpacing(LAYOUT.space_sm)
        snapshots_layout.addLayout(snapshot_heading)
        snapshots_layout.addWidget(scroll, 1)
        snapshots_layout.addWidget(self._progress_panel)
        detail_layout.addWidget(snapshots, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal, page)
        splitter.setObjectName("backupBrowserSplitter")
        splitter.setProperty("sourceListBrowser", True)
        splitter.setHandleWidth(LAYOUT.source_list_splitter_handle_width)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(rail)
        splitter.addWidget(detail)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes((LAYOUT.source_list_width, 900))
        self._browser_splitter = splitter

        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter)
        return page

    def refresh(self) -> None:
        if not self._controller.busy:
            self._has_loaded = True
            self._controller.refresh()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._has_loaded:
            QTimer.singleShot(0, self.refresh)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._page_header.set_title(self.tr("Backups"))
            self._refresh.setText(self.tr("Refresh"))
            self._import_button.setText(self.tr("Import Backups…"))
            self._import_button.setToolTip(
                self.tr("Import backups from Original iOpenPod")
            )
            self._recover_button.setText(self.tr("Recover iPod"))
            self._backup_now.setText(self.tr("Back Up Now"))
            self._open_folder.setText(self.tr("Open Folder"))
            self._snapshots_label.setText(self.tr("Saved backups"))
            self._cancel.setText(self.tr("Cancel"))
            self._device_rail.set_title(self.tr("Your iPods"))
            self._empty_title.setText(self.tr("Your first backup starts here"))
            self._empty_detail.setText(
                self.tr(
                    "Connect your iPod to save a copy you can restore later. "
                    "Have backups from Original iOpenPod? Choose Import Backups."
                )
            )
            self._empty_backup.setText(self.tr("Back Up Now"))
            self._render_inventory()
            self._render_recovery()
            self._render_catalog()
        super().changeEvent(event)

    @Slot(object)
    def _inventory_changed(self, value: object) -> None:
        if not isinstance(value, BackupInventory):
            return
        self._inventory = value
        self._render_inventory()

    def _render_inventory(self) -> None:
        selected = self._selected_device_id
        with QSignalBlocker(self._devices_list):
            self._devices_list.clear()
            selected_row = -1
            for row, device in enumerate(self._inventory.devices):
                suffix = (
                    self.tr("Connected")
                    if device.connected
                    else self.tr("Not connected")
                )
                if device.snapshot_count == 1:
                    snapshot_count = self.tr("1 backup")
                else:
                    snapshot_count = self.tr("%1 backups").replace(
                        "%1", str(device.snapshot_count)
                    )
                item = QListWidgetItem(
                    self.tr("%1\n%2 · %3")
                    .replace("%1", device.device_name)
                    .replace("%2", snapshot_count)
                    .replace("%3", suffix)
                )
                item.setData(Qt.ItemDataRole.UserRole, device.device_id)
                item.setToolTip(device.device_name)
                self._devices_list.addItem(item)
                if device.device_id == selected:
                    selected_row = row
            if selected_row < 0 and self._inventory.devices:
                selected_row = next(
                    (
                        row
                        for row, device in enumerate(self._inventory.devices)
                        if device.connected
                    ),
                    0,
                )
            if selected_row >= 0:
                self._devices_list.setCurrentRow(selected_row)
        self._device_rail.set_count(len(self._inventory.devices))
        self._render_recovery()
        self._content.setCurrentWidget(
            self._browser if self._inventory.devices else self._empty
        )
        if selected_row >= 0:
            item = self._devices_list.item(selected_row)
            self._queue_catalog(str(item.data(Qt.ItemDataRole.UserRole)))
        self._availability_changed()

    def _render_recovery(self) -> None:
        pending = self._inventory.pending_recoveries
        if not pending:
            self._pending_recovery_id = ""
            self._recovery_banner.hide()
            return
        record = pending[0]
        self._pending_recovery_id = record.id
        self._recovery_text.setText(
            self.tr(
                "An interrupted restore must be recovered before another iPod "
                "write. Safety Snapshot: %1"
            ).replace("%1", record.safety_snapshot_id)
        )
        self._recovery_banner.show()

    @Slot(QListWidgetItem, QListWidgetItem)
    def _device_selected(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is not None:
            self._queue_catalog(str(current.data(Qt.ItemDataRole.UserRole)))

    def _queue_catalog(self, device_id: str) -> None:
        self._selected_device_id = device_id
        self._pending_catalog_id = device_id
        QTimer.singleShot(0, self._load_pending_catalog)

    @Slot()
    def _load_pending_catalog(self) -> None:
        if self._controller.busy or not self._pending_catalog_id:
            return
        device_id, self._pending_catalog_id = self._pending_catalog_id, ""
        self._controller.load_catalog(device_id)

    @Slot(object)
    def _catalog_changed(self, value: object) -> None:
        if not isinstance(value, BackupCatalog):
            return
        if value.device.device_id != self._selected_device_id:
            return
        self._catalog = value
        self._render_catalog()

    def _render_catalog(self) -> None:
        catalog = self._catalog
        if catalog is None:
            return
        device = catalog.device
        self._device_art.set_image(device.metadata.product_image)
        self._device_name.setText(device.device_name)
        model = " · ".join(
            part
            for part in (device.metadata.family, device.metadata.generation)
            if part
        )
        self._device_model.setText(model or self.tr("iPod"))
        connected = self._inventory.connected_device_id == device.device_id
        self._device_summary.setText(
            self.tr("Save a copy of your iPod to come back to later.")
            if connected
            else self.tr("Connect this iPod to back it up or restore a saved backup.")
        )
        self._snapshots_count.setText(
            self.tr("%1 · %2 stored")
            .replace("%1", str(len(catalog.snapshots)))
            .replace("%2", _format_size(catalog.stored_size))
        )
        while self._snapshot_layout.count() > 1:
            item = self._snapshot_layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._cards.clear()
        identified = device.has_backup_identifier
        restore_hint = ""
        if not connected:
            restore_hint = self.tr("Connect this iPod to restore a backup.")
        elif not identified:
            restore_hint = self.tr(
                "iOpenPod needs to recognize this iPod before restoring a backup."
            )
        for snapshot in catalog.snapshots:
            snapshot_can_restore = (
                snapshot.identity_state is not SnapshotIdentityState.UNSTABLE
            )
            snapshot_hint = restore_hint or snapshot.validation_error
            if not snapshot_can_restore:
                snapshot_hint = self.tr(
                    "iOpenPod can't confirm which iPod this backup belongs to. "
                    "You can still export its files."
                )
            elif snapshot.requires_restore_confirmation and not snapshot_hint:
                snapshot_hint = self.tr(
                    "You'll be asked to confirm this backup belongs to your iPod."
                )
            card = BackupSnapshotCard(
                snapshot,
                can_restore=connected and identified and snapshot_can_restore,
                restore_hint=snapshot_hint,
                parent=self._snapshot_host,
            )
            card.restoreRequested.connect(self._restore_snapshot)
            card.exportRequested.connect(self._export_snapshot)
            card.deleteRequested.connect(self._delete_snapshot)
            card.noteChanged.connect(self._update_note)
            self._snapshot_layout.insertWidget(self._snapshot_layout.count() - 1, card)
            self._cards.append(card)
        if not catalog.snapshots:
            empty = QLabel(
                self.tr("No backups yet. Make your first copy with Back Up Now.")
                if connected
                else self.tr(
                    "No backups yet. Connect this iPod to make your first copy."
                ),
                self._snapshot_host,
            )
            empty.setObjectName("backupArchiveEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self._snapshot_layout.insertWidget(0, empty)
        self._availability_changed()

    @Slot(str)
    def _restore_snapshot(self, snapshot_id: str) -> None:
        catalog = self._catalog
        if catalog is None:
            return
        snapshot = next(
            (item for item in catalog.snapshots if item.id == snapshot_id),
            None,
        )
        if snapshot is None:
            return
        legacy_confirmation = snapshot.requires_restore_confirmation
        if legacy_confirmation:
            title = self.tr("Restore an Imported Backup?")
            detail = self.tr(
                "This backup came from Original iOpenPod. Confirm that the "
                "connected iPod is the one this backup belongs to. "
                "Restoring replaces its contents, including removing files that "
                "aren't in this backup. iOpenPod will save a safety backup first. "
                "Keep your iPod connected until the restore finishes."
            )
        else:
            title = self.tr("Restore This Backup?")
            detail = self.tr(
                "Your iPod will return to how it was when this backup was made. "
                "Files that aren't in the backup will be removed. "
                "iOpenPod will save a safety backup of your iPod first. "
                "Keep your iPod connected until the restore finishes."
            )
        answer = QMessageBox.question(
            self,
            title,
            detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.restore_snapshot(
                catalog.device.device_id,
                snapshot_id,
                legacy_confirmed=legacy_confirmation,
            )

    @Slot(str)
    def _export_snapshot(self, snapshot_id: str) -> None:
        catalog = self._catalog
        if catalog is None:
            return
        destination = QFileDialog.getExistingDirectory(
            self,
            self.tr("Choose a Folder for the Exported Backup"),
            str(self._controller.backup_root.parent),
        )
        if destination:
            self._controller.export_snapshot(
                catalog.device.device_id, snapshot_id, destination
            )

    @Slot(str)
    def _delete_snapshot(self, snapshot_id: str) -> None:
        catalog = self._catalog
        if catalog is None:
            return
        answer = QMessageBox.question(
            self,
            self.tr("Delete This Backup?"),
            self.tr(
                "This backup will be permanently deleted. Your iPod and other "
                "backups won't be changed. This cannot be undone."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.delete_snapshot(catalog.device.device_id, snapshot_id)

    @Slot(str, str)
    def _update_note(self, snapshot_id: str, note: str) -> None:
        catalog = self._catalog
        if catalog is not None:
            self._controller.update_note(catalog.device.device_id, snapshot_id, note)

    @Slot(object)
    def _progress_changed(self, value: object) -> None:
        if not isinstance(value, BackupProgress):
            return
        self._progress_panel.show()
        self._progress_title.setText(value.message)
        self._progress_file.setText(value.current_file)
        if value.stage in {
            BackupStage.FINALIZING,
            BackupStage.COMPLETE,
            BackupStage.NO_CHANGES,
        }:
            self._progress_eta.reset()
        elif value.total_bytes > 0 and value.stage is BackupStage.CAPTURING:
            self._progress_eta.set_progress(
                value.stage.value,
                value.completed_bytes,
                value.total_bytes,
                unit="bytes",
            )
        else:
            self._progress_eta.set_progress(
                value.stage.value,
                value.current,
                value.total if value.total > 0 else None,
            )
        if value.total_bytes > 0:
            scale = 10_000
            self._progress_bar.setRange(0, scale)
            self._progress_bar.setValue(
                min(scale, value.completed_bytes * scale // value.total_bytes)
            )
        elif value.total <= 0:
            self._progress_bar.setRange(0, 0)
        else:
            self._progress_bar.setRange(0, value.total)
            self._progress_bar.setValue(min(value.current, value.total))
        self._cancel.setEnabled(value.can_cancel)

    @Slot(bool)
    def _busy_changed(self, busy: bool) -> None:
        self._progress_eta.reset()
        self._availability_changed()
        if not busy:
            QTimer.singleShot(0, self._load_pending_catalog)
            QTimer.singleShot(1_500, self._hide_progress_if_idle)

    @Slot()
    @Slot(bool)
    def _device_busy_changed(self, _busy: bool | None = None) -> None:
        self._availability_changed()

    @Slot(object)
    def _device_write_policy_changed(self, _policy: object) -> None:
        self._availability_changed()

    def _availability_changed(self) -> None:
        editable = not self._controller.busy
        can_create = (
            editable
            and self._devices.active_ipod is not None
            and not self._devices.busy
        )
        self._refresh.setEnabled(editable)
        self._import_button.setEnabled(editable)
        selected_is_connected = (
            self._selected_device_id == self._inventory.connected_device_id
        )
        self._backup_now.setEnabled(can_create and selected_is_connected)
        self._empty_backup.setEnabled(can_create)
        self._open_folder.setEnabled(editable and bool(self._selected_device_id))
        self._devices_list.setEnabled(editable)
        self._recover_button.setEnabled(
            editable
            and bool(self._pending_recovery_id)
            and self._devices.active_ipod is not None
            and not self._devices.busy
        )
        restore_writes_allowed = (
            self._controller.device_write_policy is DeviceWritePolicy.ALLOWED
        )
        for card in self._cards:
            card.set_actions_enabled(
                editable and not self._devices.busy,
                restore_writes_allowed=restore_writes_allowed,
            )

    @Slot(object)
    def _operation_failed(self, value: object) -> None:
        if not isinstance(value, BackupOperationFailure) or not self.isVisible():
            return
        diagnostic = f"Code: {value.failure.code.value}"
        if value.failure.detail:
            diagnostic = f"{diagnostic}\n{value.failure.detail}"
        self._show_backup_message(
            BackupMessage(
                BackupMessageSeverity.ERROR,
                self.tr("Backup Operation Failed"),
                value.failure.summary,
                value.failure.action,
                diagnostic,
            )
        )

    @Slot()
    def _import_original(self) -> None:
        source = QFileDialog.getExistingDirectory(
            self,
            self.tr("Choose an Original iOpenPod Backup Folder"),
            str(self._controller.backup_root.parent),
        )
        if not source:
            return
        answer = QMessageBox.question(
            self,
            self.tr("Import Original iOpenPod Backups?"),
            self.tr(
                "iOpenPod will check and copy backups from Original iOpenPod "
                "into your saved backups. The originals will not be changed."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.import_original(source)

    @Slot()
    def _recover_restore(self) -> None:
        if not self._pending_recovery_id:
            return
        answer = QMessageBox.question(
            self,
            self.tr("Recover Interrupted Restore?"),
            self.tr(
                "iOpenPod will inspect the retained journal. If the selected "
                "restore did not finish durably, it will return the iPod to the "
                "verified Safety Snapshot. Keep both the iPod and Backup Archive "
                "connected."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.recover_restore(self._pending_recovery_id)

    @Slot(object, object)
    def _operation_completed(self, operation: object, result: object) -> None:
        if not isinstance(operation, BackupOperation):
            return
        if operation in {
            BackupOperation.CREATE,
            BackupOperation.DELETE,
            BackupOperation.UPDATE_NOTE,
            BackupOperation.RECOVER_RESTORE,
        }:
            self._pending_catalog_id = self._selected_device_id
        if not self.isVisible():
            return
        outcome = _terminal_outcome(result)
        if outcome is not None:
            self._show_backup_message(backup_message_for(outcome))
            return
        if operation is BackupOperation.RESTORE and isinstance(
            result, BackupRestoreResult
        ):
            QMessageBox.information(
                self,
                self.tr("Restore Complete"),
                self.tr(
                    "The iPod now matches the selected snapshot. Safety snapshot: %1"
                ).replace("%1", result.safety_snapshot_id),
            )
        elif operation is BackupOperation.EXPORT and isinstance(
            result, BackupExportResult
        ):
            QMessageBox.information(
                self,
                self.tr("Backup Export Complete"),
                self.tr("Exported %1 files to:\n\n%2")
                .replace("%1", f"{result.file_count:,}")
                .replace("%2", str(result.destination)),
            )

    def _show_backup_message(self, message: BackupMessage) -> None:
        dialog = QMessageBox(self)
        icons = {
            BackupMessageSeverity.INFO: QMessageBox.Icon.Information,
            BackupMessageSeverity.SUCCESS: QMessageBox.Icon.Information,
            BackupMessageSeverity.WARNING: QMessageBox.Icon.Warning,
            BackupMessageSeverity.ERROR: QMessageBox.Icon.Critical,
        }
        dialog.setIcon(icons[message.severity])
        dialog.setWindowTitle(message.title)
        dialog.setText(message.body)
        dialog.setInformativeText(message.next_step)
        if message.diagnostic_detail:
            dialog.setDetailedText(message.diagnostic_detail)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()

    @Slot(object)
    def _operation_cancelled(self, _operation: object) -> None:
        if self.isVisible():
            self._progress_title.setText(self.tr("Operation cancelled safely."))

    @Slot()
    def _hide_progress_if_idle(self) -> None:
        if not self._controller.busy:
            self._progress_panel.hide()

    @Slot()
    def _open_archive(self) -> None:
        path = self._controller.archive_path(self._selected_device_id)
        if not path.is_dir():
            QMessageBox.information(
                self,
                self.tr("Backup Folder Not Created Yet"),
                self.tr("Make your first backup and its folder will appear here."),
            )
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(
                self,
                self.tr("Could Not Open Backup Folder"),
                str(path),
            )

    @Slot(object)
    def _active_ipod_changed(self, _value: object) -> None:
        if self.isVisible() and not self._controller.busy:
            QTimer.singleShot(0, self.refresh)
        self._availability_changed()

    @Slot(str, object)
    def _setting_changed(self, key: str, _value: object) -> None:
        if key != BACKUP_LOCATION.key:
            return
        self._has_loaded = False
        self._catalog = None
        self._selected_device_id = ""
        if self.isVisible():
            QTimer.singleShot(0, self.refresh)

    @Slot(str)
    def _theme_changed(self, _theme: str) -> None:
        self._apply_styles()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            render_backup_page_style(
                self._theme_manager.tokens,
                self._theme_manager.typography,
            )
        )


__all__ = ["BackupPage", "BackupSnapshotCard"]
