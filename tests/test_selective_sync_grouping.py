from types import SimpleNamespace
from typing import Any, cast

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QPushButton, QScrollArea, QTableWidget

import iopenpod.gui.widgets.selectiveSyncBrowser as selective_sync_browser_module
from iopenpod.gui.styles import accent_btn_css
from iopenpod.gui.widgets.MBGridView import GridRecord, MusicBrowserGrid
from iopenpod.gui.widgets.photoTile import PhotoGridTile
from iopenpod.gui.widgets.selectiveSyncBrowser import (
    PCMusicBrowserGrid,
    PCPhotoListView,
    PCTrackListView,
    SelectiveSyncBrowser,
)
from iopenpod.gui.widgets.syncReview import StorageBarWidget
from iopenpod.sync.contracts import SyncAction, SyncItem, SyncPlan
from iopenpod.sync.pc_library import PCTrack
from iopenpod.sync.photos import (
    PCPhoto,
    PhotoAlbumChange,
    PhotoMembershipChange,
    PhotoSyncItem,
    PhotoSyncPlan,
)


def _track(
    title: str,
    relative_path: str,
    *,
    artist: str = "Unknown Artist",
    album: str = "Unknown Album",
    album_artist: str | None = None,
    is_video: bool = False,
    video_kind: str = "",
) -> PCTrack:
    extension = "." + relative_path.rsplit(".", 1)[-1].lower()
    return PCTrack(
        path=f"/music/{relative_path}",
        relative_path=relative_path,
        filename=relative_path.rsplit("/", 1)[-1],
        extension=extension,
        mtime=0,
        size=1,
        title=title,
        artist=artist,
        album=album,
        album_artist=album_artist,
        genre=None,
        year=None,
        track_number=None,
        track_total=None,
        disc_number=None,
        disc_total=None,
        duration_ms=1000,
        bitrate=None,
        sample_rate=None,
        rating=None,
        is_video=is_video,
        video_kind=video_kind,
    )


def _browser_with_tracks(tracks: list[PCTrack]) -> SelectiveSyncBrowser:
    browser = SelectiveSyncBrowser.__new__(SelectiveSyncBrowser)
    browser._all_tracks = tracks
    browser._playlist_discovery = None
    browser._groups = {}
    browser._buckets = {}
    browser._selected_tracks = {}
    browser._selected_photos = {}
    browser._selected_playlists = {}
    browser._grids = {}
    browser._grid_loaded = set()
    def _art_candidates(track_list: list) -> list[str]:
        return []

    browser._art_candidates = _art_candidates
    return browser


def _check_state_at(table: QTableWidget, row: int) -> Qt.CheckState:
    item = table.item(row, 0)
    assert item is not None
    return item.checkState()


def _set_check_state_at(
    table: QTableWidget,
    row: int,
    check_state: Qt.CheckState,
) -> None:
    item = table.item(row, 0)
    assert item is not None
    item.setCheckState(check_state)


def _photo_record_key_at(view: PCPhotoListView, index: int) -> object:
    record = view._photo_grid.recordAt(index)
    assert record is not None
    return record.key


def _photo_checkbox_at(view: PCPhotoListView, index: int) -> QCheckBox:
    tile = view._photo_grid._visible_widgets[index]
    assert isinstance(tile, PhotoGridTile)
    checkbox = tile.checkbox
    assert checkbox is not None
    return checkbox


def test_selective_sync_photo_search_matches_symbol_variants() -> None:
    photo = PCPhoto(
        visual_hash="hash",
        display_name="John’s Photo.jpg",
        source_path="/photos/John’s Photo.jpg",
        size=1,
    )
    view = SimpleNamespace(_search_query="john's")

    assert PCPhotoListView._matches_search(cast(Any, view), photo)


def test_done_selecting_uses_standard_primary_action_style(qtbot) -> None:
    settings = SimpleNamespace(track_list_columns_by_content={})
    browser = SelectiveSyncBrowser(
        settings_service=cast(
            Any,
            SimpleNamespace(
                get_global_settings=lambda: settings,
                get_effective_settings=lambda: settings,
            ),
        ),
        device_sessions=cast(
            Any,
            SimpleNamespace(current_session=lambda: None),
        ),
    )
    qtbot.addWidget(browser)

    assert browser._done_btn.styleSheet() == accent_btn_css()


