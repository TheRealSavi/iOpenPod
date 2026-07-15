from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from PIL import Image
from PyQt6.QtCore import QEvent, QPoint, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QComboBox, QDialog, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QSlider, QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget

from iopenpod.application.context import RuntimeSettingsService
from iopenpod.application.services import DeviceCapabilitySnapshot, DeviceIdentitySnapshot, DeviceManagerLike, DeviceSession, SettingsService, SettingsSnapshot
from iopenpod.gui import imgMaker
from iopenpod.gui.imgMaker import ArtworkFormatPreview, TrackArtworkPreview, get_track_artwork_previews
from iopenpod.gui.styles import (
    BROWSER_SEARCH_CONTROL_SIZE,
    BROWSER_SEARCH_FIELD_WIDTH,
    Colors,
    Metrics,
    browser_search_field_css,
)
from iopenpod.gui.widgets.MBListView import (
    _OPEN_TRACK_SHORTCUT,
    _OPEN_WITH_TRACK_SHORTCUT,
    COLUMN_CONFIG,
    DEFAULT_AUDIOBOOK_COLUMNS,
    DEFAULT_PODCAST_COLUMNS,
    SORTABLE_NUMERIC_KEYS,
    MusicBrowserList,
    build_new_regular_playlist,
    chapter_count_from_data,
    chapter_summary_from_data,
    podcast_conversion_changes_for_track,
)
from iopenpod.gui.widgets.trackContextMenu import (
    ChapteredAlbumMenuAction,
    build_track_context_menu,
)
from iopenpod.gui.widgets.trackEditorDialog import (
    TrackEditorDialog,
    TrackFieldSpec,
    _ArtworkPreviewPanel,
    _ChapterTimelineEditor,
    _format_datetime_value,
    _parse_datetime_text,
    _SquareCropCanvas,
    _subgroup_for_key,
    _TrackFieldRow,
)
from iopenpod.gui.widgets.trackListTitleBar import TrackListTitleBar
from iopenpod.infrastructure import settings_persistence
from iopenpod.infrastructure.settings_runtime import SettingsRuntime
from iopenpod.infrastructure.settings_schema import AppSettings, DeviceSettingsState

_QTEST: Any = QTest


def _tree_child_text(tree: QTreeWidget, section_index: int, child_index: int, column: int) -> str:
    section = tree.topLevelItem(section_index)
    assert section is not None
    child = section.child(child_index)
    assert child is not None
    return child.text(column)


def _tree_child_value_for_key(tree: QTreeWidget, section_index: int, key: str) -> str:
    section = tree.topLevelItem(section_index)
    assert section is not None
    for index in range(section.childCount()):
        child = section.child(index)
        assert child is not None
        if child.text(0) == key:
            return child.text(1)
    raise AssertionError(f"Missing metadata key {key!r}")


def _table_item(table: QTableWidget, row: int, column: int) -> QTableWidgetItem:
    item = table.item(row, column)
    assert item is not None
    return item


@dataclass
class _CancellationToken:
    def is_cancelled(self) -> bool:
        return False


class _DeviceManager:
    """Mock DeviceManagerLike for testing."""
    device_changed = None
    device_settings_loaded = None
    device_settings_failed = None

    def __init__(self) -> None:
        self.cancellation_token: _CancellationToken = _CancellationToken()
        self._device_path: str | None = None
        self._discovered_ipod: object | None = None
        self._device_settings_loading = False
        self._itunesdb_path: str | None = None
        self._artworkdb_path: str | None = None
        self._artwork_folder_path: str | None = None

    @property
    def device_path(self) -> str | None:
        return self._device_path

    @device_path.setter
    def device_path(self, path: str | None) -> None:
        self._device_path = path

    @property
    def discovered_ipod(self) -> object | None:
        return self._discovered_ipod

    @discovered_ipod.setter
    def discovered_ipod(self, ipod: object | None) -> None:
        self._discovered_ipod = ipod

    @property
    def device_settings_loading(self) -> bool:
        return self._device_settings_loading

    @property
    def itunesdb_path(self) -> str | None:
        return self._itunesdb_path

    @property
    def artworkdb_path(self) -> str | None:
        return self._artworkdb_path

    @property
    def artwork_folder_path(self) -> str | None:
        return self._artwork_folder_path

    def is_valid_ipod_root(self, path: str) -> bool:
        return True

    def cancel_all_operations(self) -> None:
        pass


@dataclass
class _Session:
    device_path: str | None = None
    itunesdb_path: str | None = None
    artworkdb_path: str | None = None
    artwork_folder_path: str | None = None
    device_settings_loading: bool = False
    discovered_ipod: object | None = None
    identity: DeviceIdentitySnapshot | None = None
    capabilities: DeviceCapabilitySnapshot | None = None

    @property
    def has_device(self) -> bool:
        return bool(self.device_path)


class _SettingsService:
    """Mock SettingsService for testing."""

    def __init__(self) -> None:
        self._settings = AppSettings()

    def get_global_settings(self) -> AppSettings:
        return self._settings

    def get_effective_settings(self) -> AppSettings:
        return self._settings

    def save_global_settings(self, settings: AppSettings) -> SettingsSnapshot:
        self._settings = settings
        return SettingsSnapshot.from_settings(settings)

    def device_settings_key(
        self,
        ipod_root: str = "",
        device_info: object | None = None,
    ) -> str:
        return "test_device_key"

    def get_device_settings_for_edit(
        self,
        ipod_root: str,
        device_key: str = "",
    ) -> DeviceSettingsState:
        return DeviceSettingsState(settings=self._settings)

    def save_device_settings(
        self,
        ipod_root: str,
        settings: AppSettings,
        use_global_settings: bool = False,
        device_key: str = "",
    ) -> None:
        pass

    def reset_device_settings_to_global(
        self,
        ipod_root: str,
        device_key: str = "",
        use_global_settings: bool = False,
    ) -> AppSettings:
        return self._settings

    def get_global_snapshot(self) -> SettingsSnapshot:
        return SettingsSnapshot.from_settings(self._settings)

    def get_effective_snapshot(self) -> SettingsSnapshot:
        return SettingsSnapshot.from_settings(self._settings)

    def reload(self) -> SettingsSnapshot:
        return SettingsSnapshot.from_settings(self._settings)


class _DeviceSessions:
    def __init__(self, session: _Session | None = None) -> None:
        self._manager = _DeviceManager()
        self._session = session or _Session()

    def current_session(self) -> DeviceSession:
        return cast(DeviceSession, self._session)

    def manager(self) -> DeviceManagerLike:
        return cast(DeviceManagerLike, self._manager)


class _Signal:
    def __init__(self) -> None:
        self.emit_count = 0

    def emit(self) -> None:
        self.emit_count += 1


class _LibraryCache:
    def __init__(self, *, ready: bool = True) -> None:
        self._ready = ready
        self.updated: list[tuple[list[dict], dict[str, object]]] = []
        self.updated_by_track: list[tuple[list[dict], dict[int, dict[str, object]]]] = []
        self.playlist_quick_sync = _Signal()

    def is_ready(self) -> bool:
        return self._ready

    def get_playlists(self) -> list[dict]:
        return []

    def update_track_flags(self, tracks: list[dict], changes: dict[str, object]) -> None:
        self.updated.append((list(tracks), dict(changes)))
        for track in tracks:
            track.update(changes)

    def update_track_flags_by_track(
        self,
        tracks: list[dict],
        changes_by_track: dict[int, dict[str, object]],
    ) -> None:
        self.updated_by_track.append((list(tracks), dict(changes_by_track)))
        for track in tracks:
            track.update(changes_by_track.get(id(track), {}))


class _RepoTempDir:
    def __enter__(self) -> Path:
        repo_root = Path(__file__).resolve().parents[1]
        self.path = repo_root / ".tmp" / f"mb-list-view-{uuid4().hex}"
        self.path.mkdir(parents=True, exist_ok=False)
        return self.path

    def __exit__(self, exc_type, exc, tb) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def _tracks_for_music() -> list[dict[str, object]]:
    return [
        {
            "Title": "Song A",
            "Artist": "Artist A",
            "Album": "Album A",
            "Genre": "Rock",
            "year": 2001,
            "track_number": 1,
            "length": 180000,
            "rating": 80,
            "play_count_1": 5,
            "date_added": 1710000000,
        }
    ]


def _tracks_for_album_filters() -> list[dict[str, object]]:
    return [
        {
            "Title": "Alpha One",
            "Artist": "Artist A",
            "Album": "Album A",
            "Genre": "Rock",
            "year": 2001,
            "track_number": 1,
            "length": 180000,
            "rating": 80,
            "play_count_1": 5,
            "date_added": 1710000000,
        },
        {
            "Title": "Alpha Two",
            "Artist": "Artist A",
            "Album": "Album A",
            "Genre": "Rock",
            "year": 2001,
            "track_number": 2,
            "length": 181000,
            "rating": 80,
            "play_count_1": 6,
            "date_added": 1710000100,
        },
        {
            "Title": "Beta One",
            "Artist": "Artist B",
            "Album": "Album B",
            "Genre": "Jazz",
            "year": 2002,
            "track_number": 1,
            "length": 190000,
            "rating": 60,
            "play_count_1": 2,
            "date_added": 1710000200,
        },
        {
            "Title": "Beta Two",
            "Artist": "Artist B",
            "Album": "Album B",
            "Genre": "Jazz",
            "year": 2002,
            "track_number": 2,
            "length": 191000,
            "rating": 60,
            "play_count_1": 3,
            "date_added": 1710000300,
        },
    ]


