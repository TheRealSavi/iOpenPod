"""Library double-click preferences share ordered selection and existing actions."""

import pytest
from PySide6.QtCore import QEvent, QItemSelectionModel, QModelIndex, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.core.settings.definitions import (
    IPOD_LIBRARY_VIEW_MODE,
    LIBRARY_DOUBLE_CLICK_SHORTCUT,
    IPodLibraryViewMode,
    LibraryDoubleClickShortcut,
)
from iOpenPod.app.models.track_table_model import TrackColumn
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.pages.playlist_page import PlaylistPage
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.track_actions import TrackActions, TrackSelection
from iPodDB.library import LibrarySnapshot, Playlist, Track, playlist_entries

_TRACKS = (
    Track(1, "One", "Artist A", "Album A", 30_000, track_number=1),
    Track(2, "Two", "Artist A", "Album A", 30_000, track_number=2),
    Track(3, "Three", "Artist B", "Album B", 30_000, track_number=1),
)
_CURRENT = Track(4, "Current", "Other", "Other", 30_000)
_PENDING = Track(5, "Pending", "Other", "Other", 30_000)


def test_setting_options_apply_and_survive_retranslation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context()
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    try:
        combo = page.findChild(AppComboBox, "libraryDoubleClickShortcutCombo")
        tabs = page.findChild(QTabWidget, "settingsTabs")
        assert combo is not None and tabs is not None
        library = next(
            tabs.widget(i) for i in range(tabs.count()) if tabs.tabText(i) == "Library"
        )
        assert library is not None
        assert library.findChild(AppComboBox, combo.objectName()) is combo
        assert [combo.itemText(i) for i in range(combo.count())] == [
            "Add to Queue",
            "Play next",
            "Play now",
            "Edit",
        ]
        assert combo.currentData() == "add-to-queue"
        for action in LibraryDoubleClickShortcut:
            combo.setCurrentIndex(combo.findData(action.value))
            assert context.settings.get(LIBRARY_DOUBLE_CLICK_SHORTCUT) == action.value

        context.settings.set_global(LIBRARY_DOUBLE_CLICK_SHORTCUT, "play-now")
        assert combo.currentData() == "play-now"
        changes = QSignalSpy(context.settings.settingChanged)

        def translate(_page: SettingsPage, text: str) -> str:
            return f"Translated {text}"

        monkeypatch.setattr(SettingsPage, "tr", translate)
        APPLICATION.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
        assert combo.currentText() == "Translated Play now"
        assert combo.currentData() == "play-now"
        assert changes.count() == 0
    finally:
        page.close()
        context.shutdown()


