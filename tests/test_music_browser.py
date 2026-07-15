from types import SimpleNamespace
from typing import Any, cast

from PIL import Image
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QLineEdit, QSplitter

from iopenpod.gui.styles import Colors, context_menu_css
from iopenpod.gui.widgets import artworkUnifier as artwork_unifier_module
from iopenpod.gui.widgets.artworkUnifier import (
    artwork_compare_hash,
    build_album_artwork_unify_context,
)
from iopenpod.gui.widgets.musicBrowser import MusicBrowser
from iopenpod.gui.widgets.trackContextMenu import resolve_grid_item_tracks
from iopenpod.gui.widgets.trackListTitleBar import TrackListTitleBar, _resolve_bar_palette


def _build_browser(category: str = "Albums") -> Any:
    scheduled: list[str] = []
    visible_row_refreshes: list[str] = []
    browser = SimpleNamespace(
        _current_category=category,
        _tab_dirty={
            "Playlists": False,
            "Podcasts": False,
            "Photos": False,
        },
        _schedule_refresh_current_category=lambda: scheduled.append("refresh"),
        browserTrack=SimpleNamespace(
            _refresh_visible_rows=lambda: visible_row_refreshes.append("rows")
        ),
    )
    browser._mark_tab_dirty = MusicBrowser._mark_tab_dirty.__get__(browser)
    return cast(Any, browser), scheduled, visible_row_refreshes


def test_rating_edit_refreshes_visible_rows_without_reloading_album_grid() -> None:
    browser, scheduled, visible_row_refreshes = _build_browser("Albums")

    MusicBrowser._on_track_fields_changed(browser, {"rating"})

    assert browser._tab_dirty["Playlists"] is True
    assert browser._tab_dirty["Podcasts"] is True
    assert scheduled == []
    assert visible_row_refreshes == ["rows"]


def test_album_edit_reloads_album_grid() -> None:
    browser, scheduled, visible_row_refreshes = _build_browser("Albums")

    MusicBrowser._on_track_fields_changed(browser, {"album"})

    assert scheduled == ["refresh"]
    assert visible_row_refreshes == []


def test_production_grouping_field_names_reload_grid() -> None:
    for field_name in ("Album Artist", "compilation_flag"):
        browser, scheduled, visible_row_refreshes = _build_browser("Albums")

        MusicBrowser._on_track_fields_changed(browser, {field_name})

        assert scheduled == ["refresh"]
        assert visible_row_refreshes == []


def test_track_edits_do_not_reload_photo_browser() -> None:
    browser, scheduled, visible_row_refreshes = _build_browser("Photos")

    MusicBrowser._on_track_fields_changed(browser, {"rating"})

    assert browser._tab_dirty["Playlists"] is True
    assert browser._tab_dirty["Podcasts"] is True
    assert browser._tab_dirty["Photos"] is False
    assert scheduled == []
    assert visible_row_refreshes == []


def test_context_menu_css_styles_disabled_rows_and_icon_gutter() -> None:
    css = context_menu_css()

    assert "padding: 6px;" in css
    assert "padding: 8px 28px 8px 12px;" in css
    assert "QMenu::item:disabled" in css
    assert "QMenu::item:disabled:selected" in css
    assert f"color: {Colors.TEXT_DISABLED};" in css


def test_grid_item_track_resolution_matches_album_artist_and_genre_groups() -> None:
    album_track_one = {
        "db_track_id": 1,
        "Title": "One",
        "Album": "Album A",
        "Artist": "Artist A",
        "Genre": "Rock",
        "media_type": 1,
    }
    album_track_two = {
        "db_track_id": 2,
        "Title": "Two",
        "Album": "Album A",
        "Artist": "Artist A",
        "Genre": "Rock",
        "media_type": 1,
    }
    same_album_other_artist = {
        "db_track_id": 3,
        "Title": "Three",
        "Album": "Album A",
        "Artist": "Artist B",
        "Genre": "Rock",
        "media_type": 1,
    }
    same_artist_other_album = {
        "db_track_id": 4,
        "Title": "Four",
        "Album": "Album B",
        "Artist": "Artist A",
        "Genre": "Jazz",
        "media_type": 1,
    }
    video_track = {
        "db_track_id": 5,
        "Title": "Video",
        "Album": "Album A",
        "Artist": "Artist A",
        "Genre": "Rock",
        "media_type": 2,
    }
    all_tracks = [
        album_track_one,
        album_track_two,
        same_album_other_artist,
        same_artist_other_album,
        video_track,
    ]

    assert resolve_grid_item_tracks(
        {"category": "Albums", "album": "Album A", "artist": "Artist A"},
        all_tracks,
    ) == [album_track_one, album_track_two]
    assert resolve_grid_item_tracks(
        {"category": "Artists", "filter_key": "Artist", "filter_value": "Artist A"},
        all_tracks,
    ) == [album_track_one, album_track_two, same_artist_other_album]
    assert resolve_grid_item_tracks(
        {"category": "Genres", "filter_key": "Genre", "filter_value": "Rock"},
        all_tracks,
    ) == [album_track_one, album_track_two, same_album_other_artist]