def test_selective_sync_track_list_sorts_checkboxes_by_selected_state(qtbot) -> None:
    settings = SimpleNamespace(track_list_columns_by_content={})
    view = PCTrackListView(
        settings_service=cast(
            Any,
            SimpleNamespace(
                get_global_settings=lambda: settings,
                get_effective_settings=lambda: settings,
            ),
        ),
        device_sessions=cast(
            Any,
            SimpleNamespace(current_session=lambda: None),
        ),
    )
    qtbot.addWidget(view)
    tracks = [
        _track("Selected 1", "Album/Selected 1.mp3"),
        _track("Unselected", "Album/Unselected.mp3"),
        _track("Selected 2", "Album/Selected 2.mp3"),
    ]
    view.setTracks(
        tracks,
        {
            tracks[0].path: True,
            tracks[1].path: False,
            tracks[2].path: True,
        },
    )
    table = view._browser_list.table
    qtbot.waitUntil(
        lambda: table.rowCount() == 3
        and all(table.item(row, 0) is not None for row in range(3))
    )

    table.sortItems(0, Qt.SortOrder.DescendingOrder)
    assert [_check_state_at(table, row) for row in range(3)] == [
        Qt.CheckState.Checked,
        Qt.CheckState.Checked,
        Qt.CheckState.Unchecked,
    ]

    _set_check_state_at(table, 0, Qt.CheckState.Unchecked)
    qtbot.waitUntil(
        lambda: [_check_state_at(table, row) for row in range(3)]
        == [
            Qt.CheckState.Checked,
            Qt.CheckState.Unchecked,
            Qt.CheckState.Unchecked,
        ]
    )


def test_selective_sync_track_list_bulk_changes_all_sorted_checkboxes(qtbot) -> None:
    settings = SimpleNamespace(track_list_columns_by_content={})
    view = PCTrackListView(
        settings_service=cast(
            Any,
            SimpleNamespace(
                get_global_settings=lambda: settings,
                get_effective_settings=lambda: settings,
            ),
        ),
        device_sessions=cast(
            Any,
            SimpleNamespace(current_session=lambda: None),
        ),
    )
    qtbot.addWidget(view)
    tracks = [
        _track("Selected 1", "Album/Selected 1.mp3"),
        _track("Unselected 1", "Album/Unselected 1.mp3"),
        _track("Selected 2", "Album/Selected 2.mp3"),
        _track("Unselected 2", "Album/Unselected 2.mp3"),
    ]
    view.setTracks(
        tracks,
        {
            tracks[0].path: True,
            tracks[1].path: False,
            tracks[2].path: True,
            tracks[3].path: False,
        },
    )
    table = view._browser_list.table
    qtbot.waitUntil(
        lambda: table.rowCount() == 4
        and all(table.item(row, 0) is not None for row in range(4))
    )
    table.sortItems(0, Qt.SortOrder.DescendingOrder)

    view.setAllChecked(False)

    assert all(
        _check_state_at(table, row) == Qt.CheckState.Unchecked
        for row in range(table.rowCount())
    )

    view.setAllChecked(True)

    assert all(
        _check_state_at(table, row) == Qt.CheckState.Checked
        for row in range(table.rowCount())
    )


def test_photo_picker_group_by_selected_toggle_controls_its_grid(qtbot) -> None:
    view = PCPhotoListView()
    qtbot.addWidget(view)
    toggle = view._grid_header.findChild(QPushButton, "gridGroupBySelectedButton")

    assert toggle is not None and not toggle.isHidden()
    assert toggle.isChecked()
    assert view._photo_grid.isGroupedBySelected()
    toggle.click()

    assert not view._photo_grid.isGroupedBySelected()


def test_photo_picker_moves_clicked_items_between_selection_sections(qtbot) -> None:
    view = PCPhotoListView()
    qtbot.addWidget(view)
    view.resize(1000, 700)
    view.show()
    photos = [
        PCPhoto("a", "Alpha", source_path="/photos/alpha.jpg", size=1),
        PCPhoto("b", "Bravo", source_path="/photos/bravo.jpg", size=1),
        PCPhoto("c", "Charlie", source_path="/photos/charlie.jpg", size=1),
        PCPhoto("d", "Delta", source_path="/photos/delta.jpg", size=1),
    ]
    selection = {
        photos[0].source_path: False,
        photos[1].source_path: True,
        photos[2].source_path: False,
        photos[3].source_path: True,
    }
    view.setPhotos(photos, selection)
    view._photo_grid.setGroupBySelected(True)
    qtbot.waitUntil(lambda: len(view._photo_grid.gridItems) == 4, timeout=2000)

    assert [
        _photo_record_key_at(view, index)
        for index in range(view._photo_grid.count())
    ] == [
        photos[1].source_path,
        photos[3].source_path,
        photos[0].source_path,
        photos[2].source_path,
    ]

    delta_index = next(
        index
        for index in range(view._photo_grid.count())
        if _photo_record_key_at(view, index) == photos[3].source_path
    )
    _photo_checkbox_at(view, delta_index).click()

    qtbot.waitUntil(
        lambda: [
            _photo_record_key_at(view, index)
            for index in range(view._photo_grid.count())
        ]
        == [
            photos[1].source_path,
            photos[0].source_path,
            photos[2].source_path,
            photos[3].source_path,
        ],
        timeout=2000,
    )
    assert selection[photos[3].source_path] is False


