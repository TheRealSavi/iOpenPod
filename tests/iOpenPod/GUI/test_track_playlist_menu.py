"""Track destinations follow the sidebar's visible Playlist hierarchy."""

from collections.abc import Iterator

import pytest
from PySide6.QtWidgets import QMenu, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import build_context

from iOpenPod.GUI.widgets.track_actions import TrackActions, TrackSelection
from iPodDB.library import (
    LibrarySnapshot,
    Playlist,
    PlaylistKind,
    Track,
    playlist_entries,
)

_TRACKS = (
    Track(1, "One", "Artist", "Album", 30_000),
    Track(2, "Two", "Artist", "Album", 30_000),
)


@pytest.fixture
def actions() -> Iterator[TrackActions]:
    context = build_context()
    parent = QWidget()
    try:
        yield TrackActions(
            context.library_workspace, context.playback_controller, parent
        )
    finally:
        parent.close()
        parent.deleteLater()
        context.shutdown()


def _destinations(actions: TrackActions) -> QMenu:
    selection = TrackSelection(
        (_TRACKS[1], _TRACKS[0], _TRACKS[1]), actions.workspace.edit_revision
    )
    menu = actions.build_menu(selection)
    destinations = next(
        action for action in menu.actions() if action.text() == "Add to Playlist"
    ).menu()
    assert isinstance(destinations, QMenu)
    return destinations


@pytest.mark.parametrize(
    ("path", "destination_id"),
    (
        (("Podcasts",), 30),
        (("Road Trips", "Coast"), 21),
        (("Road Trips", "Summer", "Coast"), 22),
    ),
)
def test_destinations_filter_and_nest_playlists_with_only_leaf_actions(
    actions: TrackActions, path: tuple[str, ...], destination_id: int
) -> None:
    source = (
        Playlist(22, "Coast", parent_id=11, entries=playlist_entries((1,))),
        Playlist(1, "Podcasts", system_managed=True),
        Playlist(10, "Road Trips", PlaylistKind.FOLDER),
        Playlist(21, "Coast", parent_id=10),
        Playlist(11, "Summer", PlaylistKind.FOLDER, parent_id=10),
        Playlist(2, "Renamed Podcasts", parent_id=11, system_managed=True),
        Playlist(3, "Smart", PlaylistKind.SMART),
        Playlist(4, "Nested Smart", PlaylistKind.SMART, parent_id=10),
        Playlist(30, "Podcasts"),
        Playlist(40, "Empty Folder", PlaylistKind.FOLDER),
    )
    workspace = actions.workspace
    workspace.load(LibrarySnapshot(_TRACKS, source))
    menu = _destinations(actions)
    root = menu.actions()
    assert [action.text() for action in root] == [
        "New Playlist…",
        "",
        "Road Trips",
        "Podcasts",
        "Empty Folder",
    ]
    assert root[1].isSeparator()
    trips = root[2].menu()
    assert isinstance(trips, QMenu)
    assert [action.text() for action in trips.actions()] == ["Coast", "Summer"]
    summer = trips.actions()[1].menu()
    assert isinstance(summer, QMenu)
    assert [action.text() for action in summer.actions()] == ["Coast"]
    empty = root[4].menu()
    assert isinstance(empty, QMenu) and not empty.actions()

    for folder in (trips, summer, empty):
        folder.menuAction().trigger()
    assert workspace.playlists == source and not workspace.dirty

    for name in path[:-1]:
        submenu = next(item for item in menu.actions() if item.text() == name).menu()
        assert isinstance(submenu, QMenu)
        menu = submenu
    destination = next(item for item in menu.actions() if item.text() == path[-1])
    assert not isinstance(destination.menu(), QMenu) and destination.isEnabled()
    destination.trigger()

    for original in source:
        current = workspace.playlist(original.playlist_id)
        assert current is not None
        expected = original.track_ids
        if original.playlist_id == destination_id:
            expected += (2, 1, 2)
        assert current.track_ids == expected


@pytest.mark.parametrize(
    "playlists",
    (
        (),
        (
            Playlist(1, "Podcasts", system_managed=True),
            Playlist(2, "Smart", PlaylistKind.SMART),
        ),
    ),
)
def test_no_destinations_keeps_new_playlist_without_a_separator(
    actions: TrackActions, playlists: tuple[Playlist, ...]
) -> None:
    actions.workspace.load(LibrarySnapshot(_TRACKS, playlists))
    assert [item.text() for item in _destinations(actions).actions()] == [
        "New Playlist…"
    ]


def test_folders_can_cascade_many_levels(actions: TrackActions) -> None:
    depth = 32
    folders = tuple(
        Playlist(
            number,
            f"Folder {number}",
            PlaylistKind.FOLDER,
            parent_id=number - 1 if number else None,
        )
        for number in range(depth)
    )
    actions.workspace.load(
        LibrarySnapshot(
            _TRACKS, (*folders, Playlist(depth, "Leaf", parent_id=depth - 1))
        )
    )
    menu = _destinations(actions)
    for number in range(depth):
        submenu = next(
            item for item in menu.actions() if item.text() == f"Folder {number}"
        ).menu()
        assert isinstance(submenu, QMenu)
        menu = submenu
    assert [item.text() for item in menu.actions()] == ["Leaf"]
    menu.actions()[0].trigger()
    leaf = actions.workspace.playlist(depth)
    assert leaf is not None and leaf.track_ids == (2, 1, 2)
