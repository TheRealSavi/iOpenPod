from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QHeaderView

from app_core.context import RuntimeSettingsService
from app_core.services import DeviceCapabilitySnapshot, DeviceIdentitySnapshot, DeviceManagerLike, DeviceSession, SettingsService, SettingsSnapshot
from GUI.widgets.MBListView import MusicBrowserList, build_new_regular_playlist
from infrastructure import settings_persistence
from infrastructure.settings_runtime import SettingsRuntime
from infrastructure.settings_schema import AppSettings, DeviceSettingsState

_QTEST: Any = QTest


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
    def __init__(self) -> None:
        self._manager = _DeviceManager()

    def current_session(self) -> DeviceSession:
        return cast(DeviceSession, _Session())

    def manager(self) -> DeviceManagerLike:
        return cast(DeviceManagerLike, self._manager)


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
) -> MusicBrowserList:
    view = MusicBrowserList(
        settings_service=settings_service or _SettingsService(),
        device_sessions=_DeviceSessions(),
        show_art_override=False,
    )
    qtbot.addWidget(view)
    view.resize(900, 500)
    view.show()
    qtbot.wait(50)
    return view


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
