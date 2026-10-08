"""External media drops enter the existing Sync workflow from the Library."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QCheckBox, QLabel, QStackedWidget, QWidget
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_library_write_controller import wait_for
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.context import AppContext
from iOpenPod.app.host_media_folders import (
    HOST_MEDIA_FOLDERS,
    HostMediaFolder,
    HostMediaType,
    save_host_media_folders,
)
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.GUI.dialogs.media_folders import MediaFolderSettingsDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.sync_workspace import SyncStage, SyncWorkspace
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.host_media_drop import HostMediaDropTarget, dropped_host_paths
from iOpenPod.GUI.widgets.host_scan_issues import HostScanIssues
from iOpenPod.GUI.widgets.sidebar import Sidebar
from storage import HostPath


@pytest.fixture
def shell(tmp_path: Path) -> Iterator[tuple[MainWindow, AppContext]]:
    device = build_device(tmp_path)
    context = build_context(device_coordinator=device.coordinator)
    window = MainWindow(context, auto_discover=False)
    window.show()
    APPLICATION.processEvents()
    try:
        yield window, context
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def _mime(path: Path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    return mime


def _enter(target: QWidget, mime: QMimeData) -> QDragEnterEvent:
    event = QDragEnterEvent(
        QPoint(30, 30),
        Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    APPLICATION.sendEvent(target, event)
    return event


def _drop(target: QWidget, mime: QMimeData) -> QDropEvent:
    event = QDropEvent(
        QPointF(30, 30),
        Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    APPLICATION.sendEvent(target, event)
    return event


@pytest.mark.parametrize("suffix", [".MP3", ".mp4", ".jpg", ".m3u8"])
def test_drop_over_grid_shows_overlay_and_starts_scoped_sync(
    shell: tuple[MainWindow, AppContext],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    window, context = shell
    source = tmp_path / ("dropped" + suffix)
    source.write_bytes(b"fixture")
    calls: list[tuple[tuple[HostMediaFolder, ...], tuple[HostPath, ...]]] = []

    def start(
        folders: tuple[HostMediaFolder, ...], *, files: tuple[HostPath, ...] = ()
    ) -> bool:
        calls.append((folders, files))
        return True

    monkeypatch.setattr(context.host_media_controller, "start", start)
    saved = context.settings.get(HOST_MEDIA_FOLDERS)
    grid = window.findChild(AlbumGridView, "albumGrid")
    overlay = window.findChild(QLabel, "hostMediaDropOverlay")
    workspace = window.findChild(SyncWorkspace)
    assert grid is not None and overlay is not None and workspace is not None
    mime = _mime(source)
    enter = _enter(grid.viewport(), mime)
    assert enter.isAccepted()
    assert enter.dropAction() == Qt.DropAction.CopyAction
    assert overlay.isVisible()
    assert "Drop to Sync with Host" in overlay.text()
    APPLICATION.sendEvent(grid.viewport(), QDragLeaveEvent())
    assert overlay.isHidden()
    assert _enter(grid.viewport(), mime).isAccepted()
    drop = _drop(grid.viewport(), mime)
    assert drop.isAccepted() and drop.dropAction() == Qt.DropAction.CopyAction
    assert overlay.isHidden()
    assert not calls  # Native drop finishes before modal/workspace transitions.
    APPLICATION.processEvents()
    assert calls == [((), (HostPath(source),))]
    assert workspace.isVisible() and workspace.stage is SyncStage.SCANNING
    assert context.settings.get(HOST_MEDIA_FOLDERS) == saved


@pytest.mark.parametrize(
    ("accepted", "recurse", "media_type"),
    [
        (True, False, HostMediaType.AUDIO),
        (True, True, HostMediaType.VIDEO),
        (True, False, HostMediaType.PHOTOS),
        (True, True, HostMediaType.PLAYLISTS),
        (False, True, HostMediaType.AUDIO),
    ],
)
def test_folder_drop_uses_shared_scan_settings_and_cancel_aborts(
    shell: tuple[MainWindow, AppContext],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accepted: bool,
    recurse: bool,
    media_type: HostMediaType,
) -> None:
    window, context = shell
    source = tmp_path / "media"
    source.mkdir()
    save_host_media_folders(context.settings, (HostMediaFolder(HostPath(tmp_path)),))
    saved = context.settings.get(HOST_MEDIA_FOLDERS)
    calls: list[tuple[HostMediaFolder, ...]] = []
    prompts: list[str] = []

    def start(folders: tuple[HostMediaFolder, ...]) -> bool:
        calls.append(folders)
        return True

    def configure(dialog: MediaFolderSettingsDialog) -> int:
        label = dialog.findChild(QLabel, "mediaFolderPath")
        recursion = dialog.findChild(QCheckBox, "recurseMediaFolder")
        follow = dialog.findChild(QCheckBox, "followMediaFolderSymlinks")
        assert label is not None and recursion is not None
        assert recursion.isVisibleTo(dialog) and recursion.isChecked()
        assert follow is not None and not follow.isChecked()
        follow.setChecked(True)
        prompts.append(label.text())
        recursion.setChecked(recurse)
        for kind in HostMediaType:
            checkbox = dialog.findChild(QCheckBox, f"scan{kind.value.title()}")
            assert checkbox is not None and checkbox.isVisibleTo(dialog)
            assert checkbox.isChecked()
            checkbox.setChecked(kind is media_type)
        if accepted:
            dialog.accept()
        else:
            dialog.reject()
        return dialog.result()

    monkeypatch.setattr(context.host_media_controller, "start", start)
    monkeypatch.setattr(MediaFolderSettingsDialog, "exec", configure)
    pages = window.findChild(QStackedWidget, "pageStack")
    workspace = window.findChild(SyncWorkspace)
    assert pages is not None and workspace is not None
    mime = _mime(source)
    assert _enter(pages, mime).isAccepted()
    assert _drop(pages, mime).isAccepted()
    APPLICATION.processEvents()
    assert len(prompts) == 1 and str(source) in prompts[0]
    assert context.settings.get(HOST_MEDIA_FOLDERS) == saved
    if not accepted:
        assert not calls and not workspace.isVisible()
    else:
        assert calls == [
            (
                HostMediaFolder(
                    HostPath(source),
                    recurse=recurse,
                    media_types=frozenset((media_type,)),
                    follow_symlinks=True,
                ),
            )
        ]
        assert workspace.isVisible()


@pytest.mark.parametrize(
    "page_id", [PageId.SETTINGS, PageId.BACKUPS, PageId.SYNESTHESIA, PageId.PODCASTS]
)
def test_non_library_pages_reject_drops(
    shell: tuple[MainWindow, AppContext],
    tmp_path: Path,
    page_id: PageId,
) -> None:
    window, _ = shell
    sidebar = window.findChild(Sidebar)
    assert sidebar is not None
    sidebar.pageRequested.emit(page_id.value)
    pages = window.findChild(QStackedWidget, "pageStack")
    overlay = window.findChild(QLabel, "hostMediaDropOverlay")
    assert pages is not None and overlay is not None
    assert not _enter(pages, _mime(tmp_path)).isAccepted()
    assert overlay.isHidden()


def test_locked_library_and_sync_workspace_reject_drops(
    shell: tuple[MainWindow, AppContext],
    tmp_path: Path,
) -> None:
    window, context = shell
    pages = window.findChild(QStackedWidget, "pageStack")
    workspaces = window.findChild(QStackedWidget, "workspaceStack")
    sync = window.findChild(SyncWorkspace)
    assert pages is not None and workspaces is not None and sync is not None
    context.host_media_controller.busy = True
    assert not _enter(pages, _mime(tmp_path)).isAccepted()
    context.host_media_controller.busy = False
    assert _enter(pages, _mime(tmp_path)).isAccepted()
    workspaces.setCurrentWidget(sync)
    assert not _enter(pages, _mime(tmp_path)).isAccepted()


def test_unsupported_remote_and_mixed_selections_are_rejected(tmp_path: Path) -> None:
    unsupported = tmp_path / "notes.txt"
    unsupported.write_text("notes", encoding="utf-8")
    assert not dropped_host_paths(_mime(unsupported))
    assert not dropped_host_paths(_mime(tmp_path / "missing.mp3"))
    mime = _mime(tmp_path)
    mime.setUrls([*mime.urls(), QUrl("https://example.com/music.mp3")])
    assert not dropped_host_paths(mime)
    mime.setUrls(
        [QUrl.fromLocalFile(str(tmp_path)), QUrl.fromLocalFile(str(unsupported))]
    )
    assert not dropped_host_paths(mime)
    assert not dropped_host_paths(QMimeData())


@pytest.mark.parametrize("broken", [False, True])
def test_explicit_link_with_no_media_suffix_reaches_scan_validation(
    tmp_path: Path, broken: bool
) -> None:
    target = tmp_path / "song.mp3"
    if not broken:
        target.write_bytes(b"fixture")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(target)
    except OSError as error:
        pytest.skip(f"Host cannot create symbolic links: {error}")
    assert dropped_host_paths(_mime(alias)) == (alias,)


def test_real_drop_scan_reaches_sync_selection_with_only_selected_photo(
    shell: tuple[MainWindow, AppContext],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, context = shell
    photo = tmp_path / "selected.png"
    Image.new("RGB", (8, 8), "red").save(photo)
    Image.new("RGB", (8, 8), "blue").save(tmp_path / "unrelated.png")
    monkeypatch.setattr(context.ipod_media_controller, "start", lambda: True)
    pages = window.findChild(QStackedWidget, "pageStack")
    sync = window.findChild(SyncWorkspace)
    assert pages is not None and sync is not None
    mime = _mime(photo)
    assert _enter(pages, mime).isAccepted()
    assert _drop(pages, mime).isAccepted()
    APPLICATION.processEvents()
    wait_for(lambda: not context.host_media_controller.busy)
    library = context.host_media_controller.latest_library
    assert library is not None and library.snapshot.photos is not None
    assert len(library.snapshot.photos.photos) == 1
    context.ipod_media_controller.finished.emit(
        IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
    )
    assert sync.isVisible() and sync.stage is SyncStage.SELECT


def test_no_active_ipod_rejects_drop(tmp_path: Path) -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        APPLICATION.processEvents()
        pages = window.findChild(QStackedWidget, "pageStack")
        assert pages is not None
        assert not _enter(pages, _mime(tmp_path)).isAccepted()
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)


def test_skipped_link_stays_visible_in_empty_selection_and_review(
    shell: tuple[MainWindow, AppContext],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, context = shell
    selected = tmp_path / "selected"
    selected.mkdir()
    photo = tmp_path / "outside.png"
    Image.new("RGB", (8, 8), "red").save(photo)
    try:
        (selected / "linked.png").symlink_to(photo)
    except OSError as error:
        pytest.skip(f"Host cannot create symbolic links: {error}")

    def accept_settings(_dialog: MediaFolderSettingsDialog) -> int:
        return 1

    monkeypatch.setattr(MediaFolderSettingsDialog, "exec", accept_settings)
    monkeypatch.setattr(context.ipod_media_controller, "start", lambda: True)
    pages = window.findChild(QStackedWidget, "pageStack")
    sync = window.findChild(SyncWorkspace)
    assert pages is not None and sync is not None
    mime = _mime(selected)
    assert _enter(pages, mime).isAccepted()
    assert _drop(pages, mime).isAccepted()
    APPLICATION.processEvents()
    wait_for(lambda: not context.host_media_controller.busy)
    library = context.host_media_controller.latest_library
    assert library is not None and library.issues
    context.ipod_media_controller.finished.emit(
        IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
    )
    panel = sync.findChild(HostScanIssues)
    assert panel is not None and panel.has_issues and panel.isVisible()
    assert sync.stage is SyncStage.SELECT
    sync.show_review()
    assert panel.isVisible()
    sync.show_scan("Rescanning")
    assert panel.isHidden() and not panel.has_issues


def test_queued_drop_does_not_outlive_its_library_surface(tmp_path: Path) -> None:
    surface = QWidget()
    surface.show()
    target = HostMediaDropTarget(surface, lambda: True)
    deliveries: list[object] = []
    target.pathsDropped.connect(deliveries.append)
    mime = _mime(tmp_path)
    assert _enter(surface, mime).isAccepted()
    assert _drop(surface, mime).isAccepted()
    surface.deleteLater()
    APPLICATION.sendPostedEvents(surface, QEvent.Type.DeferredDelete)
    APPLICATION.processEvents()
    assert not deliveries