def test_plan_photo_picker_moves_clicked_items_between_selection_sections(qtbot) -> None:
    settings = SimpleNamespace(track_list_columns_by_content={})
    browser = SelectiveSyncBrowser(
        settings_service=cast(
            Any,
            SimpleNamespace(
                get_global_settings=lambda: settings,
                get_effective_settings=lambda: settings,
            ),
        ),
        device_sessions=cast(
            Any,
            SimpleNamespace(current_session=lambda: None),
        ),
    )
    qtbot.addWidget(browser)
    browser.resize(1000, 700)
    browser.show()
    photos = [
        PhotoSyncItem("a", "Alpha", source_path="/photos/alpha.jpg"),
        PhotoSyncItem("b", "Bravo", source_path="/photos/bravo.jpg"),
        PhotoSyncItem("c", "Charlie", source_path="/photos/charlie.jpg"),
        PhotoSyncItem("d", "Delta", source_path="/photos/delta.jpg"),
    ]
    photo_plan = PhotoSyncPlan()
    photo_plan.photos_to_add = photos
    browser.load_sync_plan(
        SyncPlan(photo_plan=photo_plan),
        {"photos_to_add": {id(photos[1]), id(photos[3])}},
    )
    view = browser._photo_list
    view._photo_grid.setGroupBySelected(True)
    qtbot.waitUntil(lambda: len(view._photo_grid.gridItems) == 4, timeout=2000)

    assert [
        _photo_record_key_at(view, index)
        for index in range(view._photo_grid.count())
    ] == [
        photos[1].source_path,
        photos[3].source_path,
        photos[0].source_path,
        photos[2].source_path,
    ]

    delta_index = next(
        index
        for index in range(view._photo_grid.count())
        if _photo_record_key_at(view, index) == photos[3].source_path
    )
    _photo_checkbox_at(view, delta_index).click()

    qtbot.waitUntil(
        lambda: [
            _photo_record_key_at(view, index)
            for index in range(view._photo_grid.count())
        ]
        == [
            photos[1].source_path,
            photos[0].source_path,
            photos[2].source_path,
            photos[3].source_path,
        ],
        timeout=2000,
    )
    assert photos[3].source_path not in browser._selected_photos or not browser._selected_photos[photos[3].source_path]
    assert id(photos[3]) not in browser._plan_selection_state["photos_to_add"]


def test_pc_category_grid_groups_selected_partial_and_unselected_records(qtbot) -> None:
    grid = PCMusicBrowserGrid()
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(grid)
    grid.attachScrollArea(scroll)
    qtbot.addWidget(scroll)
    scroll.resize(920, 620)
    scroll.show()
    states = {
        "Alpha Partial": "Partially Selected",
        "Bravo Selected": "Selected",
        "Charlie Unselected": "Unselected",
    }
    grid.setSelectionSectionResolver(lambda item: states[str(item["title"])])
    grid._set_source_items(
        [
            {
                "title": title,
                "album": title,
                "category": "Albums",
                "filter_key": "album",
                "filter_value": title,
            }
            for title in states
        ],
        reset_scroll=False,
    )

    grid.setGroupBySelected(True)
    qtbot.waitUntil(
        lambda: all(
            not header.isHidden()
            for header in grid._section_headers.values()
        ),
        timeout=2000,
    )

    assert [record.title for record in grid._visible_records] == [
        "Bravo Selected",
        "Alpha Partial",
        "Charlie Unselected",
    ]
    assert list(grid._section_headers) == [
        "Selected",
        "Partially Selected",
        "Unselected",
    ]
    assert all(
        header.styleSheet().endswith("border: none;")
        for header in grid._section_headers.values()
    )

    states["Charlie Unselected"] = "Selected"
    grid.refreshSectionGrouping()

    assert [record.title for record in grid._visible_records] == [
        "Bravo Selected",
        "Charlie Unselected",
        "Alpha Partial",
    ]

    grid.setGroupBySelected(False)

    assert [record.title for record in grid._visible_records] == [
        "Alpha Partial",
        "Bravo Selected",
        "Charlie Unselected",
    ]


