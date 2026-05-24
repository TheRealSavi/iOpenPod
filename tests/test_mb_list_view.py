from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from PIL import Image
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QComboBox, QHeaderView, QLineEdit, QPushButton, QTreeWidget

from app_core.context import RuntimeSettingsService
from app_core.services import DeviceCapabilitySnapshot, DeviceIdentitySnapshot, DeviceManagerLike, DeviceSession, SettingsService, SettingsSnapshot
from GUI import imgMaker
from GUI.imgMaker import ArtworkFormatPreview, TrackArtworkPreview, get_track_artwork_previews
from GUI.widgets.MBListView import MusicBrowserList, build_new_regular_playlist
from GUI.widgets.trackEditorDialog import (
    TrackEditorDialog,
    _ArtworkPreviewPanel,
    _format_datetime_value,
    _parse_datetime_text,
    _SquareCropCanvas,
    _subgroup_for_key,
)
from infrastructure import settings_persistence
from infrastructure.settings_runtime import SettingsRuntime
from infrastructure.settings_schema import AppSettings, DeviceSettingsState

_QTEST: Any = QTest


def _tree_child_text(tree: QTreeWidget, section_index: int, child_index: int, column: int) -> str:
    section = tree.topLevelItem(section_index)
    assert section is not None
    child = section.child(child_index)
    assert child is not None
    return child.text(column)


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


class _Signal:
    def __init__(self) -> None:
        self.emit_count = 0

    def emit(self) -> None:
        self.emit_count += 1


class _LibraryCache:
    def __init__(self, *, ready: bool = True) -> None:
        self._ready = ready
        self.updated: list[tuple[list[dict], dict[str, object]]] = []
        self.playlist_quick_sync = _Signal()

    def is_ready(self) -> bool:
        return self._ready

    def get_playlists(self) -> list[dict]:
        return []

    def update_track_flags(self, tracks: list[dict], changes: dict[str, object]) -> None:
        self.updated.append((list(tracks), dict(changes)))
        for track in tracks:
            track.update(changes)


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
    library_cache: Any | None = None,
    content_type_override: str | None = None,
) -> MusicBrowserList:
    view = MusicBrowserList(
        settings_service=settings_service or _SettingsService(),
        device_sessions=_DeviceSessions(),
        library_cache=library_cache,
        show_art_override=False,
        content_type_override=content_type_override,
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


def test_track_editor_dialog_artwork_panel_switches_formats_and_artworks(qtbot, monkeypatch) -> None:
    red = Image.new("RGBA", (20, 20), (255, 0, 0, 255))
    blue = Image.new("RGBA", (30, 30), (0, 0, 255, 255))
    green = Image.new("RGBA", (40, 40), (0, 255, 0, 255))
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
                ArtworkFormatPreview(103, "103 40x40", "Other", 40, 40, "RGB565_LE", 3200, "F103_1.ithmb", 20, green, (("Thumbnail Image.result.correlationID", "103"),)),
            ),
            metadata=(("img_id", "101"), ("songId", "1")),
        ),
    ]
    monkeypatch.setattr(
        "GUI.widgets.trackEditorDialog.get_track_artwork_previews",
        lambda _tracks: previews,
    )

    dialog = TrackEditorDialog([{"db_track_id": 1, "Title": "One", "artwork_id_ref": 100}])
    qtbot.addWidget(dialog)

    panel = dialog.findChild(_ArtworkPreviewPanel)
    assert panel is not None
    assert panel._counter_label.text() == "1 of 2"
    assert "Format 101" in panel._meta_label.text()
    assert _tree_child_text(panel._metadata_tree, 0, 0, 0) == "img_id"
    assert _tree_child_text(panel._metadata_tree, 0, 0, 1) == "100"

    format_102 = next(button for button in panel.findChildren(QPushButton) if button.text() == "102 30x30")
    format_102.click()
    assert "Format 102" in panel._meta_label.text()
    assert _tree_child_text(panel._metadata_tree, 1, 0, 1) == "102"

    panel._next_btn.click()
    assert panel._counter_label.text() == "2 of 2"
    assert "Format 103" in panel._meta_label.text()
    assert _tree_child_text(panel._metadata_tree, 0, 0, 1) == "101"


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
