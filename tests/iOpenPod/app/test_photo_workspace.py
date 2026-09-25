"""Reversible Application Layer Photo drafts over the common Library interface."""

from dataclasses import replace

import pytest

from iOpenPod.app.library_workspace import LibraryWorkspace, PhotoUpdate
from iPodDB.library import (
    IPodPhotoAlbumDetails,
    LibrarySnapshot,
    Photo,
    PhotoAlbum,
    PhotoAlbumKind,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
)


def _photos() -> PhotoLibrary:
    photo = Photo(
        100,
        representations=(
            PhotoRepresentation(
                PhotoRepresentationKind.THUMBNAIL,
                1017,
                "Photos/Thumbs/F1017_1.ithmb",
                0,
                4096,
                220,
                176,
            ),
        ),
    )
    details = IPodPhotoAlbumDetails(album_type=1)
    return PhotoLibrary(
        photos=(photo,),
        albums=(
            PhotoAlbum(
                101,
                "Photo Library",
                (100,),
                PhotoAlbumKind.MASTER,
                ipod=details,
            ),
            PhotoAlbum(
                102,
                "Favorites",
                (100,),
                ipod=IPodPhotoAlbumDetails(album_type=2, previous_album_id=101),
            ),
        ),
    )


def test_workspace_exposes_and_reverses_photo_drafts_for_ui_models() -> None:
    workspace = LibraryWorkspace()
    source = LibrarySnapshot(photos=_photos())
    workspace.load(source)
    assert source.photos is not None
    assert workspace.photos is source.photos
    assert workspace.photo(100) is source.photos.photos[0]
    assert workspace.photo_album(102) is source.photos.albums[1]

    revision = workspace.edit_revision
    photo = workspace.photo(100)
    assert photo is not None
    workspace.replace_photo(
        replace(photo, rating=80),
        revision,
    )
    album = workspace.photo_album(102)
    assert album is not None
    workspace.replace_photo_album(
        replace(album, name="Sunsets", photo_ids=()),
        workspace.edit_revision,
    )

    desired = workspace.desired_snapshot()
    assert desired.photos is not None
    assert desired.photos.photos[0].rating == 80
    assert desired.photos.albums[1].name == "Sunsets"
    assert desired.photos.albums[1].photo_ids == ()
    assert workspace.dirty

    workspace.reset_changes()
    assert workspace.desired_snapshot() == source
    assert not workspace.dirty


def test_workspace_applies_photo_metadata_as_one_atomic_batch() -> None:
    workspace = LibraryWorkspace()
    photos = _photos()
    second = replace(
        photos.photos[0],
        photo_id=200,
        rating=20,
        original_date=10,
        taken_date=11,
    )
    source = replace(photos, photos=(*photos.photos, second))
    workspace.load(LibrarySnapshot(photos=source))
    starting_revision = workspace.revision
    revisions: list[int] = []

    def record_revision(_photos: PhotoLibrary | None) -> None:
        revisions.append(workspace.revision)

    workspace.photosChanged.connect(record_revision)

    workspace.apply_photo_edits(
        (
            PhotoUpdate(100, rating=80, original_date=20),
            PhotoUpdate(200, rating=80, original_date=20),
        ),
        workspace.edit_revision,
    )

    assert workspace.photos is not None
    assert tuple(
        (photo.rating, photo.original_date, photo.taken_date)
        for photo in workspace.photos.photos
    ) == ((80, 20, 0), (80, 20, 11))
    assert revisions == [starting_revision + 1]

    before = workspace.photos
    with pytest.raises(ValueError, match="ratings use 0-100"):
        workspace.apply_photo_edits(
            (PhotoUpdate(100, taken_date=30), PhotoUpdate(200, rating=101)),
            workspace.edit_revision,
        )
    assert workspace.photos is before
    assert revisions == [starting_revision + 1]


def test_workspace_creates_an_empty_photo_album_with_device_policy() -> None:
    workspace = LibraryWorkspace()
    source = LibrarySnapshot(photos=_photos())
    workspace.load(source, photo_album_creation_type=6)
    assert workspace.supports_photo_album_creation

    album = workspace.create_photo_album("  New favorites  ", workspace.edit_revision)

    assert album == PhotoAlbum(
        103,
        "New favorites",
        ipod=IPodPhotoAlbumDetails(
            album_type=6,
            previous_album_id=103,
        ),
    )
    assert workspace.photos is not None
    assert workspace.photos.albums[-1] is album
    assert workspace.dirty

    workspace.reset_changes()
    assert workspace.desired_snapshot() == source


