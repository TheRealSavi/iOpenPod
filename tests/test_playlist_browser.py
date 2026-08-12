from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any, cast

from PyQt6.QtCore import QByteArray, QMimeData, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel

from iopenpod.application import runtime
from iopenpod.application.services import (
    DeviceSessionService,
    LibraryService,
    SettingsService,
)
from iopenpod.application.smart_playlist_preview import SmartPlaylistPreviewResult
from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets import playlistBrowser as playlist_browser_module
from iopenpod.gui.widgets.playlistBrowser import (
    PlaylistBrowser,
    PlaylistInfoCard,
    PlaylistListPanel,
    _is_ipod_category_playlist,
    _is_regular_track_playlist,
    _is_user_smart_playlist,
    _playlist_parent_folder_options,
    _podcast_grouping_summary,
)
from iopenpod.gui.widgets.sidebarNavButton import SidebarNavButton
from iopenpod.itunesdb_shared.extraction import extract_playlist_item_extras


def test_dataset5_smart_playlist_is_not_treated_as_ipod_category() -> None:
    playlist = {
        "Title": "Recently Added",
        "_source": "smart",
        "mhsd5_type": 0,
        "smart_playlist_data": {"live_update": True},
    }

    assert not _is_ipod_category_playlist(playlist)
    assert _is_user_smart_playlist(playlist)


def test_dataset5_origin_is_internal_browsing_category_even_without_marker() -> None:
    playlist = {
        "Title": "Recently Added",
        "_source": "smart",
        "_mhsd_dataset_type": 5,
        "mhsd5_type": 0,
        "smart_playlist_data": {"live_update": True},
    }

    assert _is_ipod_category_playlist(playlist)
    assert not _is_user_smart_playlist(playlist)


def test_dataset5_browsing_category_is_not_treated_as_user_smart_playlist() -> None:
    playlist = {
        "Title": "Music",
        "_source": "category",
        "mhsd5_type": 4,
        "smart_playlist_data": {"live_update": True},
    }

    assert _is_ipod_category_playlist(playlist)
    assert not _is_user_smart_playlist(playlist)


def test_string_zero_mhsd5_type_stays_a_smart_playlist() -> None:
    playlist = {
        "Title": "Smart",
        "_source": "smart",
        "mhsd5_type": "0",
        "smart_playlist_data": {"live_update": True},
    }

    assert not _is_ipod_category_playlist(playlist)
    assert _is_user_smart_playlist(playlist)


def test_regular_track_playlist_excludes_generated_playlist_types() -> None:
    assert _is_regular_track_playlist({"Title": "Manual", "_source": "regular"})
    assert _is_regular_track_playlist({"Title": "Parsed Manual"})
    assert not _is_regular_track_playlist({"Title": "Library", "master_flag": 1})
    assert not _is_regular_track_playlist({"Title": "Music", "_source": "category", "mhsd5_type": 4})
    assert not _is_regular_track_playlist({"Title": "Smart", "smart_playlist_data": {"live_update": True}})
    assert _is_regular_track_playlist({
        "Title": "Type 3 Manual",
        "_source": "regular",
        "_mhsd_dataset_type": 3,
    })
    assert not _is_regular_track_playlist({"Title": "Podcasts", "podcast_flag": 1})
    assert not _is_regular_track_playlist({"Title": "Synced", "_source": "sync_playlist_file"})


def test_category_playlist_requires_dataset5_location() -> None:
    assert _is_ipod_category_playlist({
        "Title": "Music",
        "_source": "category",
        "_mhsd_dataset_type": 5,
        "mhsd5_type": 4,
    })
    assert not _is_ipod_category_playlist({
        "Title": "Suspicious Type 2",
        "_source": "regular",
        "_mhsd_dataset_type": 2,
        "mhsd5_type": 4,
    })


def test_playlist_item_extras_preserve_dataset3_group_title() -> None:
    assert extract_playlist_item_extras(
        [{"data": {"mhod_type": 1, "string": "The Show"}}]
    ) == {"podcast_group_title": "The Show"}


def test_dataset3_podcast_grouping_summary_uses_group_headers() -> None:
    playlist = {
        "_mhsd_dataset_type": 3,
        "Title": "Podcasts",
        "podcast_flag": 1,
        "items": [
            {
                "podcast_group_flag": 256,
                "group_id": 44,
                "track_id": 0,
                "podcast_group_title": "The Show",
            },
            {"track_id": 10, "group_id_ref": 44},
            {"track_id": 11, "group_id_ref": 44},
        ],
    }

    assert _podcast_grouping_summary(
        playlist,
        {
            10: {"Title": "Episode One"},
            11: {"Title": "Episode Two"},
        },
    ) == [
        {
            "group_id": 44,
            "title": "The Show",
            "count": 2,
            "preview_titles": ["Episode One", "Episode Two"],
        }
    ]


