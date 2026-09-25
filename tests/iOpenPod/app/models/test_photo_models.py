"""Tests for Photo Album and Photo grid projections."""

from dataclasses import replace

from PySide6.QtCore import Qt

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.photo_album_membership_model import (
    PhotoAlbumMembershipModel,
    PhotoAlbumMembershipRole,
    PhotoAlbumMembershipSummary,
)
from iOpenPod.app.models.photo_list_model import (
    PhotoAlbumListModel,
    PhotoAlbumRole,
    PhotoAlbumSummary,
    PhotoFilterProxyModel,
    PhotoListModel,
    PhotoRole,
    PhotoSortMode,
)
from iPodDB.library import (
    LibrarySnapshot,
    Photo,
    PhotoAlbum,
    PhotoAlbumKind,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
)


def test_photo_models_are_empty_without_a_photo_database() -> None:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot())

    albums = PhotoAlbumListModel(workspace)
    photos = PhotoListModel(workspace)

    assert albums.rowCount() == 0
    assert albums.album_at(0) is None
    assert photos.rowCount() == 0
    assert photos.photo_at(0) is None
    assert not photos.index_for_photo(10).isValid()


def test_album_model_projects_all_photos_then_user_albums_in_source_order() -> None:
    workspace = _workspace()
    model = PhotoAlbumListModel(workspace)

    assert model.rowCount() == 3
    assert tuple(model.index(row, 0).data() for row in range(3)) == (
        "All Photos",
        "Road Trip",
        "Favorites",
    )

    all_photos = model.album_at(0)
    assert all_photos == PhotoAlbumSummary(None, "All Photos", 3, True)
    assert model.index(0, 0).data(PhotoAlbumRole.SUMMARY) is all_photos
    assert model.index(0, 0).data(PhotoAlbumRole.ID) is None
    assert model.index(0, 0).data(PhotoAlbumRole.PHOTO_COUNT) == 3
    assert model.index(0, 0).data(PhotoAlbumRole.IS_ALL_PHOTOS) is True

    road_trip = model.index(1, 0)
    assert road_trip.data(PhotoAlbumRole.ID) == 201
    assert road_trip.data(PhotoAlbumRole.NAME) == "Road Trip"
    assert road_trip.data(PhotoAlbumRole.PHOTO_COUNT) == 4
    assert road_trip.data(PhotoAlbumRole.IS_ALL_PHOTOS) is False
    assert all(
        model.index(row, 0).data(PhotoAlbumRole.ID) != 200
        for row in range(model.rowCount())
    )


def test_album_membership_order_skips_missing_photos() -> None:
    model = PhotoListModel(_workspace())

    assert _photo_ids(model) == (
        10,
        20,
        30,
    )
    assert model.rows_for_photo(30) == (2,)
    assert tuple(index.row() for index in model.indexes_for_photo(30)) == (2,)

    model.set_album_id(201)

    assert model.album_id == 201
    assert _photo_ids(model) == (
        30,
        10,
        30,
    )
    assert model.rows_for_photo(30) == (0, 2)
    assert tuple(index.row() for index in model.indexes_for_photo(30)) == (0, 2)
    assert model.index_for_photo(30).row() == 0
    assert model.rows_for_photo(999) == ()
    assert model.indexes_for_photo(999) == ()
    assert not model.index_for_photo(999).isValid()

    model.set_album_id(404)
    assert model.rowCount() == 0
    assert model.rows_for_photo(30) == ()


def test_photo_model_exposes_photo_roles() -> None:
    model = PhotoListModel(_workspace())
    index = model.index(1, 0)
    photo = model.photo_at(1)

    assert photo is not None
    assert index.data(Qt.ItemDataRole.DisplayRole) == "Photo 20"
    assert index.data(PhotoRole.PHOTO) is photo
    assert index.data(PhotoRole.ID) == 20
    assert index.data(PhotoRole.RATING) == 80
    assert index.data(PhotoRole.ORIGINAL_DATE) == 1_700_000_020
    assert index.data(PhotoRole.TAKEN_DATE) == 1_700_000_120
    assert index.data(PhotoRole.FORMAT_COUNT) == 2
    assert index.data(PhotoRole.SOURCE_SIZE) == 4_096
    assert "photo 20" in str(index.data(PhotoRole.SEARCH_TEXT))
    assert "f1001_1.ithmb" in str(index.data(PhotoRole.SEARCH_TEXT))
    assert model.data(model.index(-1, 0), PhotoRole.PHOTO) is None


def test_photo_proxy_searches_paths_and_applies_explicit_sort_modes() -> None:
    source = PhotoListModel(_workspace())
    proxy = PhotoFilterProxyModel(source)

    assert _photo_ids(proxy) == (10, 20, 30)

    proxy.set_query("F1001_1.ITHMB")
    assert _photo_ids(proxy) == (20,)

    proxy.set_query("")
    proxy.set_sort_mode(PhotoSortMode.RATING)
    assert _photo_ids(proxy) == (20, 30, 10)
    assert proxy.index_for_photo(30).row() == 1

    proxy.set_sort_direction(Qt.SortOrder.DescendingOrder)
    assert _photo_ids(proxy) == (10, 30, 20)
    proxy.set_sort_direction(Qt.SortOrder.AscendingOrder)

    proxy.set_sort_mode(PhotoSortMode.DATE_TAKEN)
    assert _photo_ids(proxy) == (30, 20, 10)

    proxy.set_sort_mode(PhotoSortMode.SOURCE_ORDER)
    assert _photo_ids(proxy) == (10, 20, 30)
    proxy.set_sort_direction(Qt.SortOrder.DescendingOrder)
    assert _photo_ids(proxy) == (30, 20, 10)


