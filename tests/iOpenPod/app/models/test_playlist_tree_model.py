"""Playlist hierarchy and drag lifetime behavior."""

import pytest
from PySide6.QtCore import QMimeData, QModelIndex, Qt

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.playlist_tree_model import PlaylistRole, PlaylistTreeModel
from iPodDB.library import LibrarySnapshot, Playlist, PlaylistKind


def _workspace() -> LibraryWorkspace:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            playlists=(
                Playlist(0, "Road Trips", PlaylistKind.FOLDER),
                Playlist(1, "Summer", PlaylistKind.FOLDER, parent_id=0),
                Playlist(2, "Coast", parent_id=1),
                Playlist(3, "Favorites", PlaylistKind.SMART),
                Playlist(4, "Evening"),
            ),
        )
    )
    return workspace


def test_tree_exposes_names_kinds_and_parent_relationships() -> None:
    model = PlaylistTreeModel(_workspace())
    assert model.rowCount() == 3
    assert model.columnCount() == 1
    folder = model.index(0, 0)
    nested = model.index(0, 0, folder)
    leaf = model.index(0, 0, nested)
    assert folder.data() == "Road Trips"
    assert model.playlist_id(folder) == 0
    assert nested.data() == "Summer"
    assert leaf.data() == "Coast"
    assert leaf.parent() == nested
    assert nested.parent() == folder
    assert not folder.parent().isValid()
    assert model.rowCount(leaf) == 0
    assert model.index_for_id(2) == leaf
    assert not model.index_for_id(999).isValid()
    assert not model.index(0, 1).isValid()
    assert not model.index(100, 0).isValid()
    assert model.index(1, 0).data(PlaylistRole.KIND) == PlaylistKind.SMART
    assert model.flags(folder) & Qt.ItemFlag.ItemIsDropEnabled
    assert model.flags(leaf) & Qt.ItemFlag.ItemIsDropEnabled
    assert model.flags(QModelIndex()) & Qt.ItemFlag.ItemIsDropEnabled


def test_tree_hides_system_managed_playlist_without_removing_it_from_workspace() -> (
    None
):
    workspace = _workspace()
    podcasts = Playlist(5, "Not named Podcasts", system_managed=True)
    snapshot = workspace.snapshot
    assert snapshot is not None
    workspace.load(
        LibrarySnapshot(
            playlists=(*snapshot.playlists, podcasts),
        )
    )

    model = PlaylistTreeModel(workspace)

    assert model.rowCount() == 3
    assert not model.index_for_id(podcasts.playlist_id).isValid()
    retained = workspace.playlist(podcasts.playlist_id)
    assert retained is not None and retained.system_managed


def test_tree_has_no_python_recursion_limit_for_nested_folders() -> None:
    depth = 2_000
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            playlists=tuple(
                Playlist(
                    number,
                    f"Folder {number}",
                    PlaylistKind.FOLDER,
                    parent_id=number - 1 if number else None,
                )
                for number in range(depth)
            )
        )
    )
    model = PlaylistTreeModel(workspace)
    parent = QModelIndex()
    for number in range(depth):
        assert model.rowCount(parent) == 1
        index = model.index(0, 0, parent)
        assert model.playlist_id(index) == number
        assert index.parent() == parent
        parent = index
    assert model.rowCount(parent) == 0


def test_drag_moves_a_playlist_into_a_folder_and_back_to_root() -> None:
    workspace = _workspace()
    model = PlaylistTreeModel(workspace)
    drag = model.mimeData([model.index_for_id(4)])
    assert model.dropMimeData(
        drag, Qt.DropAction.MoveAction, -1, -1, model.index_for_id(1)
    )
    assert model.index_for_id(4).parent() == model.index_for_id(1)
    assert workspace.dirty
    drag = model.mimeData([model.index_for_id(4)])
    assert model.dropMimeData(drag, Qt.DropAction.MoveAction, -1, 0, QModelIndex())
    assert not model.index_for_id(4).parent().isValid()
    assert not workspace.dirty


@pytest.mark.parametrize("source,target", [(0, 1), (0, 0), (4, 2), (4, 4)])
def test_drag_rejects_cycles_self_and_nonfolder_targets(
    source: int, target: int
) -> None:
    workspace = _workspace()
    model = PlaylistTreeModel(workspace)
    drag = model.mimeData([model.index_for_id(source)])
    assert not model.canDropMimeData(
        drag, Qt.DropAction.MoveAction, -1, -1, model.index_for_id(target)
    )
    assert not model.dropMimeData(
        drag, Qt.DropAction.MoveAction, -1, -1, model.index_for_id(target)
    )
    assert not workspace.dirty