def test_podcast_flag_playlist_gets_podcast_section_even_when_display_merged(qtbot) -> None:
    panel = PlaylistListPanel()
    qtbot.addWidget(panel)

    panel.loadPlaylists([
        {
            "Title": "Manual",
            "playlist_id": 1,
            "_mhsd_dataset_type": 2,
            "_mhsd_display_types": [2],
        },
        {
            "Title": "Podcasts",
            "playlist_id": 2,
            "podcast_flag": 1,
            "_mhsd_dataset_type": 3,
            "_mhsd_display_merged": True,
            "_mhsd_display_types": [2, 3],
        },
    ])

    section_labels = [
        child.text()
        for child in panel.findChildren(QLabel)
        if child.text().endswith("PLAYLISTS")
    ]

    assert "REGULAR PLAYLISTS" in section_labels
    assert "PODCAST PLAYLISTS" in section_labels


def test_playlist_info_card_uses_named_quiet_and_danger_component_paints(qtbot) -> None:
    card = PlaylistInfoCard()
    qtbot.addWidget(card)

    assert paint_css("text.primary") in card.title_label.styleSheet()
    assert paint_css("control.quiet.hover_fill") in card.edit_btn.styleSheet()
    assert paint_css("status.danger.subtle_fill") in card.delete_btn.styleSheet()
    assert paint_css("status.danger.border") in card.delete_btn.styleSheet()


def test_playlist_info_card_shows_phase_game_flag_exact_value(qtbot) -> None:
    card = PlaylistInfoCard()
    qtbot.addWidget(card)

    card.showPlaylist({"Title": "Phase Music", "phase_game_flag": 25}, [])

    detail_text = [label.text() for label in card.findChildren(QLabel)]
    assert "Phase Game Flag" in detail_text
    assert "25 (0x0019; observed Phase Music value)" in detail_text


def test_playlist_list_renders_folder_hierarchy_and_selects_folder_aggregate(qtbot) -> None:
    panel = PlaylistListPanel()
    qtbot.addWidget(panel)
    folder = {
        "Title": "This is…",
        "playlist_id": 10,
        "is_folder": True,
        "podcast_flag": 0x0100,
        "items": [{"track_id": 101}, {"track_id": 102}],
        "mhip_child_count": 2,
    }
    panel.loadPlaylists(
        [
            folder,
            {
                "Title": "This is Mariah Carey",
                "playlist_id": 11,
                "parent_folder_playlist_id": 10,
                "smart_playlist_data": {"live_update": True},
            },
            {
                "Title": "Divas",
                "playlist_id": 12,
                "is_folder": True,
            },
            {
                "Title": "Whitney Houston",
                "playlist_id": 13,
                "parent_folder_playlist_id": 12,
            },
            {
                "Title": "Nested Divas",
                "playlist_id": 14,
                "is_folder": True,
                "parent_folder_playlist_id": 12,
            },
            {
                "Title": "Chaka Khan",
                "playlist_id": 15,
                "parent_folder_playlist_id": 14,
            },
            {"Title": "Road Trip", "playlist_id": 20},
        ]
    )

    buttons = panel.findChildren(SidebarNavButton)
    by_title = {button.toolTip().splitlines()[0]: button for button in buttons}

    assert by_title["This is…"].property("playlistDepth") == 0
    assert by_title["This is Mariah Carey"].property("playlistDepth") == 1
    assert by_title["Divas"].property("playlistDepth") == 0
    assert by_title["Whitney Houston"].property("playlistDepth") == 1
    assert by_title["Nested Divas"].property("playlistDepth") == 1
    assert by_title["Chaka Khan"].property("playlistDepth") == 2
    assert by_title["Road Trip"].property("playlistDepth") == 0

    with qtbot.waitSignal(panel.playlist_selected) as emitted:
        qtbot.mouseClick(by_title["This is…"], Qt.MouseButton.LeftButton)

    assert emitted.args == [folder]


