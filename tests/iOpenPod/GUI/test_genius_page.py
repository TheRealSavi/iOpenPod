"""Native Genius browsing uses read-only captured state and existing Track playback."""

from collections.abc import Iterator
from dataclasses import dataclass, replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QShortcut
from PySide6.QtWidgets import QLabel, QTreeWidget
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
from iOpenPod.app.models.library_filter_models import TrackFilterProxyModel
from iOpenPod.GUI.dialogs.playlist_editor import PlaylistEditorDialog, kind_label
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.genius_page import GeniusPage
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.playlist_tree import PlaylistTree
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.themed_buttons import ActionButton
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
    page = GeniusPage(context.settings, context.theme_manager, artwork)
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
    assert visible_ids(page) == (3, 1, 1)
    assert page.track_table.horizontalHeader().sortIndicatorSection() == -1
    assert label(page, "pageTitle").text() == "Saved seed"
    assert "Smart" not in label(page, "pageDescription").text()
    assert not page.track_table.dragEnabled()
    assert not page.findChildren(QShortcut)
    assert not browser.context.library_workspace.dirty


def test_mix_explains_members_and_only_requested_track_is_played(
    browser: Browser,
) -> None:
    page = browser.page
    select(page, 1)
    assert visible_ids(page) == (2, 3, 1)
    assert (
        label(page, "pageDescription").text()
        == "Mix tracks are possible starting songs; the iPod generates the mix when you play it."
    )
    played: list[tuple[Track, ...]] = []
    queued: list[tuple[Track, ...]] = []
    next_tracks: list[tuple[Track, ...]] = []
    page.playRequested.connect(played.append)
    page.queueRequested.connect(queued.append)
    page.playNextRequested.connect(next_tracks.append)
    page.track_table.selectRow(1)
    button(page, "playSelectedGeniusTracks").click()
    button(page, "queueSelectedGeniusTracks").click()
    button(page, "playNextGeniusTracks").click()
    assert played == queued == next_tracks == [(_TRACKS[2],)]
    page.track_table.trackActivated.emit(_TRACKS[1])
    assert played[-1] == (_TRACKS[1],)
    assert not browser.context.library_workspace.dirty


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
    assert "Choose a Genius" in label(page, "geniusEmpty").text()
    select(page, 1)
    page.set_active_ipod(None)
    assert tree(page).topLevelItemCount() == 0
    assert visible_ids(page) == ()
    assert not button(page, "playSelectedGeniusTracks").isEnabled()
    assert "Connect and choose" in label(page, "geniusEmpty").text()


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


def test_shell_keeps_genius_table_outside_mutable_actions_and_drag() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False, defer_startup=True)
    try:
        page = window.findChild(GeniusPage, "geniusPage")
        assert page is not None
        assert not page.track_table.dragEnabled()
        assert (
            page.track_table.contextMenuPolicy()
            is not Qt.ContextMenuPolicy.CustomContextMenu
        )
        assert not page.track_table.findChildren(QShortcut)
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
