"""Guided first unlock, with illustrated DFU instructions and native controls."""

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from iOpenPod.app.firmware.bootloader_controller import BootloaderController
from iOpenPod.app.firmware.bootloader_install import UnlockStage
from iOpenPod.app.firmware.shared_bootloader import VERSION
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.firmware_setup import DfuGuide, FirmwareSetupView
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind


class BootloaderUnlockDialog(QDialog):
    def __init__(
        self,
        controller: BootloaderController,
        active: ActiveIPod | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("bootloaderUnlockDialog")
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
        self._detail.setObjectName("bootloaderDetail")
        self._progress = self._view.progress
        self._guide = DfuGuide(self._view)
        self._guide.hide()
        self._view.body.insertWidget(1, self._guide)
        self._close = ActionButton(parent=self)
        self._close.setAutoDefault(False)
        self._close.setObjectName("bootloaderClose")
        self._start = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._start.setAutoDefault(False)
        self._start.setObjectName("bootloaderStart")
        self._close.clicked.connect(self.reject)
        self._start.clicked.connect(self._begin)
        self._view.buttons.addWidget(self._close)
        self._view.buttons.addWidget(self._start)
        controller.changed.connect(self._refresh)
        controller.prepare()
        self._refresh()

    def _begin(self) -> None:
        started = (
            self._controller.resume()
            if self._controller.can_resume
            else self._active is not None and self._controller.start(self._active)
        )
        if not started:
            self._detail.setText(
                self.tr(
                    "The selected iPod is no longer available. Close setup and select it again."
                )
            )
            self._start.setEnabled(False)

    def _refresh(self) -> None:
        state = self._controller.progress
        self.setWindowTitle(self.tr("Install unlocked bootloader"))
        self._view.eyebrow.setText(self.tr("CUSTOM FIRMWARE  /  STEP 1 OF 2"))
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
            UnlockStage.READY: (
                self.tr("Unlock your Classic"),
                self.tr(
                    "Install Bootloader {version} to enable iOpenPod firmware. Your current firmware and music stay in place.\n\nNext, we'll guide you into DFU mode using two buttons on your iPod."
                ).format(version=VERSION),
            ),
            UnlockStage.WAITING_DFU: (
                self.tr("Enter DFU mode"),
                self.tr(
                    "Keep USB connected and turn Hold off so no orange is showing."
                ),
            ),
            UnlockStage.CHECKING: (
                self.tr("Your iPod is connected"),
                self.tr(
                    "Checking its identity and preparing the bootloader. Leave the screen black and USB connected."
                ),
            ),
            UnlockStage.INSTALLING: (
                self.tr("Installing the bootloader"),
                self.tr(
                    "Keep USB connected and leave the buttons alone. The iPod's screen will stay black during installation."
                ),
            ),
            UnlockStage.VERIFYING: (
                self.tr("Checking the installation"),
                self.tr(
                    "Verifying the bootloader on your iPod. Keep it connected with the screen black."
                ),
            ),
            UnlockStage.RESTART: (
                self.tr("Already unlocked")
                if state.already_unlocked
                else self.tr("Bootloader installed"),
                self.tr(
                    "Hold Menu + Select until the Apple logo appears, then release both. Let your iPod start normally.\n\nClose this window and select the iPod again. In Device Summary, choose Install universal 2.0.5."
                ),
            ),
            UnlockStage.COMPLETE: (
                self.tr("Your iPod is unlocked"),
                self.tr(
                    "The bootloader is verified and your iPod has reconnected. You can now install iOpenPod firmware from Device Summary."
                ),
            ),
            UnlockStage.CANCELED: (
                self.tr("Setup canceled"),
                self.tr(
                    "No installation was started. If the screen is black, hold Menu + Select until the Apple logo appears, then release."
                ),
            ),
            UnlockStage.ERROR: (self.tr("Setup needs attention"), state.detail),
        }
        heading, detail = messages[state.stage]
        notice = ""
        status = ""
        tone = "default"
        if state.stage is UnlockStage.READY:
            notice = self.tr(
                "Charge your iPod first and keep USB connected. An interrupted bootloader write may require DFU recovery."
            )
        elif state.stage is UnlockStage.WAITING_DFU:
            notice = self.tr(
                "If iTunes offers to restore the iPod, dismiss that prompt."
            )
            status = self.tr(
                "Waiting for DFU · Installation starts automatically when detected."
            )
        elif state.stage in (
            UnlockStage.CHECKING,
            UnlockStage.INSTALLING,
            UnlockStage.VERIFYING,
        ):
            status = self.tr("Keep your iPod connected")
            if state.percent is not None:
                status = self.tr("{percent}% complete · Keep USB connected").format(
                    percent=state.percent
                )
        elif state.stage in (UnlockStage.RESTART, UnlockStage.COMPLETE):
            status, tone = self.tr("Bootloader verified"), "success"
            if state.stage is UnlockStage.RESTART:
                notice = self.tr(
                    "If it does not reconnect after starting, unplug and reconnect USB."
                )
        elif state.stage is UnlockStage.ERROR:
            status, tone = self.tr("Setup stopped"), "error"
            notice = self.tr(
                "No write is retried automatically. If installation started, keep the iPod connected and reopen setup to check its result before restarting."
            )
        if self._controller.can_resume:
            heading = self.tr("Check unfinished installation")
            detail = self.tr(
                "Keep iPod {serial} connected with its screen black. Check result verifies the previous installation; it does not install again."
            ).format(serial=serial)
            status, tone = (
                self.tr("Previous installation needs verification"),
                "default",
            )
            notice = ""
        self._heading.setText(heading)
        self._detail.setText(detail)
        show_guide = state.stage is UnlockStage.WAITING_DFU
        if show_guide and self._guide.isHidden():
            available = self.screen().availableGeometry().height() - LAYOUT.space_3xl
            self.resize(self.width(), min(LAYOUT.firmware_guide_height, available))
        self._guide.setVisible(show_guide)
        self._view.notice.setText(notice)
        self._view.notice.setVisible(bool(notice))
        self._view.set_status(status, tone=tone)
        self._start.setText(
            self.tr("Check result")
            if self._controller.can_resume
            else self.tr("Start DFU setup")
        )
        self._start.setVisible(
            state.stage is UnlockStage.READY or self._controller.can_resume
        )
        self._start.setEnabled(not self._controller.busy)
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
