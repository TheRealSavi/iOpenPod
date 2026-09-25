from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QToolButton,
    QTreeView,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from device_registry import DEFAULT_DEVICE_REGISTRY, IdentificationStatus
from iOpenPod.app.host_media_library import (
    HostMediaCacheStats,
    HostMediaFileKind,
    HostMediaLibrary,
    HostMediaSource,
)
from iOpenPod.app.library_sync_helper import (
    IPodMediaCacheStats,
    IPodMediaLibrary,
    IPodTrackFingerprint,
)
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.models.sync_plan_table_model import SyncPlanColumn
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.models.track_table_model import TrackColumn
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.GUI import main_window as main_window_module
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.sync_plan_page import SyncPlanPage
from iOpenPod.GUI.sync_workspace import SyncStage, SyncWorkspace
from iOpenPod.GUI.widgets.playlist_tree import PlaylistTree
from iOpenPod.GUI.widgets.sync_review_group import SyncReviewGroup
from iOpenPod.GUI.widgets.sync_storage_bar import SyncStorageBar
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import LibrarySnapshot, Playlist, PlaylistKind, Track, TrackMetadata
from storage import DevicePath, FileFingerprint, HostPath


def _item(
    action: SyncPlanAction,
    name: str,
    *,
    media_kind: SyncPlanMediaKind = SyncPlanMediaKind.TRACK,
) -> SyncPlanItem:
    host_path = None if action is SyncPlanAction.REMOVE else f"C:/Music/{name}"
    ipod_id = None if action is SyncPlanAction.ADD else len(name) + 1
    ipod_path = (
        None if action is SyncPlanAction.ADD else f"iPod_Control/Music/F00/{name}"
    )
    basis = {
        SyncPlanAction.ADD: SyncPlanBasis.HOST_ONLY,
        SyncPlanAction.UPDATE: SyncPlanBasis.HOST_FACTS_CHANGED,
        SyncPlanAction.REMOVE: SyncPlanBasis.IPOD_ONLY,
        SyncPlanAction.UNCHANGED: SyncPlanBasis.CONTENT_MATCH,
        SyncPlanAction.ATTENTION: SyncPlanBasis.MISSING_IDENTITY,
    }[action]
    return SyncPlanItem(
        action,
        media_kind,
        basis,
        name,
        "Artist · Album" if media_kind is SyncPlanMediaKind.TRACK else "640 x 480",
        host_path,
        ipod_path,
        ipod_id,
        host_size_changed=action is SyncPlanAction.UPDATE,
    )


def _plan() -> SyncPlan:
    return SyncPlan(
        (
            _item(SyncPlanAction.ADD, "add.mp3"),
            _item(SyncPlanAction.UPDATE, "update.mp3"),
            _item(SyncPlanAction.REMOVE, "remove.mp3"),
            _item(SyncPlanAction.UNCHANGED, "same.mp3"),
            _item(
                SyncPlanAction.ATTENTION,
                "photo.jpg",
                media_kind=SyncPlanMediaKind.PHOTO,
            ),
        )
    )


def _selection(plan: SyncPlan) -> SyncSelection:
    tracks = tuple(
        Track(
            index + 1,
            item.name,
            "Artist",
            "Album",
            180_000,
            metadata=TrackMetadata(location=item.host_path),
        )
        for index, item in enumerate(plan.items)
        if item.host_path is not None and item.media_kind is SyncPlanMediaKind.TRACK
    )
    library = HostMediaLibrary(LibrarySnapshot(tracks), (), (), HostMediaCacheStats())
    selection = SyncSelection()
    selection.reset(library, plan)
    selection.set_tracks_checked((track.track_id for track in tracks), True)
    return selection


@pytest.fixture
def review_page() -> Iterator[SyncPlanPage]:
    page = SyncPlanPage()
    page.resize(1100, 700)
    page.show()
    yield page
    page.close()
    page.deleteLater()
    APPLICATION.sendPostedEvents(page, QEvent.Type.DeferredDelete)


def _group(page: SyncPlanPage, action: SyncPlanAction) -> SyncReviewGroup:
    return next(
        group
        for group in page.findChildren(SyncReviewGroup)
        if group.action is action and group.media in {None, SyncPlanMediaKind.TRACK}
    )