def _tracks_for_video() -> list[dict[str, object]]:
    return [
        {
            "Title": "Video A",
            "Artist": "Director A",
            "Album": "Collection A",
            "length": 240000,
            "media_type": 0x02,
            "size": 900_000_000,
            "bitrate": 2400,
            "date_added": 1711000000,
            "rating": 60,
            "play_count_1": 2,
        }
    ]


def _mount_list(
    qtbot,
    settings_service: SettingsService | None = None,
    device_sessions: _DeviceSessions | None = None,
    library_cache: Any | None = None,
    content_type_override: str | None = None,
    show_art_override: bool | None = False,
    show_search_bar: bool = True,
) -> MusicBrowserList:
    view = MusicBrowserList(
        settings_service=settings_service or _SettingsService(),
        device_sessions=device_sessions or _DeviceSessions(),
        library_cache=library_cache,
        show_art_override=show_art_override,
        content_type_override=content_type_override,
        show_search_bar=show_search_bar,
    )
    qtbot.addWidget(view)
    view.resize(900, 500)
    view.show()
    qtbot.wait(50)
    return view


def _many_tracks_with_art(count: int) -> list[dict[str, object]]:
    return [
        {
            "Title": f"Song {idx:03d}",
            "Artist": "Artist",
            "Album": "Album",
            "Genre": "Rock",
            "year": 2001,
            "track_number": idx + 1,
            "length": 180000,
            "rating": 80,
            "play_count_1": 5,
            "date_added": 1710000000,
            "artwork_id_ref": idx + 1,
        }
        for idx in range(count)
    ]


def _load_content(
    qtbot,
    view: MusicBrowserList,
    *,
    tracks: list[dict[str, object]],
    media_type_filter: int | None,
) -> None:
    view.clearTable()
    view._all_tracks = tracks
    view._tracks = tracks
    view._media_type_filter = media_type_filter
    view._is_playlist_mode = False
    view._setup_columns()
    view._populate_table()
    qtbot.waitUntil(lambda: view.table.rowCount() == len(tracks), timeout=2000)


def _visible_column_order(view: MusicBrowserList) -> list[str]:
    header = view.table.horizontalHeader()
    assert header is not None
    result: list[str] = []
    for visual_index in range(view.table.columnCount()):
        col_key = view._col_key_at(visual_index)
        if col_key is not None:
            result.append(col_key)
    return result


def test_tracklist_search_section_sits_above_table(qtbot) -> None:
    view = _mount_list(qtbot)

    assert view._search_bar.objectName() == "trackListSearchBar"
    assert view._search_field.objectName() == "trackListSearchField"
    assert view._search_field.placeholderText() == "Search tracks"
    assert view._layout.indexOf(view._search_bar) < view._layout.indexOf(view.table)
    assert view._search_field.size().width() == BROWSER_SEARCH_FIELD_WIDTH
    assert view._search_field.size().height() == BROWSER_SEARCH_CONTROL_SIZE
    assert view._search_field.styleSheet() == browser_search_field_css()
    search_layout = view._search_bar.layout()
    assert search_layout is not None
    assert search_layout.indexOf(view._search_field) == 1
    leading_item = search_layout.itemAt(0)
    assert leading_item is not None
    assert leading_item.spacerItem() is not None
    assert search_layout.contentsMargins().right() == Metrics.GRID_MARGIN_X


def test_tracklist_search_matches_hidden_and_formatted_metadata(qtbot) -> None:
    view = _mount_list(qtbot)
    tracks: list[dict[str, object]] = [
        {
            "Title": "First Song",
            "Artist": "Alpha",
            "Album": "Album A",
            "Genre": "Rock",
            "Comment": "A deeply hidden needle",
            "explicit_flag": 0,
        },
        {
            "Title": "Second Song",
            "Artist": "Beta",
            "Album": "Album B",
            "Genre": "Jazz",
            "Comment": "Nothing unusual",
            "explicit_flag": 1,
        },
        {
            "Title": "Third Song",
            "Artist": "Gamma",
            "Album": "Album C",
            "Genre": "Ambient",
            "Comment": "Another note",
            "explicit_flag": 0,
        },
    ]
    _load_content(qtbot, view, tracks=tracks, media_type_filter=0x01)
    assert "Comment" not in view._columns
    assert "explicit_flag" not in view._columns
    view.table.selectRow(0)

    view._search_field.setText("hidden needle")
    qtbot.waitUntil(lambda: view.table.rowCount() == 1, timeout=2000)
    assert view.tracks == [tracks[0]]
    selection_model = view.table.selectionModel()
    assert selection_model is not None
    assert [index.row() for index in selection_model.selectedRows()] == [0]

    view._search_field.setText("second jazz")
    qtbot.waitUntil(
        lambda: len(view.tracks) == 1 and view.tracks[0] is tracks[1],
        timeout=2000,
    )

    view._search_field.setText("explicit")
    qtbot.waitUntil(
        lambda: len(view.tracks) == 1 and view.tracks[0] is tracks[1],
        timeout=2000,
    )

    view._search_field.clear()
    qtbot.waitUntil(lambda: view.table.rowCount() == len(tracks), timeout=2000)
    assert view.tracks == tracks


def test_tracklist_search_matches_symbol_variants(qtbot) -> None:
    view = _mount_list(qtbot)
    track: dict[str, object] = {"Title": "Don’t Stop"}
    _load_content(qtbot, view, tracks=[track], media_type_filter=0x01)

    view.setSearchQuery("don't")

    qtbot.waitUntil(lambda: not view._search_timer.isActive(), timeout=2000)
    assert view.tracks == [track]


def test_title_bar_search_filters_embedded_track_list(qtbot) -> None:
    view = _mount_list(qtbot, show_search_bar=False)
    titlebar = TrackListTitleBar(QSplitter())
    qtbot.addWidget(titlebar)
    titlebar.search_changed.connect(view.setSearchQuery)
    view.search_query_changed.connect(titlebar.setSearchQuery)

    tracks: list[dict[str, object]] = [
        {"Title": "First", "Comment": "Needle in hidden metadata"},
        {"Title": "Second", "Comment": "Nothing to find"},
    ]
    _load_content(qtbot, view, tracks=tracks, media_type_filter=0x01)
    assert view._search_bar.isHidden()

    titlebar.search.setText("needle")
    qtbot.waitUntil(lambda: view.table.rowCount() == 1, timeout=2000)
    assert view.tracks == [tracks[0]]

    view.clearTable(clear_cache=True)
    assert titlebar.search.text() == ""


def test_tracklist_search_filters_only_the_current_list_scope(qtbot) -> None:
    view = _mount_list(qtbot)
    tracks: list[dict[str, object]] = [
        {"Title": "Inside Match", "Artist": "Alpha", "Album": "Album A"},
        {"Title": "Inside Other", "Artist": "Beta", "Album": "Album A"},
        {"Title": "Outside Match", "Artist": "Gamma", "Album": "Album B"},
    ]
    _load_content(qtbot, view, tracks=tracks, media_type_filter=0x01)
    view.filterByAlbum("Album A")
    qtbot.waitUntil(lambda: view.table.rowCount() == 2, timeout=2000)

    view._search_field.setText("match")
    qtbot.waitUntil(lambda: view.table.rowCount() == 1, timeout=2000)

    assert view.tracks == [tracks[0]]
    assert view._status_label.text() == "1 of 2 songs"


def test_tracklist_artwork_loads_only_visible_prefetch_rows(qtbot):
    view = _mount_list(qtbot, show_art_override=True)
    tracks = _many_tracks_with_art(300)

    _load_content(qtbot, view, tracks=tracks, media_type_filter=0x01)

    needed = view._visible_artwork_ids_needing_load()

    assert needed
    assert 1 in needed
    assert len(needed) < len(tracks)
    assert tracks[-1]["artwork_id_ref"] not in needed


def test_tracklist_population_does_not_decode_shared_artwork_on_ui_thread(
    qtbot,
    monkeypatch,
):
    def fail_get_artwork(*_args, **_kwargs):
        raise AssertionError("track rows should not decode artwork synchronously")

    monkeypatch.setattr(imgMaker, "get_artwork", fail_get_artwork)
    view = _mount_list(qtbot, show_art_override=True)

    _load_content(
        qtbot,
        view,
        tracks=_many_tracks_with_art(1),
        media_type_filter=0x01,
    )

    art_item = view.table.item(0, 0)
    assert art_item is not None
    assert art_item.data(Qt.ItemDataRole.UserRole + 2) == 1
    assert art_item.icon().isNull()


