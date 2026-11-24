"""Wizard lifecycle: no GUI-thread USB, no closing a live writer, fresh reconnect."""

from collections.abc import Callable
from dataclasses import replace
from threading import Event
from typing import TYPE_CHECKING, cast

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton
from tests.iOpenPod.GUI.firmware_helpers import until
from tests.iOpenPod.GUI.test_device_summary_page import APPLICATION, summary_active_ipod

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.firmware.bootloader_controller import BootloaderController
from iOpenPod.app.firmware.bootloader_install import (
    UnlockIdentity,
    UnlockProgress,
    UnlockStage,
)
from iOpenPod.app.firmware.bootloader_targets import bootloader_target
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.GUI.dialogs.bootloader_unlock import BootloaderUnlockDialog
from iOpenPod.GUI.pages.device_summary import DeviceSummaryPage
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from storage import UsbControlDriverError

if TYPE_CHECKING:
    from iOpenPod.app.device_controller import DeviceController


class Devices(QObject):
    activeIPodChanged = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.active_ipod: ActiveIPod | None = summary_active_ipod()
        self.busy = False
        self.released = False

    def prepare_firmware_mode_change(self, expected: ActiveIPod) -> bool:
        assert expected is self.active_ipod
        self.active_ipod = None
        self.activeIPodChanged.emit(None)
        self.busy = True
        return True

    def begin_recovery_operation(self) -> bool:
        self.busy = True
        return True

    def finish_exclusive_operation(self) -> None:
        self.busy = False
        self.released = True

    def refresh_devices(self) -> None:
        assert not self.busy


class Installer:
    platform = "windows"

    def __init__(self) -> None:
        self.write = Event()
        self.finish = Event()
        self.pending: UnlockIdentity | None = None
        self.resume_calls = 0

    def pending_identity(self) -> UnlockIdentity | None:
        return self.pending

    def run(
        self,
        identity: UnlockIdentity,
        cancel: Event,
        publish: Callable[[UnlockProgress], None],
        *,
        verify_only: bool = False,
    ) -> bool:
        if verify_only:
            self.resume_calls += 1
            self.pending = None
            return False
        publish(UnlockProgress(UnlockStage.CHECKING))
        while not self.write.wait(0.01):
            if cancel.is_set():
                raise InterruptedError
        publish(UnlockProgress(UnlockStage.INSTALLING))
        assert self.finish.wait(5)
        return False


@pytest.mark.parametrize(
    "platform,expected",
    [("windows", "iTunes"), ("linux", "administrator approval once")],
)
def test_first_setup_explains_host_usb_access(platform: str, expected: str) -> None:
    devices, installer = Devices(), Installer()
    installer.platform = platform
    controller = BootloaderController(installer, cast("DeviceController", devices))
    dialog = BootloaderUnlockDialog(controller, devices.active_ipod)
    try:
        assert any(expected in label.text() for label in dialog.findChildren(QLabel))
    finally:
        controller.shutdown()
        dialog.close()


def test_missing_windows_driver_guidance_is_owned_by_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices, installer = Devices(), Installer()

    def unavailable(
        _identity: UnlockIdentity,
        _cancel: Event,
        _publish: Callable[[UnlockProgress], None],
        *,
        verify_only: bool = False,
    ) -> bool:
        raise UsbControlDriverError("No compatible USB control driver is available")

    monkeypatch.setattr(installer, "run", unavailable)
    controller = BootloaderController(installer, cast("DeviceController", devices))
    active = devices.active_ipod
    assert active is not None
    try:
        assert controller.start(active)
        until(lambda: not controller.busy)
        assert controller.progress.stage is UnlockStage.ERROR
        assert "iTunes" in controller.progress.detail
        assert "does not install a Windows USB driver" in controller.progress.detail
        assert devices.released
    finally:
        controller.shutdown()


