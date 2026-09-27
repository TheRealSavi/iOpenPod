"""Device Picker for choosing one discovered candidate as the Active iPod."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.models.device import (
    DeviceCandidate,
    DeviceCandidateId,
    DeviceCandidateIssue,
    DeviceCandidateIssueCode,
    DeviceDiscovery,
    DeviceReadiness,
)
from iOpenPod.GUI.dialogs.linux_identity_setup import LinuxIdentitySetupDialog
from iOpenPod.GUI.presentation.device_images import device_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from PySide6.QtGui import QHideEvent, QShowEvent

_CANDIDATE_ID_ROLE = Qt.ItemDataRole.UserRole.value


class DevicePickerDialog(QDialog):
    """Present path-free discovery state and return one opaque candidate ID."""

    refreshRequested = Signal()
    deviceSelected = Signal(str)
    visibilityChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("devicePicker")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumSize(520, 400)
        self.resize(600, 440)
        self._discovery = DeviceDiscovery(candidates=())
        self._busy = False
        self._searching = False
        self._search_error = ""
        self._search_delay = QTimer(self)
        self._search_delay.setSingleShot(True)
        self._search_delay.setInterval(200)
        self._search_delay.timeout.connect(self._refresh_search_status)

        self._title = QLabel(self)
        self._title.setObjectName("pageTitle")
        self._description = QLabel(self)
        self._description.setObjectName("pageDescription")
        self._description.setWordWrap(True)

        self._search_status = QLabel(self)
        self._search_status.setObjectName("deviceSearchStatus")

        self._candidates = QListWidget(self)
        self._candidates.setObjectName("deviceCandidateList")
        self._candidates.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._candidates.setIconSize(
            QSize(LAYOUT.device_picker_image_size, LAYOUT.device_picker_image_size)
        )
        self._candidates.setCursor(Qt.CursorShape.PointingHandCursor)
        self._candidates.currentItemChanged.connect(self._selection_changed)
        self._candidates.itemDoubleClicked.connect(self._item_activated)

        self._detail = QLabel(self)
        self._detail.setObjectName("deviceCandidateDetail")
        self._detail.setWordWrap(True)

        self._refresh = ActionButton(parent=self)
        self._refresh.clicked.connect(self.refreshRequested.emit)
        self._linux_setup = ActionButton(parent=self)
        self._linux_setup.setObjectName("linuxIdentitySetupButton")
        self._linux_setup.clicked.connect(self._show_linux_setup)
        self._linux_setup.hide()
        self._cancel = ActionButton(parent=self)
        self._cancel.clicked.connect(self.close)
        self._select = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._select.setDefault(True)
        self._select.clicked.connect(self._select_current)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(LAYOUT.space_xs)
        actions.addWidget(self._refresh)
        actions.addWidget(self._linux_setup)
        actions.addStretch(1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._select)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addWidget(self._description)
        layout.addWidget(self._search_status)
        layout.addWidget(self._candidates, 1)
        layout.addWidget(self._detail)
        layout.addLayout(actions)
        self.retranslate_ui()
        self._refresh_candidates()

    def set_discovery(self, discovery: DeviceDiscovery) -> None:
        if discovery == self._discovery:
            return
        selected_id = self._selected_candidate_id()
        self._discovery = discovery
        self._refresh_candidates(selected_id)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh.setEnabled(not busy)
        self._candidates.setEnabled(not busy or self._searching)
        self._refresh_selection_state()

    def set_searching(self, searching: bool) -> None:
        if searching == self._searching:
            return
        self._searching = searching
        if searching:
            self._search_delay.start()
        else:
            self._search_delay.stop()
        self._candidates.setEnabled(not self._busy or searching)
        self._refresh_search_status()

    def set_search_error(self, message: str) -> None:
        self._search_error = message
        self._refresh_search_status()

    def _refresh_search_status(self) -> None:
        if self._search_error:
            text = self.tr("Could not check all devices · retrying automatically")
        elif self._searching and not self._search_delay.isActive():
            text = self.tr("Searching for iPods…")
        else:
            text = self.tr("Connected iPods appear automatically")
        self._search_status.setText(text)
        self._search_status.setToolTip(self._search_error)

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Choose an iPod"))
        self._title.setText(self.tr("Choose an iPod"))
        self._description.setText(
            self.tr(
                "Select a recognized iPod. Its identity and library are checked "
                "again before it becomes active."
            )
        )
        self._refresh.setText(QCoreApplication.translate("CommonActions", "Refresh"))
        self._linux_setup.setText(self.tr("Set Up Linux"))
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))
        self._select.setText(self.tr("Use This iPod"))
        self._refresh_search_status()
        self._refresh_candidates(self._selected_candidate_id())

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.visibilityChanged.emit(True)

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self.visibilityChanged.emit(False)

    def _refresh_candidates(
        self,
        selected_id: DeviceCandidateId | None = None,
    ) -> None:
        self._candidates.clear()
        selected_item: QListWidgetItem | None = None
        for candidate in self._discovery.candidates:
            item = QListWidgetItem(_candidate_label(candidate))
            image_name = (
                candidate.profile.product_image
                if candidate.profile is not None
                else "iPodGeneric.png"
            )
            item.setIcon(
                device_icon(
                    image_name,
                    LAYOUT.device_picker_image_size,
                    self.devicePixelRatioF(),
                )
            )
            item.setData(_CANDIDATE_ID_ROLE, candidate.id.value)
            item.setToolTip(_readiness_text(self, candidate.readiness))
            if not candidate.selectable:
                item.setForeground(self.palette().color(self.foregroundRole()))
            self._candidates.addItem(item)
            if candidate.id == selected_id:
                selected_item = item

        if selected_item is None and self._candidates.count() > 0:
            selected_item = self._candidates.item(0)
        if selected_item is not None:
            self._candidates.setCurrentItem(selected_item)
        else:
            self._detail.setText(self.tr("No removable devices were found."))
        self._refresh_selection_state()

    def _selection_changed(
        self,
        _current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        self._refresh_selection_state()

    def _item_activated(self, _item: QListWidgetItem) -> None:
        self._select_current()

    def _refresh_selection_state(self) -> None:
        candidate = self._selected_candidate()
        selectable = candidate is not None and candidate.selectable and not self._busy
        self._select.setEnabled(selectable)
        linux_setup_available = candidate is not None and _needs_linux_identity_setup(
            candidate
        )
        self._linux_setup.setVisible(linux_setup_available)
        self._linux_setup.setEnabled(linux_setup_available and not self._busy)
        if candidate is None:
            if self._candidates.count() > 0:
                self._detail.setText(self.tr("Select a device to see its status."))
            return

        status = _readiness_text(self, candidate.readiness)
        profile = candidate.profile_name or self.tr("Unrecognized device")
        detail = self.tr("%1 · %2").replace("%1", profile).replace("%2", status)
        issue_details = tuple(_issue_text(self, issue) for issue in candidate.issues)
        if issue_details:
            detail = f"{detail}\n{issue_details[0]}"
        self._detail.setText(detail)

    def _show_linux_setup(self) -> None:
        candidate = self._selected_candidate()
        if (
            candidate is None
            or not _needs_linux_identity_setup(candidate)
            or self._busy
        ):
            return
        LinuxIdentitySetupDialog(self).exec()

    def _select_current(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None or not candidate.selectable or self._busy:
            return
        self.deviceSelected.emit(candidate.id.value)
        self.close()

    def _selected_candidate(self) -> DeviceCandidate | None:
        candidate_id = self._selected_candidate_id()
        return (
            self._discovery.candidate(candidate_id)
            if candidate_id is not None
            else None
        )

    def _selected_candidate_id(self) -> DeviceCandidateId | None:
        if self._candidates.currentRow() < 0:
            return None
        item = self._candidates.currentItem()
        value = item.data(_CANDIDATE_ID_ROLE)
        return DeviceCandidateId(value) if isinstance(value, str) and value else None


def _candidate_label(candidate: DeviceCandidate) -> str:
    description = candidate.profile_name or candidate.host_description
    return (
        f"{candidate.display_name} — {description}"
        if description
        else candidate.display_name
    )


def _needs_linux_identity_setup(candidate: DeviceCandidate) -> bool:
    return any(
        issue.code is DeviceCandidateIssueCode.HARDWARE_PROBE_SETUP_REQUIRED
        for issue in candidate.issues
    )


def _readiness_text(
    _dialog: DevicePickerDialog,
    readiness: DeviceReadiness,
) -> str:
    return {
        DeviceReadiness.READY: QCoreApplication.translate(
            "DevicePickerDialog", "Ready to load"
        ),
        DeviceReadiness.SYNC_RECOVERY_REQUIRED: QCoreApplication.translate(
            "DevicePickerDialog",
            "Select to restore interrupted changes or keep current contents",
        ),
        DeviceReadiness.UNKNOWN: QCoreApplication.translate(
            "DevicePickerDialog", "Not recognized as a supported iPod"
        ),
        DeviceReadiness.AMBIGUOUS: QCoreApplication.translate(
            "DevicePickerDialog", "More identity information is needed"
        ),
        DeviceReadiness.CONFLICTING: QCoreApplication.translate(
            "DevicePickerDialog", "Device identity information conflicts"
        ),
        DeviceReadiness.RECOVERY_MODE: QCoreApplication.translate(
            "DevicePickerDialog", "Recovery mode is not loadable"
        ),
        DeviceReadiness.DATABASE_MISSING: QCoreApplication.translate(
            "DevicePickerDialog", "No iTunesDB was found"
        ),
        DeviceReadiness.DATABASE_UNSUPPORTED: QCoreApplication.translate(
            "DevicePickerDialog", "This iPod database format is not supported yet"
        ),
        DeviceReadiness.INSPECTION_FAILED: QCoreApplication.translate(
            "DevicePickerDialog", "The device filesystem could not be inspected"
        ),
    }[readiness]


def _issue_text(
    _dialog: DevicePickerDialog,
    issue: DeviceCandidateIssue,
) -> str:
    return {
        DeviceCandidateIssueCode.METADATA_UNREADABLE: QCoreApplication.translate(
            "DevicePickerDialog", "Some device identity metadata could not be read."
        ),
        DeviceCandidateIssueCode.METADATA_RECONCILIATION_SKIPPED: QCoreApplication.translate(
            "DevicePickerDialog",
            "Device identity metadata needs repair, but this Volume is read-only.",
        ),
        DeviceCandidateIssueCode.METADATA_RECONCILIATION_FAILED: QCoreApplication.translate(
            "DevicePickerDialog",
            "Device identity metadata could not be repaired safely.",
        ),
        DeviceCandidateIssueCode.HARDWARE_PROBE_SETUP_REQUIRED: QCoreApplication.translate(
            "DevicePickerDialog",
            "Linux needs the bundled identity rule before iOpenPod can verify "
            "this model. Install 61-iopenpod.rules in /etc/udev/rules.d, reload "
            "udev rules, then reconnect the iPod.",
        ),
        DeviceCandidateIssueCode.HARDWARE_PROBE_FAILED: QCoreApplication.translate(
            "DevicePickerDialog", "Current hardware identity could not be verified."
        ),
        DeviceCandidateIssueCode.DATABASE_EMPTY: QCoreApplication.translate(
            "DevicePickerDialog", "The iPod database is empty."
        ),
        DeviceCandidateIssueCode.DATABASE_FALLBACK: QCoreApplication.translate(
            "DevicePickerDialog", "iOpenPod loaded the fallback database copy."
        ),
        DeviceCandidateIssueCode.ARTWORK_DATABASE_UNREADABLE: QCoreApplication.translate(
            "DevicePickerDialog", "Album artwork could not be loaded."
        ),
        DeviceCandidateIssueCode.VOLUME_PRESENTATION_INCOMPLETE: QCoreApplication.translate(
            "DevicePickerDialog",
            "The iPod's desktop name or icon could not be fully updated.",
        ),
        DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING: QCoreApplication.translate(
            "DevicePickerDialog", "Recovery-file cleanup could not finish."
        ),
        DeviceCandidateIssueCode.TRANSACTION_CLEANUP_FLUSH_PENDING: QCoreApplication.translate(
            "DevicePickerDialog",
            "Recovery files were removed. Safely eject before unplugging.",
        ),
        DeviceCandidateIssueCode.INSPECTION_FAILED: QCoreApplication.translate(
            "DevicePickerDialog", "The device filesystem could not be inspected."
        ),
    }[issue.code]