def _drag_header_section(
    view: MusicBrowserList,
    *,
    source_visual: int,
    target_visual: int,
) -> None:
    header = view.table.horizontalHeader()
    assert header is not None
    viewport = header.viewport()
    assert viewport is not None
    source_x = header.sectionPosition(source_visual) + (header.sectionSize(source_visual) // 2)
    target_x = header.sectionPosition(target_visual) + 5
    center_y = header.height() // 2
    _QTEST.mousePress(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(source_x, center_y),
        delay=10,
    )
    _QTEST.mouseMove(viewport, QPoint(target_x, center_y), delay=10)
    _QTEST.mouseRelease(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(target_x, center_y),
        delay=10,
    )


def _resize_header_section(
    view: MusicBrowserList,
    *,
    visual_index: int,
    delta_x: int,
) -> int:
    header = view.table.horizontalHeader()
    assert header is not None
    viewport = header.viewport()
    assert viewport is not None
    edge_x = header.sectionPosition(visual_index) + header.sectionSize(visual_index) - 1
    center_y = header.height() // 2
    _QTEST.mousePress(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(edge_x, center_y),
        delay=10,
    )
    _QTEST.mouseMove(viewport, QPoint(edge_x + delta_x, center_y), delay=10)
    _QTEST.mouseRelease(
        viewport,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(edge_x + delta_x, center_y),
        delay=10,
    )
    return header.sectionSize(visual_index)


def test_default_column_width_uses_distribution_not_single_outlier(qtbot):
    view = _mount_list(qtbot)
    tracks = [
        {
            "Title": f"Song {idx:02d}",
            "Artist": "Artist",
            "Album": "Album",
            "Genre": "Rock",
            "year": 2001,
            "track_number": idx + 1,
            "length": 180000,
            "rating": 80,
            "play_count_1": 5,
            "date_added": 1710000000,
        }
        for idx in range(80)
    ]
    outlier_title = "A very long live bootleg title with extra venue notes " * 18
    tracks.append(
        {
            "Title": outlier_title,
            "Artist": "Artist",
            "Album": "Album",
            "Genre": "Rock",
            "year": 2001,
            "track_number": 81,
            "length": 180000,
            "rating": 80,
            "play_count_1": 5,
            "date_added": 1710000000,
        }
    )

    _load_content(qtbot, view, tracks=tracks, media_type_filter=0x01)

    title_col = view._columns.index("Title")
    title_width = view.table.columnWidth(title_col)
    outlier_width = view.table.fontMetrics().horizontalAdvance(outlier_title)

    assert title_width >= view.table.fontMetrics().horizontalAdvance("Song 00")
    assert title_width < outlier_width * 0.6


def test_column_layout_persists_per_content_type(qtbot):
    view = _mount_list(qtbot)

    _load_content(qtbot, view, tracks=_tracks_for_music(), media_type_filter=0x01)

    header = view.table.horizontalHeader()
    assert header is not None
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive

    header.moveSection(2, 1)
    view._on_header_section_moved(2, 2, 1)
    view.table.setColumnWidth(0, 260)
    qtbot.waitUntil(
        lambda: list(
            view._settings_service.get_global_settings()
            .track_list_columns_by_content.get("music", {})
        )[:3]
        == ["Title", "Album", "Artist"],
        timeout=2000,
    )

    saved_music = view._settings_service.get_global_settings().track_list_columns_by_content["music"]
    assert list(saved_music)[:3] == ["Title", "Album", "Artist"]
    assert saved_music["Title"] == 260

    _load_content(qtbot, view, tracks=_tracks_for_video(), media_type_filter=0x02)
    header = view.table.horizontalHeader()
    assert header is not None
    header.moveSection(5, 4)
    view._on_header_section_moved(5, 5, 4)
    qtbot.waitUntil(
        lambda: list(
            view._settings_service.get_global_settings()
            .track_list_columns_by_content.get("video", {})
        )[:6]
        == [
            "Title",
            "Artist",
            "Album",
            "length",
            "size",
            "media_type",
        ],
        timeout=2000,
    )

    saved_video = view._settings_service.get_global_settings().track_list_columns_by_content["video"]
    assert list(saved_video)[:6] == [
        "Title",
        "Artist",
        "Album",
        "length",
        "size",
        "media_type",
    ]

    _load_content(qtbot, view, tracks=_tracks_for_music(), media_type_filter=0x01)
    view._save_user_widths()

    assert view._user_col_order is not None
    assert view._user_col_order[:3] == ["Title", "Album", "Artist"]
    assert view._user_col_widths is not None
    assert view._user_col_widths["Title"] == 260


def test_reset_columns_removes_saved_widths_and_recalculates(qtbot):
    view = _mount_list(qtbot)
    _load_content(qtbot, view, tracks=_tracks_for_music(), media_type_filter=0x01)

    view.table.setColumnWidth(0, 260)
    view._on_header_section_resized(0, 100, 260)
    qtbot.waitUntil(
        lambda: (
            view._settings_service.get_global_settings()
            .track_list_columns_by_content.get("music", {})
            .get("Title")
        )
        == 260,
        timeout=2000,
    )

    view._reset_columns()
    qtbot.waitUntil(lambda: view.table.rowCount() == 1, timeout=2000)

    settings = view._settings_service.get_global_settings()
    assert "music" not in settings.track_list_columns_by_content
    assert view._user_col_order is None
    assert view._user_col_widths == {}
    assert view.table.columnWidth(0) != 260


def test_resize_single_column_to_fit_recalculates_only_that_column(qtbot):
    view = _mount_list(qtbot)
    _load_content(qtbot, view, tracks=_tracks_for_music(), media_type_filter=0x01)

    title_col = view._columns.index("Title")
    artist_col = view._columns.index("Artist")
    view.table.setColumnWidth(title_col, 420)
    view.table.setColumnWidth(artist_col, 333)

    view._resize_column_to_current_content(title_col)

    qtbot.waitUntil(
        lambda: (
            view._settings_service.get_global_settings()
            .track_list_columns_by_content.get("music", {})
            .get("Title")
        )
        == view.table.columnWidth(title_col),
        timeout=2000,
    )

    assert view.table.columnWidth(title_col) != 420
    assert view.table.columnWidth(artist_col) == 333


def test_resize_all_columns_to_fit_recalculates_current_columns(qtbot):
    view = _mount_list(qtbot)
    _load_content(qtbot, view, tracks=_tracks_for_music(), media_type_filter=0x01)

    title_col = view._columns.index("Title")
    artist_col = view._columns.index("Artist")
    view.table.setColumnWidth(title_col, 420)
    view.table.setColumnWidth(artist_col, 333)

    view._resize_all_columns_to_current_content()

    qtbot.waitUntil(
        lambda: "music"
        in view._settings_service.get_global_settings().track_list_columns_by_content,
        timeout=2000,
    )

    saved_music = view._settings_service.get_global_settings().track_list_columns_by_content["music"]
    assert view.table.columnWidth(title_col) != 420
    assert view.table.columnWidth(artist_col) != 333
    assert saved_music["Title"] == view.table.columnWidth(title_col)
    assert saved_music["Artist"] == view.table.columnWidth(artist_col)


def test_album_navigation_preserves_user_column_order(qtbot):
    view = _mount_list(qtbot)
    tracks = _tracks_for_album_filters()

    _load_content(qtbot, view, tracks=tracks, media_type_filter=0x01)

    header = view.table.horizontalHeader()
    assert header is not None
    header.moveSection(2, 1)
    view._on_header_section_moved(2, 2, 1)

    qtbot.waitUntil(
        lambda: list(
            view._settings_service.get_global_settings()
            .track_list_columns_by_content.get("music", {})
        )[:3]
        == ["Title", "Album", "Artist"],
        timeout=2000,
    )

    initial_order = _visible_column_order(view)
    assert initial_order[:3] == ["Title", "Album", "Artist"]

    view.applyFilter({"filter_key": "Album", "filter_value": "Album B"})
    qtbot.waitUntil(lambda: view.table.rowCount() == 2, timeout=2000)
    assert _visible_column_order(view)[:3] == ["Title", "Album", "Artist"]

    view.applyFilter({"filter_key": "Album", "filter_value": "Album A"})
    qtbot.waitUntil(lambda: view.table.rowCount() == 2, timeout=2000)
    assert _visible_column_order(view)[:3] == ["Title", "Album", "Artist"]


def test_column_width_changes_debounced(qtbot):
    """Test that multiple rapid width changes are debounced before saving to settings."""
    view = _mount_list(qtbot)
    _load_content(qtbot, view, tracks=_tracks_for_music(), media_type_filter=0x01)

    header = view.table.horizontalHeader()
    assert header is not None

    # Simulate rapid drag resizes
    original_artist_width = header.sectionSize(1)

    # Simulate multiple resize events (like during a drag)
    final_artist_width = original_artist_width
    for i in range(10):
        final_artist_width = original_artist_width + 10 + i
        view.table.setColumnWidth(1, final_artist_width)
        view._on_header_section_resized(1, original_artist_width, final_artist_width)

    # Wait for debounce timeout to complete
    qtbot.waitUntil(
        lambda: "music"
        in view._settings_service.get_global_settings().track_list_columns_by_content,
        timeout=2000,
    )

    # Verify settings are saved
    saved_music = view._settings_service.get_global_settings().track_list_columns_by_content["music"]
    assert saved_music["Artist"] == final_artist_width


def test_flush_pending_column_changes(qtbot):
    """Test that flush_pending_column_changes() immediately saves pending changes."""
    view = _mount_list(qtbot)
    _load_content(qtbot, view, tracks=_tracks_for_music(), media_type_filter=0x01)

    header = view.table.horizontalHeader()
    assert header is not None

    # Make a column change
    header.moveSection(2, 1)
    view._on_header_section_moved(2, 2, 1)

    # Don't wait for the debounce timer, instead flush immediately
    view.flush_pending_column_changes()

    # Settings should be saved immediately
    saved_music = view._settings_service.get_global_settings().track_list_columns_by_content["music"]
    assert list(saved_music)[:3] == ["Title", "Album", "Artist"]


def test_hideEvent_flushes_pending_changes(qtbot):
    """Test that pending column changes are flushed when widget is hidden."""
    view = _mount_list(qtbot)
    _load_content(qtbot, view, tracks=_tracks_for_music(), media_type_filter=0x01)

    header = view.table.horizontalHeader()
    assert header is not None

    # Make a column change
    header.moveSection(2, 1)
    view._on_header_section_moved(2, 2, 1)

    # Simulate widget being hidden (should trigger flush)
    view.hide()

    # Settings should be saved
    saved_music = view._settings_service.get_global_settings().track_list_columns_by_content["music"]
    assert list(saved_music)[:3] == ["Title", "Album", "Artist"]


def test_human_drag_reorder_persists_to_settings_file_without_force_flush(
    qtbot,
    monkeypatch,
):
    with _RepoTempDir() as tmp_path:
        settings_dir = tmp_path / "settings"
        settings_path = settings_dir / "settings.json"
        monkeypatch.setattr(
            settings_persistence,
            "default_settings_dir",
            lambda: str(settings_dir),
        )
        monkeypatch.setattr(
            settings_persistence,
            "get_settings_path",
            lambda: str(settings_path),
        )

        service = RuntimeSettingsService(runtime=SettingsRuntime())
        view = _mount_list(qtbot, settings_service=service)
        _load_content(qtbot, view, tracks=_tracks_for_music(), media_type_filter=0x01)

        header = view.table.horizontalHeader()
        assert header is not None
        header.moveSection(2, 1)
        view._on_header_section_moved(2, 2, 1)

        qtbot.waitUntil(settings_path.exists, timeout=2000)
        qtbot.waitUntil(
            lambda: list(
                json.loads(settings_path.read_text(encoding="utf-8"))
                .get("track_list_columns_by_content", {})
                .get("music", {})
            )[:3]
            == ["Title", "Album", "Artist"],
            timeout=2000,
        )


def test_human_resize_persists_to_settings_file_without_force_flush(
    qtbot,
    monkeypatch,
):
    with _RepoTempDir() as tmp_path:
        settings_dir = tmp_path / "settings"
        settings_path = settings_dir / "settings.json"
        monkeypatch.setattr(
            settings_persistence,
            "default_settings_dir",
            lambda: str(settings_dir),
        )
        monkeypatch.setattr(
            settings_persistence,
            "get_settings_path",
            lambda: str(settings_path),
        )

        service = RuntimeSettingsService(runtime=SettingsRuntime())
        view = _mount_list(qtbot, settings_service=service)
        _load_content(qtbot, view, tracks=_tracks_for_music(), media_type_filter=0x01)

        resized_width = _resize_header_section(view, visual_index=0, delta_x=40)

        qtbot.waitUntil(settings_path.exists, timeout=2000)
        qtbot.waitUntil(
            lambda: (
                json.loads(settings_path.read_text(encoding="utf-8"))
                .get("track_list_columns_by_content", {})
                .get("music", {})
                .get("Title")
            )
            == resized_width,
            timeout=2000,
        )


def test_build_new_regular_playlist_marks_payload_as_new_regular_playlist() -> None:
    playlist = build_new_regular_playlist(
        [
            {"track_id": 101, "Title": "First"},
            {"track_id": 202, "Title": "Second"},
        ]
    )

    assert playlist is not None
    assert playlist["Title"] == "New Playlist"
    assert playlist["_isNew"] is True
    assert playlist["_source"] == "regular"
    assert isinstance(playlist["playlist_id"], int)
    assert playlist["playlist_id"] > 0
    assert playlist["items"] == [{"track_id": 101}, {"track_id": 202}]


def test_build_new_regular_playlist_returns_none_without_valid_track_ids() -> None:
    assert build_new_regular_playlist([{"Title": "Missing ID"}, {"track_id": 0}]) is None


def test_chapter_columns_are_available_for_spoken_word_views() -> None:
    chapter_data = {
        "chapters": [
            {"startpos": 0, "title": "Intro"},
            {"startpos": 60_000, "title": "Part One"},
            {"startpos": 120_000, "title": "Part Two"},
            {"startpos": 180_000, "title": "Credits"},
        ]
    }

    assert COLUMN_CONFIG["chapter_count"][0] == "Chapters"
    assert COLUMN_CONFIG["chapter_summary"][0] == "Chapter Titles"
    assert "chapter_count" in SORTABLE_NUMERIC_KEYS
    assert "chapter_count" in DEFAULT_PODCAST_COLUMNS
    assert "chapter_count" in DEFAULT_AUDIOBOOK_COLUMNS
    assert "chapter_summary" not in DEFAULT_PODCAST_COLUMNS
    assert chapter_count_from_data(chapter_data) == 4
    assert chapter_summary_from_data(chapter_data) == "Intro, Part One, Part Two, +1 more"


def test_chapter_count_column_formats_in_podcast_view(qtbot) -> None:
    view = _mount_list(qtbot)
    tracks = [
        {
            "Title": "Episode A",
            "Artist": "Show A",
            "Album": "Podcast A",
            "length": 120_000,
            "media_type": 0x04,
            "chapter_data": {
                "chapters": [
                    {"startpos": 0, "title": "Intro"},
                    {"startpos": 60_000, "title": "Main"},
                ]
            },
        }
    ]

    _load_content(qtbot, view, tracks=tracks, media_type_filter=0x04)

    chapter_col = view._columns.index("chapter_count")
    item = view.table.item(0, chapter_col)
    assert item is not None
    assert item.text() == "2 chapters"
    assert item.data(Qt.ItemDataRole.UserRole) == 2

    view._show_column("chapter_summary")
    summary_col = view._columns.index("chapter_summary")
    qtbot.waitUntil(lambda: view.table.item(0, summary_col) is not None, timeout=2000)
    summary_item = view.table.item(0, summary_col)
    assert summary_item is not None
    assert summary_item.text() == "Intro, Main"


def test_edit_action_label_includes_selection_count(qtbot) -> None:
    view = _mount_list(qtbot)

    assert view._edit_action_label([{"db_track_id": 1}]) == "Edit (1)"
    assert view._edit_action_label([{"db_track_id": 1}, {"db_track_id": 2}, {"db_track_id": 3}]) == "Edit (3)"


def test_edit_action_is_only_available_for_ready_ipod_tracks(qtbot) -> None:
    cache = _LibraryCache()
    view = _mount_list(qtbot, library_cache=cache)

    assert view._can_edit_selected_tracks([{"db_track_id": 1, "Title": "Track"}])
    assert not view._can_edit_selected_tracks([{"Title": "No persistent id"}])

    pc_view = _mount_list(qtbot, library_cache=cache, content_type_override="pc_tracks")
    assert not pc_view._can_edit_selected_tracks([{"db_track_id": 1, "Title": "PC Track"}])


def test_track_file_resolution_uses_current_device_path(qtbot, tmp_path: Path) -> None:
    track_path = tmp_path / "iPod_Control" / "Music" / "F00" / "Song.mp3"
    track_path.parent.mkdir(parents=True)
    track_path.write_bytes(b"audio")
    view = _mount_list(
        qtbot,
        device_sessions=_DeviceSessions(_Session(device_path=str(tmp_path))),
    )

    paths = view._resolved_track_file_paths(
        [{"Location": ":iPod_Control:Music:F00:Song.mp3"}]
    )

    assert paths == [str(track_path)]


def test_open_track_file_actions_open_resolved_file(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    track_path = tmp_path / "iPod_Control" / "Music" / "F00" / "Song.mp3"
    track_path.parent.mkdir(parents=True)
    track_path.write_bytes(b"audio")
    view = _mount_list(
        qtbot,
        device_sessions=_DeviceSessions(_Session(device_path=str(tmp_path))),
    )
    opened: list[list[str]] = []
    picked: list[tuple[list[str], MusicBrowserList]] = []
    monkeypatch.setattr(
        "iopenpod.gui.widgets.MBListView.open_files_with_default_app",
        lambda paths: opened.append(list(paths)) or True,
    )
    monkeypatch.setattr(
        "iopenpod.gui.widgets.MBListView.open_files_with_app_picker",
        lambda paths, parent: picked.append((list(paths), parent)) or True,
    )

    menu = QMenu(view)
    view._add_open_file_actions(menu, [{"Location": ":iPod_Control:Music:F00:Song.mp3"}])
    actions = menu.actions()

    assert actions[0].text() == f"Open Track File\t{_OPEN_TRACK_SHORTCUT}"
    assert actions[0].isEnabled()
    assert actions[1].text() == f"Open With...\t{_OPEN_WITH_TRACK_SHORTCUT}"
    assert actions[1].isEnabled()

    actions[0].trigger()
    actions[1].trigger()

    assert opened == [[str(track_path)]]
    assert picked == [([str(track_path)], view)]


def test_open_track_file_actions_disable_missing_files(qtbot, tmp_path: Path) -> None:
    view = _mount_list(
        qtbot,
        device_sessions=_DeviceSessions(_Session(device_path=str(tmp_path))),
    )
    menu = QMenu(view)

    view._add_open_file_actions(menu, [{"Location": ":iPod_Control:Music:F00:Missing.mp3"}])
    actions = menu.actions()

    assert actions[0].text() == f"Open Track File\t{_OPEN_TRACK_SHORTCUT}"
    assert not actions[0].isEnabled()
    assert actions[1].text() == f"Open With...\t{_OPEN_WITH_TRACK_SHORTCUT}"
    assert not actions[1].isEnabled()


def test_open_with_action_uses_one_picker_for_multiple_tracks(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_path = tmp_path / "iPod_Control" / "Music" / "F00" / "One.mp3"
    second_path = tmp_path / "iPod_Control" / "Music" / "F01" / "Two.mp3"
    first_path.parent.mkdir(parents=True)
    second_path.parent.mkdir(parents=True)
    first_path.write_bytes(b"audio")
    second_path.write_bytes(b"audio")
    view = _mount_list(
        qtbot,
        device_sessions=_DeviceSessions(_Session(device_path=str(tmp_path))),
    )
    picked: list[tuple[list[str], MusicBrowserList]] = []
    monkeypatch.setattr(
        "iopenpod.gui.widgets.MBListView.open_files_with_app_picker",
        lambda paths, parent: picked.append((list(paths), parent)) or True,
    )
    menu = QMenu(view)

    view._add_open_file_actions(
        menu,
        [
            {"Location": ":iPod_Control:Music:F00:One.mp3"},
            {"Location": ":iPod_Control:Music:F01:Two.mp3"},
        ],
    )
    actions = menu.actions()

    assert actions[0].text() == f"Open 2 Track Files\t{_OPEN_TRACK_SHORTCUT}"
    assert actions[0].isEnabled()
    assert actions[1].text() == f"Open With...\t{_OPEN_WITH_TRACK_SHORTCUT}"
    assert actions[1].isEnabled()

    actions[1].trigger()

    assert picked == [([str(first_path), str(second_path)], view)]


def test_open_track_shortcut_labels_use_platform_controls() -> None:
    if sys.platform == "darwin":
        assert _OPEN_TRACK_SHORTCUT == "⌘+O"
        assert _OPEN_WITH_TRACK_SHORTCUT == "⌘+⇧+O"
    else:
        assert _OPEN_TRACK_SHORTCUT == "Ctrl+O"
        assert _OPEN_WITH_TRACK_SHORTCUT == "Ctrl+Shift+O"


def test_open_track_keyboard_shortcuts_route_to_open_handlers(
    qtbot,
    monkeypatch,
) -> None:
    view = _mount_list(qtbot)
    opened: list[str] = []
    picked: list[str] = []
    monkeypatch.setattr(
        view,
        "_open_selected_track_files",
        lambda: opened.append("open"),
    )
    monkeypatch.setattr(
        view,
        "_open_selected_track_file_with_picker",
        lambda: picked.append("open-with"),
    )

    open_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_O,
        Qt.KeyboardModifier.ControlModifier,
    )
    open_with_event = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_O,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )

    assert view.eventFilter(view.table, open_event) is True
    assert view.eventFilter(view.table, open_with_event) is True
    assert opened == ["open"]
    assert picked == ["open-with"]


@pytest.mark.parametrize(
    ("key", "modifier"),
    [
        (Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier),
        (Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier),
        (Qt.Key.Key_Shift, Qt.KeyboardModifier.ShiftModifier),
        (Qt.Key.Key_Meta, Qt.KeyboardModifier.MetaModifier),
    ],
)
def test_modifier_only_keypresses_do_not_trigger_table_shortcuts(
    qtbot,
    key: Qt.Key,
    modifier: Qt.KeyboardModifier,
) -> None:
    view = _mount_list(qtbot)
    event = QKeyEvent(QEvent.Type.KeyPress, key, modifier)

    assert view.eventFilter(view.table, event) is False


def test_podcast_conversion_changes_set_ipod_podcast_fields() -> None:
    track = {
        "db_track_id": 1,
        "Title": "Episode",
        "Artist": "Host",
        "Album": "Example Show",
        "Genre": "Comedy",
        "media_type": 0x01,
        "play_count_1": 0,
        "skip_when_shuffling": 0,
        "remember_position": 0,
        "use_podcast_now_playing_flag": 0,
    }

    assert podcast_conversion_changes_for_track(track) == {
        "media_type": 0x04,
        "use_podcast_now_playing_flag": 1,
        "podcast_flag": 1,
        "skip_when_shuffling": 1,
        "remember_position": 1,
        "not_played_flag": 2,
        "Category": "Comedy",
        "Show": "Example Show",
    }


def test_convert_to_podcast_action_stages_per_track_updates(qtbot) -> None:
    cache = _LibraryCache()
    view = _mount_list(qtbot, library_cache=cache)
    track = {
        "db_track_id": 1001,
        "Title": "Episode",
        "Artist": "Host",
        "Album": "",
        "Genre": "",
        "media_type": 0x01,
        "play_count_1": 3,
        "skip_when_shuffling": 0,
        "remember_position": 0,
        "use_podcast_now_playing_flag": 0,
    }

    view._convert_tracks_to_podcast([track])

    assert cache.updated_by_track == [
        (
            [track],
            {
                id(track): {
                    "media_type": 0x04,
                    "use_podcast_now_playing_flag": 1,
                    "podcast_flag": 1,
                    "skip_when_shuffling": 1,
                    "remember_position": 1,
                    "not_played_flag": 1,
                    "Category": "Podcast",
                    "Genre": "Podcast",
                    "Album": "Host",
                    "Show": "Host",
                }
            },
        )
    ]
    assert track["media_type"] == 0x04
    assert track["use_podcast_now_playing_flag"] == 1
    assert track["skip_when_shuffling"] == 1
    assert track["remember_position"] == 1


def test_convert_to_podcast_action_disables_ready_podcasts(qtbot) -> None:
    cache = _LibraryCache()
    view = _mount_list(qtbot, library_cache=cache)
    menu = QMenu(view)
    ready_track = {
        "db_track_id": 1,
        "Title": "Episode",
        "media_type": 0x04,
        "use_podcast_now_playing_flag": 1,
        "skip_when_shuffling": 1,
        "remember_position": 1,
    }

    act = view._add_convert_to_podcast_action(menu, [ready_track])

    assert act is not None
    assert act.text() == "Convert to Podcast"
    assert not act.isEnabled()


def test_album_group_menu_differs_from_track_menu_only_by_conversion_action(qtbot) -> None:
    cache = _LibraryCache()
    view = _mount_list(qtbot, library_cache=cache)
    tracks = [
        {"db_track_id": 1, "Title": "One"},
        {"db_track_id": 2, "Title": "Two"},
    ]

    track_menu = build_track_context_menu(view, view, tracks)
    album_menu = build_track_context_menu(
        view,
        view,
        tracks,
        chaptered_album_action=ChapteredAlbumMenuAction(
            items=({"category": "Albums", "track_count": 2},),
            requested=lambda _items: None,
        ),
    )

    track_actions = [
        action.text() for action in track_menu.actions() if not action.isSeparator()
    ]
    album_actions = [
        action.text() for action in album_menu.actions() if not action.isSeparator()
    ]
    conversion_label = "Convert to a single chaptered track"
    conversion_index = album_actions.index(conversion_label)

    assert (
        album_actions[:conversion_index] + album_actions[conversion_index + 1 :]
        == track_actions
    )


def test_shared_menu_actions_use_explicit_group_track_selection(qtbot) -> None:
    cache = _LibraryCache()
    view = _mount_list(qtbot, library_cache=cache)
    group_tracks = [
        {"db_track_id": 1, "Title": "One", "rating": 0},
        {"db_track_id": 2, "Title": "Two", "rating": 20},
    ]
    removed: list[list[dict]] = []
    view.remove_from_ipod_requested.connect(removed.append)

    menu = build_track_context_menu(view, view, group_tracks)
    rating_menu = next(
        action.menu()
        for action in menu.actions()
        if action.menu() is not None and action.text() == "Rating"
    )
    assert rating_menu is not None
    five_stars = next(
        action for action in rating_menu.actions() if action.text().strip() == "★★★★★"
    )
    remove_action = next(
        action
        for action in menu.actions()
        if action.text() == "Remove 2 Tracks from iPod"
    )

    five_stars.trigger()
    remove_action.trigger()

    assert cache.updated[-1] == (group_tracks, {"rating": 100})
    assert removed == [group_tracks]


def test_rating_context_menu_shows_mixed_selection_header(qtbot) -> None:
    cache = _LibraryCache()
    view = _mount_list(qtbot, library_cache=cache)
    tracks = [
        {"db_track_id": 1, "Title": "One", "rating": 20},
        {"db_track_id": 2, "Title": "Two", "rating": 80},
    ]

    menu = QMenu(view)
    view._build_rating_menu(menu, "", tracks, cache)
    rating_menu = menu.actions()[0].menu()
    assert rating_menu is not None

    actions = rating_menu.actions()
    assert actions[0].text() == "(mixed selection)"
    assert not actions[0].isEnabled()
    assert actions[1].isSeparator()
    assert actions[2].text() == "   No Rating"


def test_rating_context_menu_omits_mixed_header_for_unanimous_selection(qtbot) -> None:
    cache = _LibraryCache()
    view = _mount_list(qtbot, library_cache=cache)
    tracks = [
        {"db_track_id": 1, "Title": "One", "rating": 80},
        {"db_track_id": 2, "Title": "Two", "rating": 80},
    ]

    menu = QMenu(view)
    view._build_rating_menu(menu, "", tracks, cache)
    rating_menu = menu.actions()[0].menu()
    assert rating_menu is not None

    actions = rating_menu.actions()
    assert actions[0].text() == "   No Rating"
    assert actions[4].text() == "✓ ★★★★"


def test_volume_context_menu_uses_slider_widget(qtbot) -> None:
    cache = _LibraryCache()
    view = _mount_list(qtbot, library_cache=cache)
    tracks = [
        {"db_track_id": 1, "Title": "One", "volume": 64},
        {"db_track_id": 2, "Title": "Two", "volume": 64},
    ]

    menu = QMenu(view)
    view._build_volume_menu(menu, "", tracks)

    volume_menu = menu.actions()[0].menu()
    assert volume_menu is not None
    assert volume_menu.title() == "Volume Adjustment"
    assert len(volume_menu.actions()) == 1

    widget = cast(Any, volume_menu.actions()[0]).defaultWidget()
    assert widget is not None
    slider = widget.findChild(QSlider, "volumeAdjustmentSlider")
    value_label = widget.findChild(QLabel, "volumeAdjustmentValueLabel")
    assert slider is not None
    assert value_label is not None
    assert slider.minimum() == -255
    assert slider.maximum() == 255
    assert slider.value() == 64
    assert value_label.text() == "+25%"

    slider.setValue(128)

    assert value_label.text() == "+50%"
    assert cache.updated[-1] == (tracks, {"volume": 128})


def test_volume_context_menu_mixed_selection_can_commit_zero(qtbot) -> None:
    cache = _LibraryCache()
    view = _mount_list(qtbot, library_cache=cache)
    tracks = [
        {"db_track_id": 1, "Title": "One", "volume": -64},
        {"db_track_id": 2, "Title": "Two", "volume": 64},
    ]

    menu = QMenu(view)
    view._build_volume_menu(menu, "", tracks)
    volume_menu = menu.actions()[0].menu()
    assert volume_menu is not None
    widget = cast(Any, volume_menu.actions()[0]).defaultWidget()
    assert widget is not None
    slider = widget.findChild(QSlider, "volumeAdjustmentSlider")
    value_label = widget.findChild(QLabel, "volumeAdjustmentValueLabel")
    assert slider is not None
    assert value_label is not None

    assert slider.value() == 0
    assert value_label.text() == "Mixed values"

    slider.sliderReleased.emit()

    assert value_label.text() == "No adjustment (0%)"
    assert cache.updated[-1] == (tracks, {"volume": 0})


def test_volume_context_menu_slider_zero_is_magnetic(qtbot) -> None:
    cache = _LibraryCache()
    view = _mount_list(qtbot, library_cache=cache)
    tracks = [{"db_track_id": 1, "Title": "One", "volume": 64}]

    menu = QMenu(view)
    view._build_volume_menu(menu, "", tracks)
    volume_menu = menu.actions()[0].menu()
    assert volume_menu is not None
    widget = cast(Any, volume_menu.actions()[0]).defaultWidget()
    assert widget is not None
    slider = widget.findChild(QSlider, "volumeAdjustmentSlider")
    value_label = widget.findChild(QLabel, "volumeAdjustmentValueLabel")
    assert slider is not None
    assert value_label is not None

    slider.sliderMoved.emit(8)

    assert slider.sliderPosition() == 0
    assert value_label.text() == "No adjustment (0%)"
    assert cache.updated == []

    slider.setValue(8)

    assert slider.value() == 0
    assert cache.updated[-1] == (tracks, {"volume": 0})

    slider.setValue(13)

    assert slider.value() == 13
    assert value_label.text() == "+5%"
    assert cache.updated[-1] == (tracks, {"volume": 13})


def test_apply_track_edits_updates_cache_and_visible_row(qtbot) -> None:
    cache = _LibraryCache()
    view = _mount_list(qtbot, library_cache=cache)
    tracks = [
        {
            "db_track_id": 1001,
            "Title": "Song A",
            "Artist": "Artist A",
            "Album": "Album A",
            "Genre": "Rock",
            "year": 2001,
            "track_number": 1,
            "length": 180000,
            "rating": 80,
            "play_count_1": 5,
            "date_added": 1710000000,
        }
    ]
    _load_content(qtbot, view, tracks=tracks, media_type_filter=0x01)

    view._apply_track_edits([tracks[0]], {"Artist": "Edited Artist", "rating": 100})

    assert cache.updated == [([tracks[0]], {"Artist": "Edited Artist", "rating": 100})]
    assert tracks[0]["Artist"] == "Edited Artist"
    artist_item = view.table.item(0, 1)
    rating_item = view.table.item(0, 7)
    assert artist_item is not None
    assert rating_item is not None
    assert artist_item.text() == "Edited Artist"
    assert rating_item.text() == "★★★★★"


def test_track_editor_dialog_collects_modified_field_changes(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {"db_track_id": 1, "Title": "One", "Artist": "Shared"},
            {"db_track_id": 2, "Title": "Two", "Artist": "Shared"},
        ]
    )
    qtbot.addWidget(dialog)

    title_row = next(row for row in dialog._rows if row.spec.key == "Title")
    artist_row = next(row for row in dialog._rows if row.spec.key == "Artist")
    artist_editor = cast(QLineEdit, artist_row.editor)
    artist_editor.setText("Edited Artist")

    assert not title_row.is_modified()
    assert dialog.changes() == {"Artist": "Edited Artist"}