def test_pc_category_grid_keeps_active_sort_within_selection_sections(qtbot) -> None:
    grid = PCMusicBrowserGrid()
    qtbot.addWidget(grid)
    states = {
        "Selected Low": "Selected",
        "Selected High": "Selected",
        "Partial": "Partially Selected",
        "Unselected": "Unselected",
    }
    years = {
        "Selected Low": 10,
        "Selected High": 40,
        "Partial": 30,
        "Unselected": 20,
    }
    grid.setSelectionSectionResolver(lambda item: states[str(item["title"])])
    grid._set_source_items(
        [
            {
                "title": title,
                "album": title,
                "category": "Albums",
                "filter_key": "album",
                "filter_value": title,
                "year": years[title],
            }
            for title in states
        ],
        reset_scroll=False,
    )

    grid.setGroupBySelected(True)
    grid.setSort("year", reverse=True)

    assert [record.title for record in grid._visible_records] == [
        "Selected High",
        "Selected Low",
        "Partial",
        "Unselected",
    ]

    states["Partial"] = "Selected"
    grid.refreshSectionGrouping()

    assert [record.title for record in grid._visible_records] == [
        "Selected High",
        "Partial",
        "Selected Low",
        "Unselected",
    ]


def test_selective_sync_classifies_category_cards_from_track_selection() -> None:
    tracks = [
        _track("Album A 1", "Album A/01.mp3"),
        _track("Album A 2", "Album A/02.mp3"),
        _track("Album B", "Album B/01.mp3"),
        _track("Album C", "Album C/01.mp3"),
    ]
    browser = _browser_with_tracks(tracks)
    browser._current_mode = "Albums"
    browser._selected_tracks = {
        tracks[0].path: True,
        tracks[1].path: False,
        tracks[2].path: True,
        tracks[3].path: False,
    }
    browser._build_groups()

    assert browser._selection_section_for_grid_item(
        {"category": "Albums", "title": "Album A"}
    ) == "Partially Selected"
    assert browser._selection_section_for_grid_item(
        {"category": "Albums", "title": "Album B"}
    ) == "Selected"
    assert browser._selection_section_for_grid_item(
        {"category": "Albums", "title": "Album C"}
    ) == "Unselected"


def test_plan_bulk_selection_refreshes_category_grouping() -> None:
    item = object()
    browser = SelectiveSyncBrowser.__new__(SelectiveSyncBrowser)
    browser._plan_selection_mode = True
    browser._plan_section_by_key = {
        "tracks": {"bucket": "tracks", "items": [item]},
    }
    browser._current_plan_section_key = "tracks"
    browser._plan_selection_state = {"tracks": set()}
    browser._selected_tracks = {"/music/song.mp3": False}
    browser._selected_photos = {}
    browser._selected_playlists = {}
    browser_any = cast(Any, browser)
    browser_any._content = SimpleNamespace(currentIndex=lambda: 0)
    refreshes: list[None] = []
    browser_any._refresh_grid_selection_grouping = lambda _mode=None: refreshes.append(None)
    browser_any._update_plan_footer = lambda: None

    browser._on_select_all()

    assert browser._selected_tracks["/music/song.mp3"] is True
    assert refreshes == [None]

    browser._on_deselect_all()

    assert browser._selected_tracks["/music/song.mp3"] is False
    assert refreshes == [None, None]


