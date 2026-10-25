"""Native Genius browsing uses read-only captured state and existing Track playback."""

from collections.abc import Iterator
from dataclasses import dataclass, replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QShortcut
from PySide6.QtWidgets import QLabel, QMenu, QSplitter, QTreeWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    FeatureSupport,
    IdentificationStatus,
)
from iOpenPod.app.context import AppContext
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceReadiness,
)
from iOpenPod.app.models.library_drag import TrackSelectionMimeData, dropped_tracks
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.GUI.delegates.genius_collection_delegate import (
    DETAIL_ROLE,
    SECTION_ROLE,
    GeniusCollectionDelegate,
)
from iOpenPod.GUI.dialogs.playlist_editor import PlaylistEditorDialog, kind_label
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.genius_page import GeniusPage
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets import track_table as track_table_module
from iOpenPod.GUI.widgets.browser_chrome import SourceListPanel
from iOpenPod.GUI.widgets.library_toolbar import LibraryToolbar
from iOpenPod.GUI.widgets.playlist_artwork_banner import PlaylistArtworkBanner
from iOpenPod.GUI.widgets.playlist_tree import PlaylistTree
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.themed_buttons import ActionButton
from iOpenPod.GUI.widgets.track_actions import TrackActions
from iPodDB.library import LibrarySnapshot, Playlist, PlaylistKind, Track
from iPodDB.library.genius import (
    GeniusBrowse,
    GeniusBrowseIssue,
    GeniusCollection,
    GeniusCollectionKind,
)
from storage import FileFingerprint

_TRACKS = (
    Track(1, "Alpha", "Artist", "Album", 120_000),
    Track(2, "Beta", "Artist", "Album", 180_000),
    Track(3, "Gamma", "Artist", "Album", 90_000),
)
_BROWSE = GeniusBrowse(
    collections=(
        GeniusCollection(
            "saved:1", "Saved seed", GeniusCollectionKind.PLAYLIST, (3, 1, 1), 3
        ),
        GeniusCollection("mix:2", "Test Mix", GeniusCollectionKind.MIX, (2, 3, 1), 2),
    )
)


def active() -> ActiveIPod:
    profile = next(
        p for p in DEFAULT_DEVICE_REGISTRY.profiles if p.model_number == "MB565"
    )
    return ActiveIPod(
        DeviceCandidate(
            DeviceCandidateId("genius-test"),
            "Test iPod",
            "Virtual iPod",
            "virtual",
            IdentificationStatus.EXACT,
            DeviceReadiness.READY,
            profile,
            120_000_000_000,
            60_000_000_000,
        ),
        profile,
        LibrarySnapshot(_TRACKS),
        "iTunesDB",
        FileFingerprint(1000, 0, 0, 0, "0" * 64),
        genius=_BROWSE,
    )


@dataclass(frozen=True)
class Browser:
    page: GeniusPage
    context: AppContext


@pytest.fixture
def browser() -> Iterator[Browser]:
    context = build_context()
    artwork = ArtworkPixmapProvider(context.artwork_controller)
    page = GeniusPage(
        context.library_workspace, context.settings, context.theme_manager, artwork
    )
    page.set_active_ipod(active())
    page.resize(1000, 700)
    page.show()
    APPLICATION.processEvents()
    try:
        yield Browser(page, context)
    finally:
        page.close()
        context.shutdown()
        artwork.deleteLater()
        page.deleteLater()
        APPLICATION.processEvents()


def tree(page: GeniusPage) -> QTreeWidget:
    result = page.findChild(QTreeWidget, "geniusCollections")
    assert result is not None
    return result


def label(page: GeniusPage, name: str) -> QLabel:
    result = page.findChild(QLabel, name)
    assert result is not None
    return result


def button(page: GeniusPage, name: str) -> ActionButton:
    result = page.findChild(ActionButton, name)
    assert result is not None
    return result


