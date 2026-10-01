"""Preferences are visible, selectable, and cleared with the Active iPod."""

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit, QTabWidget
from tests.iOpenPod.app.services.test_device_coordinator import (
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.services.test_ipod_preferences_inspection import (
    _install_preferences,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.models.ipod_preferences import (
    IPodPreferenceSection,
    PreferenceFileStatus,
)
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.widgets.ipod_preferences import IPodPreferencesView
from storage import Storage
from storage.testing import VirtualStoragePlatform


def test_settings_preferences_tab_is_read_only_and_tracks_active_device(
    tmp_path: Path,
) -> None:
    root = _ipod_volume(tmp_path / "ipod", model_number="MB565")
    _install_preferences(root)
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    coordinator = DeviceCoordinator(Storage(platform))
    active = coordinator.select_device(
        coordinator.discover_devices().candidates[0].id, reconcile_metadata=False
    )
    context = build_context(device_coordinator=coordinator)
    window = MainWindow(context, auto_discover=False)
    try:
        page = window.findChild(SettingsPage)
        assert page is not None
        view = page.findChild(IPodPreferencesView)
        tabs = page.findChild(QTabWidget, "settingsTabs")
        note = page.findChild(QLabel, "pageMeta")
        assert view is not None and tabs is not None and note is not None
        tabs.setCurrentIndex(
            next(
                i for i in range(tabs.count()) if tabs.tabText(i) == "iPod Preferences"
            )
        )
        assert note.text() == "iPod preferences are read-only."
        changes = QSignalSpy(context.settings.settingChanged)
        timezone = view.findChild(QLabel, "ipodPreference_device_timezone")
        unknown = view.findChild(QLabel, "ipodPreference_itunes_open_itunes")
        assert timezone is not None and timezone.text() == "America/Detroit"
        assert unknown is not None and unknown.text() == "Unknown (code 254)"
        assert timezone.textFormat() is Qt.TextFormat.PlainText
        assert (
            timezone.textInteractionFlags()
            & Qt.TextInteractionFlag.TextSelectableByMouse
        )
        assert not timezone.textInteractionFlags() & Qt.TextInteractionFlag.TextEditable
        assert not view.findChildren(QComboBox)
        assert not view.findChildren(QLineEdit)
        assert not view.findChildren(QAbstractButton)
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        assert view.findChild(QLabel, "ipodPreference_device_timezone") is not None
        missing = IPodPreferenceSection(
            "device",
            "Device settings",
            PreferenceFileStatus.MISSING,
            detail="No preferences file",
        )
        other = replace(
            active,
            library=replace(active.library, device_name="<b>Other iPod</b>"),
            preferences=(missing,),
        )
        context.device_controller.activeIPodChanged.emit(other)
        status = view.findChild(QLabel, "ipodPreferencesStatus")
        assert status is not None and status.text() == "<b>Other iPod</b>"
        assert status.textFormat() is Qt.TextFormat.PlainText
        assert view.findChild(QLabel, "ipodPreference_device_timezone") is None
        assert view.findChild(QLabel, "ipodPreferenceStatus_device") is not None
        context.device_controller.activeIPodChanged.emit(None)
        assert status.text() == "Connect and select an iPod to view its preferences."
        assert view.findChild(QLabel, "ipodPreferenceStatus_device") is None
        assert changes.count() == 0
        tabs.setCurrentIndex(0)
        assert note.text() == "Changes are saved automatically."
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)
