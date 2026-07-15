"""Shared track context-menu helpers for list and grouped grid views."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QMenu, QWidget

from iopenpod.application.runtime import display_playlists_from_rows
from iopenpod.sync.album_chapters import is_music_track, resolve_album_tracks

from ..glyphs import glyph_icon
from ..styles import Colors, context_menu_css

CTRL = "⌘" if sys.platform == "darwin" else "Ctrl"
ALT = "⌥" if sys.platform == "darwin" else "Alt"


class TrackContextMenuHost(Protocol):
    """Actions and state required by the shared track menu."""

    _library_cache: Any
    _is_playlist_mode: bool
    _current_playlist: dict | None
    table: Any

    def _can_edit_selected_tracks(self, selected: list[dict]) -> bool: ...
    def _edit_action_label(self, selected: list[dict]) -> str: ...
    def _edit_tracks(self, selected: list[dict] | None = None) -> None: ...
    def _add_convert_to_podcast_action(
        self,
        menu: QMenu,
        selected: list[dict],
    ) -> Any: ...
    def _create_new_playlist_from_selected(
        self,
        selected: list[dict] | None = None,
    ) -> None: ...
    def _add_selected_to_playlist(
        self,
        playlist: dict,
        selected: list[dict] | None = None,
    ) -> None: ...
    def _remove_selected_from_playlist(
        self,
        selected: list[dict] | None = None,
    ) -> None: ...
    def _is_reorderable_playlist(self) -> bool: ...
    def _move_selected_rows(self, direction: int) -> None: ...
    def _build_flag_menu(
        self,
        menu: QMenu,
        style: str,
        selected: list[dict],
        cache: Any,
    ) -> None: ...
    def _build_content_advisory_menu(
        self,
        menu: QMenu,
        style: str,
        selected: list[dict],
    ) -> None: ...
    def _build_rating_menu(
        self,
        menu: QMenu,
        style: str,
        selected: list[dict],
        cache: Any,
    ) -> None: ...
    def _build_volume_menu(
        self,
        menu: QMenu,
        style: str,
        selected: list[dict],
    ) -> None: ...
    def _add_open_file_actions(
        self,
        menu: QMenu,
        selected: list[dict],
    ) -> None: ...
    def _copy_selection(self, selected: list[dict] | None = None) -> None: ...
    def _copy_files_to_clipboard(
        self,
        selected: list[dict] | None = None,
    ) -> None: ...
    def _request_split_chapters(self, selected: list[dict]) -> None: ...
    def _request_remove_from_ipod(self, selected: list[dict]) -> None: ...


@dataclass(frozen=True)
class ChapteredAlbumMenuAction:
    """Album-only control appended to the otherwise common track menu."""

    items: tuple[dict, ...]
    requested: Callable[[list[dict]], None]


def _playlist_dataset_type(playlist: dict | None) -> int:
    if not playlist:
        return 0
    try:
        return int(playlist.get("_mhsd_dataset_type", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _is_ipod_category_playlist(playlist: dict | None) -> bool:
    if not playlist:
        return False
    dataset_type = _playlist_dataset_type(playlist)
    if dataset_type:
        return dataset_type == 5
    return bool(playlist.get("_source") == "category")


def _is_display_merged_playlist(playlist: dict | None) -> bool:
    return bool(playlist and playlist.get("_mhsd_display_merged"))


def _is_editable_regular_playlist(playlist: dict | None) -> bool:
    return bool(
        playlist
        and not playlist.get("master_flag")
        and not playlist.get("smart_playlist_data")
        and not _is_ipod_category_playlist(playlist)
        and playlist.get("_source") not in ("smart", "category")
        and (
            playlist.get("podcast_flag", 0) != 1
            or _is_display_merged_playlist(playlist)
        )
    )


def _chapter_count(track: dict) -> int:
    chapter_data = track.get("chapter_data")
    if not isinstance(chapter_data, dict):
        return 0
    chapters = chapter_data.get("chapters")
    if not isinstance(chapters, list):
        return 0
    return sum(isinstance(chapter, dict) for chapter in chapters)


def build_track_context_menu(
    parent: QWidget,
    host: TrackContextMenuHost,
    selected: list[dict],
    *,
    chaptered_album_action: ChapteredAlbumMenuAction | None = None,
) -> QMenu:
    """Build the common track menu for an explicit track selection."""

    selected_snapshot = list(selected)
    menu = QMenu(parent)
    menu_style = context_menu_css()
    menu.setStyleSheet(menu_style)

    cache = host._library_cache

    can_edit = host._can_edit_selected_tracks(selected_snapshot)
    if can_edit:
        edit_act = menu.addAction(
            f"{host._edit_action_label(selected_snapshot)}\t{CTRL}+E"
        )
        if edit_act:
            icon = glyph_icon("edit", 14, Colors.TEXT_PRIMARY)
            if icon is not None:
                edit_act.setIcon(icon)
            edit_act.triggered.connect(
                lambda _=False: host._edit_tracks(selected_snapshot)
            )
        host._add_convert_to_podcast_action(menu, selected_snapshot)

    if chaptered_album_action is not None:
        conversion_items = [dict(item) for item in chaptered_album_action.items]
        conversion_action = menu.addAction("Convert to a single chaptered track")
        if conversion_action:
            icon = glyph_icon("chaptered-track", 14, Colors.TEXT_PRIMARY)
            if icon is not None:
                conversion_action.setIcon(icon)
            enabled = all(
                int(item.get("track_count", 0) or 0) >= 2
                for item in conversion_items
            )
            conversion_action.setEnabled(enabled)
            if enabled:
                conversion_action.triggered.connect(
                    lambda _=False: chaptered_album_action.requested(conversion_items)
                )

    if can_edit:
        menu.addSeparator()

    if len(selected_snapshot) == 1 and _chapter_count(selected_snapshot[0]) >= 2:
        split_act = menu.addAction("Split chapters into individual tracks")
        if split_act:
            icon = glyph_icon("chaptered-track", 14, Colors.TEXT_PRIMARY)
            if icon is not None:
                split_act.setIcon(icon)
            split_act.triggered.connect(
                lambda _=False: host._request_split_chapters(selected_snapshot)
            )
        menu.addSeparator()

    if cache is not None and cache.is_ready():
        regular = [
            playlist
            for playlist in display_playlists_from_rows(cache.get_playlists())
            if _is_editable_regular_playlist(playlist)
        ]

        add_menu = menu.addMenu("Add to Playlist")
        if add_menu:
            add_menu.setStyleSheet(menu_style)
            new_playlist_act = add_menu.addAction("New Playlist")
            if new_playlist_act:
                icon = glyph_icon("plus", 14, Colors.TEXT_PRIMARY)
                if icon is not None:
                    new_playlist_act.setIcon(icon)
                new_playlist_act.triggered.connect(
                    lambda _=False: host._create_new_playlist_from_selected(
                        selected_snapshot
                    )
                )

            if regular:
                add_menu.addSeparator()
                for playlist in regular:
                    act = add_menu.addAction(playlist.get("Title", "Untitled"))
                    if act:
                        act.triggered.connect(
                            lambda _=False, p=playlist: host._add_selected_to_playlist(
                                p,
                                selected_snapshot,
                            )
                        )

    if host._is_playlist_mode and _is_editable_regular_playlist(
        host._current_playlist
    ):
        menu.addSeparator()
        count = len(selected_snapshot)
        label = f"Remove {count} Track{'s' if count != 1 else ''} from Playlist"
        remove_act = menu.addAction(label)
        if remove_act:
            remove_act.triggered.connect(
                lambda _=False: host._remove_selected_from_playlist(selected_snapshot)
            )

    menu.addSeparator()
    count = len(selected_snapshot)
    remove_ipod_act = menu.addAction(
        f"Remove {count} Track{'s' if count != 1 else ''} from iPod"
    )
    if remove_ipod_act:
        icon = glyph_icon("minus", 14, Colors.TEXT_PRIMARY)
        if icon is not None:
            remove_ipod_act.setIcon(icon)
        remove_ipod_act.triggered.connect(
            lambda _=False: host._request_remove_from_ipod(selected_snapshot)
        )

    if host._is_reorderable_playlist():
        selected_rows = sorted({index.row() for index in host.table.selectedIndexes()})
        menu.addSeparator()
        up_act = menu.addAction(f"Move Up\t{CTRL}+↑")
        if up_act:
            up_act.setEnabled(bool(selected_rows) and selected_rows[0] > 0)
            up_act.triggered.connect(lambda: host._move_selected_rows(-1))
        down_act = menu.addAction(f"Move Down\t{CTRL}+↓")
        if down_act:
            down_act.setEnabled(
                bool(selected_rows)
                and selected_rows[-1] < host.table.rowCount() - 1
            )
            down_act.triggered.connect(lambda: host._move_selected_rows(1))

    menu.addSeparator()
    if cache is not None:
        host._build_flag_menu(menu, menu_style, selected_snapshot, cache)
    host._build_content_advisory_menu(menu, menu_style, selected_snapshot)
    if cache is not None:
        host._build_rating_menu(menu, menu_style, selected_snapshot, cache)
    host._build_volume_menu(menu, menu_style, selected_snapshot)

    menu.addSeparator()
    host._add_open_file_actions(menu, selected_snapshot)

    menu.addSeparator()
    copy_text_act = menu.addAction(f"Copy as Text\t{CTRL}+C")
    if copy_text_act:
        copy_text_act.triggered.connect(
            lambda _=False: host._copy_selection(selected_snapshot)
        )
    copy_files_act = menu.addAction(f"Copy as File(s)\t{CTRL}+{ALT}+C")
    if copy_files_act:
        copy_files_act.triggered.connect(
            lambda _=False: host._copy_files_to_clipboard(selected_snapshot)
        )

    return menu


def show_track_context_menu(
    parent: QWidget,
    host: TrackContextMenuHost,
    selected: list[dict],
    global_pos: QPoint,
    *,
    chaptered_album_action: ChapteredAlbumMenuAction | None = None,
) -> QMenu:
    """Build and display the common track context menu."""

    menu = build_track_context_menu(
        parent,
        host,
        selected,
        chaptered_album_action=chaptered_album_action,
    )
    menu.exec(global_pos)
    return menu


def resolve_grid_item_tracks(
    item: dict,
    all_tracks: list[dict],
) -> list[dict]:
    """Resolve one Album, Artist, or Genre grid payload to its music tracks."""

    if item.get("category", "Albums") == "Albums":
        return resolve_album_tracks(item, all_tracks)

    filter_key = item.get("filter_key")
    filter_value = item.get("filter_value")
    if not isinstance(filter_key, str) or filter_value is None:
        return []

    return [
        track
        for track in all_tracks
        if is_music_track(track) and track.get(filter_key) == filter_value
    ]
