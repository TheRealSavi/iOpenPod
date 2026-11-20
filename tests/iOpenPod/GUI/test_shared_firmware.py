"""Summary actions, worker ownership and completion after upload."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, cast

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton
from tests.iOpenPod.boot_report_helpers import report_xml
from tests.iOpenPod.GUI.firmware_helpers import until
from tests.iOpenPod.GUI.test_bootloader_unlock import Devices
from tests.iOpenPod.GUI.test_device_summary_page import APPLICATION, summary_active_ipod

from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.firmware.bootloader_install import UnlockIdentity
from iOpenPod.app.firmware.bootloader_report import read_bootloader_report
from iOpenPod.app.firmware.bootloader_targets import bootloader_target
from iOpenPod.app.firmware.shared_controller import SharedFirmwareController
from iOpenPod.app.firmware.shared_install import (
    InstallProgress,
    InstallStage,
)
from iOpenPod.app.firmware.shared_records import (
    PENDING_STATES,
    InstallRecord,
    InstallRecordState,
    VisibleLayout,
    finish_uploaded,
)
from iOpenPod.app.firmware.shared_release import MOD_VERSION, RELEASE_BYTES
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.GUI.dialogs.shared_firmware import SharedFirmwareDialog
from iOpenPod.GUI.pages.device_summary import DeviceSummaryPage
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from storage import MountedVolume, Storage, StorageError
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator


class Installer:
    platform = "windows"

    def __init__(self) -> None:
        self.unlocked = True
        self.hardware_family: int | None = None
        self.write = Event()
        self.finish = Event()
        self.saved: InstallRecord | None = None
        self.installs = 0

    def pending_identity(self) -> UnlockIdentity | None:
        self.saved = finish_uploaded(self.saved)
        return (
            self.saved.identity
            if self.saved and self.saved.state in PENDING_STATES
            else None
        )

    def record(self, identity: UnlockIdentity) -> InstallRecord | None:
        return self.saved

    def require_bootloader(self, identity: UnlockIdentity) -> int:
        if not self.unlocked:
            raise ValueError("Unlock first")
        return self.hardware_family or identity.family or 35

    def install(
        self,
        identity: UnlockIdentity,
        mounted: MountedVolume,
        cancel: Event,
        publish: Callable[[InstallProgress], None],
    ) -> None:
        publish(InstallProgress(InstallStage.CHECKING))
        while not self.write.wait(0.01):
            if cancel.is_set():
                raise InterruptedError
        self.installs += 1
        publish(InstallProgress(InstallStage.INSTALLING, 50))
        assert self.finish.wait(5)
        self.saved = InstallRecord(
            identity,
            "volume",
            VisibleLayout("", "", 63, ""),
            {},
            state=InstallRecordState.COMPLETE,
        )


class Coordinator:
    def __init__(self, path: Path) -> None:
        platform = VirtualStoragePlatform()
        platform.add_volume(path)
        self.mounted = Storage(platform).inspect(path)

    def firmware_volume(self, expected: ActiveIPod) -> MountedVolume:
        return self.mounted


def controller_for(
    tmp_path: Path,
) -> tuple[SharedFirmwareController, Devices, Installer]:
    devices, installer = Devices(), Installer()
    controller = SharedFirmwareController(
        installer,
        cast("DeviceController", devices),
        cast("DeviceCoordinator", Coordinator(tmp_path)),
    )
    return controller, devices, installer


@pytest.mark.parametrize("family", (24, 33, 35, 38))
def test_summary_enables_install_after_unlock_for_each_family(
    tmp_path: Path, family: int
) -> None:
    controller, _devices, installer = controller_for(tmp_path)
    installer.hardware_family = family
    target = bootloader_target(family)
    active = summary_active_ipod()
    active = replace(
        active,
        updater_family_id=family,
        firmware_version=target.apple_version,
        profile=replace(active.profile, model_number=target.models[0]),
    )
    theme = ThemeManager(
        APPLICATION, SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    )
    page = DeviceSummaryPage(theme=theme, shared_firmware_controller=controller)
    try:
        installer.unlocked = False
        page.set_active_ipod(active)
        page.show()
        button = page.findChild(QPushButton, "installSharedFirmware")
        assert button is not None and not button.isEnabled()
        assert not button.isVisible()
        unlock = page.findChild(QPushButton, "unlockBootloader")
        assert unlock is not None and unlock.isVisible()
        installer.unlocked = True
        controller.changed.emit()
        assert button.isEnabled() and button.isVisible()
        assert not unlock.isVisible()
        family_label = page.findChild(QLabel, "deviceSummary_hardware_family")
        assert family_label is not None and family_label.text() == str(family)
        assert family_label.toolTip() == "Last verified in DFU"
        assert any(MOD_VERSION in label.text() for label in page.findChildren(QLabel))
        hint = page.findChild(QLabel, "deviceSharedFirmwareHint")
        assert hint is not None and "Step" not in hint.text()
        page.set_busy(True)
        assert not button.isEnabled() and button.isVisible()
    finally:
        page.close()
        controller.shutdown()
        theme.close()


def test_unreadable_unlock_record_disables_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, devices, installer = controller_for(tmp_path)

    def unreadable(_identity: UnlockIdentity) -> None:
        raise StorageError("Cannot read the saved unlock record")

    monkeypatch.setattr(installer, "require_bootloader", unreadable)
    try:
        assert not controller.has_bootloader_record(devices.active_ipod)
    finally:
        controller.shutdown()


@pytest.mark.parametrize("status", [0, 1, 2, 3, 4])
def test_current_bootloader_report_takes_precedence_over_local_record(
    tmp_path: Path, status: int
) -> None:
    controller, devices, installer = controller_for(tmp_path)
    active = devices.active_ipod
    assert active is not None
    active = replace(
        active,
        bootloader_report=read_bootloader_report(
            report_xml(
                Status=status,
                DeviceSerial=active.serial_number,
                DeviceModel=active.profile.model_number,
            ),
            serial=active.serial_number,
            model=active.profile.model_number,
        ),
    )
    theme = ThemeManager(
        APPLICATION, SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    )
    page = DeviceSummaryPage(theme=theme, shared_firmware_controller=controller)
    page.set_active_ipod(active)
    page.show()
    try:
        for local_receipt in (False, True):
            installer.unlocked = local_receipt
            controller.changed.emit()
            assert controller.can_install(active) is (status == 4)
            unlock = page.findChild(QPushButton, "unlockBootloader")
            assert unlock is not None and unlock.isVisible() is (status != 4)
            install = page.findChild(QPushButton, "installSharedFirmware")
            assert install is not None and install.isVisible() is (status == 4)
            current = page.findChild(QLabel, "deviceFirmwareCurrent")
            assert current is not None and not current.isVisible()
            if status in (0, 1, 2, 3):
                version = page.findChild(QLabel, "deviceSummary_bootloader_version")
                assert version is not None and version.text() == "Unavailable"
    finally:
        page.close()
        controller.shutdown()
        theme.close()


def test_upload_finishes_with_close_and_no_post_install_action(tmp_path: Path) -> None:
    controller, devices, installer = controller_for(tmp_path)
    dialog = SharedFirmwareDialog(controller, devices.active_ipod)
    try:
        dialog.open()
        action = dialog.findChild(QPushButton, "sharedFirmwareAction")
        assert action is not None
        installer.write.set()
        action.click()
        until(lambda: controller.progress.stage == InstallStage.INSTALLING)
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        dialog.close()
        assert controller.busy and dialog.isVisible()
        installer.finish.set()
        until(lambda: not controller.busy)
        assert controller.progress.stage is InstallStage.COMPLETE
        assert devices.released and devices.active_ipod is None
        assert not action.isVisible()
        assert installer.installs == 1 and controller.pending is None
        detail = dialog.findChild(QLabel, "sharedFirmwareDetail")
        assert detail is not None and MOD_VERSION in detail.text()
        assert "unchanged" not in detail.text()
        close = dialog.findChild(QPushButton, "sharedFirmwareClose")
        assert close is not None and close.isEnabled()
        close.click()
        assert not dialog.isVisible()
    finally:
        installer.finish.set()
        controller.shutdown()
        dialog.close()


def test_prewrite_cancel_releases_device_without_installing(tmp_path: Path) -> None:
    controller, devices, installer = controller_for(tmp_path)
    dialog = SharedFirmwareDialog(controller, devices.active_ipod)
    try:
        dialog.open()
        button = dialog.findChild(QPushButton, "sharedFirmwareAction")
        assert button is not None
        button.click()
        until(lambda: controller.progress.stage == InstallStage.CHECKING)
        dialog.reject()
        until(lambda: not controller.busy)
        assert controller.progress.stage == InstallStage.CANCELED
        assert installer.installs == 0 and devices.released
    finally:
        installer.finish.set()
        controller.shutdown()
        dialog.close()


@pytest.mark.parametrize(
    "state",
    [
        InstallRecordState.AWAITING_BOOT,
        InstallRecordState.REBOOT_IN_FLIGHT,
        InstallRecordState.BOOT_VERIFIED,
    ],
)
def test_legacy_uploaded_receipt_offers_new_install_immediately(
    tmp_path: Path,
    state: InstallRecordState,
) -> None:
    controller, devices, installer = controller_for(tmp_path)
    active = devices.active_ipod
    assert active is not None
    installer.saved = InstallRecord(
        UnlockIdentity(active.serial_number, active.profile.model_number),
        "volume",
        VisibleLayout("", "", 63, ""),
        {},
        state=state,
        mod_version="0.6.4-diag",
        acknowledged_bytes=RELEASE_BYTES["0.6.4-diag"],
        acknowledged_commands=5,
        command_count=5,
    )
    dialog = SharedFirmwareDialog(controller, active)
    try:
        dialog.open()
        assert controller.progress.stage is InstallStage.READY
        assert controller.pending is None
        action = dialog.findChild(QPushButton, "sharedFirmwareAction")
        assert action is not None and action.text() == "Install firmware"
        assert action.isVisible() and action.isEnabled()
        assert installer.saved.state is InstallRecordState.COMPLETE
        assert installer.installs == 0
    finally:
        controller.shutdown()
        dialog.close()


def test_incomplete_upload_has_no_check_or_replay_action(tmp_path: Path) -> None:
    controller, devices, installer = controller_for(tmp_path)
    active = devices.active_ipod
    assert active is not None
    installer.saved = InstallRecord(
        UnlockIdentity(active.serial_number, active.profile.model_number),
        "volume",
        VisibleLayout("", "", 63, ""),
        {},
        state=InstallRecordState.INTERRUPTED,
    )
    dialog = SharedFirmwareDialog(controller, active)
    try:
        dialog.open()
        assert controller.progress.stage is InstallStage.ERROR
        assert controller.needs_attention
        action = dialog.findChild(QPushButton, "sharedFirmwareAction")
        assert action is not None and not action.isVisible()
        assert not controller.start(active)
        assert installer.installs == 0
    finally:
        controller.shutdown()
        dialog.close()


@pytest.mark.parametrize(
    "current_version,current_family", [(False, True), (True, False), (False, False)]
)
def test_saved_bootloader_record_does_not_replace_current_firmware_capture(
    tmp_path: Path,
    current_version: bool,
    current_family: bool,
) -> None:
    controller, _devices, installer = controller_for(tmp_path)
    active = replace(
        summary_active_ipod(),
        firmware_version_current=current_version,
        updater_family_current=current_family,
    )
    try:
        assert controller.has_bootloader_record(active)
        assert not controller.can_install(active)
        assert not controller.start(active)
        assert installer.installs == 0
    finally:
        controller.shutdown()
