"""Behavioral tests for choosing Host Media Library folders."""

import os
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPropertyAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QToolButton,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION
from tests.iOpenPod.GUI.application_shell_test_support import build_context as _context
from tests.iOpenPod.GUI.application_shell_test_support import tracks as _tracks

from iOpenPod.app.core.settings.definitions import PLAYER_POSITION, PlayerPosition
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import (
    DeviceSettingsStore,
    GlobalSettingsStore,
)
from iOpenPod.app.host_media_folders import (
    HostMediaType,
    create_host_media_folder,
    load_host_media_folders,
    save_host_media_folders,
)
from iOpenPod.GUI import main_window as main_window_module
from iOpenPod.GUI.dialogs.media_folders import (
    MediaFoldersDialog,
    MediaFolderSettingsDialog,
)
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.presentation.theme.stylesheet import render_stylesheet
from iOpenPod.GUI.presentation.theme.tokens import (
    DARK_TOKENS,
    LIGHT_TOKENS,
    ThemeTokens,
    resolve_typography,
)
from iOpenPod.GUI.sync_workspace import SyncStage, SyncWorkspace
from iOpenPod.GUI.widgets.player_bar import PlayerBar
from iOpenPod.GUI.widgets.status_list import StatusListButton
from iOpenPod.GUI.widgets.themed_buttons import IconButton


def _settings() -> SettingsService:
    return SettingsService(GlobalSettingsStore(), DeviceSettingsStore())


@pytest.mark.parametrize("tokens", [LIGHT_TOKENS, DARK_TOKENS])
def test_dropped_folder_settings_render_the_theme_surface(
    tmp_path: Path, tokens: ThemeTokens
) -> None:
    original = APPLICATION.styleSheet()
    APPLICATION.setStyleSheet(render_stylesheet(tokens, resolve_typography()))
    dialog = MediaFolderSettingsDialog(create_host_media_folder(tmp_path))
    try:
        dialog.show()
        APPLICATION.processEvents()
        assert dialog.grab().toImage().pixelColor(2, 2) == QColor(tokens.window)
        controls = dialog.findChildren(QCheckBox)
        assert len(controls) == 6
        assert all(control.isVisible() for control in controls)
        assert all(
            control.isChecked() == (control.objectName() != "followMediaFolderSymlinks")
            for control in controls
        )
    finally:
        dialog.close()
        dialog.deleteLater()
        APPLICATION.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
        APPLICATION.setStyleSheet(original)


def test_native_picker_adds_once_with_enabled_default_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = tmp_path / "Media"
    selected.mkdir()
    calls: list[tuple[str, QFileDialog.Option]] = []

    def choose_folder(
        _parent: object,
        _caption: str,
        directory: str,
        options: QFileDialog.Option,
    ) -> str:
        calls.append((directory, options))
        return os.fspath(selected)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", choose_folder)
    dialog = MediaFoldersDialog(_settings())

    try:
        add = dialog.findChild(QPushButton, "addMediaFolder")
        assert add is not None
        add.click()
        add.click()

        assert len(dialog.folders) == 1
        assert dialog.folders[0] == create_host_media_folder(selected)
        assert calls[0][1] == QFileDialog.Option.ShowDirsOnly
        assert all(
            checkbox.isChecked()
            == (checkbox.objectName() != "followMediaFolderSymlinks")
            for checkbox in dialog.findChildren(QCheckBox)
        )
    finally:
        dialog.close()


def test_folder_settings_and_removal_are_staged_then_persisted(
    tmp_path: Path,
) -> None:
    service = _settings()
    dialog = MediaFoldersDialog(service)

    try:
        assert dialog.add_folder(tmp_path / "Music")
        assert dialog.add_folder(tmp_path / "Pictures")

        rows = dialog.findChildren(QFrame, "mediaFolderRow")
        assert len(rows) == 2
        settings_button = rows[0].findChild(QToolButton, "mediaFolderSettingsButton")
        recurse = rows[0].findChild(QCheckBox, "recurseMediaFolder")
        follow = rows[0].findChild(QCheckBox, "followMediaFolderSymlinks")
        video = rows[0].findChild(QCheckBox, "scanVideo")
        playlists = rows[0].findChild(QCheckBox, "scanPlaylists")
        assert settings_button is not None
        assert recurse is not None
        assert follow is not None and not follow.isChecked()
        assert video is not None
        assert playlists is not None

        settings_button.click()
        recurse.setChecked(False)
        follow.setChecked(True)
        video.setChecked(False)
        playlists.setChecked(False)

        remove = rows[1].findChild(QToolButton, "removeMediaFolder")
        assert remove is not None
        remove.click()
        sync = dialog.findChild(QPushButton, "syncMediaFolders")
        assert sync is not None
        sync.click()

        assert load_host_media_folders(service) == dialog.folders
        assert len(dialog.folders) == 1
        assert dialog.folders[0].recurse is False
        assert dialog.folders[0].follow_symlinks is True
        assert dialog.folders[0].media_types == frozenset(
            {HostMediaType.AUDIO, HostMediaType.PHOTOS}
        )
    finally:
        dialog.close()


def test_cancel_discards_staged_folder_changes(tmp_path: Path) -> None:
    service = _settings()
    original = create_host_media_folder(tmp_path / "Original")
    save_host_media_folders(service, (original,))
    dialog = MediaFoldersDialog(service)

    try:
        dialog.clear_folders()
        dialog.reject()

        assert load_host_media_folders(service) == (original,)
    finally:
        dialog.close()