@pytest.mark.parametrize("family", (24, 33, 35, 38))
def test_shared_loader_is_selectable_for_each_supported_family(
    family: int,
) -> None:
    devices, installer = Devices(), Installer()
    active = summary_active_ipod()
    target = bootloader_target(family)
    devices.active_ipod = replace(
        active,
        updater_family_id=family,
        firmware_version=target.apple_version,
        profile=replace(active.profile, model_number=target.models[0]),
    )
    controller = BootloaderController(installer, cast("DeviceController", devices))
    dialog = BootloaderUnlockDialog(controller, devices.active_ipod)
    try:
        dialog.open()
        APPLICATION.processEvents()
        assert controller.supported(devices.active_ipod)
        detail = dialog.findChild(QLabel, "bootloaderDetail")
        assert detail is not None
        assert "Bootloader 2.1.0" in detail.text()
        assert "has not yet been tested" not in detail.text()
        assert detail.height() >= detail.heightForWidth(detail.width())
    finally:
        controller.shutdown()
        dialog.close()


def test_escape_cancels_preparation_and_releases_device() -> None:
    devices, installer = Devices(), Installer()
    controller = BootloaderController(installer, cast("DeviceController", devices))
    dialog = BootloaderUnlockDialog(controller, devices.active_ipod)
    try:
        dialog.open()
        start = dialog.findChild(QPushButton, "bootloaderStart")
        assert start is not None
        start.click()
        until(lambda: controller.progress.stage is UnlockStage.CHECKING)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        until(lambda: not controller.busy)
        assert controller.progress.stage is UnlockStage.CANCELED
        assert devices.released
        assert dialog.isVisible()
        dialog.reject()
        assert not dialog.isVisible()
    finally:
        installer.finish.set()
        controller.shutdown()
        dialog.close()


def test_escape_and_close_cannot_detach_live_writer() -> None:
    devices, installer = Devices(), Installer()
    controller = BootloaderController(installer, cast("DeviceController", devices))
    active = devices.active_ipod
    assert active is not None
    dialog = BootloaderUnlockDialog(controller, active)
    try:
        dialog.open()
        installer.write.set()
        assert controller.start(active)
        until(lambda: controller.progress.stage is UnlockStage.INSTALLING)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        dialog.close()
        APPLICATION.processEvents()
        assert dialog.isVisible() and controller.busy and devices.busy
        installer.finish.set()
        until(lambda: not controller.busy)
        assert controller.progress.stage is UnlockStage.RESTART
        devices.activeIPodChanged.emit(replace(active, serial_number="OTHER123456"))
        assert controller.progress.stage is UnlockStage.RESTART
        devices.activeIPodChanged.emit(active)
        until(lambda: controller.progress.stage is UnlockStage.COMPLETE)
    finally:
        installer.finish.set()
        controller.shutdown()
        dialog.close()


def test_unfinished_install_can_be_checked_without_mounted_ipod() -> None:
    devices, installer = Devices(), Installer()
    devices.active_ipod = None
    installer.pending = UnlockIdentity("8K123ABC9ZS", "MB565")
    controller = BootloaderController(installer, cast("DeviceController", devices))
    theme = ThemeManager(
        APPLICATION, SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    )
    page = DeviceSummaryPage(theme=theme, bootloader_controller=controller)
    dialog = BootloaderUnlockDialog(controller, None)
    try:
        page.show()
        button = page.findChild(QPushButton, "unlockBootloader")
        assert button is not None and button.isEnabled() and button.isVisible()
        dialog.open()
        start = dialog.findChild(QPushButton, "bootloaderStart")
        detail = dialog.findChild(QLabel, "bootloaderDetail")
        assert start is not None and start.text() == "Check result"
        assert detail is not None and "8K123ABC9ZS" in detail.text()
        start.click()
        until(lambda: not controller.busy)
        assert installer.resume_calls == 1
        assert controller.progress.stage is UnlockStage.RESTART
    finally:
        controller.shutdown()
        dialog.close()
        page.close()
        theme.close()