def test_photo_models_refresh_after_workspace_draft_replacements() -> None:
    workspace = _workspace()
    albums = PhotoAlbumListModel(workspace)
    photos = PhotoListModel(workspace)
    photos.set_album_id(202)

    photo = workspace.photo(20)
    assert photo is not None
    workspace.replace_photo(
        replace(photo, rating=100),
        workspace.edit_revision,
    )

    assert photos.index_for_photo(20).data(PhotoRole.RATING) == 100
    assert photos.photo_at(0) is workspace.photo(20)

    album = workspace.photo_album(202)
    assert album is not None
    workspace.replace_photo_album(
        replace(album, name="Five Stars", photo_ids=(30, 10)),
        workspace.edit_revision,
    )

    assert albums.index(2, 0).data(PhotoAlbumRole.NAME) == "Five Stars"
    assert albums.index(2, 0).data(PhotoAlbumRole.PHOTO_COUNT) == 2
    assert _photo_ids(photos) == (
        30,
        10,
    )
    assert photos.rows_for_photo(20) == ()
    assert photos.rows_for_photo(30) == (0,)
    assert photos.rows_for_photo(10) == (1,)


def test_album_membership_model_projects_collages_and_bulk_check_states() -> None:
    workspace = _workspace()
    model = PhotoAlbumMembershipModel(workspace, (10, 20))

    assert model.rowCount() == 2
    road_trip = model.index(0, 0)
    summary = road_trip.data(PhotoAlbumMembershipRole.SUMMARY)
    assert summary == PhotoAlbumMembershipSummary(
        album_id=201,
        name="Road Trip",
        photo_count=4,
        preview_photo_ids=(30, 10, 0, 0),
        check_state=Qt.CheckState.PartiallyChecked,
    )
    assert road_trip.data(Qt.ItemDataRole.CheckStateRole) is (
        Qt.CheckState.PartiallyChecked
    )
    assert road_trip.flags() & Qt.ItemFlag.ItemIsUserCheckable

    favorites = model.index(1, 0)
    assert favorites.data(PhotoAlbumMembershipRole.PREVIEW_PHOTO_IDS) == (
        20,
        0,
        0,
        0,
    )
    assert favorites.data(Qt.ItemDataRole.CheckStateRole) is (
        Qt.CheckState.PartiallyChecked
    )


def test_album_membership_checking_adds_missing_photos_and_unchecking_removes_all() -> (
    None
):
    workspace = _workspace()
    model = PhotoAlbumMembershipModel(workspace, (10, 20))
    index = model.index(0, 0)

    assert model.setData(
        index,
        Qt.CheckState.Checked,
        Qt.ItemDataRole.CheckStateRole,
    )
    album = workspace.photo_album(201)
    assert album is not None and album.photo_ids == (30, 999, 10, 30, 20)
    assert model.index(0, 0).data(Qt.ItemDataRole.CheckStateRole) is (
        Qt.CheckState.Checked
    )

    assert model.setData(
        model.index(0, 0),
        Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole,
    )
    album = workspace.photo_album(201)
    assert album is not None and album.photo_ids == (30, 999, 30)
    assert model.index(0, 0).data(Qt.ItemDataRole.CheckStateRole) is (
        Qt.CheckState.Unchecked
    )


def _workspace() -> LibraryWorkspace:
    workspace = LibraryWorkspace()
    workspace.load(LibrarySnapshot(photos=_photo_library()))
    return workspace


def _photo_ids(model: PhotoListModel | PhotoFilterProxyModel) -> tuple[int, ...]:
    photos: list[int] = []
    for row in range(model.rowCount()):
        photo = model.photo_at(row)
        assert photo is not None
        photos.append(photo.photo_id)
    return tuple(photos)


def _photo_library() -> PhotoLibrary:
    photos = (
        _photo(10, rating=20, representation_count=1),
        _photo(20, rating=80, representation_count=2),
        _photo(30, rating=40, representation_count=1),
    )
    return PhotoLibrary(
        photos=photos,
        albums=(
            PhotoAlbum(
                200,
                "Photo Library",
                (10, 20, 30),
                PhotoAlbumKind.MASTER,
            ),
            PhotoAlbum(201, "Road Trip", (30, 999, 10, 30)),
            PhotoAlbum(202, "Favorites", (20,)),
        ),
    )


def _photo(
    photo_id: int,
    *,
    rating: int,
    representation_count: int,
) -> Photo:
    return Photo(
        photo_id,
        rating=rating,
        original_date=1_700_000_000 + photo_id,
        taken_date=1_700_000_100 + photo_id,
        source_size_bytes=4_096,
        representations=tuple(
            PhotoRepresentation(
                PhotoRepresentationKind.THUMBNAIL,
                1_000 + index,
                f"Photos/Thumbs/F{1_000 + index}_1.ithmb",
                index * 4_096,
                4_096,
                220,
                176,
            )
            for index in range(representation_count)
        ),
    )