def test_track_editor_dialog_reset_restores_mixed_field(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {"db_track_id": 1, "Title": "One"},
            {"db_track_id": 2, "Title": "Two"},
        ]
    )
    qtbot.addWidget(dialog)

    title_row = next(row for row in dialog._rows if row.spec.key == "Title")
    title_editor = cast(QLineEdit, title_row.editor)

    title_editor.setText("Unified Title")
    assert title_row.is_modified()
    assert dialog.changes() == {"Title": "Unified Title"}

    title_row.reset_button.click()
    assert not title_row.is_modified()
    assert title_editor.text() == ""
    assert title_editor.placeholderText() == "Mixed values"
    assert dialog.changes() == {}


def test_track_editor_dialog_uses_known_mhit_value_domains(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "One",
                "explicit_flag": 2,
                "checked_flag": 0,
                "not_played_flag": 2,
                "media_type": 0x40,
            },
        ]
    )
    qtbot.addWidget(dialog)

    explicit_row = next(row for row in dialog._rows if row.spec.key == "explicit_flag")
    checked_row = next(row for row in dialog._rows if row.spec.key == "checked_flag")
    played_row = next(row for row in dialog._rows if row.spec.key == "not_played_flag")
    media_row = next(row for row in dialog._rows if row.spec.key == "media_type")

    explicit_combo = cast(QComboBox, explicit_row.editor)
    checked_combo = cast(QComboBox, checked_row.editor)
    played_combo = cast(QComboBox, played_row.editor)
    media_combo = cast(QComboBox, media_row.editor)

    assert explicit_row.spec.editable
    assert explicit_combo.currentData() == 2
    assert explicit_combo.currentText() == "Clean"
    assert checked_combo.itemData(0) == 0
    assert checked_combo.itemData(1) == 1
    assert played_combo.currentData() == 2
    assert media_combo.currentData() == 0x40


