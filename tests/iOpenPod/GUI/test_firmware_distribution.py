"""Store and standalone composition with a selected iPod, without USB access."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QLabel, QWidget
from tests.iOpenPod.GUI.test_device_summary_page import APPLICATION, summary_active_ipod

from iOpenPod.app import context
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.device_controller import DeviceController
from iOpenPod.app.firmware import bootloader_install, shared_install
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.GUI.pages.device_summary import DeviceSummaryPage
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from storage import Storage


@pytest.mark.parametrize("identity_error", [False, True])
def test_msix_or_unresolved_identity_has_only_read_only_firmware_details(
    monkeypatch: pytest.MonkeyPatch, identity_error: bool
) -> None:
    def packaged() -> bool:
        if identity_error:
            raise OSError("Cannot inspect package identity")
        return True

    monkeypatch.setattr(context, "has_package_identity", packaged)
    storage = Mock(spec=Storage, platform_name="windows")
    bootloader, firmware = context.create_firmware_controllers(
        storage, Mock(spec=DeviceController), Mock(spec=DeviceCoordinator), APPLICATION
    )
    assert bootloader is None and firmware is None
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    page = DeviceSummaryPage(
        theme=theme,
        bootloader_controller=bootloader,
        shared_firmware_controller=firmware,
    )
    try:
        active = summary_active_ipod()
        page.set_active_ipod(active)
        page.show()
        actions = page.findChild(QWidget, "deviceFirmwareActions")
        version = page.findChild(QLabel, "deviceSummary_firmware")
        assert actions is not None and not actions.isVisible()
        assert version is not None and version.isVisible()
        assert version.text() == active.firmware_version
    finally:
        page.close()
        theme.close()


@pytest.mark.parametrize("platform", ["windows", "linux", "macos"])
def test_standalone_keeps_firmware_controllers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str
) -> None:
    def unpackaged() -> bool:
        assert platform == "windows"
        return False

    monkeypatch.setattr(context, "has_package_identity", unpackaged)
    monkeypatch.setattr(bootloader_install, "firmware_directory", lambda: tmp_path)
    monkeypatch.setattr(shared_install, "firmware_directory", lambda: tmp_path)
    bootloader, firmware = context.create_firmware_controllers(
        Mock(spec=Storage, platform_name=platform),
        Mock(spec=DeviceController),
        Mock(spec=DeviceCoordinator),
        APPLICATION,
    )
    assert bootloader is not None and firmware is not None
    bootloader.shutdown()
    firmware.shutdown()
