"""Photo Album drops stage only current, source-bound membership additions."""

import pytest
from PySide6.QtCore import QMimeData, QModelIndex, Qt

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.library_drag import (
    PHOTO_MIME_TYPE,
    PhotoSelectionMimeData,
    TrackSelectionMimeData,
)
from iOpenPod.app.models.photo_list_model import PhotoAlbumListModel, PhotoAlbumRole
from iPodDB.library import (
    LibrarySnapshot,
    Photo,
    PhotoAlbum,
    PhotoAlbumKind,
    PhotoLibrary,
)


def _workspace() -> LibraryWorkspace:
    workspace = LibraryWorkspace()
    workspace.load(
        LibrarySnapshot(
            photos=PhotoLibrary(
                photos=(Photo(10), Photo(20), Photo(30)),
                albums=(
                    PhotoAlbum(
                        100, "Photo Library", (10, 20, 30), PhotoAlbumKind.MASTER
                    ),
                    PhotoAlbum(101, "Source", (30, 10, 20)),
                    PhotoAlbum(102, "Destination", (20, 20)),
                ),
            )
        )
    )
    return workspace


def test_drop_adds_missing_photos_in_selection_order_as_one_draft_edit() -> None:
    workspace = _workspace()
    original = workspace.snapshot
    model = PhotoAlbumListModel(workspace)
    data = PhotoSelectionMimeData(workspace, (30, 20, 10, 30))
    revisions: list[object] = []
    workspace.photosChanged.connect(revisions.append)
    target = model.index(2, 0)

    assert target.flags() & Qt.ItemFlag.ItemIsDropEnabled
    assert not model.index(0, 0).flags() & Qt.ItemFlag.ItemIsDropEnabled
    assert not model.flags(QModelIndex()) & Qt.ItemFlag.ItemIsDropEnabled
    assert model.canDropMimeData(data, Qt.DropAction.CopyAction, -1, -1, target)
    assert model.dropMimeData(data, Qt.DropAction.CopyAction, -1, -1, target)

    album = workspace.photo_album(102)
    assert album is not None and album.photo_ids == (20, 20, 30, 10)
    assert model.index(2, 0).data(PhotoAlbumRole.PHOTO_COUNT) == 4
    assert len(revisions) == 1
    assert workspace.snapshot is original
    assert original is not None and original.photos is not None
    assert workspace.photos is not None
    assert workspace.photos.photos == original.photos.photos
    assert workspace.photos.albums[:2] == original.photos.albums[:2]


def test_dropping_existing_members_is_an_accepted_no_op() -> None:
    workspace = _workspace()
    model = PhotoAlbumListModel(workspace)
    revision = workspace.edit_revision

    assert model.dropMimeData(
        PhotoSelectionMimeData(workspace, (20, 20)),
        Qt.DropAction.CopyAction,
        -1,
        0,
        model.index(2, 0),
    )

    assert workspace.edit_revision == revision
    album = workspace.photo_album(102)
    assert album is not None and album.photo_ids == (20, 20)


@pytest.mark.parametrize(
    "invalid",
    [
        "external",
        "tracks",
        "empty",
        "missing",
        "foreign",
        "stale",
        "reloaded",
        "locked",
    ],
)
def test_invalid_photo_drags_cannot_change_membership(invalid: str) -> None:
    workspace = _workspace()
    model = PhotoAlbumListModel(workspace)
    data: QMimeData = PhotoSelectionMimeData(workspace, (10, 30))
    if invalid == "external":
        data = QMimeData()
        data.setData(PHOTO_MIME_TYPE, b"selection")
    elif invalid == "tracks":
        data = TrackSelectionMimeData(workspace, (10,))
    elif invalid == "empty":
        data = PhotoSelectionMimeData(workspace, ())
    elif invalid == "missing":
        data = PhotoSelectionMimeData(workspace, (10, 999))
    elif invalid == "foreign":
        data = PhotoSelectionMimeData(_workspace(), (10, 30))
    elif invalid == "stale":
        workspace.rename_photo_album(101, "Renamed", workspace.edit_revision)
    elif invalid == "reloaded":
        workspace.load(workspace.snapshot)
    elif invalid == "locked":
        workspace.set_locked(True)
        assert not model.index(2, 0).flags() & Qt.ItemFlag.ItemIsDropEnabled
    before = workspace.desired_snapshot()
    revision = workspace.edit_revision
    target = model.index(2, 0)

    assert not model.canDropMimeData(data, Qt.DropAction.CopyAction, -1, -1, target)
    assert not model.dropMimeData(data, Qt.DropAction.CopyAction, -1, -1, target)
    assert workspace.desired_snapshot() == before
    assert workspace.edit_revision == revision


@pytest.mark.parametrize(
    ("action", "row", "column", "target_row"),
    [
        (Qt.DropAction.MoveAction, -1, -1, 2),
        (Qt.DropAction.IgnoreAction, -1, -1, 2),
        (Qt.DropAction.CopyAction, 0, -1, 2),
        (Qt.DropAction.CopyAction, -1, 1, 2),
        (Qt.DropAction.CopyAction, -1, -1, 0),
        (Qt.DropAction.CopyAction, -1, -1, -1),
    ],
)
def test_only_drops_onto_user_albums_can_add_membership(
    action: Qt.DropAction, row: int, column: int, target_row: int
) -> None:
    workspace = _workspace()
    model = PhotoAlbumListModel(workspace)
    revision = workspace.edit_revision
    data = PhotoSelectionMimeData(workspace, (10,))
    target = model.index(target_row, 0)

    assert not model.canDropMimeData(data, action, row, column, target)
    assert not model.dropMimeData(data, action, row, column, target)
    assert workspace.edit_revision == revision


def test_drop_revalidates_when_saving_starts_after_hover() -> None:
    workspace = _workspace()
    model = PhotoAlbumListModel(workspace)
    data = PhotoSelectionMimeData(workspace, (10,))
    target = model.index(2, 0)
    revision = workspace.edit_revision
    assert model.canDropMimeData(data, Qt.DropAction.CopyAction, -1, -1, target)
    workspace.set_locked(True)

    assert not model.dropMimeData(data, Qt.DropAction.CopyAction, -1, -1, target)
    assert workspace.edit_revision == revision

    workspace.set_locked(False)
    assert model.dropMimeData(data, Qt.DropAction.CopyAction, -1, -1, target)