def test_playlist_move_targets_exclude_self_and_descendants_and_show_paths() -> None:
    moving = {
        "Title": "Moving Folder",
        "playlist_id": 20,
        "is_folder": True,
        "parent_folder_playlist_id": 10,
    }
    playlists = [
        {"Title": "Root", "playlist_id": 10, "is_folder": True},
        moving,
        {
            "Title": "Child",
            "playlist_id": 30,
            "is_folder": True,
            "parent_folder_playlist_id": 20,
        },
        {"Title": "Cabinet", "playlist_id": 40, "is_folder": True},
        {
            "Title": "Shelf",
            "playlist_id": 50,
            "is_folder": True,
            "parent_folder_playlist_id": 40,
        },
    ]

    assert _playlist_parent_folder_options(moving, playlists) == [
        (40, "Cabinet"),
        (50, "Cabinet › Shelf"),
        (10, "Root"),
    ]


def test_playlist_context_menu_hides_move_when_no_valid_target_exists(qtbot) -> None:
    panel = PlaylistListPanel()
    qtbot.addWidget(panel)
    folder = {"Title": "Folder", "playlist_id": 10, "is_folder": True}
    child = {
        "Title": "Child",
        "playlist_id": 11,
        "parent_folder_playlist_id": 10,
    }
    panel.loadPlaylists([folder, child])
    folder_index = next(index for index, playlist in panel._playlist_map.items() if playlist is folder)

    menu = panel._build_context_menu(folder_index, panel)
    action_texts = [action.text() for action in menu.actions() if not action.isSeparator()]
    assert action_texts == ["Edit Folder…", "Delete Folder…"]


def test_playlist_context_move_emits_new_parent(qtbot) -> None:
    panel = PlaylistListPanel()
    qtbot.addWidget(panel)
    folder = {"Title": "Folder", "playlist_id": 10, "is_folder": True}
    playlist = {"Title": "Loose", "playlist_id": 20}
    panel.loadPlaylists([folder, playlist])
    playlist_index = next(index for index, row in panel._playlist_map.items() if row is playlist)
    menu = panel._build_context_menu(playlist_index, panel)
    move_action = next(action for action in menu.actions() if action.text() == "Move to Folder")
    move_menu = move_action.menu()
    assert move_menu is not None
    folder_action = next(action for action in move_menu.actions() if action.text() == "Folder")

    with qtbot.waitSignal(panel.playlist_move_requested) as emitted:
        folder_action.trigger()

    assert emitted.args == [playlist, 10]


def test_playlist_context_move_preserves_64_bit_folder_id(qtbot) -> None:
    panel = PlaylistListPanel()
    qtbot.addWidget(panel)
    folder_id = 0x7ABC_DEF0_1234_5678
    folder = {"Title": "Folder", "playlist_id": folder_id, "is_folder": True}
    playlist = {"Title": "Loose", "playlist_id": 0x6ABC_DEF0_1234_5678}
    panel.loadPlaylists([folder, playlist])
    playlist_index = next(index for index, row in panel._playlist_map.items() if row is playlist)
    menu = panel._build_context_menu(playlist_index, panel)
    move_action = next(action for action in menu.actions() if action.text() == "Move to Folder")
    move_menu = move_action.menu()
    assert move_menu is not None
    folder_action = next(action for action in move_menu.actions() if action.text() == "Folder")

    with qtbot.waitSignal(panel.playlist_move_requested) as emitted:
        folder_action.trigger()

    assert emitted.args == [playlist, folder_id]


def test_playlist_drop_preserves_64_bit_folder_id(qtbot) -> None:
    panel = PlaylistListPanel()
    qtbot.addWidget(panel)
    folder_id = 0x7ABC_DEF0_1234_5678
    folder = {"Title": "Folder", "playlist_id": folder_id, "is_folder": True}
    playlist = {"Title": "Loose", "playlist_id": 0x6ABC_DEF0_1234_5678}
    panel.loadPlaylists([folder, playlist])
    source_index = next(index for index, row in panel._playlist_map.items() if row is playlist)
    target_button = next(button for index, button in enumerate(panel._buttons) if panel._playlist_map[index] is folder)
    mime = QMimeData()
    mime.setData(
        playlist_browser_module.IOP_PLAYLIST_DRAG_MIME,
        QByteArray(str(source_index).encode("ascii")),
    )
    event = SimpleNamespace(
        mimeData=lambda: mime,
        acceptProposedAction=lambda: None,
        ignore=lambda: None,
    )

    with qtbot.waitSignal(panel.playlist_move_requested) as emitted:
        target_button.dropEvent(cast(Any, event))

    assert emitted.args == [playlist, folder_id]


