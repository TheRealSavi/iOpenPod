"""Inline track cells use the same Library actions as the normal Track table."""

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QToolButton
from tests.iOpenPod.GUI.application_shell_test_support import (
    APPLICATION,
    build_context,
    show_albums,
)

from iOpenPod.app.core.settings.definitions import (
    IPOD_LIBRARY_VIEW_MODE,
    LIBRARY_DOUBLE_CLICK_SHORTCUT,
    IPodLibraryViewMode,
    LibraryDoubleClickShortcut,
)
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.inline_album_panel import InlineAlbumPanel
from iOpenPod.GUI.widgets.track_actions import TrackActions
from iPodDB.library import LibrarySnapshot, Track, TrackMetadata


def test_inline_cells_keep_context_selection_and_ordered_playback() -> None:
    context = build_context()
    tracks = tuple(
        Track(number, f"Song {number}", "Artist", "Album", 180_000, track_number=number)
        for number in range(1, 5)
    )
    context.library_workspace.load(LibrarySnapshot(tracks, ()))
    context.track_model.replace_tracks(tracks)
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    context.settings.set_global(
        LIBRARY_DOUBLE_CLICK_SHORTCUT, LibraryDoubleClickShortcut.PLAY_NOW.value
    )
    window = MainWindow(context, auto_discover=False)
    show_albums(window)
    try:
        window.resize(1600, 950)
        window.show()
        QTest.qWait(50)
        page = window.findChild(LibraryPage, "albumsPage")
        assert page is not None
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        actions = window.findChild(TrackActions)
        assert grid is not None and panel is not None and actions is not None
        grid.clicked.emit(grid.model().index(0, 0))
        QTest.qWait(280)
        view = panel.track_view
        assert view.model().columnCount() == 2
        right = view.model().index(0, 1)
        # A context click selects only this cell, never the other Track in its row.
        selection = actions.selection(view, view.visualRect(right).center())
        assert selection.tracks == (tracks[2],)
        assert len(view.selectionModel().selectedIndexes()) == 1
        view.doubleClicked.emit(right)
        assert context.playback_controller.current_track == tracks[2]
        view.clearSelection()
        for column, row in ((1, 0), (0, 1), (0, 0)):
            view.selectionModel().select(
                view.model().index(row, column),
                QItemSelectionModel.SelectionFlag.Select,
            )
        assert actions.selection(view).tracks == tracks[:3]
        view.selectionModel().setCurrentIndex(
            view.model().index(0, 0), QItemSelectionModel.SelectionFlag.NoUpdate
        )
        QTest.keyClick(view, Qt.Key.Key_Return)
        assert context.playback_controller.current_track == tracks[0]
        assert (
            tuple(
                entry.track for entry in context.playback_controller.queue_model.entries
            )
            == tracks[1:3]
        )
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize("action", ("Play", "PlayNext", "Queue"))
@pytest.mark.parametrize("already_playing", (False, True))
def test_album_buttons_play_or_queue_the_complete_album(
    action: str, already_playing: bool
) -> None:
    context = build_context()
    tracks = tuple(
        Track(
            number,
            f"Song {number}",
            "Artist",
            "Album",
            180_000,
            track_number=(number - 1) % 2 + 1,
            metadata=TrackMetadata(disc_number=(number - 1) // 2 + 1),
        )
        for number in range(1, 5)
    )
    outside = Track(10, "Current", "Another artist", "Other album", 180_000)
    pending = Track(11, "Pending", "Another artist", "Other album", 180_000)
    library = (outside, *reversed(tracks), pending)
    context.library_workspace.load(LibrarySnapshot(library))
    context.track_model.replace_tracks(library)
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    window = MainWindow(context, auto_discover=False)
    show_albums(window)
    try:
        window.resize(1600, 950)
        window.show()
        QTest.qWait(50)
        page = window.findChild(LibraryPage, "albumsPage")
        assert page is not None
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        assert grid is not None and panel is not None
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(grid.model().index(0, 0)).center(),
        )
        QTest.qWait(280)
        # Select just one Track and a different card. The buttons must still use
        # the open Album, in disc/track order, without altering either selection.
        view = panel.track_view
        view.setCurrentIndex(view.model().index(0, 1))
        grid.setCurrentIndex(grid.model().index(1, 0))
        selected = panel.selected_tracks()
        assert selected == (tracks[2],)
        playback = context.playback_controller
        if already_playing:
            playback.play_now((outside, pending))
        button = panel.findChild(QToolButton, f"inlineAlbum{action}")
        assert button is not None and button.isEnabled()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        if not already_playing or action == "Play":
            assert playback.current_track == tracks[0]
            expected = (*tracks[1:], pending) if already_playing else tracks[1:]
        else:
            assert playback.current_track == outside
            expected = (
                (*tracks, pending) if action == "PlayNext" else (pending, *tracks)
            )
        assert tuple(entry.track for entry in playback.queue_model.entries) == expected
        assert panel.selected_tracks() == selected
        assert grid.currentIndex().row() == 1
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize("focus", ("album", "track", "tracks"))
def test_physical_shortcuts_use_the_focused_album_or_inline_track(focus: str) -> None:
    context = build_context()
    tracks = tuple(
        Track(number, f"Song {number}", "Artist", "Album", 180_000, track_number=number)
        for number in range(1, 5)
    )
    context.library_workspace.load(LibrarySnapshot(tracks))
    context.track_model.replace_tracks(tracks)
    context.settings.set_global(
        IPOD_LIBRARY_VIEW_MODE, IPodLibraryViewMode.ITUNES_11.value
    )
    window = MainWindow(context, auto_discover=False)
    show_albums(window)
    try:
        window.resize(1600, 950)
        window.show()
        window.activateWindow()
        QTest.qWait(50)
        page = window.findChild(LibraryPage, "albumsPage")
        assert page is not None
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        assert grid is not None and panel is not None
        QTest.mouseMove(
            grid.viewport(), grid.visualRect(grid.model().index(0, 0)).center()
        )
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(grid.model().index(0, 0)).center(),
        )
        QTest.qWait(280)
        view = grid if focus == "album" else panel.track_view
        if focus != "album":
            assert view.model().columnCount() == 2
            index = view.model().index(0, 1)
            QTest.mouseClick(
                view.viewport(),
                Qt.MouseButton.LeftButton,
                pos=view.visualRect(index).center(),
            )
            if focus == "tracks":
                view.selectionModel().select(
                    view.model().index(0, 0), QItemSelectionModel.SelectionFlag.Select
                )
        assert view.hasFocus()
        expected = (
            tracks
            if focus == "album"
            else (tracks[0], tracks[2])
            if focus == "tracks"
            else tracks[2:3]
        )

        # Actual key events catch ambiguous shortcuts between the nested views;
        # emitting QShortcut.activated directly bypasses Qt's shortcut matching.
        QTest.keyClick(view, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
        editor = window.findChild(MetadataEditorDialog)
        assert editor is not None and editor.isVisible()
        if focus == "track":
            title = editor.rows["title"].editor
            assert isinstance(title, QLineEdit) and title.text() == "Song 3"
        else:
            assert editor.windowTitle() == f"Edit {len(expected)} Tracks"
        editor.reject()
        APPLICATION.processEvents()
        window.activateWindow()
        QTest.qWait(30)
        view.setFocus()
        APPLICATION.processEvents()
        assert view.hasFocus()

        QTest.keyClick(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        assert APPLICATION.clipboard().text() == "\n".join(
            f"{track.title}\tArtist\tAlbum" for track in expected
        )
        playback = context.playback_controller
        playback.enqueue(tracks[0])
        QTest.keyClick(view, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier)
        assert tuple(entry.track for entry in playback.queue_model.entries) == expected
        playback.enqueue(tracks[-1])
        QTest.keyClick(
            view,
            Qt.Key.Key_Q,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        assert tuple(entry.track for entry in playback.queue_model.entries) == (
            *expected,
            *expected,
            tracks[-1],
        )
    finally:
        window.close()
        context.shutdown()
