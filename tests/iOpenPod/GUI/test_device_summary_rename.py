"""Summary renaming uses the revision-bound Library edit workflow."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.GUI.test_device_summary_page import summary_active_ipod

from iOpenPod.app.core.settings.definitions import DRAFT_ALL_CHANGES
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.device_summary import DeviceSummaryPage
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.widgets.sidebar import DeviceCard, Sidebar
from iOpenPod.GUI.widgets.themed_buttons import IconButton


@pytest.fixture
def editor() -> Iterator[tuple[LibraryWorkspace, DeviceSummaryPage, QLineEdit]]:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    theme = ThemeManager(APPLICATION, settings)
    workspace = LibraryWorkspace()
    active = summary_active_ipod()
    workspace.load(active.library)
    page = DeviceSummaryPage(theme=theme, workspace=workspace)
    page.set_active_ipod(active)
    page.resize(900, 800)
    page.show()
    APPLICATION.processEvents()
    line = page.findChild(QLineEdit, "deviceSummaryNameEdit")
    assert line is not None
    try:
        yield workspace, page, line
    finally:
        page.close()
        theme.close()


def _click(page: DeviceSummaryPage, name: str) -> None:
    button = page.findChild(IconButton, name)
    assert button is not None
    button.click()


@pytest.mark.parametrize("commit", ["enter", "apply", "focus-out"])
def test_pencil_replaces_name_and_applies_validated_name(
    editor: tuple[LibraryWorkspace, DeviceSummaryPage, QLineEdit], commit: str
) -> None:
    workspace, page, line = editor
    name = page.findChild(QLabel, "deviceSummaryName")
    assert name is not None
    _click(page, "deviceSummaryRename")
    assert line.isVisible() and name.isHidden()
    assert line.selectedText() == "John's iPod"
    line.setText("  Travel iPod  ")
    if commit == "apply":
        _click(page, "deviceSummaryRenameApply")
    elif commit == "focus-out":
        line.clearFocus()
    else:
        QTest.keyClick(line, Qt.Key.Key_Return)
    assert workspace.device_name == "Travel iPod"
    assert name.text() == "Travel iPod" and name.isVisible()
    assert line.isHidden()


@pytest.mark.parametrize("cancel_button", [False, True])
def test_cancel_discards_rename(
    editor: tuple[LibraryWorkspace, DeviceSummaryPage, QLineEdit], cancel_button: bool
) -> None:
    workspace, page, line = editor
    revision = workspace.edit_revision
    _click(page, "deviceSummaryRename")
    line.setText("Discard this")
    if cancel_button:
        _click(page, "deviceSummaryRenameCancel")
    else:
        QTest.keyClick(line, Qt.Key.Key_Escape)
    assert workspace.edit_revision == revision
    assert workspace.device_name == "John's iPod" and line.isHidden()


def test_blank_and_stale_edits_show_validation_without_overwriting_name(
    editor: tuple[LibraryWorkspace, DeviceSummaryPage, QLineEdit],
) -> None:
    workspace, page, line = editor
    _click(page, "deviceSummaryRename")
    line.setText("  ")
    QTest.keyClick(line, Qt.Key.Key_Return)
    feedback = page.findChild(QLabel, "renameIPodFeedback")
    assert feedback is not None and feedback.isVisible() and feedback.text()
    assert line.isVisible() and workspace.device_name == "John's iPod"
    workspace.rename_device("Changed elsewhere", workspace.edit_revision)
    line.setText("Stale edit")
    QTest.keyClick(line, Qt.Key.Key_Return)
    assert line.isVisible() and workspace.device_name == "Changed elsewhere"
    _click(page, "deviceSummaryRenameCancel")
    name = page.findChild(QLabel, "deviceSummaryName")
    assert name is not None and name.text() == "Changed elsewhere"


@pytest.mark.parametrize("change", ["disconnect", "replace", "lock", "busy"])
def test_device_or_edit_availability_changes_cancel_pending_rename(
    editor: tuple[LibraryWorkspace, DeviceSummaryPage, QLineEdit], change: str
) -> None:
    workspace, page, line = editor
    _click(page, "deviceSummaryRename")
    line.setText("Pending")
    if change == "disconnect":
        page.set_active_ipod(None)
    elif change == "replace":
        workspace.load(summary_active_ipod().library)
    elif change == "lock":
        workspace.set_locked(True)
    else:
        page.set_busy(True)
    assert line.isHidden()
    assert workspace.device_name == "John's iPod"
    _click(page, "deviceSummaryRenameApply")
    assert workspace.device_name == "John's iPod"


def test_summary_rename_updates_sidebar_through_the_shared_workspace() -> None:
    context = build_context()
    context.settings.set_global(DRAFT_ALL_CHANGES, True)
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        context.device_controller.activeIPodChanged.emit(summary_active_ipod())
        sidebar = window.findChild(Sidebar)
        page = window.findChild(DeviceSummaryPage)
        card = window.findChild(DeviceCard)
        assert sidebar is not None and page is not None and card is not None
        sidebar.pageRequested.emit(PageId.DEVICE_SUMMARY.value)
        _click(page, "deviceSummaryRename")
        line = page.findChild(QLineEdit, "deviceSummaryNameEdit")
        assert line is not None
        line.setText("Shared name")
        QTest.keyClick(line, Qt.Key.Key_Return)
        assert context.library_workspace.device_name == "Shared name"
        button = card.findChild(QPushButton, "deviceName")
        assert button is not None
        assert button.text() == "Shared name"
    finally:
        context.library_workspace.load(summary_active_ipod().library)
        window.close()
        context.shutdown()