def test_reconciled_folder_with_aggregate_rules_stays_a_folder_in_gui(qtbot) -> None:
    folder = {
        "Title": "Algorithms",
        "playlist_id": 10,
        "playlist_kind_flags": 0x0100,
        "podcast_flag": 0x0100,
        "is_folder": True,
        "is_podcast": False,
        "smart_playlist_data": {"check_rules": True},
        "smart_playlist_rules": {
            "conjunction": "OR",
            "rules": [{"field_id": 0x28, "action_id": 1, "from_value": 11}],
        },
    }

    assert not _is_user_smart_playlist(folder)
    assert not _is_regular_track_playlist(folder)

    card = PlaylistInfoCard()
    qtbot.addWidget(card)
    card.showPlaylist(folder, [])

    assert card.type_label.text().endswith("Playlist Folder")
    assert not card.edit_btn.isHidden()
    assert not card.delete_btn.isHidden()
    assert card.evaluate_btn.isHidden()


class _DeleteTestSignal:
    def connect(self, _callback) -> None:
        return


class _DeleteTestWorker:
    def __init__(self, *_args, **_kwargs) -> None:
        self.finished_ok = _DeleteTestSignal()
        self.failed = _DeleteTestSignal()
        self.started = False

    def start(self) -> None:
        self.started = True


class _DeleteTestCache:
    def __init__(self, playlists: list[dict]) -> None:
        self.playlists = playlists
        self.saved: list[dict] = []
        self.removed: list[tuple[int, int | None]] = []

    def get_playlists(self) -> list[dict]:
        return self.playlists

    def save_user_playlist(self, playlist: dict) -> None:
        self.saved.append(playlist)

    def remove_user_playlist(self, playlist_id: int, dataset_type: int | None) -> None:
        self.removed.append((playlist_id, dataset_type))


class _MoveTestCache(_DeleteTestCache):
    def is_ready(self) -> bool:
        return True

    def get_track_id_index(self) -> dict[int, dict]:
        return {}

    def save_user_playlist(self, playlist: dict) -> None:
        super().save_user_playlist(playlist)
        playlist_id = playlist.get("playlist_id")
        self.playlists = [playlist if row.get("playlist_id") == playlist_id else row for row in self.playlists]


def _playlist_browser_for_delete_test(
    qtbot,
    cache: _DeleteTestCache | runtime.iTunesDBCache,
) -> PlaylistBrowser:
    settings = SimpleNamespace(get_global_settings=lambda: SimpleNamespace(track_list_columns_by_content={}))
    device_sessions = SimpleNamespace(current_session=lambda: SimpleNamespace(device_path="", storage=None))
    libraries = SimpleNamespace(cache=lambda: cache)
    browser = PlaylistBrowser(
        cast(SettingsService, settings),
        cast(DeviceSessionService, device_sessions),
        cast(LibraryService, libraries),
    )
    qtbot.addWidget(browser)
    return browser


class _PreviewTestCache(QObject):
    tracks_changed = pyqtSignal()
    playlists_changed = pyqtSignal()
    playlist_quick_sync = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.track_rows = [
            {"track_id": 1, "Title": "One", "Artist": "First"},
            {"track_id": 2, "Title": "Two", "Artist": "Second"},
        ]
        self.track_read_threads: list[int] = []
        self.write_attempts = 0

    def is_ready(self) -> bool:
        return True

    def get_tracks(self) -> list[dict]:
        self.track_read_threads.append(threading.get_ident())
        return list(self.track_rows)

    def get_playlists(self) -> list[dict]:
        return []

    def get_data(self) -> dict:
        return {}

    def save_user_playlist(self, _playlist: dict) -> None:
        self.write_attempts += 1
        raise AssertionError("preview unexpectedly persisted a playlist")


def _playlist_browser_for_preview_test(
    qtbot,
    cache: _PreviewTestCache,
) -> PlaylistBrowser:
    global_settings = SimpleNamespace(track_list_columns_by_content={})
    effective_settings = SimpleNamespace(show_art_in_tracklist=False)
    settings = SimpleNamespace(
        get_global_settings=lambda: global_settings,
        get_effective_settings=lambda: effective_settings,
    )
    device_sessions = SimpleNamespace(current_session=lambda: SimpleNamespace(device_path="", storage=None))
    libraries = SimpleNamespace(cache=lambda: cache)
    browser = PlaylistBrowser(
        cast(SettingsService, settings),
        cast(DeviceSessionService, device_sessions),
        cast(LibraryService, libraries),
    )
    qtbot.addWidget(browser)
    return browser


