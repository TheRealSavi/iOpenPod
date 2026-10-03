"""The real status controls drive updates and protect application work."""

import pytest
from PySide6.QtWidgets import QLabel, QPushButton, QWidget
from tests.iOpenPod.app.test_updates import FakeBackend
from tests.iOpenPod.GUI.application_shell_test_support import (
    build_context,
    tracks,
)

from iOpenPod.app.core.settings.definitions import DRAFT_ALL_CHANGES
from iOpenPod.app.library_export_controller import LibraryExportController
from iOpenPod.app.updates.backend import (
    InstallChannel,
    UpdateOutcome,
    UpdateProvider,
    UpdateResult,
)
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.widgets.status_controls import StatusBarControls
from iPodDB.library import LibrarySnapshot


def test_about_button_checks_again_and_shows_channel_and_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context()
    backend = FakeBackend()
    mock_provider(monkeypatch, backend)
    window = MainWindow(context, auto_discover=False)
    try:
        button = window.findChild(QPushButton, "checkAppUpdates")
        version_row = window.findChild(QWidget, "currentAppVersion")
        assert version_row is not None
        version = version_row.findChild(QLabel, "settingDescription")
        message = window.findChild(QLabel, "appUpdateMessage")
        assert button is not None and version is not None and message is not None
        window.check_app_updates()
        assert "Microsoft Store" in version.text()
        assert not button.isEnabled()
        button.click()
        assert backend.checks == 1
        backend.deliver(UpdateResult(UpdateOutcome.CURRENT))
        assert button.isEnabled()
        assert "reports no updates" in message.text()
        button.click()
        assert backend.checks == 2
        assert not button.isEnabled()
        backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
        assert button.isEnabled()
        assert "update available" in message.text()
        assert backend.installs == 0
    finally:
        window.close()
        context.shutdown()


def test_about_unsupported_check_explains_limitation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def create_provider(_window: int) -> UpdateProvider:
        return UpdateProvider(InstallChannel.FLATPAK)

    monkeypatch.setattr(
        "iOpenPod.GUI.main_window.create_update_provider",
        create_provider,
    )
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        window.check_app_updates()
        button = window.findChild(QPushButton, "checkAppUpdates")
        version_row = window.findChild(QWidget, "currentAppVersion")
        assert version_row is not None
        version = version_row.findChild(QLabel, "settingDescription")
        message = window.findChild(QLabel, "appUpdateMessage")
        assert button is not None and version is not None and message is not None
        assert "Flatpak" in version.text() and "Flathub" not in version.text()
        assert message.text() == ""
        button.click()
        assert button.isEnabled()
        assert "not available" in message.text()
        assert "no updates" not in message.text()
    finally:
        window.close()
        context.shutdown()


def mock_provider(monkeypatch: pytest.MonkeyPatch, backend: FakeBackend) -> None:
    def create_provider(_window: int) -> UpdateProvider:
        return UpdateProvider(InstallChannel.MICROSOFT_STORE, backend)

    monkeypatch.setattr(
        "iOpenPod.GUI.main_window.create_update_provider", create_provider
    )


def offer_update(window: MainWindow, backend: FakeBackend) -> StatusBarControls:
    window.check_app_updates()
    backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
    controls = window.findChild(StatusBarControls)
    assert controls is not None
    assert controls.action.text() == "Update now"
    return controls


def test_status_update_button_reserves_work_and_restores_after_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context()
    backend = FakeBackend()
    mock_provider(monkeypatch, backend)
    window = MainWindow(context, auto_discover=False)
    try:
        controls = offer_update(window, backend)
        controls.action.click()
        backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
        assert backend.installs == 1
        assert context.device_controller.busy
        assert context.library_workspace.locked
        central = window.centralWidget()
        assert central is not None and not central.isEnabled()
        assert not window.close()  # Preserve HWND during Windows consent/install.
        backend.deliver(UpdateResult(UpdateOutcome.CANCELED))
        assert not context.device_controller.busy
        assert not context.library_workspace.locked
        assert central.isEnabled()
    finally:
        window.close_app_updates()
        window.close()
        context.shutdown()


def test_install_guard_keeps_unsaved_draft_and_busy_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context()
    context.settings.set_global(DRAFT_ALL_CHANGES, True)
    context.library_workspace.load(LibrarySnapshot(tracks(1)))
    backend = FakeBackend()
    mock_provider(monkeypatch, backend)
    window = MainWindow(context, auto_discover=False)
    try:
        controls = offer_update(window, backend)
        context.library_workspace.rename_device(
            "Unsaved iPod name", context.library_workspace.edit_revision
        )
        controls.action.click()
        backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
        assert "Library Draft" in context.status.current_message
        assert backend.installs == 0
        assert context.library_workspace.dirty
        assert not context.library_workspace.locked
        context.library_workspace.load(None)
        exporter = window.findChild(LibraryExportController)
        assert exporter is not None
        with monkeypatch.context() as patch:
            patch.setattr(exporter, "busy", True)
            controls.action.click()
            backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
            assert "Finish the current work" in context.status.current_message
            assert backend.installs == 0
        assert not context.device_controller.busy
    finally:
        window.close()
        context.shutdown()


def test_failed_settings_save_releases_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context()
    backend = FakeBackend()
    mock_provider(monkeypatch, backend)
    window = MainWindow(context, auto_discover=False)

    def fail() -> None:
        raise OSError("settings disk full")

    try:
        controls = offer_update(window, backend)
        with monkeypatch.context() as patch:
            patch.setattr(context.settings, "sync", fail)
            controls.action.click()
            backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
        assert "settings disk full" in context.status.current_message
        assert backend.installs == 0
        assert not context.device_controller.busy
        assert not context.library_workspace.locked
    finally:
        window.close()
        context.shutdown()