def test_track_editor_dialog_checked_flag_uses_checkbox_wording(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "One",
                "checked_flag": 0,
            },
        ]
    )
    qtbot.addWidget(dialog)

    checked_row = next(row for row in dialog._rows if row.spec.key == "checked_flag")
    checked_combo = cast(QComboBox, checked_row.editor)

    assert checked_row.spec.label == "Checked"
    assert checked_combo.itemText(0) == "Checked (0)"
    assert checked_combo.itemText(1) == "Unchecked (1)"
    assert "does not control normal playback" in checked_row.spec.help_text


def test_track_artwork_previews_collect_assigned_artwork_and_formats(tmp_path, monkeypatch) -> None:
    def _container(format_id: int, width: int, height: int) -> dict[str, object]:
        return {
            "Thumbnail Image": {
                "result": {
                    "correlationID": format_id,
                    "ithmbOffset": format_id,
                    "imgSize": width * height * 2,
                    "imageWidth": width,
                    "imageHeight": height,
                    "image_format": {
                        "format_id": format_id,
                        "width": width,
                        "height": height,
                        "format": "RGB565_LE",
                        "description": f"Format {format_id}",
                    },
                    "3": {"File Name": f":F{format_id}_1.ithmb"},
                }
            }
        }

    def _fake_generate_image(_path, image_info):
        return Image.new(
            "RGBA",
            (image_info["imageWidth"], image_info["imageHeight"]),
            (image_info["correlationID"] % 255, 0, 0, 255),
        )

    monkeypatch.setattr(imgMaker, "generate_image", _fake_generate_image)
    artworkdb = {
        "mhli": [
            {
                "img_id": 100,
                "songId": 1,
                "_image_containers": [_container(101, 20, 20), _container(102, 40, 40)],
            },
            {
                "img_id": 101,
                "songId": 1,
                "_image_containers": [_container(103, 30, 30)],
            },
        ]
    }

    previews = get_track_artwork_previews(
        {"db_track_id": 1, "artwork_id_ref": 100},
        artworkdb_data=artworkdb,
        artwork_folder_path=str(tmp_path),
        img_id_index={100: artworkdb["mhli"][0], 101: artworkdb["mhli"][1]},
    )

    assert [preview.img_id for preview in previews] == [100, 101]
    assert ("img_id", "100") in previews[0].metadata
    assert [variant.format_id for variant in previews[0].variants] == [102, 101]
    assert ("Thumbnail Image.result.correlationID", "102") in previews[0].variants[0].metadata
    assert [variant.format_id for variant in previews[1].variants] == [103]


