"""Duplicate choices apply consistently to menus and sidebar Track drops."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QMessageBox, QPushButton, QTreeView, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.models.library_drag import TrackSelectionMimeData
from iOpenPod.app.models.playlist_tree_model import PlaylistTreeModel
from iOpenPod.GUI.widgets.playlist_tree import PlaylistTree
from iOpenPod.GUI.widgets.track_actions import TrackActions, TrackSelection
from iPodDB.library import LibrarySnapshot, Playlist, Track, playlist_entries

_TRACKS = tuple(Track(i, f"Song {i}", "Artist", "Album", 1_000) for i in (1, 2, 3))
_PLAYLIST = Playlist(10, "Destination", entries=playlist_entries((1, 1)))


@pytest.fixture
def actions() -> Iterator[TrackActions]:
    context = build_context()
    parent = QWidget()
    context.library_workspace.load(LibrarySnapshot(_TRACKS, (_PLAYLIST,)))
    try:
        yield TrackActions(
            context.library_workspace, context.playback_controller, parent
        )
    finally:
        parent.close()
        parent.deleteLater()
        context.shutdown()


def _add(actions: TrackActions, route: str, track_ids: tuple[int, ...]) -> None:
    workspace = actions.workspace
    if route == "menu":
        actions.add_to_playlist(
            TrackSelection(
                tuple(_TRACKS[i - 1] for i in track_ids), workspace.edit_revision
            ),
            10,
        )
        return
    sidebar = PlaylistTree(workspace)
    try:
        tree = sidebar.findChild(QTreeView, "playlistTree")
        toggle = sidebar.findChild(QPushButton, "playlistSectionToggle")
        assert tree is not None and toggle is not None
        model = tree.model()
        assert isinstance(model, PlaylistTreeModel)
        sidebar.resize(240, 300)
        sidebar.show()
        toggle.click()
        APPLICATION.processEvents()
        position = tree.visualRect(model.index_for_id(10)).center()
        data = TrackSelectionMimeData(workspace, track_ids)
        drop = QDropEvent(
            QPointF(position),
            Qt.DropAction.CopyAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        tree.dropEvent(drop)
    finally:
        sidebar.close()
        sidebar.deleteLater()


@pytest.mark.parametrize("route", ("menu", "drop"))
@pytest.mark.parametrize(
    ("choice", "track_ids", "expected"),
    (
        ("Add Again", (3, 1, 2, 1), (1, 1, 3, 1, 2, 1)),
        ("Skip", (3, 1, 2, 1), (1, 1, 3, 2)),
        ("Skip", (1, 1), (1, 1)),
        ("Add Again", (1, 1), (1, 1, 1, 1)),
        ("Cancel", (3, 1, 2), (1, 1)),
        ("close", (3, 1, 2), (1, 1)),
        ("none", (3, 2, 3), (1, 1, 3, 2, 3)),
    ),
)
def test_addition_choices(
    actions: TrackActions,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    choice: str,
    track_ids: tuple[int, ...],
    expected: tuple[int, ...],
) -> None:
    dialogs: list[QMessageBox] = []
    original_exec = QMessageBox.exec

    def respond(dialog: QMessageBox) -> int:
        dialogs.append(dialog)
        assert dialog.text() == (
            "Some songs are already in this playlist, would you like to add those "
            "again, or skip them?"
        )
        assert dialog.icon() == QMessageBox.Icon.Warning
        default = dialog.defaultButton()
        assert default.text() == "Skip"
        assert dialog.escapeButton() == dialog.button(QMessageBox.StandardButton.Cancel)
        assert actions.workspace.playlist(10) == _PLAYLIST
        if choice == "close":
            QTimer.singleShot(0, dialog.close)
        else:
            button = next(
                button for button in dialog.buttons() if button.text() == choice
            )
            QTimer.singleShot(0, button.click)
        return original_exec(dialog)

    monkeypatch.setattr(QMessageBox, "exec", respond)
    revision = actions.workspace.edit_revision
    _add(actions, route, track_ids)
    assert len(dialogs) == (0 if choice == "none" else 1)
    updated = actions.workspace.playlist(10)
    assert updated is not None and updated.track_ids == expected
    assert updated.entries[:2] == _PLAYLIST.entries
    assert actions.workspace.dirty == (expected != _PLAYLIST.track_ids)
    if expected == _PLAYLIST.track_ids:
        assert actions.workspace.edit_revision == revision


@pytest.mark.parametrize("route", ("menu", "drop"))
@pytest.mark.parametrize("change", ("reload", "edit", "lock", "disconnect"))
def test_prompt_cannot_apply_to_a_changed_workspace(
    actions: TrackActions,
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    change: str,
) -> None:
    workspace = actions.workspace

    def respond(dialog: QMessageBox) -> int:
        if change == "reload":
            workspace.load(LibrarySnapshot(_TRACKS, (_PLAYLIST,)))
        elif change == "edit":
            workspace.set_tracks(10, (2,))
        elif change == "lock":
            workspace.set_locked(True)
        else:
            workspace.load(None)
        next(
            button for button in dialog.buttons() if button.text() == "Add Again"
        ).click()
        return 0

    monkeypatch.setattr(QMessageBox, "exec", respond)
    if route == "menu":
        with pytest.raises(ValueError):
            _add(actions, route, (1, 3))
    else:
        _add(actions, route, (1, 3))
    updated = workspace.playlist(10)
    if change == "disconnect":
        assert updated is None
    else:
        assert updated is not None
        assert updated.track_ids == ((2,) if change == "edit" else (1, 1))