def visible_ids(page: GeniusPage) -> tuple[int, ...]:
    model = page.track_table.model()
    assert isinstance(model, TrackFilterProxyModel)
    return tuple(
        track.track_id
        for row in range(model.rowCount())
        if (track := model.track_at(model.index(row, 0))) is not None
    )


def select(page: GeniusPage, section: int) -> None:
    group = tree(page).topLevelItem(section)
    assert group is not None
    item = group.child(0)
    assert item is not None
    tree(page).setCurrentItem(item)


def test_groups_and_saved_playlist_preserve_order_and_repeated_occurrences(
    browser: Browser,
) -> None:
    page = browser.page
    assert [
        item.text(0)
        for i in range(2)
        if (item := tree(page).topLevelItem(i)) is not None
    ] == [
        "Genius Playlists",
        "Genius Mixes",
    ]
    select(page, 0)
    assert tree(page).isVisible()
    split = page.findChild(QSplitter, "geniusSplit")
    toolbar = page.findChild(LibraryToolbar)
    banner = page.findChild(PlaylistArtworkBanner, "playlistArtworkBanner")
    assert split is not None
    assert toolbar is not None and banner is not None
    assert split.y() >= toolbar.y() + toolbar.height()
    panel = page.findChild(SourceListPanel, "geniusCollectionPanel")
    assert panel is not None and split.widget(0) is panel
    assert panel.minimumWidth() == LAYOUT.source_list_minimum_width
    assert panel.maximumWidth() == LAYOUT.source_list_maximum_width
    assert panel.title_label.text() == "Genius"
    assert panel.count_label.text() == "2"
    assert split.handleWidth() == LAYOUT.source_list_splitter_handle_width
    assert panel.isAncestorOf(tree(page))
    assert isinstance(tree(page).itemDelegate(), GeniusCollectionDelegate)
    section = tree(page).topLevelItem(0)
    assert section is not None and section.data(0, SECTION_ROLE) is True
    item = section.child(0)
    assert item is not None and item.data(0, DETAIL_ROLE) == "3 tracks"
    detail_widget = split.widget(1)
    assert detail_widget is not None
    assert detail_widget.isAncestorOf(banner)
    assert detail_widget.isAncestorOf(page.track_table)
    assert visible_ids(page) == (3, 1, 1)
    assert page.track_table.horizontalHeader().sortIndicatorSection() == -1
    assert label(page, "pageTitle").text() == "Saved seed"
    assert "Genius Playlist · 3 tracks" in label(page, "pageMeta").text()
    assert "Smart" not in label(page, "pageDescription").text()
    assert isinstance(page, PlaylistPage)
    assert page.findChild(PlaylistPage) is None
    assert page.findChild(PlaylistArtworkBanner, "playlistArtworkBanner") is not None
    assert button(page, "editPlaylist").isHidden()
    assert button(page, "evaluateSmartPlaylist").isHidden()
    assert button(page, "removePlaylist").isVisible()
    assert not button(page, "removePlaylist").isEnabled()
    assert button(page, "exportPlaylist").isVisible()
    assert button(page, "queuePlaylist").isVisible()
    assert button(page, "playNextPlaylist").isVisible()
    assert not page.track_table.dragEnabled()
    assert not page.findChildren(QShortcut)
    assert not browser.context.library_workspace.dirty