def test_artist_grid_context_menu_passes_all_group_tracks_to_track_menu(
    monkeypatch,
) -> None:
    artist_tracks = [
        {"db_track_id": 1, "Title": "One", "Artist": "Artist A"},
        {"db_track_id": 2, "Title": "Two", "Artist": "Artist A"},
    ]

    class _Cache:
        @staticmethod
        def is_ready() -> bool:
            return True

        @staticmethod
        def get_tracks() -> list[dict]:
            return [*artist_tracks, {"db_track_id": 3, "Artist": "Artist B"}]

    shown: list[tuple[object, list[dict], QPoint]] = []
    menu_host = SimpleNamespace()
    monkeypatch.setattr(
        "iopenpod.gui.widgets.musicBrowser.show_track_context_menu",
        lambda _parent, host, tracks, pos: shown.append((host, tracks, pos)),
    )
    browser = SimpleNamespace(
        _current_category="Artists",
        _library_cache=_Cache(),
        browserTrack=menu_host,
    )
    browser._resolve_grid_tracks_for_menu = (
        MusicBrowser._resolve_grid_tracks_for_menu.__get__(browser)
    )
    item = {
        "category": "Artists",
        "filter_key": "Artist",
        "filter_value": "Artist A",
    }
    pos = QPoint(12, 34)

    MusicBrowser._onGridItemContextRequested(cast(Any, browser), [item], pos)

    assert shown == [(menu_host, artist_tracks, pos)]


def test_album_grid_context_menu_adds_chaptered_conversion_to_shared_menu(
    monkeypatch,
) -> None:
    tracks = [
        {"db_track_id": 1, "Title": "One", "Album": "Album", "Artist": "Artist"},
        {"db_track_id": 2, "Title": "Two", "Album": "Album", "Artist": "Artist"},
    ]

    class _Cache:
        @staticmethod
        def is_ready() -> bool:
            return True

        @staticmethod
        def get_tracks() -> list[dict]:
            return tracks

    shown: list[tuple[object, list[dict], QPoint, dict[str, Any]]] = []
    menu_host = SimpleNamespace()
    monkeypatch.setattr(
        "iopenpod.gui.widgets.musicBrowser.show_track_context_menu",
        lambda _parent, host, selected, pos, **kwargs: shown.append(
            (host, selected, pos, kwargs)
        ),
    )
    emitted: list[list[dict]] = []
    browser = SimpleNamespace(
        _current_category="Albums",
        _library_cache=_Cache(),
        browserTrack=menu_host,
        album_conversion_requested=SimpleNamespace(emit=emitted.append),
    )
    browser._resolve_grid_tracks_for_menu = (
        MusicBrowser._resolve_grid_tracks_for_menu.__get__(browser)
    )
    album_item = {
        "category": "Albums",
        "album": "Album",
        "artist": "Artist",
        "track_count": 2,
    }

    pos = QPoint(12, 34)
    MusicBrowser._onGridItemContextRequested(
        cast(Any, browser),
        [album_item],
        pos,
    )

    assert shown[0][0] is menu_host
    assert shown[0][1] == tracks
    assert shown[0][2] == pos
    conversion_action = shown[0][3]["chaptered_album_action"]
    assert list(conversion_action.items) == [album_item]
    conversion_action.requested([album_item])
    assert emitted == [[album_item]]


def test_genre_grid_context_menu_passes_all_group_tracks_to_track_menu(
    monkeypatch,
) -> None:
    genre_tracks = [
        {"db_track_id": 1, "Title": "One", "Genre": "Rock"},
        {"db_track_id": 2, "Title": "Two", "Genre": "Rock"},
    ]

    class _Cache:
        @staticmethod
        def is_ready() -> bool:
            return True

        @staticmethod
        def get_tracks() -> list[dict]:
            return [*genre_tracks, {"db_track_id": 3, "Genre": "Jazz"}]

    shown: list[tuple[object, list[dict], QPoint]] = []
    menu_host = SimpleNamespace()
    monkeypatch.setattr(
        "iopenpod.gui.widgets.musicBrowser.show_track_context_menu",
        lambda _parent, host, tracks, pos: shown.append((host, tracks, pos)),
    )
    browser = SimpleNamespace(
        _current_category="Genres",
        _library_cache=_Cache(),
        browserTrack=menu_host,
    )
    browser._resolve_grid_tracks_for_menu = (
        MusicBrowser._resolve_grid_tracks_for_menu.__get__(browser)
    )
    pos = QPoint(12, 34)

    MusicBrowser._onGridItemContextRequested(
        cast(Any, browser),
        [{"category": "Genres", "filter_key": "Genre", "filter_value": "Rock"}],
        pos,
    )

    assert shown == [(menu_host, genre_tracks, pos)]