def test_sync_can_persist_removing_the_last_folder(tmp_path: Path) -> None:
    service = _settings()
    save_host_media_folders(
        service,
        (create_host_media_folder(tmp_path / "Original"),),
    )
    dialog = MediaFoldersDialog(service)

    try:
        dialog.clear_folders()
        sync = dialog.findChild(QPushButton, "syncMediaFolders")
        assert sync is not None and sync.isEnabled()
        sync.click()

        assert load_host_media_folders(service) == ()
    finally:
        dialog.close()


def test_sync_with_host_opens_the_folder_dialog_without_replacing_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[SettingsService] = []

    class FakeMediaFoldersDialog:
        def __init__(self, settings: SettingsService, _parent: object) -> None:
            opened.append(settings)

        def exec(self) -> int:
            return QDialog.DialogCode.Rejected

        def deleteLater(self) -> None:
            return None

    monkeypatch.setattr(
        main_window_module,
        "MediaFoldersDialog",
        FakeMediaFoldersDialog,
    )
    context = _context()
    window = MainWindow(context, auto_discover=False)
    original_content = window.centralWidget()

    try:
        sync = window.findChild(QPushButton, "syncWithHost")
        assert sync is not None
        assert not sync.isEnabled()
        sync.setEnabled(True)
        sync.click()

        assert opened == [context.settings]
        assert window.centralWidget() is original_content
        assert window.findChild(QPushButton, "hostLibrarySource") is None
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("position", tuple(PlayerPosition))
def test_player_and_status_bar_remain_available_across_pages_and_sync_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    position: PlayerPosition,
) -> None:
    folder = create_host_media_folder(tmp_path / "Music")
    started: list[object] = []
    context = _context()
    context.settings.set_global(PLAYER_POSITION, position.value)

    class FakeMediaFoldersDialog:
        folders = (folder,)

        def __init__(self, _settings: SettingsService, _parent: object) -> None:
            return None

        def exec(self) -> int:
            return QDialog.DialogCode.Accepted

        def deleteLater(self) -> None:
            return None

    monkeypatch.setattr(
        main_window_module,
        "MediaFoldersDialog",
        FakeMediaFoldersDialog,
    )

    def start_scan(_self: object, folders: object) -> bool:
        started.append(folders)
        return True

    monkeypatch.setattr(
        type(context.host_media_controller),
        "start",
        start_scan,
    )
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        track = _tracks(1)[0]
        context.playback_controller.enqueue(track)
        height_animation = window.findChild(QPropertyAnimation, "playerHeightAnimation")
        assert height_animation is not None
        height_animation.setCurrentTime(height_animation.duration())
        APPLICATION.processEvents()
        shell = window.centralWidget()
        player = window.findChild(PlayerBar)
        pages = window.findChild(QStackedWidget, "pageStack")
        status_bar = window.findChild(QStatusBar, "appStatusBar")
        status_list = window.findChild(StatusListButton)
        pane = window.findChild(QWidget, "playbackPane")
        queue_toggle = window.findChild(IconButton, "playerQueueToggle")
        play_pause = window.findChild(IconButton, "playerPlayPause")
        assert shell is not None
        assert player is not None
        assert pages is not None
        assert status_bar is not None
        assert status_list is not None
        assert status_bar.parentWidget() is window
        assert not shell.isAncestorOf(status_bar)
        assert pane is not None
        assert queue_toggle is not None
        assert play_pause is not None

        def assert_status_visible() -> None:
            assert window.statusBar() is status_bar
            assert status_bar.isVisible() and status_bar.height() > 0
            assert status_list.isVisible()
            assert shell.geometry().bottom() < status_bar.geometry().top()
            assert window.rect().contains(status_bar.geometry())

        for index in range(pages.count()):
            pages.setCurrentIndex(index)
            APPLICATION.processEvents()
            assert player.isVisible() and player.height() > 0
            assert_status_visible()
        original_page = pages.currentWidget()

        sync = window.findChild(QPushButton, "syncWithHost")
        assert sync is not None
        sync.setEnabled(True)
        sync.click()
        workspace = window.findChild(SyncWorkspace, "syncWorkspace")
        assert workspace is not None

        assert started == [(folder,)]
        assert workspace.stage is SyncStage.SCANNING
        assert window.findChild(QFrame, "syncScanPanel") is not None
        assert window.windowTitle() == "Sync with Host — iOpenPod"
        queue_toggle.click()
        for stage in (SyncStage.SCANNING, SyncStage.SELECT, SyncStage.REVIEW):
            if stage is SyncStage.SELECT:
                workspace.show_selection()
            elif stage is SyncStage.REVIEW:
                workspace.show_review()
            APPLICATION.processEvents()
            assert workspace.isVisible()
            assert not pages.isVisible()
            assert window.centralWidget() is shell
            assert window.findChild(PlayerBar) is player
            assert player.isVisible() and player.height() > 0
            assert_status_visible()
            message = f"Status during {stage.value}"
            context.status.show("shell-test", message)
            assert status_bar.currentMessage() == message
            assert pane.isVisible()
            assert player.track == track
            assert context.playback_controller.playing
            player_bounds = player.geometry()
            workspace_bounds = workspace.rect().translated(
                workspace.mapTo(shell, workspace.rect().topLeft())
            )
            assert not player_bounds.intersects(workspace_bounds)
            if position is PlayerPosition.TOP:
                assert player_bounds.bottom() < workspace_bounds.top()
            else:
                assert player_bounds.top() > workspace_bounds.bottom()
            play_pause.click()
            assert not context.playback_controller.playing
            play_pause.click()
            assert context.playback_controller.playing

        workspace.exitRequested.emit()
        APPLICATION.processEvents()
        assert not workspace.isVisible()
        assert pages.isVisible()
        assert pages.currentWidget() is original_page
        assert player.isVisible()
        assert_status_visible()
        assert pane.isVisible()
        assert player.track == track
        assert context.playback_controller.playing
        assert window.windowTitle() == "iOpenPod"
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)
