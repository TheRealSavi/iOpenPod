from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from iopenpod.application.services import (
    DeviceSessionService,
    LibraryService,
    SettingsService,
)
from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets import playlistBrowser as playlist_browser_module
from iopenpod.gui.widgets.playlistBrowser import (
    PlaylistBrowser,
    PlaylistInfoCard,
    PlaylistListPanel,
    _is_ipod_category_playlist,
    _is_regular_track_playlist,
    _is_user_smart_playlist,
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


def _playlist_browser_for_delete_test(qtbot, cache: _DeleteTestCache) -> PlaylistBrowser:
    settings = SimpleNamespace(
        get_global_settings=lambda: SimpleNamespace(track_list_columns_by_content={})
    )
    device_sessions = SimpleNamespace(
        current_session=lambda: SimpleNamespace(device_path="", storage=None)
    )
    libraries = SimpleNamespace(cache=lambda: cache)
    browser = PlaylistBrowser(
        cast(SettingsService, settings),
        cast(DeviceSessionService, device_sessions),
        cast(LibraryService, libraries),
    )
    qtbot.addWidget(browser)
    return browser


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