def test_workspace_rejects_photo_album_creation_without_a_policy() -> None:
    workspace = LibraryWorkspace()
    photos = _photos()
    workspace.load(
        LibrarySnapshot(
            photos=replace(
                photos,
                albums=(photos.albums[0], replace(photos.albums[1], ipod=None)),
            )
        )
    )
    assert not workspace.supports_photo_album_creation

    with pytest.raises(ValueError, match="creation policy"):
        workspace.create_photo_album("New", workspace.edit_revision)


def test_workspace_stages_only_user_photo_album_deletion() -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(photos=_photos()))

    with pytest.raises(ValueError, match="master Photo Library"):
        workspace.remove_photo_album(101, workspace.edit_revision)

    workspace.remove_photo_album(102, workspace.edit_revision)
    desired = workspace.desired_snapshot()
    assert desired.photos is not None
    assert tuple(album.album_id for album in desired.photos.albums) == (101,)
    assert workspace.delete_omissions


def test_workspace_renames_only_a_user_photo_album() -> None:
    workspace = LibraryWorkspace()
    source = _photos()
    workspace.load(LibrarySnapshot(photos=source))

    renamed = workspace.rename_photo_album(
        102,
        "  Summer favorites  ",
        workspace.edit_revision,
    )

    assert renamed.name == "Summer favorites"
    assert renamed.photo_ids == (100,)
    assert workspace.photos is not None
    assert workspace.photos.photos == source.photos
    assert workspace.photos.albums[0] is source.albums[0]

    with pytest.raises(ValueError, match="cannot be renamed"):
        workspace.rename_photo_album(101, "Other", workspace.edit_revision)
    with pytest.raises(ValueError, match="Enter a name"):
        workspace.rename_photo_album(102, "   ", workspace.edit_revision)


def test_workspace_stages_photo_deletion_and_prunes_every_album_occurrence() -> None:
    workspace = LibraryWorkspace()
    photos = _photos()
    second = replace(photos.photos[0], photo_id=200)
    workspace.load(
        LibrarySnapshot(
            photos=replace(
                photos,
                photos=(*photos.photos, second),
                albums=(
                    replace(photos.albums[0], photo_ids=(100, 200, 100)),
                    replace(photos.albums[1], photo_ids=(100, 100, 200)),
                ),
            )
        )
    )

    workspace.remove_photos((100,), workspace.edit_revision)

    desired = workspace.desired_snapshot()
    assert desired.photos is not None
    assert tuple(photo.photo_id for photo in desired.photos.photos) == (200,)
    assert tuple(album.photo_ids for album in desired.photos.albums) == ((200,), (200,))
    assert workspace.delete_omissions

    with pytest.raises(ValueError, match="missing or repeated Photo"):
        workspace.remove_photos((200, 200), workspace.edit_revision)


def test_workspace_rejects_every_master_photo_album_edit() -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(photos=_photos()))
    master = workspace.photo_album(101)
    assert master is not None

    for edited in (
        replace(master, name="Renamed master"),
        replace(master, photo_ids=()),
        replace(master, repeat=True),
    ):
        with pytest.raises(ValueError, match="master Photo Library album is read-only"):
            workspace.replace_photo_album(edited, workspace.edit_revision)

    assert workspace.photo_album(101) is master
    assert not workspace.dirty


def test_workspace_adds_and_removes_selected_photos_from_a_user_album() -> None:
    workspace = LibraryWorkspace()
    source = _photos()
    second = replace(source.photos[0], photo_id=200)
    workspace.load(
        LibrarySnapshot(
            photos=replace(
                source,
                photos=(*source.photos, second),
                albums=(
                    source.albums[0],
                    replace(source.albums[1], photo_ids=(100, 100)),
                ),
            )
        )
    )

    workspace.set_photo_album_membership(
        102,
        (100, 200, 200),
        included=True,
        expected=workspace.edit_revision,
    )
    album = workspace.photo_album(102)
    assert album is not None and album.photo_ids == (100, 100, 200)

    workspace.set_photo_album_membership(
        102,
        (100,),
        included=False,
        expected=workspace.edit_revision,
    )
    album = workspace.photo_album(102)
    assert album is not None and album.photo_ids == (200,)


def test_workspace_rejects_invalid_photo_album_membership_edits() -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(photos=_photos()))

    with pytest.raises(ValueError, match="master Photo Library"):
        workspace.set_photo_album_membership(
            101,
            (100,),
            included=True,
            expected=workspace.edit_revision,
        )
    with pytest.raises(ValueError, match="current Library"):
        workspace.set_photo_album_membership(
            102,
            (999,),
            included=True,
            expected=workspace.edit_revision,
        )