def test_title_bar_palette_reuses_contrast_ensured_grid_color() -> None:
    display_rgb = (86, 112, 144)

    palette = _resolve_bar_palette(display_rgb, contrast_ensured=True)

    assert palette["bg"] == display_rgb


def test_title_bar_places_metadata_search_before_window_controls(qtbot) -> None:
    splitter = QSplitter()
    titlebar = TrackListTitleBar(splitter)
    qtbot.addWidget(splitter)
    qtbot.addWidget(titlebar)
    titlebar.show()

    search = titlebar.findChild(QLineEdit, "trackListTitleSearchField")
    assert search is titlebar.search
    assert search is not None
    assert search.placeholderText() == "Search tracks"
    assert titlebar.titleBarLayout.indexOf(search) < titlebar.titleBarLayout.indexOf(
        titlebar.button1
    )
    assert (search.width(), search.height()) == (190, 28)
    assert "QLineEdit#trackListTitleSearchField" in search.styleSheet()

    palette = _resolve_bar_palette(
        (86, 112, 144),
        text=(18, 18, 24),
        text_secondary=(45, 50, 60),
        contrast_ensured=True,
    )
    titlebar.setColor(
        86,
        112,
        144,
        text=(18, 18, 24),
        text_secondary=(45, 50, 60),
        contrast_ensured=True,
    )
    compact_search_css = "".join(search.styleSheet().split())
    secondary_rgb = ",".join(str(value) for value in palette["text_secondary"])
    primary_rgb = ",".join(str(value) for value in palette["text"])
    assert f"color:rgb({secondary_rgb});" in compact_search_css
    assert f"color:rgb({primary_rgb});" in compact_search_css

    emitted: list[str] = []
    titlebar.search_changed.connect(emitted.append)
    search.setText("hidden metadata")
    assert emitted == ["hidden metadata"]

    titlebar.setFullscreenMode(True)
    assert search.isVisible()
    assert titlebar.button1.isHidden()
    assert titlebar.button2.isHidden()


def test_title_bar_uses_prominent_gradient_from_contrast_ensured_color(qtbot) -> None:
    splitter = QSplitter()
    titlebar = TrackListTitleBar(splitter)
    qtbot.addWidget(splitter)
    qtbot.addWidget(titlebar)

    titlebar.setColor(
        86,
        112,
        144,
        text=(18, 18, 24),
        text_secondary=(45, 50, 60),
        contrast_ensured=True,
    )

    compact_css = "".join(titlebar.styleSheet().split())
    assert "qlineargradient" in compact_css
    assert "stop:0rgba(110,132,160,92)" in compact_css
    assert "stop:0.58rgba(86,112,144,70)" in compact_css
    assert "stop:1rgba(65,85,109,60)" in compact_css
    assert "border-top:" not in compact_css
    assert "border-left:" not in compact_css
    assert "border-bottom:" not in compact_css
    assert "color:rgb(18,18,24);" not in compact_css


