"""Presentation snapshots exercise every setup stage without device access."""

from typing import TYPE_CHECKING, cast

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QScrollArea
from tests.iOpenPod.GUI.test_device_summary_page import APPLICATION, summary_active_ipod

from iOpenPod.app.core.settings.definitions import AppearanceMode
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.firmware.bootloader_install import (
    UnlockIdentity,
    UnlockProgress,
    UnlockStage,
)
from iOpenPod.app.firmware.shared_install import InstallProgress, InstallStage
from iOpenPod.app.firmware.shared_release import MOD_VERSION
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.GUI.dialogs.bootloader_unlock import BootloaderUnlockDialog
from iOpenPod.GUI.dialogs.shared_firmware import SharedFirmwareDialog
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.firmware_setup import DfuDiagram, DfuGuide

if TYPE_CHECKING:
    from collections.abc import Iterator

    from iOpenPod.app.firmware.bootloader_controller import BootloaderController
    from iOpenPod.app.firmware.shared_controller import SharedFirmwareController


@pytest.fixture(autouse=True)
def setup_theme() -> "Iterator[None]":
    """Use the app's actual theme instead of another GUI test's global styling."""
    font = APPLICATION.font()
    palette = APPLICATION.palette()
    stylesheet = APPLICATION.styleSheet()
    theme = ThemeManager(
        APPLICATION, SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    )
    theme.set_mode(AppearanceMode.LIGHT)
    try:
        yield
    finally:
        theme.close()
        APPLICATION.setFont(font)
        APPLICATION.setPalette(palette)
        APPLICATION.setStyleSheet(stylesheet)


class BootSnapshot(QObject):
    changed = Signal()

    def __init__(self, stage: UnlockStage) -> None:
        super().__init__()
        self.progress = UnlockProgress(
            stage,
            50 if stage is UnlockStage.INSTALLING else None,
            "The selected iPod disconnected during the identity check.",
        )
        self.pending: UnlockIdentity | None = None
        self.busy = stage in (
            UnlockStage.WAITING_DFU,
            UnlockStage.CHECKING,
            UnlockStage.INSTALLING,
            UnlockStage.VERIFYING,
        )
        self.can_cancel = stage in (UnlockStage.WAITING_DFU, UnlockStage.CHECKING)
        self.can_resume = False

    def prepare(self) -> None:
        pass

    def cancel(self) -> None:
        pass


class FirmwareSnapshot(QObject):
    changed = Signal()

    def __init__(self, stage: InstallStage) -> None:
        super().__init__()
        self.progress = InstallProgress(
            stage,
            50 if stage is InstallStage.INSTALLING else None,
            "The selected iPod disconnected during the identity check.",
        )
        self.pending: UnlockIdentity | None = None
        self.mod_version = MOD_VERSION
        self.busy = stage in (
            InstallStage.PREPARING,
            InstallStage.CHECKING,
            InstallStage.INSTALLING,
        )
        self.can_cancel = stage in (InstallStage.PREPARING, InstallStage.CHECKING)

    def prepare(self, active: ActiveIPod | None) -> None:
        pass

    def can_install(self, active: ActiveIPod | None) -> bool:
        return active is not None

    def cancel(self) -> None:
        pass


@pytest.mark.parametrize("bootloader", [False, True])
def test_pending_installation_does_not_borrow_another_ipods_name(
    bootloader: bool,
) -> None:
    pending = UnlockIdentity("TEST12345678", "MB565", 33)
    boot = BootSnapshot(UnlockStage.ERROR)
    firmware = FirmwareSnapshot(InstallStage.ERROR)
    boot.pending = firmware.pending = pending
    active = summary_active_ipod()
    assert active.serial_number != pending.serial
    dialog = (
        BootloaderUnlockDialog(cast("BootloaderController", boot), active)
        if bootloader
        else SharedFirmwareDialog(cast("SharedFirmwareController", firmware), active)
    )
    try:
        identity = dialog.findChild(QLabel, "firmwareIdentity")
        assert identity is not None
        assert identity.text() == "iPod Classic · TEST12345678"
    finally:
        dialog.close()


@pytest.mark.parametrize("stage", list(UnlockStage))
def test_bootloader_stage_controls_and_guide(stage: UnlockStage) -> None:
    snapshot = BootSnapshot(stage)
    dialog = BootloaderUnlockDialog(
        cast("BootloaderController", snapshot), summary_active_ipod()
    )
    try:
        dialog.show()
        APPLICATION.processEvents()
        close = dialog.findChild(QPushButton, "bootloaderClose")
        guide = dialog.findChild(DfuGuide)
        assert close is not None and guide is not None
        assert close.isEnabled() == (not snapshot.busy or snapshot.can_cancel)
        assert guide.isVisible() == (stage is UnlockStage.WAITING_DFU)
        if guide.isVisible():
            labels = " ".join(label.text() for label in guide.findChildren(QLabel))
            assert "Menu + Select" in labels
            assert "Apple logo" in labels and "second black screen" in labels
            assert "12 seconds" not in labels
            diagram = guide.findChild(DfuDiagram)
            assert diagram is not None and "Select" in diagram.accessibleDescription()
    finally:
        snapshot.busy = False
        dialog.close()


@pytest.mark.parametrize("stage", list(InstallStage))
def test_firmware_stage_controls(stage: InstallStage) -> None:
    snapshot = FirmwareSnapshot(stage)
    dialog = SharedFirmwareDialog(
        cast("SharedFirmwareController", snapshot), summary_active_ipod()
    )
    try:
        dialog.show()
        APPLICATION.processEvents()
        close = dialog.findChild(QPushButton, "sharedFirmwareClose")
        action = dialog.findChild(QPushButton, "sharedFirmwareAction")
        assert close is not None and action is not None
        assert close.isEnabled() == (not snapshot.busy or snapshot.can_cancel)
        assert action.isVisible() == (stage is InstallStage.READY)
    finally:
        snapshot.busy = False
        dialog.close()


@pytest.mark.parametrize("width", [320, 375, 414, 768])
@pytest.mark.parametrize("mode", [AppearanceMode.LIGHT, AppearanceMode.DARK])
@pytest.mark.parametrize("dfu", [False, True])
def test_guidance_and_controls_fit_narrow_windows(
    width: int, mode: AppearanceMode, dfu: bool
) -> None:
    theme = ThemeManager(
        APPLICATION, SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    )
    theme.set_mode(mode)
    boot = BootSnapshot(UnlockStage.WAITING_DFU)
    firmware = FirmwareSnapshot(InstallStage.COMPLETE)
    dialog = (
        BootloaderUnlockDialog(
            cast("BootloaderController", boot), summary_active_ipod()
        )
        if dfu
        else SharedFirmwareDialog(
            cast("SharedFirmwareController", firmware), summary_active_ipod()
        )
    )
    try:
        dialog.resize(width, 560)
        dialog.show()
        for _ in range(3):
            APPLICATION.processEvents()
        assert dialog.width() == width
        scroll = dialog.findChild(QScrollArea)
        assert scroll is not None and scroll.horizontalScrollBar().maximum() == 0
        for label in dialog.findChildren(QLabel):
            if label.isVisible() and label.wordWrap():
                assert label.height() >= label.heightForWidth(label.width()), (
                    label.text()
                )
        for button in dialog.findChildren(QPushButton):
            if button.isVisible():
                assert button.height() >= 44
                assert button.width() >= button.fontMetrics().horizontalAdvance(
                    button.text()
                )
    finally:
        boot.busy = firmware.busy = False
        dialog.close()
        theme.close()
