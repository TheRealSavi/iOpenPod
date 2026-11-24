"""Device Picker for choosing one discovered candidate as the Active iPod."""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
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
from iOpenPod.GUI.delegates.device_candidate_delegate import DeviceCandidateDelegate
from iOpenPod.GUI.dialogs.linux_identity_setup import LinuxIdentitySetupDialog
from iOpenPod.GUI.presentation.device_images import device_icon
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT, resolve_typography
from iOpenPod.GUI.widgets.storage_breakdown import format_capacity
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    IconButton,
    IconButtonKind,
)

if TYPE_CHECKING:
    from PySide6.QtGui import QHideEvent, QResizeEvent, QShowEvent

    from iOpenPod.GUI.presentation.theme.manager import ThemeManager

_CANDIDATE_ID_ROLE = Qt.ItemDataRole.UserRole.value


class _CandidateList(QListWidget):
    """Fit short lists to their rows and scroll longer lists."""

    def sizeHint(self) -> QSize:
        rows = min(self.count(), LAYOUT.device_picker_visible_rows)
        row_height = self.sizeHintForRow(0) if rows else 0
        return QSize(
            LAYOUT.device_picker_width - 2 * LAYOUT.space_lg,
            rows * row_height + 2 * self.frameWidth(),
        )


class DevicePickerDialog(QDialog):
    """Present path-free discovery state and return one opaque candidate ID."""

    refreshRequested = Signal()
    deviceSelected = Signal(str)
    visibilityChanged = Signal(bool)

    def __init__(
        self, parent: QWidget | None = None, *, theme: ThemeManager | None = None
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        if theme is not None:
            theme.deviceArtworkChanged.connect(self._artwork_changed)
        self.setObjectName("devicePicker")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(LAYOUT.device_picker_width, LAYOUT.device_picker_row_height)
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

        self._search_status = QLabel(self)
        self._search_status.setObjectName("deviceSearchStatus")
        self._search_status.setWordWrap(True)

        self._candidates = _CandidateList(self)
        self._candidates.setObjectName("deviceCandidateList")
        typography = theme.typography if theme is not None else resolve_typography()
        self._candidates.setItemDelegate(
            DeviceCandidateDelegate(typography, self._candidates)
        )
        self._candidates.setMouseTracking(True)
        self._candidates.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._candidates.setUniformItemSizes(True)
        self._candidates.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._candidates.setIconSize(
            QSize(LAYOUT.device_picker_image_size, LAYOUT.device_picker_image_size)
        )
        self._candidates.setCursor(Qt.CursorShape.PointingHandCursor)
        self._candidates.currentItemChanged.connect(self._selection_changed)
        self._candidates.itemDoubleClicked.connect(self._item_activated)

        self._empty = QLabel(self)
        self._empty.setObjectName("devicePickerEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setMinimumHeight(LAYOUT.device_picker_row_height)

        self._detail = QLabel(self)
        self._detail.setObjectName("deviceCandidateDetail")
        self._detail.setTextFormat(Qt.TextFormat.PlainText)
        self._detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._detail.setWordWrap(True)
        self._detail_scroll = QScrollArea(self)
        self._detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._detail_scroll.setWidgetResizable(True)
        self._detail_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._detail_scroll.setWidget(self._detail)

        self._refresh = IconButton("refresh", "", self, kind=IconButtonKind.QUIET)
        self._refresh.clicked.connect(self.refreshRequested.emit)
        self._linux_setup = ActionButton(parent=self)
        self._linux_setup.setObjectName("linuxIdentitySetupButton")
        self._linux_setup.clicked.connect(self._show_linux_setup)
        self._linux_setup.hide()
        self._cancel = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        self._cancel.clicked.connect(self.close)
        self._select = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._select.setDefault(True)
        self._select.clicked.connect(self._select_current)

        header = QHBoxLayout()
        header.addWidget(self._title, 1)
        header.addWidget(self._refresh)

        content = QVBoxLayout()
        content.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_md, LAYOUT.space_lg, LAYOUT.space_md
        )
        content.setSpacing(LAYOUT.space_sm)
        content.addLayout(header)
        content.addWidget(self._candidates)
        content.addWidget(self._empty)
        content.addWidget(self._detail_scroll)
        content.addWidget(self._linux_setup, 0, Qt.AlignmentFlag.AlignLeft)

        footer = QFrame(self)
        footer.setObjectName("devicePickerActions")
        self._actions = QGridLayout(footer)
        self._actions.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_sm, LAYOUT.space_lg, LAYOUT.space_sm
        )
        self._actions.setSpacing(LAYOUT.space_xs)
        self._actions.setColumnStretch(0, 1)
        self._actions.addWidget(self._search_status, 1, 0)
        self._actions.addWidget(self._cancel, 1, 1)
        self._actions.addWidget(self._select, 1, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(content)
        layout.addWidget(footer)
        QWidget.setTabOrder(self._candidates, self._refresh)
        self.retranslate_ui()

    def set_discovery(self, discovery: DeviceDiscovery) -> None:
        if discovery == self._discovery:
            return
        selected_id = self._selected_candidate_id()
        self._discovery = discovery
        self._refresh_candidates(selected_id)

    def _artwork_changed(self) -> None:
        self._refresh_candidates(self._selected_candidate_id())

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
        self._refresh_selection_state()
        self._refresh_search_status()

    def set_search_error(self, message: str) -> None:
        if bool(message) != bool(self._search_error):
            # Retry messages use the footer's full width. Routine searches share
            # the action row so polling never moves the buttons.
            self._actions.removeWidget(self._search_status)
            if message:
                self._actions.addWidget(self._search_status, 0, 0, 1, 3)
            else:
                self._actions.addWidget(self._search_status, 1, 0)
        self._search_error = message
        self._refresh_search_status()

    def _refresh_search_status(self) -> None:
        if self._search_error:
            text = self.tr("Could not check all devices · retrying automatically")
        elif self._searching and not self._search_delay.isActive():
            text = self.tr("Searching for iPods…")
        else:
            text = ""
        self._search_status.setText(text)
        self._search_status.setToolTip(self._search_error)

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Choose an iPod"))
        self._title.setText(self.tr("Connected devices"))
        self._candidates.setAccessibleName(self._title.text())
        self._empty.setText(self.tr("Connect an iPod to see it here."))
        refresh = QCoreApplication.translate("CommonActions", "Refresh")
        self._refresh.setToolTip(refresh)
        self._refresh.setAccessibleName(refresh)
        self._linux_setup.setText(self.tr("Set Up Linux"))
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))
        self._select.setText(self.tr("Use This iPod"))
        self._refresh_search_status()
        self._refresh_candidates(self._selected_candidate_id())

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def event(self, event: QEvent) -> bool:
        handled = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest and self.isVisible():
            self._fit_height()
        return handled

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            QCoreApplication.postEvent(self, QEvent(QEvent.Type.LayoutRequest))

    def _fit_height(self) -> None:
        # Measure wrapped messages at the current width. Long diagnostics scroll
        # independently so that the selected device and actions remain reachable.
        if not self._detail_scroll.isHidden():
            width = self.width() - 2 * LAYOUT.space_lg
            needed = self._detail.heightForWidth(width)
            limit = 6 * self._detail.fontMetrics().lineSpacing()
            self._detail_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
                if needed > limit
                else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self._detail_scroll.setFixedHeight(min(needed, limit))
        layout = self.layout()
        if layout is None:
            return
        preferred_height = (
            layout.totalHeightForWidth(self.width())
            if layout.hasHeightForWidth()
            else layout.totalSizeHint().height()
        )
        available_height = self.screen().availableGeometry().height() - LAYOUT.space_2xl
        self.resize(self.width(), min(preferred_height, available_height))

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
            item = self._candidate_item(candidate)
            self._candidates.addItem(item)
            if candidate.id == selected_id:
                selected_item = item

        if selected_item is None and self._candidates.count() > 0:
            selected_item = self._candidates.item(0)
        if selected_item is not None:
            self._candidates.setCurrentItem(selected_item)
        self._candidates.setVisible(selected_item is not None)
        self._empty.setVisible(selected_item is None)
        self._candidates.updateGeometry()
        self._refresh_selection_state()

    def _candidate_item(self, candidate: DeviceCandidate) -> QListWidgetItem:
        item = QListWidgetItem(candidate.display_name)
        model = candidate.profile_name or candidate.host_description
        if model == candidate.display_name:
            model = ""
        capacity = (
            format_capacity(candidate.total_bytes) if candidate.total_bytes > 0 else ""
        )
        subtitle = (
            self.tr("%1 · %2").replace("%2", capacity).replace("%1", model)
            if model and capacity
            else model or capacity
        )
        item.setData(DeviceCandidateDelegate.subtitle_role, subtitle)
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
                itunes_107=self._theme is not None and self._theme.itunes_107_artwork,
            )
        )
        item.setData(_CANDIDATE_ID_ROLE, candidate.id.value)
        status = _readiness_text(candidate.readiness)
        description = "\n".join(filter(None, (subtitle, status)))
        item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, description)
        tooltip = escape(f"{candidate.display_name}\n{description}").replace(
            "\n", "<br>"
        )
        item.setToolTip(f"<p>{tooltip}</p>")
        return item

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
        selectable = (
            candidate is not None
            and candidate.selectable
            and self._candidates.isEnabled()
        )
        self._select.setEnabled(selectable)
        linux_setup_available = candidate is not None and _needs_linux_identity_setup(
            candidate
        )
        self._linux_setup.setVisible(linux_setup_available)
        self._linux_setup.setEnabled(linux_setup_available and not self._busy)
        details: list[str] = []
        if candidate is not None:
            if candidate.readiness is not DeviceReadiness.READY:
                details.append(_readiness_text(candidate.readiness))
            details.extend(_issue_text(issue) for issue in candidate.issues)
        self._detail.setText("\n".join(details))
        self._detail.setVisible(bool(details))
        self._detail_scroll.setVisible(bool(details))

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
        if candidate is None or not self._select.isEnabled():
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