def test_smart_playlist_editor_preview_runs_off_thread_and_never_persists(qtbot) -> None:
    cache = _PreviewTestCache()
    browser = _playlist_browser_for_preview_test(qtbot, cache)
    ui_thread_id = threading.get_ident()

    browser._onNewPlaylist("smart")
    browser.editor.check_rules_check.setChecked(False)

    qtbot.waitUntil(
        lambda: browser.trackTitleBar.title.text() == "Live Preview · 2 tracks",
        timeout=5000,
    )

    assert cache.track_read_threads
    assert all(thread_id != ui_thread_id for thread_id in cache.track_read_threads)
    assert [track["track_id"] for track in browser.trackList.tracks] == [1, 2]
    assert cache.write_attempts == 0


def test_smart_playlist_preview_debounces_rapid_editor_changes(qtbot) -> None:
    cache = _PreviewTestCache()
    browser = _playlist_browser_for_preview_test(qtbot, cache)
    browser._SMART_PREVIEW_DEBOUNCE_MS = 30
    browser._onNewPlaylist("smart")
    browser.editor.check_rules_check.setChecked(False)
    qtbot.waitUntil(lambda: len(cache.track_read_threads) == 1, timeout=5000)
    qtbot.waitUntil(
        lambda: browser.trackTitleBar.title.text() == "Live Preview · 2 tracks",
        timeout=5000,
    )

    cache.track_read_threads.clear()
    browser.editor.check_rules_check.setChecked(True)
    browser.editor.check_rules_check.setChecked(False)
    browser.editor.check_rules_check.setChecked(True)

    qtbot.waitUntil(lambda: len(cache.track_read_threads) == 1, timeout=5000)
    qtbot.wait(100)
    assert len(cache.track_read_threads) == 1


def test_smart_playlist_preview_ignores_an_older_generation(qtbot, monkeypatch) -> None:
    cache = _PreviewTestCache()
    browser = _playlist_browser_for_preview_test(qtbot, cache)
    browser._onNewPlaylist("smart")
    calls: list[list[dict]] = []
    monkeypatch.setattr(
        browser.trackList,
        "showComputedPlaylist",
        lambda tracks, _playlist: calls.append(tracks),
    )

    browser._onSmartPlaylistPreviewReady(
        SmartPlaylistPreviewResult(
            generation=browser._smart_preview_generation - 1,
            tracks=cache.track_rows,
        )
    )

    assert calls == []


def test_sidebar_move_persists_parent_and_writes_silently(qtbot, monkeypatch) -> None:
    folder = {"Title": "Folder", "playlist_id": 10, "is_folder": True}
    playlist = {"Title": "Loose", "playlist_id": 20}
    cache = _DeleteTestCache([folder, playlist])
    browser = _playlist_browser_for_delete_test(qtbot, cache)
    write_calls: list[tuple[dict, bool]] = []
    monkeypatch.setattr(browser, "_refreshList", lambda: None)
    monkeypatch.setattr(browser.listPanel, "selectPlaylistById", lambda *_args: False)
    monkeypatch.setattr(browser, "_onPlaylistSelected", lambda _playlist: None)
    monkeypatch.setattr(
        browser,
        "_writePlaylistToIPod",
        lambda row, *, notify=True: write_calls.append((row, notify)),
    )

    browser._onPlaylistMoveRequested(playlist, 10)

    assert len(cache.saved) == 1
    assert cache.saved[0]["parent_folder_playlist_id"] == 10
    assert cache.saved[0]["unk0x30_playlist_ref"] == 10
    assert write_calls == [(cache.saved[0], False)]


def test_context_menu_move_updates_visible_playlist_hierarchy(qtbot, monkeypatch) -> None:
    folder = {"Title": "Folder", "playlist_id": 10, "is_folder": True}
    playlist = {"Title": "Loose", "playlist_id": 20}
    cache = _MoveTestCache([folder, playlist])
    browser = _playlist_browser_for_delete_test(qtbot, cache)
    monkeypatch.setattr(browser, "_writePlaylistToIPod", lambda *_args, **_kwargs: None)
    browser.loadPlaylists()

    playlist_index = next(index for index, row in browser.listPanel._playlist_map.items() if row.get("playlist_id") == 20)
    menu = browser.listPanel._build_context_menu(playlist_index, browser.listPanel)
    move_action = next(action for action in menu.actions() if action.text() == "Move to Folder")
    move_menu = move_action.menu()
    assert move_menu is not None
    folder_action = next(action for action in move_menu.actions() if action.text() == "Folder")

    folder_action.trigger()

    assert cache.saved[-1]["parent_folder_playlist_id"] == 10
    moved_button = next(button for button in browser.listPanel.findChildren(SidebarNavButton) if button.toolTip().splitlines()[0] == "Loose")
    assert moved_button.property("playlistDepth") == 1