def test_selective_sync_storage_bar_projects_normal_and_plan_selections(
    qtbot,
    monkeypatch,
) -> None:
    session = SimpleNamespace(
        device_path="/virtual-ipod",
        discovered_ipod=None,
        identity=None,
    )
    settings = SimpleNamespace(track_list_columns_by_content={})
    browser = SelectiveSyncBrowser(
        settings_service=cast(
            Any,
            SimpleNamespace(
                get_global_settings=lambda: settings,
                get_effective_settings=lambda: settings,
            ),
        ),
        device_sessions=cast(
            Any,
            SimpleNamespace(current_session=lambda: session),
        ),
    )
    qtbot.addWidget(browser)
    monkeypatch.setattr(
        selective_sync_browser_module.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=1_000, used=400),
    )

    track = _track("Song", "Album/Song.mp3")
    photo = PCPhoto("photo", "Photo", source_path="/photos/photo.jpg", size=4)
    browser._plan_selection_mode = False
    browser._all_tracks = [track]
    browser._all_photos = [photo]
    browser._selected_tracks = {track.path: True}
    browser._selected_photos = {photo.source_path: True}
    browser._update_storage_projection()

    assert isinstance(browser._storage_bar, StorageBarWidget)
    assert not browser._storage_frame.isHidden()
    assert browser._storage_bar._sync_delta == 5

    added = SyncItem(action=SyncAction.ADD_TO_IPOD, pc_track=track)
    removed = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        ipod_track={"Title": "Removed", "size": 9},
    )
    added_photo = PhotoSyncItem("new-photo", "New Photo", size=4)
    browser._plan_selection_mode = True
    browser._plan_selection_sections = [
        {"key": "to_add", "bucket": "sync_items", "items": [added]},
        {"key": "to_remove", "bucket": "sync_items", "items": [removed]},
        {"key": "photos_to_add", "bucket": "photos_to_add", "items": [added_photo]},
    ]
    browser._plan_selection_state = {
        "sync_items": {id(added), id(removed)},
        "photos_to_add": {id(added_photo)},
    }
    browser._update_storage_projection()

    assert browser._storage_bar._sync_delta == -4


def test_selective_sync_groups_unknown_albums_by_source_folder():
    browser = _browser_with_tracks(
        [
            _track("Song 1", "Album A/01 Song 1.mp3"),
            _track("Song 2", "Album A/02 Song 2.mp3"),
            _track("Song 3", "Album B/01 Song 3.mp3"),
        ]
    )

    browser._build_groups()

    albums = browser._groups["Albums"]
    assert set(albums) == {"Album A", "Album B"}
    assert albums["Album A"]["artist"] == "Unknown Artist 1"
    assert albums["Album B"]["artist"] == "Unknown Artist 2"
    assert [t.title for t in albums["Album A"]["tracks"]] == ["Song 1", "Song 2"]
    assert [t.title for t in albums["Album B"]["tracks"]] == ["Song 3"]


def test_selective_sync_unknown_artist_view_uses_parent_folder_artist():
    browser = _browser_with_tracks(
        [
            _track("Song 1", "Artist A/Album/Disc 1/01 Song 1.mp3"),
            _track("Song 2", "Artist A/Album/Disc 2/01 Song 2.mp3"),
            _track("Song 3", "Artist B/Other Album/01 Song 3.mp3"),
        ]
    )

    browser._build_groups()

    artists = browser._groups["Artists"]
    assert set(artists) == {"Artist A", "Artist B"}
    assert [t.title for t in artists["Artist A"]["tracks"]] == ["Song 1", "Song 2"]
    assert [t.title for t in artists["Artist B"]["tracks"]] == ["Song 3"]


def test_selective_sync_album_groups_use_shared_album_identity_rules():
    browser = _browser_with_tracks(
        [
            _track(
                "Song 1",
                "Compilation/01 Song 1.mp3",
                artist="Artist",
                album="Compilation",
                album_artist="Various Artists",
            ),
            _track(
                "Song 2",
                "Compilation/02 Song 2.mp3",
                artist="Artist",
                album="Compilation",
                album_artist=None,
            ),
        ]
    )

    albums = browser._build_music_albums(browser._all_tracks)
    assert set(albums) == {"Compilation"}
    assert albums["Compilation"]["artist"] == "Various Artists"
    assert [t.title for t in albums["Compilation"]["tracks"]] == ["Song 1", "Song 2"]


def test_selective_sync_movie_only_folders_do_not_create_music_albums():
    browser = _browser_with_tracks(
        [
            _track(
                "Movie",
                "Movies/Movie.mov",
                is_video=True,
                video_kind="movie",
            ),
            _track("Song", "Music Album/01 Song.mp3"),
        ]
    )

    browser._build_groups()

    assert set(browser._groups["Albums"]) == {"Music Album"}
    assert [track.title for track in browser._buckets["movie"]] == ["Movie"]


def test_selective_sync_grid_item_actions_resolve_and_toggle_tracks():
    tracks = [
        _track("Song 1", "Album A/01 Song 1.mp3"),
        _track("Song 2", "Album A/02 Song 2.mp3"),
        _track("Song 3", "Album B/01 Song 3.mp3"),
    ]
    browser = _browser_with_tracks(tracks)
    browser._current_mode = "Albums"
    browser._selected_tracks = {track.path: True for track in tracks}

    footer_updates: list[bool] = []
    browser._update_footer = lambda: footer_updates.append(True)
    browser._build_groups()

    resolved = browser._tracks_for_grid_items([
        {"title": "Album A"},
        {"title": "Album B"},
    ])
    assert [track.title for track in resolved] == ["Song 1", "Song 2", "Song 3"]

    browser._set_grid_tracks_checked(resolved[:2], False)

    assert browser._selected_tracks[tracks[0].path] is False
    assert browser._selected_tracks[tracks[1].path] is False
    assert browser._selected_tracks[tracks[2].path] is True
    assert footer_updates == [True]


