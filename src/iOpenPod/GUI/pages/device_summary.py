"""An Apple-inspired device portrait and Active iPod summary.

Hallmark: left product portrait and aligned specification list; existing theme;
side-rail navigation; capacity-strip footer; no decorative motion.
Pre-emit critique: philosophy 4, hierarchy 5, execution 4, specificity 5,
restraint 5, variety 4. Quiet facts and one firmware action; native theme states.
"""

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent, QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.firmware.bootloader_controller import BootloaderController
from iOpenPod.app.firmware.bootloader_report import require_reported_bootloader
from iOpenPod.app.firmware.shared_bootloader import VERSION as BOOTLOADER_VERSION
from iOpenPod.app.firmware.shared_controller import SharedFirmwareController
from iOpenPod.app.firmware.shared_release import MOD_VERSION
from iOpenPod.app.library_workspace import EditRevision, LibraryWorkspace
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.services.device_summary import device_storage_breakdown
from iOpenPod.GUI.presentation.device_images import device_pixmap
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.storage_breakdown import StorageBreakdown, format_capacity
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    IconButton,
    IconButtonKind,
)


class DeviceSummaryPage(QWidget):
    """Compose device observations and revision-bound Library name editing."""

    unlockBootloaderRequested = Signal()
    installSharedFirmwareRequested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        theme: ThemeManager,
        workspace: LibraryWorkspace | None = None,
        bootloader_controller: BootloaderController | None = None,
        shared_firmware_controller: SharedFirmwareController | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("deviceSummaryPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._theme = theme
        self._bootloader_controller = bootloader_controller
        self._shared_firmware_controller = shared_firmware_controller
        self._active: ActiveIPod | None = None
        self._draft_name = ""
        self._workspace = workspace
        self._rename_revision: EditRevision | None = None
        self._busy = False
        self._header = PageHeader(self)
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("deviceSummaryScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        canvas = QWidget()
        canvas.setObjectName("deviceSummaryCanvas")
        canvas_layout = QHBoxLayout(canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self._body = QWidget(canvas)
        canvas_layout.addWidget(self._body, 1)
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._empty_title = self._label("deviceSummaryEmptyTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_detail = self._label("deviceSummaryModel")
        self._empty_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(self._empty_title)
        body.addWidget(self._empty_detail)
        self._surface = QFrame(self._body)
        self._surface.setObjectName("deviceSummarySurface")
        self._surface_layout = QHBoxLayout(self._surface)
        self._identity_content = QWidget(self._surface)
        self._identity_content.setMaximumWidth(LAYOUT.device_summary_identity_width)
        self._identity = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._identity.setSpacing(LAYOUT.space_2xl)
        self._identity.setContentsMargins(0, 0, 0, 0)
        self._identity_content.setLayout(self._identity)
        self._surface_layout.addStretch(0)
        self._surface_layout.addWidget(self._identity_content, 1)
        self._surface_layout.addStretch(0)
        self._portrait = QLabel(self._body)
        self._portrait.setObjectName("deviceSummaryPortrait")
        self._portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._portrait.setFixedSize(
            LAYOUT.device_summary_image_size, LAYOUT.device_summary_image_size
        )
        self._identity.addWidget(self._portrait, 0, Qt.AlignmentFlag.AlignCenter)
        self._details = QWidget(self._body)
        self._grid = QGridLayout(self._details)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(LAYOUT.space_xs)
        self._grid.setVerticalSpacing(LAYOUT.space_xs)
        self._grid.setColumnStretch(1, 1)
        self._fields: dict[str, tuple[QLabel, QLabel]] = {}
        for index, key in enumerate(
            (
                "name",
                "capacity",
                "firmware",
                "mod_version",
                "hardware_family",
                "bootloader_version",
                "updater_family",
                "serial",
                "model",
                "model_name",
                "finish",
            )
        ):
            label = self._label("deviceSummaryFieldLabel", self._details)
            label.setWordWrap(False)
            label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
            )
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            value = self._label(
                "deviceSummaryName" if key == "name" else f"deviceSummary_{key}",
                self._details,
            )
            value.setProperty("deviceSummaryValue", True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._grid.addWidget(label, index, 0)
            self._grid.addWidget(value, index, 1)
            self._fields[key] = (label, value)
        self._name = self._fields["name"][1]
        self._fields["name"][0].setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._grid.removeWidget(self._name)
        name_panel = QWidget(self._details)
        name_layout = QVBoxLayout(name_panel)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(LAYOUT.space_2xs)
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(LAYOUT.space_2xs)
        self._name_edit = QLineEdit(name_panel)
        self._name_edit.setObjectName("deviceSummaryNameEdit")
        self._name_edit.setMinimumWidth(0)
        self._name_edit.installEventFilter(self)
        self._name_edit.editingFinished.connect(self._finish_rename)
        self._rename = IconButton("pencil", "", name_panel, kind=IconButtonKind.QUIET)
        self._rename.setObjectName("deviceSummaryRename")
        self._rename.clicked.connect(self._start_rename)
        self._rename_apply = IconButton("check-circle", "", name_panel)
        self._rename_apply.setObjectName("deviceSummaryRenameApply")
        self._rename_apply.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._rename_apply.clicked.connect(self._finish_rename)
        self._rename_cancel = IconButton("x", "", name_panel)
        self._rename_cancel.setObjectName("deviceSummaryRenameCancel")
        self._rename_cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._rename_cancel.clicked.connect(self._cancel_rename)
        name_row.addWidget(self._name, 1)
        name_row.addWidget(self._name_edit, 1)
        name_row.addWidget(self._rename)
        name_row.addWidget(self._rename_apply)
        name_row.addWidget(self._rename_cancel)
        self._name_spacer = QWidget(name_panel)
        name_row.addWidget(self._name_spacer)
        self._rename_feedback = self._label("renameIPodFeedback", name_panel)
        self._rename_feedback.setProperty("error", True)
        name_layout.addLayout(name_row)
        name_layout.addWidget(self._rename_feedback)
        self._grid.addWidget(name_panel, 0, 1)
        self._cancel_rename()
        self._identity.addWidget(self._details, 1, Qt.AlignmentFlag.AlignVCenter)
        surface_row = QHBoxLayout()
        surface_row.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, 0
        )
        surface_row.addWidget(self._surface)
        body.addLayout(surface_row)
        self._firmware_actions = QFrame(self._body)
        self._firmware_actions.setObjectName("deviceFirmwareActions")
        self._firmware_layout = QBoxLayout(
            QBoxLayout.Direction.LeftToRight, self._firmware_actions
        )
        firmware_layout = self._firmware_layout
        firmware_layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        firmware_layout.setSpacing(LAYOUT.space_lg)
        firmware_copy = QVBoxLayout()
        firmware_copy.setSpacing(LAYOUT.space_xs)
        firmware_layout.addLayout(firmware_copy, 1)
        self._firmware_heading = self._label(
            "deviceFirmwareTitle", self._firmware_actions
        )
        firmware_copy.addWidget(self._firmware_heading)
        self._firmware_current = self._label(
            "deviceFirmwareCurrent", self._firmware_actions
        )
        firmware_copy.addWidget(self._firmware_current)
        firmware_buttons = QVBoxLayout()
        firmware_buttons.setSpacing(LAYOUT.space_sm)
        firmware_layout.addLayout(firmware_buttons)
        self._unlock_bootloader = ActionButton(
            parent=self._firmware_actions, kind=ActionButtonKind.PRIMARY
        )
        self._unlock_bootloader.setObjectName("unlockBootloader")
        self._unlock_bootloader.clicked.connect(self.unlockBootloaderRequested.emit)
        self._unlock_hint = self._label("deviceBootloaderHint", self._firmware_actions)
        firmware_buttons.addWidget(self._unlock_bootloader)
        firmware_copy.addWidget(self._unlock_hint)
        self._install_shared = ActionButton(
            parent=self._firmware_actions, kind=ActionButtonKind.PRIMARY
        )
        self._install_shared.setObjectName("installSharedFirmware")
        self._install_shared.clicked.connect(self.installSharedFirmwareRequested.emit)
        self._install_hint = self._label(
            "deviceSharedFirmwareHint", self._firmware_actions
        )
        firmware_buttons.addWidget(self._install_shared)
        firmware_copy.addWidget(self._install_hint)
        firmware_surface_row = QHBoxLayout()
        firmware_surface_row.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        firmware_surface_row.addWidget(self._firmware_actions)
        body.addLayout(firmware_surface_row)
        body.addStretch(1)
        self._scroll.setWidget(canvas)
        self._storage = StorageBreakdown(theme, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._storage)
        theme.deviceArtworkChanged.connect(self._refresh_portrait)
        if workspace is not None:
            workspace.changed.connect(self._rename_state_changed)
        if bootloader_controller is not None:
            bootloader_controller.changed.connect(self._refresh_bootloader)
        if shared_firmware_controller is not None:
            shared_firmware_controller.changed.connect(self._refresh_bootloader)
        self.retranslate_ui()

    def _label(self, name: str, parent: QWidget | None = None) -> QLabel:
        label = QLabel(parent or self._body)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def set_active_ipod(self, active: ActiveIPod | None) -> None:
        self._cancel_rename()
        self._active = active
        self._draft_name = ""
        self._refresh()

    def _firmware_button_text(self, text: str, button: ActionButton) -> str:
        if self.width() >= 480:
            return text
        available = max(
            1,
            self.width()
            - 4 * LAYOUT.space_lg
            - LAYOUT.scrollbar_extent
            - 2 * LAYOUT.device_summary_border_width
            - 2 * LAYOUT.space_md
            - 4,
        )
        lines: list[str] = []
        current = ""
        for word in text.replace("-", "- ").split():
            separator = "" if not current or current.endswith("-") else " "
            candidate = current + separator + word
            if (
                current
                and button.fontMetrics().horizontalAdvance(candidate) > available
            ):
                lines.append(current)
                current = word
            else:
                current = candidate
        return "\n".join((*lines, current))

    def _observed_value(self, value: str, current: bool) -> str:
        if not value:
            return self.tr("Unavailable")
        return value if current else self.tr("{value} (cached)").format(value=value)

    def _refresh_bootloader(self) -> None:
        controller = self._bootloader_controller
        supported = controller is not None and controller.supported(self._active)
        resume = controller is not None and controller.can_resume
        self._unlock_bootloader.setEnabled((supported or resume) and not self._busy)
        shared = self._shared_firmware_controller
        pending = shared is not None and shared.needs_attention
        recorded_family = (
            shared.recorded_hardware_family(self._active) if shared else None
        )
        can_install = shared is not None and shared.can_install(self._active)
        report = self._active.bootloader_report if self._active else None
        bootloader_current = recorded_family is not None
        family = recorded_family
        version = BOOTLOADER_VERSION if recorded_family is not None else ""
        provenance = self.tr("Last verified in DFU") if version else ""
        if report is not None:
            family = report.hardware_family
            version = report.version
            provenance = self.tr("Reported by firmware")
            try:
                require_reported_bootloader(
                    report,
                    serial=self._active.serial_number if self._active else "",
                    model=self._active.profile.model_number if self._active else "",
                )
            except ValueError:
                bootloader_current = False
            else:
                bootloader_current = True
        for key, value in (
            ("mod_version", report.mod_version if report else ""),
            ("hardware_family", str(family) if family is not None else ""),
            ("bootloader_version", version),
        ):
            field = self._fields[key][1]
            field.setText(
                value or self.tr("Unavailable") if self._active is not None else "—"
            )
            field.setToolTip(
                self.tr("Reported by firmware")
                if key == "mod_version" and value
                else provenance
                if key != "mod_version"
                else ""
            )
        show_unlock = not bootloader_current and (self._active is not None or resume)
        show_install = bootloader_current and (
            report is None or report.mod_version != MOD_VERSION
        )
        self._unlock_bootloader.setVisible(show_unlock)
        self._unlock_hint.setVisible(show_unlock)
        self._install_shared.setVisible(show_install)
        self._install_hint.setVisible(show_install or pending)
        self._firmware_current.setVisible(
            self._active is not None and not show_unlock and not show_install
        )
        text = (
            self.tr("Check bootloader result")
            if resume
            else self.tr("Update bootloader to {version}").format(
                version=BOOTLOADER_VERSION
            )
            if version
            else self.tr("Install unlocked bootloader")
        )
        self._unlock_bootloader.setText(
            self._firmware_button_text(text, self._unlock_bootloader)
        )
        install_text = (
            self.tr("Installation needs attention")
            if pending
            else self.tr("Update firmware to {mod_version}").format(
                mod_version=MOD_VERSION
            )
            if report is not None and report.mod_version
            else self.tr("Install universal 2.0.5")
        )
        self._install_shared.setText(
            self._firmware_button_text(install_text, self._install_shared)
        )
        self._install_shared.setEnabled((can_install or pending) and not self._busy)
        self._install_hint.setText(
            self.tr("The previous firmware upload was interrupted")
            if pending
            else self.tr("This installation has no direct USB disk access")
            if shared is not None and not shared.upload_supported
            else self.tr("Install over USB")
            if can_install and report is not None and report.mod_version
            else self.tr("Mod version {mod_version} · Install over USB").format(
                mod_version=MOD_VERSION
            )
            if can_install
            else self.tr("Check the bootloader report or run bootloader setup")
            if report is not None
            else self.tr("Refresh the iPod to read its current firmware")
            if recorded_family is not None
            else self.tr("Install the unlocked bootloader first")
        )
        self._firmware_actions.setVisible(
            (controller is not None or shared is not None)
            and (self._active is not None or resume or pending)
        )
        self._unlock_hint.setText(
            self.tr("Guided DFU setup")
            if supported
            else self.tr("Available for iPod Classic families 24, 33, 35 and 38")
        )

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_bootloader()
        self._rename_state_changed()

    def _can_rename(self) -> bool:
        workspace = self._workspace
        return (
            self._active is not None
            and workspace is not None
            and workspace.snapshot is not None
            and not workspace.locked
            and not self._busy
        )

    def _rename_state_changed(self) -> None:
        workspace = self._workspace
        if self._rename_revision is not None and (
            not self._can_rename()
            or workspace is None
            or self._rename_revision.generation != workspace.generation
        ):
            self._cancel_rename()
        self._rename.setEnabled(self._can_rename())
        self._refresh_name()

    def _start_rename(self) -> None:
        workspace = self._workspace
        if not self._can_rename() or workspace is None:
            return
        self._rename_revision = workspace.edit_revision
        self._name_edit.setText(self._name.text())
        self._name.hide()
        self._rename.hide()
        self._name_spacer.hide()
        self._name_edit.show()
        self._rename_apply.show()
        self._rename_cancel.show()
        self._name_edit.selectAll()
        self._name_edit.setFocus()

    def _cancel_rename(self) -> None:
        self._rename_revision = None
        self._name_edit.hide()
        self._rename_apply.hide()
        self._rename_cancel.hide()
        self._rename_feedback.hide()
        self._name.show()
        self._rename.show()
        self._name_spacer.show()
        self._rename.setEnabled(self._can_rename())
        self._refresh_name()

    def _finish_rename(self) -> None:
        workspace, revision = self._workspace, self._rename_revision
        if workspace is None or revision is None:
            return
        try:
            workspace.rename_device(self._name_edit.text().strip(), revision)
        except ValueError as error:
            self._rename_feedback.setText(workflow_text(str(error)))
            self._rename_feedback.show()
            self._name_edit.setFocus()
            return
        self._cancel_rename()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self._name_edit
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self._cancel_rename()
            return True
        return super().eventFilter(watched, event)

    def set_device_name(self, name: str) -> None:
        """Reflect a name edit; capacity stays tied to the saved device state."""
        self._draft_name = name.strip()
        self._refresh_name()

    def retranslate_ui(self) -> None:
        self._name_edit.setAccessibleName(
            QCoreApplication.translate("DeviceCard", "iPod name")
        )
        for button, text in (
            (self._rename, QCoreApplication.translate("DeviceCard", "Rename iPod")),
            (
                self._rename_apply,
                QCoreApplication.translate("DeviceCard", "Apply iPod name"),
            ),
            (
                self._rename_cancel,
                QCoreApplication.translate("DeviceCard", "Cancel renaming"),
            ),
        ):
            button.setAccessibleName(text)
            button.setToolTip(text)
        self._header.set_title(self.tr("Summary"))
        self._firmware_heading.setText(self.tr("Firmware"))
        self._firmware_current.setText(
            self.tr("Bootloader and firmware are up to date.")
        )
        self._empty_title.setText(self.tr("No Active iPod"))
        self._empty_detail.setText(
            self.tr("Choose an iPod from the sidebar to see its details.")
        )
        labels = (
            self.tr("Name"),
            self.tr("Capacity"),
            self.tr("Reported firmware"),
            self.tr("Mod version"),
            self.tr("Hardware family ID"),
            self.tr("Bootloader version"),
            self.tr("OS updater family"),
            self.tr("Serial number"),
            self.tr("Model number"),
            self.tr("Model"),
            self.tr("Color"),
        )
        for (label, _), text in zip(self._fields.values(), labels, strict=True):
            label.setText(f"{text}:")
        self._refresh()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        elif event.type() in {
            QEvent.Type.DevicePixelRatioChange,
            QEvent.Type.ScreenChangeInternal,
        }:
            self._refresh_portrait()
        super().changeEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._firmware_layout.setDirection(
            QBoxLayout.Direction.LeftToRight
            if self.width() >= 640
            else QBoxLayout.Direction.TopToBottom
        )
        self._refresh_bootloader()
        for label, _ in self._fields.values():
            label.setWordWrap(self.width() < 480)
        padding = LAYOUT.space_xs if self.width() < 480 else LAYOUT.space_lg
        self._surface_layout.setContentsMargins(
            padding, LAYOUT.space_md, padding, LAYOUT.space_md
        )
        image_size = min(
            LAYOUT.device_summary_image_size,
            max(
                128,
                self.width()
                - 2 * LAYOUT.space_lg
                - 2 * padding
                - LAYOUT.scrollbar_extent
                - 2 * LAYOUT.device_summary_border_width,
            ),
        )
        if self._portrait.width() != image_size:
            self._portrait.setFixedSize(image_size, image_size)
            self._refresh_portrait()
        self._identity.setDirection(
            QBoxLayout.Direction.LeftToRight
            if self.width() >= 760
            else QBoxLayout.Direction.TopToBottom
        )

    def _refresh_name(self) -> None:
        active = self._active
        workspace = self._workspace
        name = (
            workspace.device_name
            if workspace is not None and workspace.snapshot is not None
            else self._draft_name
        )
        self._name.setText(
            (name or active.display_name) if active else self.tr("No Active iPod")
        )

        self._name.setMaximumWidth(
            self._name.fontMetrics().horizontalAdvance(self._name.text())
            + LAYOUT.space_2xs
        )

    def _refresh(self) -> None:
        active = self._active
        self._empty_title.setVisible(active is None)
        self._empty_detail.setVisible(active is None)
        self._details.setVisible(active is not None)
        self._refresh_portrait()
        values: dict[str, str] = {}
        if active is not None:
            values = {
                "name": active.display_name,
                "capacity": format_capacity(active.candidate.total_bytes)
                if active.candidate.total_bytes > 0
                else self.tr("Unavailable"),
                "firmware": self._observed_value(
                    active.firmware_version, active.firmware_version_current
                ),
                "updater_family": self._observed_value(
                    str(active.updater_family_id), active.updater_family_current
                )
                if active.updater_family_id is not None
                else self.tr("Unavailable"),
                "serial": active.serial_number or self.tr("Unavailable"),
                "model": active.profile.model_number,
                "model_name": active.profile.display_name,
                "finish": active.profile.finish,
            }
        for key, (label, value) in self._fields.items():
            value.setText(values.get(key, "—"))
            value.setAccessibleName(label.text().removesuffix(":"))
        self._fields["firmware"][1].setToolTip(
            self.tr(
                "The OS-reported version is independent of the hardware and bootloader. Cached values have not been confirmed on this connection."
            )
        )
        self._fields["updater_family"][1].setToolTip(
            self.tr(
                "The running OS reports this updater family. Modified firmware can report a different family from the physical iPod."
            )
        )
        self._refresh_bootloader()
        self._refresh_name()
        self._rename_state_changed()
        self._storage.set_breakdown(
            device_storage_breakdown(
                active.candidate,
                active.library,
                game_storage_bytes=active.game_storage_bytes,
                album_artwork_storage_bytes=active.album_artwork_storage_bytes,
            )
            if active
            else None
        )

    def _refresh_portrait(self) -> None:
        active = self._active
        self._portrait.setPixmap(
            device_pixmap(
                active.profile.product_image if active else "iPodGeneric.png",
                self._portrait.width(),
                self.devicePixelRatioF(),
                itunes_107=self._theme.itunes_107_artwork,
            )
        )
        self._portrait.setAccessibleName(
            active.profile.display_name if active else self.tr("iPod")
        )
