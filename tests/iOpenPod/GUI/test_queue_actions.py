"""Queue actions share icons and preserve the selected Track occurrences."""

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.playback_controller import PlaybackController
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.playback_pane import PlaybackPane
from iOpenPod.GUI.widgets.track_actions import TrackActions, TrackSelection
from iPodDB.library import LibrarySnapshot, Track, TrackMetadata


def test_history_clear_button_empties_the_tab_without_changing_playback() -> None:
    context = build_context()
    controller = context.playback_controller
    artwork = ArtworkPixmapProvider(context.artwork_controller)
    pane = PlaybackPane(
        controller, context.lyrics_controller, context.theme_manager, artwork
    )
    pane.resize(pane.width(), 500)
    pane.show()
    try:
        tabs = pane.findChild(QTabWidget, "playbackTabs")
        button = pane.findChild(QPushButton, "playbackClearHistory")
        stack = pane.findChild(QStackedWidget, "playbackHistoryStack")
        assert tabs is not None and button is not None and stack is not None
        tabs.setCurrentIndex(1)
        APPLICATION.processEvents()
        assert button.isVisible()
        assert button.text() == "Clear History"
        assert not button.isEnabled()
        current, pending = (
            Track(i, f"Track {i}", "Artist", "Album", 30_000) for i in range(2)
        )
        controller.insert_tracks((current, pending), 0)
        controller.seek(5_000)
        assert button.isEnabled()
        history_view = stack.currentWidget()
        assert history_view is not None
        assert history_view.objectName() == "playbackHistoryView"

        button.click()

        assert controller.history_model.entries == ()
        assert not button.isEnabled()
        empty_state = stack.currentWidget()
        assert empty_state is not None
        assert any(
            label.text() == "History is empty"
            for label in empty_state.findChildren(QLabel)
        )
        assert controller.current_track == current
        assert controller.playing
        assert controller.position_ms == 5_000
        assert tuple(entry.track for entry in controller.queue_model.entries) == (
            pending,
        )

        controller.next()
        assert button.isEnabled()
        assert stack.currentWidget() is history_view
    finally:
        pane.close()
        context.shutdown()
        pane.deleteLater()
        artwork.deleteLater()
        APPLICATION.processEvents()


@pytest.mark.parametrize("action_name", ("Play Next", "Add to Queue"))
def test_menu_queue_actions_keep_order_duplicates_and_current_track(
    action_name: str,
) -> None:
    tracks = tuple(Track(i, f"Track {i}", "Artist", "Album", 30_000) for i in range(4))
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(tracks))
    controller = PlaybackController(FakePlaybackBackend())
    parent = QWidget()
    actions = TrackActions(workspace, controller, parent)
    selection = TrackSelection(
        (tracks[2], tracks[3], tracks[2]), workspace.edit_revision
    )
    controller.enqueue(tracks[0])
    controller.enqueue(tracks[1])
    controller.seek(10_000)
    menu = actions.build_menu(selection)
    try:
        items = menu.actions()
        next_action = next(a for a in items if a.text() == "Play Next")
        last_action = next(a for a in items if a.text() == "Add to Queue")
        assert items.index(next_action) + 1 == items.index(last_action)
        assert next_action.isIconVisibleInMenu() and last_action.isIconVisibleInMenu()
        assert next_action.icon().pixmap(QSize(18, 18)).toImage() != (
            last_action.icon().pixmap(QSize(18, 18)).toImage()
        )

        next(a for a in items if a.text() == action_name).trigger()

        expected = (
            (*selection.tracks, tracks[1])
            if action_name == "Play Next"
            else (tracks[1], *selection.tracks)
        )
        assert (
            tuple(entry.track for entry in controller.queue_model.entries) == expected
        )
        assert controller.current_track == tracks[0]
        assert controller.position_ms == 10_000
        assert not workspace.dirty
    finally:
        controller.shutdown()
        parent.close()
        parent.deleteLater()
        APPLICATION.processEvents()