def test_mix_explains_members_and_only_requested_track_is_played(
    browser: Browser,
) -> None:
    page = browser.page
    select(page, 1)
    assert tree(page).isVisible()
    assert visible_ids(page) == (2, 3, 1)
    assert (
        label(page, "pageDescription").text()
        == "Mix tracks are possible starting songs; the iPod generates the mix when you play it."
    )
    assert "Genius Mix · 3 tracks" in label(page, "pageMeta").text()
    assert button(page, "editPlaylist").isHidden()
    assert button(page, "evaluateSmartPlaylist").isHidden()
    assert button(page, "removePlaylist").isVisible()
    assert not button(page, "removePlaylist").isEnabled()
    assert button(page, "exportPlaylist").isHidden()
    assert not button(page, "playSelectedGeniusTracks").isEnabled()
    assert not button(page, "queuePlaylist").isEnabled()
    assert not button(page, "playNextPlaylist").isEnabled()
    played: list[tuple[Track, ...]] = []
    queued: list[tuple[Track, ...]] = []
    next_tracks: list[tuple[Track, ...]] = []
    page.playRequested.connect(played.append)
    page.queueRequested.connect(queued.append)
    page.playNextRequested.connect(next_tracks.append)
    page.track_table.selectRow(1)
    button(page, "playSelectedGeniusTracks").click()
    button(page, "queuePlaylist").click()
    button(page, "playNextPlaylist").click()
    assert played == queued == next_tracks == [(_TRACKS[2],)]
    page.track_table.trackActivated.emit(_TRACKS[1])
    assert played[-1] == (_TRACKS[1],)
    assert not browser.context.library_workspace.dirty


def test_switching_between_mix_and_playlist_keeps_one_detail_view_and_sidebar(
    browser: Browser,
) -> None:
    page = browser.page
    detail = page

    select(page, 1)
    assert page.track_table is detail.track_table
    assert visible_ids(page) == (2, 3, 1)
    assert tree(page).isVisible()

    select(page, 0)
    assert page.track_table is detail.track_table
    assert visible_ids(page) == (3, 1, 1)
    assert tree(page).isVisible()
    assert button(page, "playSelectedGeniusTracks").isHidden()
    assert button(page, "exportPlaylist").isVisible()


def test_saved_genius_playlist_uses_playlist_search_export_and_queue(
    browser: Browser,
) -> None:
    page = browser.page
    select(page, 0)
    playlist = page
    exports: list[tuple[str, tuple[Track, ...]]] = []
    queued: list[tuple[Track, ...]] = []

    def capture_export(name: str, tracks: tuple[Track, ...]) -> None:
        exports.append((name, tracks))

    page.playlistExportRequested.connect(capture_export)
    page.queueRequested.connect(queued.append)
    search = playlist.findChild(SearchField, "playlistsSearch")
    assert search is not None
    search.set_query("Gamma")
    search.queryChanged.emit("Gamma")
    assert visible_ids(page) == (3,)

    button(page, "exportPlaylist").click()
    button(page, "queuePlaylist").click()

    assert exports == [("Saved seed", (_TRACKS[2], _TRACKS[0], _TRACKS[0]))]
    assert queued == [(_TRACKS[2],)]
    assert not browser.context.library_workspace.dirty
    assert tree(page).isVisible()
    assert page.track_table is playlist.track_table


def test_source_change_and_disconnect_clear_selection_tracks_and_playback(
    browser: Browser,
) -> None:
    page = browser.page
    select(page, 0)
    current = active()
    page.set_active_ipod(
        replace(
            current,
            candidate=replace(
                current.candidate, id=DeviceCandidateId("another-device")
            ),
        )
    )
    assert visible_ids(page) == ()
    assert "Choose a Genius" in label(page, "playlistEmpty").text()
    select(page, 1)
    page.set_active_ipod(None)
    assert tree(page).topLevelItemCount() == 0
    assert visible_ids(page) == ()
    assert not button(page, "playSelectedGeniusTracks").isEnabled()
    assert "Connect and choose" in label(page, "playlistEmpty").text()