def test_selective_sync_builds_playlist_groups_from_discovered_files():
    tracks = [
        _track("Song 1", "Album A/01 Song 1.mp3"),
        _track("Song 2", "Album A/02 Song 2.mp3"),
    ]
    browser = _browser_with_tracks(tracks)
    browser._playlist_discovery = SimpleNamespace(
        playlists=(
            SimpleNamespace(
                title="Road Trip",
                source_path="/music/playlists/road-trip.m3u8",
                items=(
                    {"source_path": tracks[1].path},
                    {"source_path": tracks[0].path},
                ),
                total_entries=3,
                skipped_entries=1,
            ),
        )
    )

    browser._build_groups()

    playlists = browser._groups["Playlists"]
    assert set(playlists) == {"Road Trip"}
    assert [track.title for track in playlists["Road Trip"]["tracks"]] == [
        "Song 2",
        "Song 1",
    ]
    assert playlists["Road Trip"]["track_count"] == 2
    assert playlists["Road Trip"]["skipped_count"] == 1
    assert "1 skipped" in playlists["Road Trip"]["subtitle"]


def test_selective_sync_grid_item_actions_resolve_playlist_tracks():
    tracks = [
        _track("Song 1", "Album A/01 Song 1.mp3"),
        _track("Song 2", "Album A/02 Song 2.mp3"),
    ]
    browser = _browser_with_tracks(tracks)
    browser._current_mode = "Playlists"
    browser._selected_tracks = {track.path: True for track in tracks}
    browser._selected_playlists = {"/music/playlists/road-trip.m3u8": True}
    browser._update_footer = lambda: None
    browser._playlist_discovery = SimpleNamespace(
        playlists=(
            SimpleNamespace(
                title="Road Trip",
                source_path="/music/playlists/road-trip.m3u8",
                items=({"source_path": tracks[1].path},),
                total_entries=1,
                skipped_entries=0,
            ),
        )
    )
    browser._build_groups()

    resolved = browser._tracks_for_grid_items([{"title": "Road Trip"}])
    browser._set_grid_playlists_checked([{"title": "Road Trip"}], False)
    browser._set_grid_tracks_checked(resolved, False)

    assert [track.title for track in resolved] == ["Song 2"]
    assert browser._selected_playlists["/music/playlists/road-trip.m3u8"] is False
    assert browser._selected_tracks[tracks[0].path] is True
    assert browser._selected_tracks[tracks[1].path] is False