def test_review_checkboxes_skip_actions_without_changing_host_membership(
    review_page: SyncPlanPage,
) -> None:
    selection = _selection(_plan())
    review_page.load_review(selection)
    candidates = selection.review_plan
    membership = selection.selected_host_count
    changes = QSignalSpy(selection.changed)
    host_changes = QSignalSpy(selection.hostSelectionChanged)

    assert selection.selected_plan.change_count == 2
    assert selection.set_review_items_checked(candidates.items, False)
    assert changes.count() == 1
    assert host_changes.count() == 0
    assert selection.selected_host_count == membership
    assert selection.review_plan == candidates
    assert selection.selected_plan.change_count == 0
    assert selection.selected_plan.attention_count == 1
    assert selection.selected_plan.count(SyncPlanAction.UNCHANGED) == 1
    assert not selection.set_review_items_checked(candidates.items, False)

    assert selection.set_review_items_checked(candidates.items, True)
    assert selection.selected_plan.change_count == 3
    assert selection.review_check_state(candidates.items[0]) is Qt.CheckState.Checked
    assert review_page.selection_summary == "3 of 3 media changes selected"
    assert selection.comparison == _plan()


def test_review_group_mixed_state_keyboard_and_item_selection_stay_in_sync(
    review_page: SyncPlanPage,
) -> None:
    selection = _selection(
        SyncPlan(
            (
                _item(SyncPlanAction.ADD, "first.mp3"),
                _item(SyncPlanAction.ADD, "second.mp3"),
            )
        )
    )
    review_page.load_review(selection)
    group = _group(review_page, SyncPlanAction.ADD)
    assert not group.toggle.isChecked()
    group.toggle.click()
    APPLICATION.processEvents()
    assert group.table.isVisible()
    assert group.proxy.setData(
        group.proxy.index(0, SyncPlanColumn.ACTION),
        Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole,
    )
    assert group.checkbox.checkState() is Qt.CheckState.PartiallyChecked
    assert group.proxy.rowCount() == 2
    assert group.toggle.isChecked()
    group.checkbox.setFocus()
    QTest.keyClick(group.checkbox, Qt.Key.Key_Space)
    assert group.checkbox.checkState() is Qt.CheckState.Checked
    assert selection.selected_plan.change_count == 2
    QTest.keyClick(group.checkbox, Qt.Key.Key_Space)
    assert selection.selected_plan.change_count == 0
    group.table.setCurrentIndex(group.proxy.index(0, SyncPlanColumn.ACTION))
    QTest.keyClick(group.table, Qt.Key.Key_Space)
    assert selection.selected_plan.change_count == 1
    assert group.checkbox.checkState() is Qt.CheckState.PartiallyChecked


def test_review_group_selection_is_filtered_but_footer_selection_covers_all(
    review_page: SyncPlanPage,
) -> None:
    selection = _selection(
        SyncPlan(
            (
                _item(SyncPlanAction.ADD, "first.mp3"),
                _item(SyncPlanAction.ADD, "second.mp3"),
                _item(SyncPlanAction.REMOVE, "orphan.mp3"),
                _item(SyncPlanAction.ATTENTION, "unknown.mp3"),
            )
        )
    )
    review_page.load_review(selection)
    review_page.proxy.set_query("first")
    APPLICATION.processEvents()
    group = _group(review_page, SyncPlanAction.ADD)
    assert group.proxy.rowCount() == 1
    group.checkbox.click()
    assert selection.selected_plan.change_count == 1
    assert selection.selected_plan.items[0].name == "second.mp3"
    select_all = review_page.findChild(QPushButton, "syncReviewSelectAll")
    assert select_all is not None
    select_all.click()
    assert selection.selected_plan.change_count == 3
    assert selection.selected_plan.attention_count == 1
    assert review_page.proxy.rowCount() == 1
    select_none = review_page.findChild(QPushButton, "syncReviewSelectNone")
    assert select_none is not None
    select_none.click()
    assert selection.selected_plan.change_count == 0
    assert review_page.proxy.rowCount() == 1


def test_review_exclusions_survive_reentry_but_not_changed_actions_or_new_scans(
    review_page: SyncPlanPage,
) -> None:
    selection = _selection(_plan())
    review_page.load_review(selection)
    update = next(
        item
        for item in selection.review_plan.items
        if item.action is SyncPlanAction.UPDATE
    )
    selection.set_review_items_checked((update,), False)
    review_page.load_review(selection)
    assert selection.selected_plan.count(SyncPlanAction.UPDATE) == 0
    selection.set_tracks_checked((2,), False)
    assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 1
    selection.set_tracks_checked((2,), True)
    assert selection.selected_plan.count(SyncPlanAction.UPDATE) == 1
    selection.clear()
    assert selection.review_plan.items == ()
    assert not selection.set_review_items_checked((update,), True)
    assert not selection.set_removal_checked(
        _item(SyncPlanAction.REMOVE, "stale.mp3"), True
    )
    assert review_page.model.rowCount() == 0