def test_draft_track_deletion_updates_genius_members_counts_and_empty_collections(
    browser: Browser,
) -> None:
    current = active()
    workspace = browser.context.library_workspace
    workspace.load(current.library)
    page = browser.page
    page.set_active_ipod(current)
    select(page, 0)
    workspace.remove_tracks((3,), workspace.edit_revision)
    assert visible_ids(page) == (1, 1)
    section = tree(page).topLevelItem(0)
    assert section is not None
    item = section.child(0)
    assert item is not None and item.data(0, DETAIL_ROLE) == "2 tracks"
    workspace.remove_tracks((1,), workspace.edit_revision)
    assert visible_ids(page) == ()
    assert tree(page).topLevelItemCount() == 1
    section = tree(page).topLevelItem(0)
    assert section is not None and section.text(0) == "Genius Mixes"
    workspace.reset_changes()
    assert tree(page).topLevelItemCount() == 2


def test_same_connection_refresh_updates_selected_tracks_and_keeps_issues_plain(
    browser: Browser,
) -> None:
    page = browser.page
    select(page, 0)
    current = active()
    changed = replace(
        current,
        library=LibrarySnapshot(
            tuple(replace(track, title="Updated") for track in _TRACKS)
        ),
        genius=replace(
            _BROWSE,
            issues=(
                GeniusBrowseIssue("capture.partial", "<invalid> companion retained"),
            ),
        ),
    )
    page.set_active_ipod(changed)
    assert visible_ids(page) == (3, 1, 1)
    model = page.track_table.model()
    assert isinstance(model, TrackFilterProxyModel)
    selected = model.track_at(model.index(0, 0))
    assert selected is not None and selected.title == "Updated"
    assert label(page, "geniusIssues").text() == "<invalid> companion retained"
    assert label(page, "geniusIssues").textFormat() is Qt.TextFormat.PlainText


def test_sidebar_exposes_capable_devices_and_actual_captured_data() -> None:
    sidebar = Sidebar()
    try:
        sidebar.set_active_ipod(None)
        assert not sidebar.page_available(PageId.GENIUS)
        current = active()
        sidebar.set_active_ipod(replace(current, genius=GeniusBrowse()))
        assert sidebar.page_available(PageId.GENIUS)
        old = next(
            p
            for p in DEFAULT_DEVICE_REGISTRY.profiles
            if p.capabilities.genius.playlists is FeatureSupport.UNSUPPORTED
            and p.capabilities.genius.mixes is FeatureSupport.UNSUPPORTED
        )
        sidebar.set_active_ipod(replace(current, profile=old, genius=GeniusBrowse()))
        assert not sidebar.page_available(PageId.GENIUS)
        sidebar.set_active_ipod(replace(current, profile=old))
        assert sidebar.page_available(PageId.GENIUS)
    finally:
        sidebar.deleteLater()


@pytest.mark.parametrize(("section", "track"), ((0, _TRACKS[2]), (1, _TRACKS[1])))
def test_shell_gives_genius_tracks_the_shared_menu_and_drag(
    monkeypatch: pytest.MonkeyPatch,
    section: int,
    track: Track,
) -> None:
    context = build_context()
    current = active()
    context.library_workspace.load(current.library)
    window = MainWindow(context, auto_discover=False, defer_startup=True)
    dragged: list[TrackSelectionMimeData] = []

    class RecordingDrag:
        def __init__(self, _source: object) -> None:
            pass

        def setMimeData(self, data: TrackSelectionMimeData) -> None:
            dragged.append(data)

        def setPixmap(self, _pixmap: object) -> None:
            pass

        def setHotSpot(self, _point: object) -> None:
            pass

        def exec(self, _action: Qt.DropAction) -> Qt.DropAction:
            return Qt.DropAction.CopyAction

    try:
        window.show()
        page = window.findChild(GeniusPage, "geniusPage")
        actions = window.findChild(TrackActions)
        assert page is not None
        assert actions is not None
        page.set_active_ipod(current)
        select(page, section)
        table = page.track_table
        table.selectRow(0)
        assert table.dragEnabled()
        assert table.contextMenuPolicy() is Qt.ContextMenuPolicy.CustomContextMenu
        assert table.findChildren(QShortcut)
        selection = actions.selection(table)
        assert selection.track_ids == (track.track_id,)
        assert selection.playlist_id is None
        menu = actions.build_menu(selection)
        try:
            assert isinstance(menu, QMenu)
            assert menu.objectName() == "trackContextMenu"
            assert any(action.text() == "Add to Playlist" for action in menu.actions())
            assert not any(
                action.text() == "Remove from Playlist" for action in menu.actions()
            )
        finally:
            menu.deleteLater()

        monkeypatch.setattr(track_table_module, "QDrag", RecordingDrag)
        table.startDrag(Qt.DropAction.CopyAction)
        assert len(dragged) == 1
        assert dragged[0].track_ids == (track.track_id,)
        assert dropped_tracks(dragged[0], context.library_workspace) == (track,)

        played: list[tuple[Track, ...]] = []
        page.playRequested.connect(played.append)
        table.doubleClicked.emit(table.model().index(0, 1))
        assert played == [(track,)]

        actions.apply(selection, "rating", 80)
        table.selectRow(0)
        updated = context.library_workspace.track(track.track_id)
        assert updated is not None and updated.rating == 80
        assert actions.selection(table).tracks == (updated,)
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.processEvents()