def test_light_theme_title_bar_uses_more_opaque_album_gradient(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(Colors, "_active_mode", "light")
    splitter = QSplitter()
    titlebar = TrackListTitleBar(splitter)
    qtbot.addWidget(splitter)
    qtbot.addWidget(titlebar)

    titlebar.setColor(
        86,
        112,
        144,
        text=(18, 18, 24),
        text_secondary=(45, 50, 60),
        contrast_ensured=True,
    )

    compact_css = "".join(titlebar.styleSheet().split())
    assert "stop:0rgba(100,123,153,132)" in compact_css
    assert "stop:0.58rgba(86,112,144,112)" in compact_css
    assert "stop:1rgba(67,87,112,96)" in compact_css
    assert "border-bottom:" not in compact_css


def test_title_bar_maximize_uses_splitter_height_when_sizes_are_collapsed(
    qtbot,
    monkeypatch,
) -> None:
    splitter = QSplitter()
    titlebar = TrackListTitleBar(splitter)
    qtbot.addWidget(splitter)
    qtbot.addWidget(titlebar)
    splitter.resize(900, 600)

    applied_sizes: list[list[int]] = []
    monkeypatch.setattr(splitter, "sizes", lambda: [0, titlebar.minimumHeight()])
    monkeypatch.setattr(splitter, "setSizes", applied_sizes.append)

    titlebar._toggleMaximize()

    assert applied_sizes == [[120, 480]]


def test_fullscreen_tracklist_sizes_hidden_grid_to_zero() -> None:
    applied_sizes: list[list[int]] = []
    browser = SimpleNamespace(
        gridTrackSplitter=SimpleNamespace(
            height=lambda: 600,
            sizes=lambda: [560, 40],
            setSizes=applied_sizes.append,
        )
    )

    MusicBrowser._show_track_list_fullscreen(cast(Any, browser))

    assert applied_sizes == [[0, 600]]


def test_album_selection_reuses_grid_display_color_for_titlebar() -> None:
    class _TitleBar:
        def __init__(self) -> None:
            self.title = ""
            self.color_calls: list[tuple[tuple, dict]] = []

        def setTitle(self, title: str) -> None:
            self.title = title

        def setColor(self, *args, **kwargs) -> None:
            self.color_calls.append((args, kwargs))

        def resetColor(self) -> None:
            raise AssertionError("display color should be used")

    applied_filters: list[dict] = []
    titlebar = _TitleBar()
    browser = SimpleNamespace(
        trackListTitleBar=titlebar,
        browserTrack=SimpleNamespace(applyFilter=applied_filters.append),
    )
    item = {
        "title": "Display Color Album",
        "category": "Albums",
        "filter_key": "album",
        "filter_value": "Display Color Album",
        "dominant_color": (8, 16, 32),
        "display_dominant_color": (86, 112, 144),
        "display_album_colors": {
            "text": (255, 255, 255),
            "text_secondary": (225, 230, 238),
        },
    }

    MusicBrowser._onGridItemSelected(cast(Any, browser), item)

    assert titlebar.title == "Display Color Album"
    assert titlebar.color_calls == [
        (
            (86, 112, 144),
            {
                "text": (255, 255, 255),
                "text_secondary": (225, 230, 238),
                "contrast_ensured": True,
            },
        )
    ]
    assert applied_filters == [item]


def test_unify_artwork_hash_dedupes_matching_rgba_pixels() -> None:
    rgb = Image.new("RGB", (8, 8), (200, 40, 20))
    rgba = Image.new("RGBA", (8, 8), (200, 40, 20, 255))
    different = Image.new("RGBA", (8, 8), (20, 40, 200, 255))

    assert artwork_compare_hash(rgb) == artwork_compare_hash(rgba)
    assert artwork_compare_hash(rgb) != artwork_compare_hash(different)


def test_unify_artwork_context_collapses_duplicate_visual_images(monkeypatch) -> None:
    red = Image.new("RGBA", (12, 12), (220, 30, 30, 255))
    blue = Image.new("RGBA", (12, 12), (30, 60, 220, 255))
    tracks = [
        {"db_track_id": 1, "Title": "A"},
        {"db_track_id": 2, "Title": "B"},
        {"db_track_id": 3, "Title": "C"},
    ]
    images = {1: red, 2: red.copy(), 3: blue}

    monkeypatch.setattr(
        "iopenpod.gui.imgMaker.configure_artwork_api",
        lambda *_args, **_kwargs: ({}, {}),
    )
    monkeypatch.setattr(
        artwork_unifier_module,
        "_track_artwork_image_for_unify",
        lambda track, **_kwargs: (
            images[int(track["db_track_id"])],
            int(track["db_track_id"]) + 100,
            "Artwork",
        ),
    )

    context = build_album_artwork_unify_context(
        {"title": "Album"},
        tracks,
        artworkdb_path="/fake/ArtworkDB",
        artwork_folder_path="/fake/Artwork",
    )

    assert context is not None
    assert len(context.choices) == 2
    assert [choice.track_count for choice in context.choices] == [2, 1]
    assert context.missing_count == 0


def test_unify_artwork_context_available_for_missing_artwork(monkeypatch) -> None:
    green = Image.new("RGBA", (12, 12), (30, 180, 80, 255))
    tracks = [
        {"db_track_id": 1, "Title": "A"},
        {"db_track_id": 2, "Title": "B"},
    ]

    monkeypatch.setattr(
        "iopenpod.gui.imgMaker.configure_artwork_api",
        lambda *_args, **_kwargs: ({}, {}),
    )
    monkeypatch.setattr(
        artwork_unifier_module,
        "_track_artwork_image_for_unify",
        lambda track, **_kwargs: (
            (green, 101, "Artwork")
            if int(track["db_track_id"]) == 1
            else None
        ),
    )

    context = build_album_artwork_unify_context(
        {"title": "Album"},
        tracks,
        artworkdb_path="/fake/ArtworkDB",
        artwork_folder_path="/fake/Artwork",
    )

    assert context is not None
    assert len(context.choices) == 1
    assert context.missing_count == 1