def test_selective_sync_plan_mode_builds_action_tabs_with_review_defaults():
    browser = SelectiveSyncBrowser.__new__(SelectiveSyncBrowser)
    add = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        pc_track=_track("New Song", "Album A/01 New Song.mp3"),
    )
    remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        ipod_track={"Title": "Gone", "size": 123},
    )
    update_file = SyncItem(
        action=SyncAction.UPDATE_FILE,
        pc_track=_track("Changed File", "Album A/02 Changed File.mp3"),
    )
    update_metadata = SyncItem(
        action=SyncAction.UPDATE_METADATA,
        pc_track=_track("Changed Details", "Album A/03 Changed Details.mp3"),
    )
    update_artwork = SyncItem(
        action=SyncAction.UPDATE_ARTWORK,
        pc_track=_track("Changed Art", "Album A/04 Changed Art.mp3"),
    )
    play_count = SyncItem(
        action=SyncAction.SYNC_PLAYCOUNT,
        pc_track=_track("Played Song", "Album A/05 Played Song.mp3"),
    )
    rating = SyncItem(
        action=SyncAction.SYNC_RATING,
        pc_track=_track("Rated Song", "Album A/06 Rated Song.mp3"),
    )
    photo = PhotoSyncItem("hash-a", "Photo A", source_path="/photos/a.jpg")
    photo_plan = PhotoSyncPlan()
    photo_plan.photos_to_add = [photo]
    photo_plan.albums_to_add = [PhotoAlbumChange("Vacation")]
    photo_plan.album_membership_adds = [
        PhotoMembershipChange("hash-a", "Vacation", "Photo A", source_path="/photos/a.jpg")
    ]
    plan = SyncPlan(
        to_add=[add],
        to_remove=[remove],
        to_update_file=[update_file],
        to_update_metadata=[update_metadata],
        to_update_artwork=[update_artwork],
        to_sync_playcount=[play_count],
        to_sync_rating=[rating],
        playlists_to_add=[{"Title": "Workout"}],
        playlists_to_edit=[{"Title": "Road Trip"}],
        playlists_to_remove=[{"Title": "Old Mix"}],
        photo_plan=photo_plan,
    )

    sections = browser._build_plan_selection_sections(plan)

    assert [section["key"] for section in sections] == [
        "to_add",
        "to_remove",
        "to_update_file",
        "to_update_metadata",
        "to_update_artwork",
        "to_sync_playcount",
        "to_sync_rating",
        "playlists_to_add",
        "playlists_to_edit",
        "playlists_to_remove",
        "photos_to_add",
        "albums_to_add",
        "album_membership_adds",
    ]
    assert [section["label"] for section in sections] == [
        "Add Items",
        "Remove Items",
        "Re-sync Files",
        "Update Details",
        "Update Artwork",
        "Play Counts",
        "Ratings",
        "Add Playlists",
        "Update Playlists",
        "Remove Playlists",
        "Add Photos",
        "Create Photo Albums",
        "Add to Photo Albums",
    ]

    state = SelectiveSyncBrowser._normalize_plan_selection_state(None, sections)

    assert id(add) in state["sync_items"]
    assert id(remove) not in state["sync_items"]
    assert id(plan.playlists_to_edit[0]) in state["playlists_to_edit"]
    assert id(photo) in state["photos_to_add"]


def test_selective_sync_plan_section_rebuilds_actions_into_music_groups():
    browser = _browser_with_tracks([])
    shown_modes: list[str] = []
    browser._apply_sidebar_visibility = lambda: None
    browser._show_mode = lambda mode: shown_modes.append(mode)
    add = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        pc_track=_track(
            "New Song",
            "Album A/01 New Song.mp3",
            artist="Artist A",
            album="Album A",
        ),
    )
    section = {
        "key": "to_add",
        "label": "Adds",
        "icon": "plus",
        "accent": "#00aa00",
        "items": [add],
        "bucket": "sync_items",
        "checked_by_default": True,
    }
    browser._plan_selection_state = {"sync_items": {id(add)}}
    browser._plan_track_key_to_selection = {}
    browser._plan_photo_key_to_selection = {}
    browser._plan_playlist_key_to_selection = {}

    browser._load_plan_section_content(section)

    assert shown_modes == ["Albums"]
    assert set(browser._groups["Albums"]) == {"Album A"}
    rebuilt_track = browser._groups["Albums"]["Album A"]["tracks"][0]
    assert rebuilt_track.title == "New Song"
    assert browser._selected_tracks[rebuilt_track.path] is True
    assert browser._plan_track_key_to_selection[rebuilt_track.path] == (
        "sync_items",
        id(add),
    )


def test_selective_sync_plan_remove_section_preserves_ipod_artwork_ref():
    browser = _browser_with_tracks([])
    shown_modes: list[str] = []
    browser._apply_sidebar_visibility = lambda: None
    browser._show_mode = lambda mode: shown_modes.append(mode)
    remove = SyncItem(
        action=SyncAction.REMOVE_FROM_IPOD,
        ipod_track={
            "Title": "Gone Song",
            "Artist": "Artist A",
            "Album": "Album A",
            "Location": ":iPod_Control:Music:F00:Gone.mp3",
            "size": 123,
            "artwork_id_ref": 321,
        },
    )
    section = {
        "key": "to_remove",
        "label": "Remove Items",
        "icon": "minus",
        "accent": "#cc0000",
        "items": [remove],
        "bucket": "sync_items",
        "checked_by_default": False,
    }
    browser._plan_selection_state = {"sync_items": {id(remove)}}
    browser._plan_track_key_to_selection = {}
    browser._plan_photo_key_to_selection = {}
    browser._plan_playlist_key_to_selection = {}

    browser._load_plan_section_content(section)

    assert shown_modes == ["Albums"]
    group = browser._groups["Albums"]["Album A"]
    rebuilt_track = group["tracks"][0]
    assert rebuilt_track.title == "Gone Song"
    assert rebuilt_track.path.startswith("iopenpod://sync-plan/track/to_remove/")
    assert rebuilt_track.__dict__["artwork_id_ref"] == 321
    assert group["art_paths"] == []
    assert group["artwork_id_ref"] == 321


