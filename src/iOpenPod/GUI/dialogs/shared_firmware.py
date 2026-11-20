"""Normal USB installation of shared Classic firmware."""

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from iOpenPod.app.firmware.shared_bootloader import VERSION as BOOTLOADER_VERSION
from iOpenPod.app.firmware.shared_controller import SharedFirmwareController
from iOpenPod.app.firmware.shared_install import InstallStage
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.firmware_setup import FirmwareSetupView, FirmwareVersions
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind


class SharedFirmwareDialog(QDialog):
    def __init__(
        self,
        controller: SharedFirmwareController,
        active: ActiveIPod | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("sharedFirmwareDialog")
        self._controller = controller
        self._active = active
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumSize(LAYOUT.firmware_dialog_minimum_width, 360)
        self.resize(LAYOUT.firmware_dialog_width, LAYOUT.firmware_dialog_height)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._view = FirmwareSetupView(self)
        layout.addWidget(self._view)
        self._heading = self._view.heading
        self._detail = self._view.detail
        self._detail.setObjectName("sharedFirmwareDetail")
        self._progress = self._view.progress
        self._versions = FirmwareVersions(self._view)
        self._view.body.insertWidget(1, self._versions)
        self._close = ActionButton(parent=self)
        self._close.setObjectName("sharedFirmwareClose")
        self._close.setAutoDefault(False)
        self._close.clicked.connect(self.reject)
        self._action = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._action.setObjectName("sharedFirmwareAction")
        self._action.setAutoDefault(False)
        self._action.clicked.connect(self._begin)
        self._view.buttons.addWidget(self._close)
        self._view.buttons.addWidget(self._action)
        controller.changed.connect(self._refresh)
        controller.prepare(active)
        self._refresh()

    def _begin(self) -> None:
        try:
            started = self._active is not None and self._controller.start(self._active)
            if not started:
                self._detail.setText(
                    self.tr("Select the same iPod again before continuing.")
                )
        except Exception as error:
            self._detail.setText(str(error))

    def _refresh(self) -> None:
        state = self._controller.progress
        self.setWindowTitle(self.tr("Install universal 2.0.5"))
        self._view.eyebrow.setText(self.tr("CUSTOM FIRMWARE  /  STEP 2 OF 2"))
        pending = self._controller.pending
        name = (
            self._active.display_name
            if self._active
            and (pending is None or pending.serial == self._active.serial_number)
            else self.tr("iPod Classic")
        )
        serial = (
            pending.serial
            if pending
            else self._active.serial_number
            if self._active
            else ""
        )
        self._view.identity.setText(f"{name} · {serial}" if serial else name)
        messages = {
            InstallStage.READY: (
                self.tr("Install iOpenPod firmware"),
                self.tr(
                    "Give your Classic the bundled firmware and mods. This step uses normal USB, with no download or DFU mode needed."
                ),
            ),
            InstallStage.PREPARING: (
                self.tr("Preparing your firmware"),
                self.tr(
                    "Unpacking and checking the firmware included with iOpenPod. You can cancel before writing begins."
                ),
            ),
            InstallStage.CHECKING: (
                self.tr("Checking your iPod"),
                self.tr(
                    "Checking its identity, firmware space and music library before installation."
                ),
            ),
            InstallStage.INSTALLING: (
                self.tr("Installing firmware"),
                self.tr(
                    "Keep USB connected and leave the buttons alone. Your iPod will restart after the upload finishes."
                ),
            ),
            InstallStage.COMPLETE: (
                self.tr("Firmware installed"),
                self.tr(
                    "Apple 2.0.5 and Mod Version {mod_version} have been uploaded. Your iPod is restarting."
                ),
            ),
            InstallStage.CANCELED: (
                self.tr("Installation canceled"),
                self.tr(
                    "No firmware was written. Select your iPod again when you are ready."
                ),
            ),
            InstallStage.ERROR: (self.tr("Installation needs attention"), state.detail),
        }
        heading, detail = messages[state.stage]
        self._heading.setText(heading)
        self._detail.setText(
            detail.replace("{mod_version}", self._controller.mod_version)
        )
        self._versions.set_version(self._controller.mod_version)
        self._versions.setVisible(
            state.stage in (InstallStage.READY, InstallStage.COMPLETE)
        )
        notice, status, tone = "", "", "default"
        if state.stage is InstallStage.READY:
            notice = self.tr(
                "Requires unlocked Bootloader {version}. Your music and disk layout are preserved. Keep your iPod charged and connected."
            ).format(version=BOOTLOADER_VERSION)
        elif state.stage is InstallStage.COMPLETE:
            status, tone = self.tr("Installation complete"), "success"
            notice = self.tr("Keep USB connected until your iPod finishes restarting.")
        elif state.stage is InstallStage.ERROR:
            status, tone = self.tr("Installation stopped"), "error"
            notice = self.tr(
                "No upload is retried automatically. Keep your iPod connected if the upload was interrupted."
            )
        elif self._controller.busy:
            status = self.tr("Keep your iPod connected")
            if state.percent is not None:
                status = self.tr("{percent}% complete · Keep USB connected").format(
                    percent=state.percent
                )
        self._view.notice.setText(notice)
        self._view.notice.setVisible(bool(notice))
        self._view.set_status(status, tone=tone)
        self._action.setText(self.tr("Install firmware"))
        self._action.setVisible(
            not self._controller.busy and state.stage is InstallStage.READY
        )
        self._action.setEnabled(
            state.stage is not InstallStage.READY
            or self._controller.can_install(self._active)
        )
        self._close.setText(
            QCoreApplication.translate("CommonActions", "Cancel")
            if self._controller.busy
            else QCoreApplication.translate("CommonActions", "Close")
        )
        self._close.setEnabled(not self._controller.busy or self._controller.can_cancel)
        self._progress.setVisible(self._controller.busy)
        self._progress.setRange(0, 0 if state.percent is None else 100)
        if state.percent is not None:
            self._progress.setValue(state.percent)

    def reject(self) -> None:
        if self._controller.busy:
            self._controller.cancel()
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._controller.busy:
            self._controller.cancel()
            event.ignore()
        else:
            super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._refresh()
        super().changeEvent(event)