def test_shell_connects_genius_queue_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queued: list[tuple[Track, ...]] = []

    def capture_queue(_window: MainWindow, tracks: tuple[Track, ...]) -> None:
        queued.append(tracks)

    monkeypatch.setattr(
        MainWindow,
        "_queue_group_tracks",
        capture_queue,
    )
    context = build_context()
    window = MainWindow(context, auto_discover=False, defer_startup=True)
    try:
        page = window.findChild(GeniusPage, "geniusPage")
        assert page is not None
        page.set_active_ipod(active())
        select(page, 0)
        button(page, "queuePlaylist").click()

        assert queued == [(_TRACKS[2], _TRACKS[0], _TRACKS[0])]
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.processEvents()


def test_genius_kind_has_a_label_but_no_create_action_or_editor(
    browser: Browser,
) -> None:
    context = browser.context
    context.library_workspace.load(LibrarySnapshot(_TRACKS))
    playlist_tree = PlaylistTree(context.library_workspace)
    try:
        assert kind_label(PlaylistKind.GENIUS) == "Genius Playlist"
        assert all(kind_label(kind) for kind in PlaylistKind)
        creatable = {
            action.data()
            for action in playlist_tree.findChildren(QAction)
            if action.data() in {kind.value for kind in PlaylistKind}
        }
        assert creatable == {
            PlaylistKind.PLAYLIST,
            PlaylistKind.SMART,
            PlaylistKind.FOLDER,
        }
        with pytest.raises(ValueError, match="read-only"):
            PlaylistEditorDialog(PlaylistKind.GENIUS)
    finally:
        playlist_tree.deleteLater()


def test_ordinary_playlist_page_refuses_genius_creation_and_mutation(
    browser: Browser,
) -> None:
    context = browser.context
    retained = Playlist(10, "Native saved", kind=PlaylistKind.GENIUS)
    context.library_workspace.load(LibrarySnapshot(_TRACKS, (retained,)))
    provider = ArtworkPixmapProvider(context.artwork_controller)
    page = PlaylistPage(
        context.library_workspace, context.settings, context.theme_manager, provider
    )
    try:
        page.select_playlist(10)
        page.create_playlist(PlaylistKind.GENIUS)
        page.edit_playlist(10)
        page.remove_playlist(10)
        edit = page.findChild(ActionButton, "editPlaylist")
        remove = page.findChild(ActionButton, "removePlaylist")
        summary = page.findChild(QLabel, "pageMeta")
        assert edit is not None and edit.isHidden()
        assert remove is not None and remove.isHidden()
        assert summary is not None and "Genius Playlist" in summary.text()
        assert not context.library_workspace.dirty
        assert context.library_workspace.playlists == (retained,)
    finally:
        page.deleteLater()
        provider.deleteLater()