def test_review_does_not_make_attention_or_unchanged_items_checkable(
    review_page: SyncPlanPage,
) -> None:
    selection = _selection(_plan())
    review_page.load_review(selection)
    action_filter = review_page.findChild(QComboBox, "syncPlanActionFilter")
    assert action_filter is not None
    action_filter.setCurrentIndex(action_filter.findData("all"))
    for action in (SyncPlanAction.ATTENTION, SyncPlanAction.UNCHANGED):
        group = _group(review_page, action)
        assert group.checkbox.isHidden()
        index = group.proxy.index(0, SyncPlanColumn.ACTION)
        assert not index.flags() & Qt.ItemFlag.ItemIsUserCheckable
        assert not group.proxy.setData(
            index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
        )


def test_review_large_group_keeps_virtual_rows_and_bounded_height(
    review_page: SyncPlanPage,
) -> None:
    plan = SyncPlan(
        tuple(_item(SyncPlanAction.ADD, f"track-{i:05}.mp3") for i in range(10_000))
    )
    selection = _selection(plan)
    review_page.load_review(selection)
    expand = review_page.findChild(QPushButton, "syncReviewExpandAll")
    collapse = review_page.findChild(QPushButton, "syncReviewCollapseAll")
    assert expand is not None and collapse is not None
    expand.click()
    APPLICATION.processEvents()
    group = _group(review_page, SyncPlanAction.ADD)
    assert group.proxy.rowCount() == 10_000
    assert group.table.isVisible()
    assert group.table.height() < 400
    assert len(group.table.findChildren(QPushButton)) == 0
    collapse.click()
    assert group.table.isHidden()


def test_review_clear_resets_search_filters_and_expansion(
    review_page: SyncPlanPage,
) -> None:
    review_page.load_review(_selection(_plan()))
    _group(review_page, SyncPlanAction.ADD).toggle.click()
    review_page.proxy.set_query("add")
    media_filter = review_page.findChild(QComboBox, "syncPlanMediaFilter")
    assert media_filter is not None
    media_filter.setCurrentIndex(media_filter.findData("photo"))
    review_page.clear_plan()
    review_page.load_review(_selection(_plan()))
    assert review_page.proxy.rowCount() == 4
    assert not _group(review_page, SyncPlanAction.ADD).toggle.isChecked()


def test_sync_plan_page_defaults_to_planned_changes_and_summarizes_all_items() -> None:
    page = SyncPlanPage()
    try:
        page.load_plan(_plan())
        page.show()
        APPLICATION.processEvents()

        table = page.findChild(QTableView, "syncPlanTable")
        state = page.findChild(QLabel, "pageMeta")
        attention = page.findChild(QLabel, "syncPlanAttention")
        assert table is not None
        assert state is not None
        assert attention is not None
        assert page.model.rowCount() == 5
        assert page.proxy.rowCount() == 4
        assert state.text() == "3 planned changes"
        assert attention.isVisible()
        assert "1 item" in attention.text()
        assert table.model().index(0, SyncPlanColumn.ACTION).data() == "Add"
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.sendPostedEvents(page, QEvent.Type.DeferredDelete)


def test_sync_plan_page_filters_by_action_media_and_search() -> None:
    page = SyncPlanPage()
    try:
        page.load_plan(_plan())
        action_filter = page.findChild(QComboBox, "syncPlanActionFilter")
        media_filter = page.findChild(QComboBox, "syncPlanMediaFilter")
        assert action_filter is not None
        assert media_filter is not None

        action_filter.setCurrentIndex(action_filter.findData("all"))
        APPLICATION.processEvents()
        assert page.proxy.rowCount() == 5

        media_filter.setCurrentIndex(media_filter.findData("photo"))
        APPLICATION.processEvents()
        assert page.proxy.rowCount() == 1

        media_filter.setCurrentIndex(media_filter.findData("all"))
        page.proxy.set_query("same.mp3")
        APPLICATION.processEvents()
        assert page.proxy.rowCount() == 1
        assert page.proxy.index(0, SyncPlanColumn.ACTION).data() == "In sync"
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.sendPostedEvents(page, QEvent.Type.DeferredDelete)