@pytest.mark.parametrize("action_name", ("Play Next", "Add to Queue", "Double-click"))
@pytest.mark.parametrize(
    ("view_name", "expected_ids"),
    (
        ("albumGrid", (1, 2, 3, 4, 5, 6)),
        ("artistsCollectionGrid", (1, 2, 3, 4, 5, 6, 7)),
        ("genresCollectionGrid", (1, 2, 3, 4, 5, 6, 7)),
        ("artistsCollectionList", (1, 2, 3, 4, 5, 6, 7)),
        ("genresCollectionList", (1, 2, 3, 4, 5, 6, 7)),
    ),
)
def test_group_queue_actions_use_album_disc_track_and_title_order(
    action_name: str, view_name: str, expected_ids: tuple[int, ...]
) -> None:
    tracks = tuple(
        Track(
            track_id,
            title,
            "Artist",
            album,
            30_000,
            genre="Genre",
            track_number=number,
            metadata=TrackMetadata(disc_number=disc),
        )
        for track_id, album, disc, number, title in reversed(
            (
                (1, "alpha", 1, 1, "Zebra"),
                (2, "alpha", 1, 2, "alpha"),
                (3, "ALPHA", 1, 2, "Zulu"),
                (4, "alpha", 1, 10, "Early"),
                (5, "alpha", 2, 1, "Start"),
                (6, "alpha", 10, 1, "Start"),
                (7, "Zulu", 0, 0, "First"),
            )
        )
    )
    current = Track(8, "Playing", "Other", "Other", 30_000, genre="Other")
    pending = Track(9, "Pending", "Other", "Other", 30_000, genre="Other")
    context = build_context()
    snapshot = LibrarySnapshot((*tracks, current, pending))
    context.library_workspace.load(snapshot)
    context.track_model.replace_tracks(snapshot.tracks)
    window = MainWindow(context, auto_discover=False)
    controller = context.playback_controller
    controller.enqueue(current)
    controller.enqueue(pending)
    try:
        window.show()
        APPLICATION.processEvents()
        actions = window.findChild(TrackActions)
        view = window.findChild(QAbstractItemView, view_name)
        assert actions is not None and view is not None
        index = view.model().index(0, 0)
        view.setCurrentIndex(index)
        if action_name == "Double-click":
            view.doubleClicked.emit(index)
        else:
            menu = actions.build_menu(actions.selection(view))
            next(
                action for action in menu.actions() if action.text() == action_name
            ).trigger()

        queued_ids = tuple(
            entry.track.track_id for entry in controller.queue_model.entries
        )
        assert queued_ids == (
            (*expected_ids, pending.track_id)
            if action_name == "Play Next"
            else (pending.track_id, *expected_ids)
        )
        assert controller.current_track == current
        assert context.library_workspace.tracks == snapshot.tracks
        assert not context.library_workspace.dirty
    finally:
        window.close()
        context.shutdown()


def test_play_next_rejects_a_stale_selection_and_disables_empty_selection() -> None:
    track = Track(1, "Track", "Artist", "Album", 30_000)
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot((track,)))
    controller = PlaybackController(FakePlaybackBackend())
    parent = QWidget()
    actions = TrackActions(workspace, controller, parent)
    selection = TrackSelection((track,), workspace.edit_revision)
    try:
        workspace.load(LibrarySnapshot())
        with pytest.raises(ValueError, match="Library changed"):
            actions.play_next(selection)
        assert controller.current_track is None
        assert controller.queue_model.entries == ()
        menu = actions.build_menu(TrackSelection((), workspace.edit_revision))
        for name in ("Play Next", "Add to Queue"):
            assert not next(a for a in menu.actions() if a.text() == name).isEnabled()
    finally:
        controller.shutdown()
        parent.close()
        parent.deleteLater()
        APPLICATION.processEvents()