def test_drag_rejects_another_model_and_a_reloaded_library() -> None:
    workspace = _workspace()
    model = PlaylistTreeModel(workspace)
    other_model = PlaylistTreeModel(workspace)
    drag = model.mimeData([model.index_for_id(4)])
    assert not other_model.canDropMimeData(
        drag, Qt.DropAction.MoveAction, -1, -1, other_model.index_for_id(1)
    )
    workspace.load(workspace.snapshot)
    assert not model.dropMimeData(
        drag, Qt.DropAction.MoveAction, -1, -1, model.index_for_id(1)
    )
    assert not workspace.dirty


def test_drag_rejects_stale_revision_indexes_and_unknown_data() -> None:
    workspace = _workspace()
    model = PlaylistTreeModel(workspace)
    old_index = model.index_for_id(4)
    drag = model.mimeData([old_index])
    workspace.move(3, 0)
    assert not model.dropMimeData(
        drag, Qt.DropAction.MoveAction, -1, -1, model.index_for_id(1)
    )
    assert model.playlist_id(old_index) is None
    assert not model.mimeData([old_index]).formats()
    assert not model.mimeData([model.index_for_id(3), model.index_for_id(4)]).formats()
    malformed = QMimeData()
    malformed.setData(model.mimeTypes()[0], b"invalid")
    assert not model.dropMimeData(
        malformed, Qt.DropAction.MoveAction, -1, -1, model.index_for_id(1)
    )


def test_drag_rejects_copy_and_invalid_drop_coordinates() -> None:
    model = PlaylistTreeModel(_workspace())
    drag = model.mimeData([model.index_for_id(4)])
    folder = model.index_for_id(1)
    assert not model.dropMimeData(drag, Qt.DropAction.CopyAction, -1, -1, folder)
    assert not model.dropMimeData(drag, Qt.DropAction.MoveAction, 500, 0, folder)
    assert not model.dropMimeData(drag, Qt.DropAction.MoveAction, -2, 0, folder)
    assert not model.dropMimeData(drag, Qt.DropAction.MoveAction, -1, 1, folder)


def test_tree_rejects_indexes_owned_by_another_model() -> None:
    workspace = _workspace()
    model = PlaylistTreeModel(workspace)
    other = PlaylistTreeModel(workspace)
    foreign_index = other.index_for_id(1)
    assert model.rowCount(foreign_index) == 0
    assert model.data(foreign_index) is None
    assert not model.index(0, 0, foreign_index).isValid()
    drag = model.mimeData([model.index_for_id(4)])
    assert not model.dropMimeData(drag, Qt.DropAction.MoveAction, -1, 0, foreign_index)


def test_full_uint64_id_survives_qt_roles_and_internal_drag() -> None:
    playlist = Playlist(0xFFFFFFFFFFFFFFFF, "Large Playlist")
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            playlists=(Playlist(0, "Folder", PlaylistKind.FOLDER), playlist)
        )
    )
    model = PlaylistTreeModel(workspace)
    index = model.index_for_id(playlist.playlist_id)
    assert index.data(PlaylistRole.PLAYLIST) == playlist
    assert model.playlist_id(index) == playlist.playlist_id
    drag = model.mimeData([index])
    assert model.dropMimeData(
        drag, Qt.DropAction.MoveAction, -1, -1, model.index_for_id(0)
    )
    assert model.index_for_id(playlist.playlist_id).parent() == model.index_for_id(0)


def test_track_drops_append_occurrences_and_reject_stale_or_nonregular_targets() -> (
    None
):
    from iOpenPod.app.models.library_drag import TrackSelectionMimeData
    from iPodDB.library import Track

    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            tracks=(Track(1, "Song", "Artist", "Album", 1000),),
            playlists=(
                Playlist(10, "Regular"),
                Playlist(11, "Folder", PlaylistKind.FOLDER),
                Playlist(12, "Smart", PlaylistKind.SMART),
            ),
        )
    )
    model = PlaylistTreeModel(workspace)
    data = TrackSelectionMimeData(workspace, (1, 1))
    for target in (11, 12):
        assert not model.canDropMimeData(
            data, Qt.DropAction.CopyAction, -1, 0, model.index_for_id(target)
        )
    assert model.dropMimeData(
        data, Qt.DropAction.CopyAction, -1, 0, model.index_for_id(10)
    )
    playlist = workspace.playlist(10)
    assert playlist is not None and playlist.track_ids == (1, 1)
    assert playlist.entries[0].entry_id != playlist.entries[1].entry_id
    assert not model.dropMimeData(
        data, Qt.DropAction.CopyAction, -1, 0, model.index_for_id(10)
    )
    assert not model.canDropMimeData(
        TrackSelectionMimeData(_workspace(), (1,)),
        Qt.DropAction.CopyAction,
        -1,
        0,
        model.index_for_id(10),
    )