def test_track_editor_dialog_artwork_panel_collapses_matching_artworks(qtbot, monkeypatch) -> None:
    red = Image.new("RGBA", (20, 20), (255, 0, 0, 255))
    blue = Image.new("RGBA", (30, 30), (0, 0, 255, 255))
    previews = [
        TrackArtworkPreview(
            img_id=100,
            song_id=1,
            variants=(
                ArtworkFormatPreview(101, "101 20x20", "Small", 20, 20, "RGB565_LE", 800, "F101_1.ithmb", 0, red, (("Thumbnail Image.result.correlationID", "101"),)),
                ArtworkFormatPreview(102, "102 30x30", "Large", 30, 30, "RGB565_LE", 1800, "F102_1.ithmb", 10, blue, (("Thumbnail Image.result.correlationID", "102"),)),
            ),
            metadata=(("img_id", "100"), ("songId", "1")),
        ),
        TrackArtworkPreview(
            img_id=101,
            song_id=1,
            variants=(
                ArtworkFormatPreview(103, "103 30x30", "Other", 30, 30, "RGB565_LE", 1800, "F103_1.ithmb", 20, blue.copy(), (("Thumbnail Image.result.correlationID", "103"),)),
            ),
            metadata=(("img_id", "101"), ("songId", "1")),
        ),
    ]
    monkeypatch.setattr(
        "iopenpod.gui.widgets.trackEditorDialog.get_track_artwork_previews",
        lambda _tracks: previews,
    )

    dialog = TrackEditorDialog([{"db_track_id": 1, "Title": "One", "artwork_id_ref": 100}])
    qtbot.addWidget(dialog)

    panel = dialog.findChild(_ArtworkPreviewPanel)
    assert panel is not None
    assert not hasattr(panel, "_prev_btn")
    assert not hasattr(panel, "_next_btn")
    assert not hasattr(panel, "_counter_label")
    assert "Format 101" in panel._meta_label.text()
    assert _tree_child_text(panel._metadata_tree, 0, 0, 0) == "img_id"
    assert _tree_child_text(panel._metadata_tree, 0, 0, 1) == "100"

    format_102 = next(button for button in panel.findChildren(QPushButton) if button.text() == "102 30x30")
    format_102.click()
    assert "Format 102" in panel._meta_label.text()
    assert _tree_child_text(panel._metadata_tree, 1, 0, 1) == "102"