def _needs_linux_identity_setup(candidate: DeviceCandidate) -> bool:
    return any(
        issue.code is DeviceCandidateIssueCode.HARDWARE_PROBE_SETUP_REQUIRED
        for issue in candidate.issues
    )


def _readiness_text(
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
        DeviceReadiness.DATABASE_INITIALIZABLE: QCoreApplication.translate(
            "DevicePickerDialog", "Select to create the missing iPod Library"
        ),
        DeviceReadiness.DATABASE_UNSUPPORTED: QCoreApplication.translate(
            "DevicePickerDialog", "This iPod database format is not supported yet"
        ),
        DeviceReadiness.INSPECTION_FAILED: QCoreApplication.translate(
            "DevicePickerDialog", "Device access could not be prepared"
        ),
    }[readiness]


def _issue_text(
    issue: DeviceCandidateIssue,
) -> str:
    summary = {
        DeviceCandidateIssueCode.TIMEZONE_UNCERTAIN: QCoreApplication.translate(
            "DevicePickerDialog",
            "Some dates need a timezone fallback or cannot be interpreted uniquely.",
        ),
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
        DeviceCandidateIssueCode.PHOTOS_DATABASE_UNREADABLE: QCoreApplication.translate(
            "DevicePickerDialog", "Photos could not be loaded."
        ),
        DeviceCandidateIssueCode.PLAYBACK_SIDECAR_FLUSH_PENDING: QCoreApplication.translate(
            "DevicePickerDialog",
            "Playback history and On-The-Go Playlists were saved. Safely eject before unplugging; device flushing could not be confirmed.",
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
            "DevicePickerDialog", "Device access could not be prepared."
        ),
    }[issue.code]
    if (
        issue.code
        in {
            DeviceCandidateIssueCode.VOLUME_PRESENTATION_INCOMPLETE,
            DeviceCandidateIssueCode.INSPECTION_FAILED,
        }
        and issue.detail
    ):
        return f"{summary}\n{issue.detail}"
    return summary