@pytest.mark.parametrize("action", LibraryDoubleClickShortcut)
@pytest.mark.parametrize(
    ("view_name", "rows", "expected"),
    (
        ("tracksTrackTable", (1, 0), _TRACKS[:2]),
        ("albumGrid", (1, 0), _TRACKS),
        ("artistsCollectionGrid", (1, 0), _TRACKS),
        ("artistsCollectionList", (1, 0), _TRACKS),
        ("playlistsTrackTable", (2, 0), (_TRACKS[0], _TRACKS[0])),
    ),
)
def test_double_click_uses_selected_tracks_and_current_preference(
    action: LibraryDoubleClickShortcut,
    view_name: str,
    rows: tuple[int, ...],
    expected: tuple[Track, ...],
) -> None:
    context = build_context()
    playlist = Playlist(10, "Repeated", entries=playlist_entries((1, 2, 1)))
    snapshot = LibrarySnapshot((*_TRACKS, _CURRENT, _PENDING), (playlist,))
    context.library_workspace.load(snapshot)
    context.track_model.replace_tracks(snapshot.tracks)
    window = MainWindow(context, auto_discover=False)
    playback = context.playback_controller
    try:
        if view_name == "playlistsTrackTable":
            page = window.findChild(PlaylistPage)
            assert page is not None
            page.select_playlist(playlist.playlist_id)
        view = window.findChild(QAbstractItemView, view_name)
        assert view is not None
        view.clearSelection()
        for row in rows:
            view.selectionModel().select(
                view.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        playback.enqueue(_CURRENT)
        playback.enqueue(_PENDING)
        playback.seek(5_000)
        current_entry_id = playback.current_entry_id
        # Change the setting after views and their handlers have been constructed.
        context.settings.set_global(LIBRARY_DOUBLE_CLICK_SHORTCUT, action.value)

        view.doubleClicked.emit(view.model().index(0, 0))

        queued = tuple(entry.track for entry in playback.queue_model.entries)
        if action is LibraryDoubleClickShortcut.ADD_TO_QUEUE:
            assert queued == (_PENDING, *expected)
        elif action is LibraryDoubleClickShortcut.PLAY_NEXT:
            assert queued == (*expected, _PENDING)
        elif action is LibraryDoubleClickShortcut.PLAY_NOW:
            assert playback.current_track == expected[0]
            assert playback.current_entry_id != current_entry_id
            assert queued == (*expected[1:], _PENDING)
            assert playback.playing
            assert playback.position_ms == 0
        else:
            assert queued == (_PENDING,)
            editor = window.findChild(MetadataEditorDialog)
            assert editor is not None and editor.isVisible()
            assert editor.windowTitle() == (
                "Edit Track"
                if len(set(expected)) == 1
                else f"Edit {len(set(expected))} Tracks"
            )
            title = editor.rows["title"].editor
            assert isinstance(title, QLineEdit)
            if len(set(expected)) == 1:
                assert title.text() == expected[0].title
            editor.reject()
        if action is not LibraryDoubleClickShortcut.PLAY_NOW:
            assert playback.current_track == _CURRENT
            assert playback.current_entry_id == current_entry_id
            assert playback.position_ms == 5_000
        assert not context.library_workspace.dirty
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize("mode", IPodLibraryViewMode)
@pytest.mark.parametrize("action", LibraryDoubleClickShortcut)
def test_single_track_double_click_works_in_both_library_layouts(
    mode: IPodLibraryViewMode, action: LibraryDoubleClickShortcut
) -> None:
    context = build_context()
    context.library_workspace.load(LibrarySnapshot(_TRACKS))
    context.track_model.replace_tracks(_TRACKS)
    context.settings.set_global(IPOD_LIBRARY_VIEW_MODE, mode.value)
    context.settings.set_global(LIBRARY_DOUBLE_CLICK_SHORTCUT, action.value)
    window = MainWindow(context, auto_discover=False)
    try:
        grid = window.findChild(QAbstractItemView, "albumGrid")
        table = window.findChild(QAbstractItemView, "trackTable")
        assert grid is not None and table is not None
        grid.clicked.emit(grid.model().index(0, 0))
        table.doubleClicked.emit(QModelIndex())
        assert context.playback_controller.current_track is None
        # A double-click selects its target when it is outside the selection.
        table.doubleClicked.emit(table.model().index(1, 0))
        playback = context.playback_controller
        if action is LibraryDoubleClickShortcut.EDIT:
            editor = window.findChild(MetadataEditorDialog)
            assert editor is not None
            title = editor.rows["title"].editor
            assert isinstance(title, QLineEdit) and title.text() == "Two"
            editor.reject()
            assert playback.current_track is None
        else:
            assert playback.current_track == _TRACKS[1]
            assert playback.queue_model.entries == ()
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize("action", LibraryDoubleClickShortcut)
def test_double_click_rejects_stale_selections(
    action: LibraryDoubleClickShortcut,
) -> None:
    context = build_context()
    context.library_workspace.load(LibrarySnapshot(_TRACKS))
    context.settings.set_global(LIBRARY_DOUBLE_CLICK_SHORTCUT, action.value)
    parent = QWidget()
    actions = TrackActions(
        context.library_workspace,
        context.playback_controller,
        parent,
        settings=context.settings,
    )
    selection = TrackSelection(_TRACKS, context.library_workspace.edit_revision)
    try:
        context.library_workspace.load(LibrarySnapshot())
        with pytest.raises(ValueError):
            actions.double_click(selection)
        assert context.playback_controller.current_track is None
        assert context.playback_controller.queue_model.entries == ()
        assert parent.findChild(MetadataEditorDialog) is None
    finally:
        parent.close()
        context.shutdown()


def test_playlist_buttons_keep_explicit_actions_with_edit_preference() -> None:
    context = build_context()
    playlist = Playlist(10, "Repeated", entries=playlist_entries((1, 2, 1)))
    context.library_workspace.load(LibrarySnapshot(_TRACKS, (playlist,)))
    context.track_model.replace_tracks(_TRACKS)
    context.settings.set_global(LIBRARY_DOUBLE_CLICK_SHORTCUT, "edit")
    window = MainWindow(context, auto_discover=False)
    playback = context.playback_controller
    try:
        page = window.findChild(PlaylistPage)
        assert page is not None
        page.select_playlist(playlist.playlist_id)
        button = page.findChild(QPushButton, "queuePlaylist")
        assert button is not None and button.isEnabled()
        playback.enqueue(_TRACKS[2])
        button.click()
        assert playback.current_track == _TRACKS[2]
        assert tuple(entry.track for entry in playback.queue_model.entries) == (
            _TRACKS[0],
            _TRACKS[1],
            _TRACKS[0],
        )
        assert window.findChild(MetadataEditorDialog) is None
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize("action", LibraryDoubleClickShortcut)
@pytest.mark.parametrize("page_id", ("tracks", "albums"))
def test_mouse_double_click_retains_selection_from_before_the_first_click(
    action: LibraryDoubleClickShortcut, page_id: str
) -> None:
    context = build_context()
    snapshot = LibrarySnapshot((*_TRACKS, _CURRENT, _PENDING))
    context.library_workspace.load(snapshot)
    context.track_model.replace_tracks(snapshot.tracks)
    context.settings.set_global(LIBRARY_DOUBLE_CLICK_SHORTCUT, action.value)
    window = MainWindow(context, auto_discover=False)
    playback = context.playback_controller
    try:
        window.show()
        next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == page_id
        ).click()
        APPLICATION.processEvents()
        view = window.findChild(
            QAbstractItemView,
            "tracksTrackTable" if page_id == "tracks" else "albumGrid",
        )
        assert view is not None
        view.clearSelection()
        for row in (1, 0):
            view.selectionModel().select(
                view.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        expected = _TRACKS[:2] if page_id == "tracks" else _TRACKS
        column = TrackColumn.TITLE if page_id == "tracks" else 0
        index = view.model().index(0, column)
        point = view.visualRect(index).center()
        playback.enqueue(_CURRENT)
        playback.enqueue(_PENDING)

        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        assert playback.current_track == _CURRENT
        assert tuple(e.track for e in playback.queue_model.entries) == (_PENDING,)
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)

        assert {i.row() for i in view.selectionModel().selectedIndexes()} == {0, 1}
        queued = tuple(e.track for e in playback.queue_model.entries)
        if action is LibraryDoubleClickShortcut.ADD_TO_QUEUE:
            assert queued == (_PENDING, *expected)
        elif action is LibraryDoubleClickShortcut.PLAY_NEXT:
            assert queued == (*expected, _PENDING)
        elif action is LibraryDoubleClickShortcut.PLAY_NOW:
            assert playback.current_track == expected[0]
            assert queued == (*expected[1:], _PENDING)
        else:
            assert queued == (_PENDING,)
            editor = window.findChild(MetadataEditorDialog)
            assert editor is not None and editor.isVisible()
            assert editor.windowTitle() == f"Edit {len(expected)} Tracks"
            editor.reject()
    finally:
        window.close()
        context.shutdown()