def test_sync_plan_page_clear_invalidates_the_presented_plan() -> None:
    page = SyncPlanPage()
    try:
        page.load_plan(_plan())
        page.clear_plan()

        assert page.plan is None
        assert page.model.rowCount() == 0
        empty = page.findChild(QLabel, "syncPlanEmpty")
        assert empty is not None
        assert empty.text() == "Run Sync with Host to prepare a plan."
    finally:
        page.close()
        page.deleteLater()
        APPLICATION.sendPostedEvents(page, QEvent.Type.DeferredDelete)


def test_completed_scans_open_selection_with_matched_checked_and_host_only_unchecked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host_path = HostPath(tmp_path / "song.mp3")
    host_track = Track(
        1,
        "Song",
        "Artist",
        "Album",
        180_000,
        metadata=TrackMetadata(location=str(host_path)),
    )
    added_path = HostPath(tmp_path / "new-song.mp3")
    added_track = Track(
        2,
        "New Song",
        "Artist",
        "Album",
        181_000,
        metadata=TrackMetadata(location=str(added_path)),
    )
    host = HostMediaLibrary(
        LibrarySnapshot(
            tracks=(host_track, added_track),
            playlists=(
                Playlist(10, "Playlist", PlaylistKind.PLAYLIST),
                Playlist(11, "Smart Playlist", PlaylistKind.SMART),
                Playlist(12, "Folder", PlaylistKind.FOLDER),
            ),
        ),
        (
            HostMediaSource(
                host_path,
                HostMediaFileKind.AUDIO,
                100,
                1_000,
                acoustic_fingerprint="1,2,3",
            ),
            HostMediaSource(
                added_path,
                HostMediaFileKind.AUDIO,
                101,
                1_001,
                acoustic_fingerprint="4,5,6",
            ),
        ),
        (),
        HostMediaCacheStats(inspected=2),
    )
    ipod_snapshot = LibrarySnapshot(
        tracks=(
            Track(
                10,
                "Song",
                "Artist",
                "Album",
                180_000,
                metadata=TrackMetadata(location="iPod_Control/Music/F00/song.mp3"),
            ),
        )
    )
    ipod = IPodMediaLibrary(
        (
            IPodTrackFingerprint(
                100,
                10,
                DevicePath("iPod_Control/Music/F00/song.mp3"),
                90,
                900,
                "1,2,3",
            ),
            IPodTrackFingerprint(
                101,
                11,
                DevicePath("iPod_Control/Music/F00/orphan.mp3"),
                50,
                900,
                "7,8,9",
            ),
        ),
        (),
        (),
        IPodMediaCacheStats(fingerprinted=1),
        None,
        False,
    )
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == "MB565"
    )
    fake_active = ActiveIPod(
        DeviceCandidate(
            DeviceCandidateId("sync-test"),
            "Test iPod",
            "USB iPod",
            "usb",
            IdentificationStatus.EXACT,
            DeviceReadiness.READY,
            profile,
            1_000,
            400,
        ),
        profile,
        ipod_snapshot,
        "iTunesDB",
        FileFingerprint(size=100, modified_ns=0, device=0, inode=0, sha256="0" * 64),
    )
    monkeypatch.setattr(
        type(context.device_controller),
        "active_ipod",
        property(lambda _controller: fake_active),
    )
    monkeypatch.setattr(context.ipod_media_controller, "start", lambda: True)

    class FakeMediaFoldersDialog:
        folders = ()

        def __init__(self, _settings: object, _parent: object) -> None:
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

    def start_host_scan(_folders: object) -> bool:
        return True

    monkeypatch.setattr(context.host_media_controller, "start", start_host_scan)

    def fail_information(*_args: object) -> None:
        pytest.fail("A completed comparison should open Sync Plan without a modal")

    monkeypatch.setattr(QMessageBox, "information", fail_information)
    try:
        sync = window.findChild(QPushButton, "syncWithHost")
        assert sync is not None
        sync.setEnabled(True)
        sync.click()
        context.host_media_controller.finished.emit(host)
        context.ipod_media_controller.finished.emit(ipod)
        APPLICATION.processEvents()

        workspace = window.findChild(SyncWorkspace, "syncWorkspace")
        assert workspace is not None
        assert workspace.stage is SyncStage.SELECT
        assert window.windowTitle() == "Sync with Host — iOpenPod"
        assert workspace.selection.track_check_state(1) is Qt.CheckState.Checked
        assert workspace.selection.track_check_state(2) is Qt.CheckState.Unchecked

        playlists = workspace.findChild(PlaylistTree, "syncPlaylistSidebar")
        assert playlists is not None
        add_playlist = playlists.findChild(QToolButton, "newPlaylistButton")
        assert add_playlist is not None
        assert add_playlist.isHidden()

        tree = playlists.findChild(QTreeView, "playlistTree")
        assert tree is not None
        context_menus = QSignalSpy(tree.customContextMenuRequested)

        def skip_context_menu(*_args: object) -> None:
            return None

        monkeypatch.setattr(QMenu, "exec", skip_context_menu)
        browser = workspace.browser
        assert browser is not None
        for playlist in host.snapshot.playlists:
            playlists.select_playlist(playlist.playlist_id)
            APPLICATION.processEvents()
            assert browser.playlist_page.selected_playlist_id == playlist.playlist_id
            for name in ("editPlaylist", "removePlaylist", "evaluateSmartPlaylist"):
                button = browser.playlist_page.findChild(QPushButton, name)
                assert button is not None and button.isHidden()
            position = tree.visualRect(tree.currentIndex()).center()
            APPLICATION.sendEvent(
                tree.viewport(),
                QContextMenuEvent(
                    QContextMenuEvent.Reason.Mouse,
                    position,
                    tree.viewport().mapToGlobal(position),
                ),
            )
        assert context_menus.count() == 0

        tracks = next(
            button
            for button in workspace.findChildren(QPushButton)
            if button.property("syncPageId") == PageId.TRACKS.value
        )
        tracks.click()
        APPLICATION.processEvents()
        table = next(
            candidate
            for candidate in workspace.findChildren(TrackTable)
            if candidate.property("tableId") == "host-tracks"
        )
        model = table.model()
        states = {
            model.index(row, TrackColumn.TITLE).data(): model.index(
                row, TrackColumn.SYNC_SELECTION
            ).data(Qt.ItemDataRole.CheckStateRole)
            for row in range(model.rowCount())
        }
        assert states == {
            "Song": Qt.CheckState.Checked,
            "New Song": Qt.CheckState.Unchecked,
        }

        bar = workspace.findChild(SyncStorageBar, "syncStorageBar")
        assert bar is not None and not bar.isHidden()
        assert bar.estimate is not None
        assert bar.estimate.projected_used_bytes == 600
        workspace.selection.set_tracks_checked((2,), True)
        assert bar.estimate.projected_used_bytes == 701
        workspace.selection.set_tracks_checked((1,), False)
        assert bar.estimate.projected_used_bytes == 611

        workspace.show_review()
        assert not bar.isHidden()
        assert bar.estimate.projected_used_bytes == 611
        review = workspace.findChild(SyncPlanPage)
        assert review is not None
        row = next(
            row
            for row in range(review.model.rowCount())
            if review.model.index(row, SyncPlanColumn.ACTION).data(
                Qt.ItemDataRole.CheckStateRole
            )
            is Qt.CheckState.Unchecked
        )
        assert review.model.setData(
            review.model.index(row, SyncPlanColumn.ACTION),
            Qt.CheckState.Checked,
            Qt.ItemDataRole.CheckStateRole,
        )
        assert bar.estimate.projected_used_bytes == 561
        add_group = _group(review, SyncPlanAction.ADD)
        add_group.checkbox.click()
        assert bar.estimate.projected_used_bytes == 460
        assert workspace.selection.track_check_state(2) is Qt.CheckState.Checked
        add_group.checkbox.click()
        assert bar.estimate.projected_used_bytes == 561
        summary = workspace.findChild(QLabel, "syncReviewSummary")
        assert summary is not None
        assert summary.text() == "3 of 3 selected · 1 Playlist change"
        playlist_preview = workspace.findChild(
            QPlainTextEdit, "syncPlaylistReviewChanges"
        )
        assert playlist_preview is not None
        assert playlist_preview.toPlainText() == "Create Playlist: 0 added, 0 removed"
        back = workspace.findChild(QPushButton, "backToSyncSelection")
        assert back is not None and back.text() == "Edit Selection"
        back.click()
        assert workspace.stage is SyncStage.SELECT
        assert bar.estimate.projected_used_bytes == 561
        assert not bar.isHidden()
        execute = workspace.findChild(QPushButton, "executeSync")
        assert execute is not None and not execute.isEnabled()

        context.device_controller.activeIPodChanged.emit(None)
        cleared_bar = workspace.findChild(SyncStorageBar, "syncStorageBar")
        assert cleared_bar is not None and cleared_bar.estimate is None
        assert cleared_bar.isHidden()
    finally:
        monkeypatch.undo()
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)