def test_context_menu_move_updates_production_cache_hierarchy(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime.DeviceManager,
        "get_instance",
        classmethod(lambda cls: SimpleNamespace(device_path="/fake/ipod")),
    )
    cache = runtime.iTunesDBCache()
    cache.set_data(
        {
            "mhlt": [],
            "mhlp": [
                {
                    "Title": "Folder",
                    "playlist_id": 10,
                    "playlist_kind_flags": 0x0100,
                    "podcast_flag": 0x0100,
                    "is_folder": True,
                    "_mhsd_dataset_type": 2,
                },
                {
                    "Title": "Loose",
                    "playlist_id": 20,
                    "_mhsd_dataset_type": 2,
                },
            ],
            "mhlp_podcast": [],
            "mhlp_smart": [],
        },
        "/fake/ipod",
    )
    browser = _playlist_browser_for_delete_test(qtbot, cache)
    monkeypatch.setattr(browser, "_writePlaylistToIPod", lambda *_args, **_kwargs: None)
    browser.loadPlaylists()

    playlist_index = next(index for index, row in browser.listPanel._playlist_map.items() if row.get("playlist_id") == 20)
    menu = browser.listPanel._build_context_menu(playlist_index, browser.listPanel)
    move_action = next(action for action in menu.actions() if action.text() == "Move to Folder")
    move_menu = move_action.menu()
    assert move_menu is not None
    folder_action = next(action for action in move_menu.actions() if action.text() == "Folder")

    folder_action.trigger()

    moved = next(row for row in cache.get_display_playlists() if row.get("playlist_id") == 20)
    assert moved["parent_folder_playlist_id"] == 10


def test_deleting_nested_folder_promotes_direct_children_to_its_parent(
    qtbot,
    monkeypatch,
) -> None:
    deleted_folder = {
        "Title": "Inner",
        "playlist_id": 20,
        "is_folder": True,
        "parent_folder_playlist_id": 10,
    }
    cache = _DeleteTestCache([
        {"Title": "Outer", "playlist_id": 10, "is_folder": True},
        deleted_folder,
        {
            "Title": "Child Folder",
            "playlist_id": 30,
            "is_folder": True,
            "parent_folder_playlist_id": 20,
        },
        {
            "Title": "Child Playlist",
            "playlist_id": 31,
            "parent_folder_playlist_id": 20,
        },
        {
            "Title": "Grandchild Playlist",
            "playlist_id": 32,
            "parent_folder_playlist_id": 30,
        },
    ])
    monkeypatch.setattr(
        playlist_browser_module,
        "_PlaylistDeleteWorker",
        _DeleteTestWorker,
    )
    browser = _playlist_browser_for_delete_test(qtbot, cache)

    browser._deletePlaylistFromIPod(deleted_folder)

    assert [playlist["playlist_id"] for playlist in cache.saved] == [30, 31]
    assert [
        playlist["parent_folder_playlist_id"] for playlist in cache.saved
    ] == [10, 10]
    assert [playlist["unk0x30_playlist_ref"] for playlist in cache.saved] == [10, 10]
    assert cache.removed == [(20, 0)]


def test_deleting_root_folder_promotes_direct_children_to_top_level(
    qtbot,
    monkeypatch,
) -> None:
    deleted_folder = {
        "Title": "Root",
        "playlist_id": 10,
        "is_folder": True,
    }
    cache = _DeleteTestCache([
        deleted_folder,
        {
            "Title": "Child Folder",
            "playlist_id": 20,
            "is_folder": True,
            "parent_folder_playlist_id": 10,
        },
    ])
    monkeypatch.setattr(
        playlist_browser_module,
        "_PlaylistDeleteWorker",
        _DeleteTestWorker,
    )
    browser = _playlist_browser_for_delete_test(qtbot, cache)

    browser._deletePlaylistFromIPod(deleted_folder)

    assert len(cache.saved) == 1
    assert cache.saved[0]["parent_folder_playlist_id"] == 0
    assert cache.saved[0]["unk0x30_playlist_ref"] == 0