def test_track_editor_dialog_artwork_panel_shows_multiple_images_for_different_art(qtbot, monkeypatch) -> None:
    red = Image.new("RGBA", (20, 20), (255, 0, 0, 255))
    blue = Image.new("RGBA", (20, 20), (0, 0, 255, 255))
    previews = [
        TrackArtworkPreview(
            img_id=100,
            song_id=1,
            variants=(
                ArtworkFormatPreview(101, "101 20x20", "Small", 20, 20, "RGB565_LE", 800, "F101_1.ithmb", 0, red, (("Thumbnail Image.result.correlationID", "101"), ("format", "Small"))),
            ),
            metadata=(("img_id", "100"), ("songId", "1"), ("kind", "Cover")),
        ),
        TrackArtworkPreview(
            img_id=101,
            song_id=2,
            variants=(
                ArtworkFormatPreview(102, "102 20x20", "Small", 20, 20, "RGB565_LE", 800, "F102_1.ithmb", 0, blue, (("Thumbnail Image.result.correlationID", "102"), ("format", "Small"))),
            ),
            metadata=(("img_id", "101"), ("songId", "2"), ("kind", "Cover")),
        ),
    ]
    monkeypatch.setattr(
        "iopenpod.gui.widgets.trackEditorDialog.get_track_artwork_previews",
        lambda _tracks: previews,
    )

    dialog = TrackEditorDialog([
        {"db_track_id": 1, "Title": "One", "artwork_id_ref": 100},
        {"db_track_id": 2, "Title": "Two", "artwork_id_ref": 101},
    ])
    qtbot.addWidget(dialog)

    panel = dialog.findChild(_ArtworkPreviewPanel)
    assert panel is not None
    assert panel._image_label.text() == "Multiple images"
    assert panel._image_label.pixmap().isNull()
    assert "different assigned artwork" in panel._meta_label.text()
    assert not panel._unify_btn.isHidden()
    context = panel.unify_context()
    assert context is not None
    assert len(context.choices) == 2
    assert _tree_child_value_for_key(panel._metadata_tree, 0, "img_id") == "mixed value"
    assert _tree_child_value_for_key(panel._metadata_tree, 0, "kind") == "Cover"
    assert _tree_child_value_for_key(panel._metadata_tree, 1, "Thumbnail Image.result.correlationID") == "mixed value"
    assert _tree_child_value_for_key(panel._metadata_tree, 1, "format") == "Small"
    assert not any(button.text().startswith(("101", "102")) for button in panel.findChildren(QPushButton))


def test_track_editor_dialog_artwork_panel_shows_multiple_values_for_artwork_presence_mix(qtbot, monkeypatch, tmp_path) -> None:
    red = Image.new("RGBA", (20, 20), (255, 0, 0, 255))
    previews = [
        TrackArtworkPreview(
            img_id=100,
            song_id=1,
            variants=(
                ArtworkFormatPreview(101, "101 20x20", "Small", 20, 20, "RGB565_LE", 800, "F101_1.ithmb", 0, red, (("Thumbnail Image.result.correlationID", "101"), ("format", "Small"))),
            ),
            metadata=(("img_id", "100"), ("songId", "1"), ("kind", "Cover")),
        ),
    ]
    monkeypatch.setattr(
        "iopenpod.gui.widgets.trackEditorDialog.get_track_artwork_previews",
        lambda _tracks: previews,
    )

    dialog = TrackEditorDialog([
        {"db_track_id": 1, "Title": "One", "artwork_id_ref": 100},
        {"db_track_id": 2, "Title": "Two", "has_artwork": 1, "artwork_count": 1},
    ])
    qtbot.addWidget(dialog)

    panel = dialog.findChild(_ArtworkPreviewPanel)
    assert panel is not None
    assert panel._image_label.text() == "Multiple values"
    assert panel._image_label.pixmap().isNull()
    assert "have artwork and some do not" in panel._meta_label.text()
    assert not panel._unify_btn.isHidden()
    context = panel.unify_context()
    assert context is not None
    assert len(context.choices) == 1
    assert context.missing_count == 1
    assert _tree_child_value_for_key(panel._metadata_tree, 0, "img_id") == "mixed value"
    assert _tree_child_value_for_key(panel._metadata_tree, 0, "kind") == "mixed value"
    assert _tree_child_value_for_key(panel._metadata_tree, 1, "format") == "mixed value"
    assert not any(button.text().startswith("101") for button in panel.findChildren(QPushButton))

    staged_path = tmp_path / "unified.png"
    staged_path.write_bytes(b"image")

    class _Dialog:
        def __init__(self, context, _parent=None) -> None:
            self._context = context

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_choice(self):
            return self._context.choices[0]

    monkeypatch.setattr("iopenpod.gui.widgets.trackEditorDialog.UnifyArtworkDialog", _Dialog)
    monkeypatch.setattr(
        "iopenpod.gui.widgets.trackEditorDialog.save_unified_artwork_temp",
        lambda _image: str(staged_path),
    )

    dialog._unify_artwork()

    assert dialog.artwork_path() is None
    assert dialog._pending_artwork_path == str(staged_path)
    assert panel._title_label.text() == "New Artwork"
    assert "pending apply" in panel._meta_label.text()
    assert panel._unify_btn.isHidden()


def test_square_crop_canvas_returns_square_output(qtbot) -> None:
    canvas = _SquareCropCanvas(Image.new("RGB", (320, 180), (255, 0, 0)))
    qtbot.addWidget(canvas)
    canvas.resize(420, 420)
    canvas.reset_view()
    canvas.set_zoom_fraction(0.5)

    cropped = canvas.cropped_image()

    assert cropped.size == (1200, 1200)


def test_track_editor_dialog_marks_structural_fields_read_only(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "One",
                "Location": ":iPod_Control:Music:F00:one.mp3",
                "size": 1234,
                "has_artwork": 1,
            },
        ]
    )
    qtbot.addWidget(dialog)

    location_row = next(row for row in dialog._rows if row.spec.key == "Location")
    size_row = next(row for row in dialog._rows if row.spec.key == "size")
    artwork_row = next(row for row in dialog._rows if row.spec.key == "has_artwork")

    location_editor = cast(QLineEdit, location_row.editor)
    size_editor = cast(QLineEdit, size_row.editor)
    artwork_combo = cast(QComboBox, artwork_row.editor)

    assert not location_row.spec.editable
    assert not size_row.spec.editable
    assert not artwork_row.spec.editable
    assert location_editor.isReadOnly()
    assert size_editor.isReadOnly()
    assert not artwork_combo.isEnabled()
    assert artwork_combo.currentData() == 1