def test_plan_grid_falls_back_to_device_artwork_when_no_pc_art_paths(monkeypatch):
    calls: list[int | None] = []

    def fake_load_cached(self, record):  # noqa: ANN001
        calls.append(record.artwork_id)
        return "device-art"

    monkeypatch.setattr(MusicBrowserGrid, "_load_cached_artwork", fake_load_cached)
    grid = PCMusicBrowserGrid.__new__(PCMusicBrowserGrid)
    grid._pc_mode = True
    grid._pc_art_map = {}
    record = GridRecord(
        source={},
        key=("Albums", "Album A"),
        title="Album A",
        subtitle="Artist A",
        payload={},
        artwork_id=321,
        artwork_key=321,
        search_words=(),
    )

    assert PCMusicBrowserGrid._load_cached_artwork(grid, record) == "device-art"
    assert calls == [321]


def test_selective_sync_plan_playlist_actions_render_as_playlist_rows():
    browser = _browser_with_tracks([])
    shown_modes: list[str] = []
    browser._apply_sidebar_visibility = lambda: None
    browser._show_mode = lambda mode: shown_modes.append(mode)
    playlist = {
        "Title": "Road Trip",
        "_sync_playlist_path": "/music/playlists/road-trip.m3u8",
        "_sync_playlist_total_entries": 12,
        "_sync_playlist_skipped_count": 1,
    }
    section = {
        "key": "playlists_to_edit",
        "label": "Update Playlists",
        "icon": "playlist",
        "accent": "#00aaee",
        "items": [playlist],
        "bucket": "playlists_to_edit",
        "checked_by_default": True,
    }
    browser._plan_selection_state = {"playlists_to_edit": {id(playlist)}}
    browser._plan_track_key_to_selection = {}
    browser._plan_photo_key_to_selection = {}
    browser._plan_playlist_key_to_selection = {}

    browser._load_plan_section_content(section)

    assert shown_modes == ["Playlists"]
    group = browser._groups["Playlists"]["Road Trip"]
    assert group["source_path"] == "/music/playlists/road-trip.m3u8"
    assert group["skipped_count"] == 1
    playlist_row = group["tracks"][0]
    assert playlist_row.title == "Road Trip"
    assert browser._selected_tracks[playlist_row.path] is True

    browser._set_plan_track_selection(playlist_row.path, False)

    assert id(playlist) not in browser._plan_selection_state["playlists_to_edit"]


class _FakeScanSignal:
    def __init__(self) -> None:
        self.disconnect_count = 0

    def disconnect(self) -> None:
        self.disconnect_count += 1


class _FakeScanWorker:
    def __init__(self, *, running: bool) -> None:
        self._running = running
        self.finished = _FakeScanSignal()
        self.progress = _FakeScanSignal()
        self.error = _FakeScanSignal()
        self.cancel_count = 0
        self.delete_later_count = 0
        self.wait_count = 0
        self.terminate_count = 0

    def isRunning(self) -> bool:
        return self._running

    def cancel(self) -> None:
        self.cancel_count += 1

    def wait(self, _timeout: int | None = None) -> bool:
        self.wait_count += 1
        return True

    def terminate(self) -> None:
        self.terminate_count += 1

    def deleteLater(self) -> None:
        self.delete_later_count += 1


def test_selective_sync_cancel_detaches_scan_worker_without_waiting():
    browser = SelectiveSyncBrowser.__new__(SelectiveSyncBrowser)
    browser_any = cast(Any, browser)
    worker = _FakeScanWorker(running=True)
    browser_any._scan_worker = worker
    browser_any._scan_orphan_workers = []

    SelectiveSyncBrowser._cleanup_scan_worker(browser)

    assert worker.cancel_count == 1
    assert worker.finished.disconnect_count == 1
    assert worker.progress.disconnect_count == 1
    assert worker.error.disconnect_count == 1
    assert worker.wait_count == 0
    assert worker.terminate_count == 0
    assert browser_any._scan_worker is None
    assert browser_any._scan_orphan_workers == [worker]


def test_selective_sync_stale_scan_completion_after_cancel_is_ignored():
    browser = SimpleNamespace(_scan_worker=None, marker="unchanged")
    worker = _FakeScanWorker(running=False)

    SelectiveSyncBrowser._on_scan_complete(
        cast(Any, browser),
        cast(Any, {"tracks": []}),
        cast(Any, worker),
    )

    assert browser.marker == "unchanged"
