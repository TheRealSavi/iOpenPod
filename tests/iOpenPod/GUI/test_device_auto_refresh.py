"""Startup restoration and picker-scoped automatic discovery."""

from pathlib import Path
from threading import Event

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QListWidget, QPushButton
from tests.iOpenPod.app.test_device_controller import (
    _device_root,  # pyright: ignore[reportPrivateUsage]
    _ObservedPlatform,  # pyright: ignore[reportPrivateUsage]
    _wait_until,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.GUI.application_shell_test_support import build_context

from iOpenPod.app.core.settings.definitions import LAST_SELECTED_IPOD_VOLUME_ID
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iOpenPod.GUI.dialogs.device_picker import DevicePickerDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.widgets.sidebar import Sidebar
from storage import Storage


def test_window_restores_remembered_ipod_without_opening_picker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("iOpenPod.app.device_controller._AUTO_REFRESH_INTERVAL_MS", 50)
    platform = _ObservedPlatform()
    platform.add_volume(
        _device_root(tmp_path / "device"),
        volume_id="remembered-volume",
        label="Remembered iPod",
    )
    context = build_context(device_coordinator=DeviceCoordinator(Storage(platform)))
    context.settings.set_global(LAST_SELECTED_IPOD_VOLUME_ID, "remembered-volume")
    window = MainWindow(context)
    try:
        window.show()
        _wait_until(lambda: context.device_controller.active_ipod is not None)
        assert context.device_controller.active_ipod is not None
        assert context.device_controller.active_ipod.display_name == "Remembered iPod"
        picker = window.findChild(DevicePickerDialog)
        assert picker is not None and not picker.isVisible()
        QTest.qWait(120)
        assert platform.scans == 1
    finally:
        window.close()
        context.shutdown()


def test_picker_search_status_is_delayed_and_does_not_replace_instructions() -> None:
    picker = DevicePickerDialog()
    try:
        status = picker.findChild(QLabel, "deviceSearchStatus")
        description = picker.findChild(QLabel, "pageDescription")
        candidates = picker.findChild(QListWidget, "deviceCandidateList")
        assert status is not None and description is not None and candidates is not None
        instructions = description.text()
        picker.set_searching(True)
        picker.set_busy(True)
        assert status.text() == "Connected iPods appear automatically"
        QTest.qWait(250)
        assert status.text() == "Searching for iPods…"
        assert candidates.isEnabled()
        assert description.text() == instructions
        picker.retranslate_ui()
        assert status.text() == "Searching for iPods…"
        picker.set_busy(False)
        picker.set_searching(False)
        assert status.text() == "Connected iPods appear automatically"
        picker.set_search_error("Temporary failure")
        assert "retrying automatically" in status.text()
        assert status.toolTip() == "Temporary failure"
        picker.set_search_error("")
        assert status.text() == "Connected iPods appear automatically"
    finally:
        picker.close()


def test_window_refreshes_open_picker_without_sidebar_search_indicator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("iOpenPod.app.device_controller._AUTO_REFRESH_INTERVAL_MS", 100)
    platform = _ObservedPlatform()
    release = Event()
    platform.release = release
    context = build_context(device_coordinator=DeviceCoordinator(Storage(platform)))
    window = MainWindow(context)
    try:
        window.show()
        picker = window.findChild(DevicePickerDialog)
        sidebar = window.findChild(Sidebar)
        assert picker is not None and sidebar is not None
        choose = next(
            button
            for button in sidebar.findChildren(QPushButton)
            if button.text() == "Choose iPod…"
        )
        QTest.qWait(100)
        assert platform.scans == 0
        assert choose.isEnabled()
        choose.click()
        _wait_until(lambda: context.device_controller.searching)
        assert choose.isEnabled()
        assert picker.isVisible()
        assert sidebar.findChild(QLabel, "deviceSearchStatus") is None
        assert all(
            "Searching" not in label.text() for label in sidebar.findChildren(QLabel)
        )
        root = _device_root(tmp_path / "device")
        platform.add_volume(root, label="Newly connected iPod")
        release.set()
        candidates = picker.findChild(QListWidget, "deviceCandidateList")
        assert candidates is not None
        _wait_until(
            lambda: candidates.count() == 1 and not context.device_controller.busy
        )
        assert "Newly connected iPod" in candidates.item(0).text()
        # Unchanged snapshots keep the actual item, selection, and scroll state.
        selected = candidates.currentItem()
        scan_count = platform.scans
        _wait_until(
            lambda: (
                platform.scans >= scan_count + 2 and not context.device_controller.busy
            )
        )
        assert candidates.currentItem() is selected
        platform.disconnect(root)
        _wait_until(
            lambda: candidates.count() == 0 and not context.device_controller.busy
        )
        picker.close()
        scan_count = platform.scans
        platform.reconnect(root)
        QTest.qWait(120)
        assert platform.scans == scan_count
        assert candidates.count() == 0
        choose.click()
        _wait_until(
            lambda: candidates.count() == 1 and not context.device_controller.busy
        )
    finally:
        release.set()
        window.close()
        context.shutdown()