def test_track_editor_dialog_edits_existing_chapters(qtbot) -> None:
    chapter_data = {
        "unk024": 0,
        "unk028": 0,
        "unk032": 0,
        "chapters": [
            {"startpos": 0, "title": "Intro"},
            {"startpos": 61_000, "title": "Act One"},
        ],
    }
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "Chaptered Album",
                "chapter_data": chapter_data,
            },
        ]
    )
    qtbot.addWidget(dialog)

    chapter_rows = [row for row in dialog._rows if row.spec.group == "Chapters"]
    keys = {row.spec.key for row in chapter_rows}
    assert keys == {"chapter_data"}

    data_row = next(row for row in chapter_rows if row.spec.key == "chapter_data")
    timeline = cast(_ChapterTimelineEditor, data_row.editor)

    assert data_row.spec.editable
    assert data_row.spec.kind == "chapters"
    assert timeline._table.rowCount() == 2
    assert _table_item(timeline._table, 0, 0).text() == "0:00"
    assert _table_item(timeline._table, 0, 1).text() == "Intro"
    assert _table_item(timeline._table, 1, 0).text() == "1:01"
    assert _table_item(timeline._table, 1, 1).text() == "Act One"
    assert dialog.changes() == {}

    _table_item(timeline._table, 1, 0).setText("1:02.500")
    _table_item(timeline._table, 1, 1).setText("Act I")

    assert data_row.is_modified()
    assert dialog.changes() == {
        "chapter_data": {
            "unk024": 0,
            "unk028": 0,
            "unk032": 0,
            "chapters": [
                {"startpos": 0, "title": "Intro"},
                {"startpos": 62_500, "title": "Act I"},
            ],
        }
    }


def test_chapter_table_editor_is_opaque_and_selects_current_text(qtbot) -> None:
    timeline = _ChapterTimelineEditor(
        {
            "chapters": [
                {"startpos": 0, "title": "Intro"},
            ],
        }
    )
    qtbot.addWidget(timeline)
    timeline.show()

    title_item = _table_item(timeline._table, 0, 1)
    timeline._table.setCurrentItem(title_item)
    timeline._table.editItem(title_item)

    qtbot.waitUntil(lambda: timeline._table.findChild(QLineEdit) is not None, timeout=1000)
    editor = timeline._table.findChild(QLineEdit)
    assert editor is not None
    assert f"background-color: {Colors.DROPDOWN_BG}" in editor.styleSheet()
    assert Colors.SURFACE_ALT not in editor.styleSheet()
    qtbot.waitUntil(lambda: editor.selectedText() == "Intro", timeout=1000)


def test_chapter_table_time_entry_shows_format_hints_and_has_room(qtbot) -> None:
    timeline = _ChapterTimelineEditor(
        {
            "chapters": [
                {"startpos": 3_723_500, "title": "Deep Cut"},
            ],
        }
    )
    qtbot.addWidget(timeline)
    timeline.show()

    assert "62500ms" in timeline._time_hint.text()
    assert timeline._table.columnWidth(0) >= 150
    start_header = timeline._table.horizontalHeaderItem(0)
    assert start_header is not None
    assert start_header.text() == "Start Time"
    assert "offsets from the beginning" in start_header.toolTip()

    start_item = _table_item(timeline._table, 0, 0)
    timeline._table.setCurrentItem(start_item)
    timeline._table.editItem(start_item)

    qtbot.waitUntil(lambda: timeline._table.findChild(QLineEdit) is not None, timeout=1000)
    editor = timeline._table.findChild(QLineEdit)
    assert editor is not None
    assert editor.placeholderText() == "0:00, 1:23.500, 62500ms"
    assert "1:02:03" in editor.toolTip()
    assert editor.minimumWidth() >= 150


def test_track_editor_dialog_adds_and_deletes_chapters(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "Plain Track",
            },
        ]
    )
    qtbot.addWidget(dialog)

    data_row = next(row for row in dialog._rows if row.spec.key == "chapter_data")
    timeline = cast(_ChapterTimelineEditor, data_row.editor)

    assert timeline._table.rowCount() == 0
    timeline._add_btn.click()
    assert timeline._table.rowCount() == 1
    _table_item(timeline._table, 0, 0).setText("0:30")
    _table_item(timeline._table, 0, 1).setText("Opening")

    timeline._add_btn.click()
    _table_item(timeline._table, 1, 0).setText("1:30")
    _table_item(timeline._table, 1, 1).setText("Main Part")

    timeline._table.selectRow(0)
    timeline._delete_btn.click()

    assert dialog.changes() == {
        "chapter_data": {
            "chapters": [
                {"startpos": 90_000, "title": "Main Part"},
            ],
        }
    }


def test_track_editor_dialog_rejects_out_of_order_chapters(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "Chaptered Album",
                "chapter_data": {
                    "chapters": [
                        {"startpos": 0, "title": "Intro"},
                        {"startpos": 61_000, "title": "Act One"},
                    ],
                },
            },
        ]
    )
    qtbot.addWidget(dialog)

    data_row = next(row for row in dialog._rows if row.spec.key == "chapter_data")
    timeline = cast(_ChapterTimelineEditor, data_row.editor)
    _table_item(timeline._table, 1, 0).setText("0:00")

    with pytest.raises(ValueError, match="ascending order"):
        data_row.value()


def test_track_editor_dialog_uses_eq_setting_field_key(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "One",
                "eq_setting": "Bass Booster",
            },
        ]
    )
    qtbot.addWidget(dialog)

    eq_rows = [row for row in dialog._rows if row.spec.key == "eq_setting"]

    assert [row.spec.key for row in eq_rows] == ["eq_setting"]
    eq_editor = cast(QLineEdit, eq_rows[0].editor)
    assert eq_editor.text() == "Bass Booster"


def test_track_editor_dialog_places_year_and_bpm_with_tags() -> None:
    assert _subgroup_for_key("Grouping", "Metadata") == "tags"
    assert _subgroup_for_key("year", "Metadata") == "tags"
    assert _subgroup_for_key("bpm", "Metadata") == "tags"


def test_track_editor_dialog_shows_unix_dates_as_readable_datetimes(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "One",
                "date_added": 1_710_000_000,
            },
        ]
    )
    qtbot.addWidget(dialog)

    date_row = next(row for row in dialog._rows if row.spec.key == "date_added")
    date_editor = cast(QLineEdit, date_row.editor)

    assert date_row.spec.kind == "date"
    assert date_editor.text() == _format_datetime_value(1_710_000_000)


def test_track_editor_dialog_parses_readable_datetimes_back_to_unix(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "One",
                "date_added": 1_710_000_000,
            },
        ]
    )
    qtbot.addWidget(dialog)

    date_row = next(row for row in dialog._rows if row.spec.key == "date_added")
    date_editor = cast(QLineEdit, date_row.editor)

    date_editor.setText(_format_datetime_value(1_710_000_600))

    assert date_row.is_modified()
    assert dialog.changes() == {"date_added": 1_710_000_600}


def test_track_editor_dialog_date_fields_still_accept_raw_unix_timestamps(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "One",
                "last_played": 1_710_000_000,
            },
        ]
    )
    qtbot.addWidget(dialog)

    played_row = next(row for row in dialog._rows if row.spec.key == "last_played")
    played_editor = cast(QLineEdit, played_row.editor)

    played_editor.setText("1710000600")

    assert played_row.is_modified()
    assert dialog.changes() == {"last_played": 1_710_000_600}


def test_track_editor_dialog_date_fields_accept_datetime_like_strings(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "One",
                "last_played": 1_710_000_000,
            },
        ]
    )
    qtbot.addWidget(dialog)

    played_row = next(row for row in dialog._rows if row.spec.key == "last_played")
    played_editor = cast(QLineEdit, played_row.editor)

    played_editor.setText("Mar 9 2024 5:30 pm")

    assert played_row.is_modified()
    assert dialog.changes() == {"last_played": _parse_datetime_text("Mar 9 2024 5:30 pm", "Last Played")}


def test_track_editor_dialog_rejects_unparseable_datetime_strings(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "One",
                "date_added": 1_710_000_000,
            },
        ]
    )
    qtbot.addWidget(dialog)

    date_row = next(row for row in dialog._rows if row.spec.key == "date_added")
    date_editor = cast(QLineEdit, date_row.editor)

    date_editor.setText("definitely not a date")

    with pytest.raises(ValueError, match="recognizable date/time"):
        date_row.value()


def test_track_editor_dialog_filter_restores_hidden_sections(qtbot) -> None:
    dialog = TrackEditorDialog(
        [
            {
                "db_track_id": 1,
                "Title": "One",
                "Artist": "Artist",
                "Comment": "Notes",
            },
        ]
    )
    qtbot.addWidget(dialog)

    title_row = next(row for row in dialog._rows if row.spec.key == "Title")
    comment_row = next(row for row in dialog._rows if row.spec.key == "Comment")
    comment_panel = next(panel for panel, rows in dialog._section_rows if comment_row in rows)

    dialog._apply_filter("Title")
    assert not title_row.isHidden()
    assert comment_row.isHidden()
    assert comment_panel.isHidden()

    dialog._apply_filter("")
    assert not title_row.isHidden()
    assert not comment_row.isHidden()
    assert not comment_panel.isHidden()


def test_track_editor_field_search_matches_symbol_variants(qtbot) -> None:
    row = _TrackFieldRow(
        TrackFieldSpec(
            key="artist_credit",
            label="Artist Credit",
            group="Metadata",
            help_text="The artist’s displayed credit",
        ),
        "",
    )
    qtbot.addWidget(row)

    assert row.matches("artist's")
