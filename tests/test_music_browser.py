from types import SimpleNamespace
from typing import Any, cast

from PIL import Image
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QSplitter

from iopenpod.gui.styles import Colors, context_menu_css
from iopenpod.gui.widgets import artworkUnifier as artwork_unifier_module
from iopenpod.gui.widgets.artworkUnifier import (
    artwork_compare_hash,
    build_album_artwork_unify_context,
)
from iopenpod.gui.widgets.musicBrowser import MusicBrowser
from iopenpod.gui.widgets.trackListTitleBar import TrackListTitleBar, _resolve_bar_palette


def _build_browser(category: str = "Albums") -> Any:
    scheduled: list[str] = []
    browser = SimpleNamespace(
        _current_category=category,
        _tab_dirty={
            "Playlists": False,
            "Podcasts": False,
            "Photos": False,
        },
        _schedule_refresh_current_category=lambda: scheduled.append("refresh"),
    )
    browser._mark_tab_dirty = MusicBrowser._mark_tab_dirty.__get__(browser)
    return cast(Any, browser), scheduled


def test_track_edits_mark_related_tabs_dirty_and_refresh_current_category() -> None:
    browser, scheduled = _build_browser("Albums")

    MusicBrowser._on_tracks_changed(browser)

    assert browser._tab_dirty["Playlists"] is True
    assert browser._tab_dirty["Podcasts"] is True
    assert browser._tab_dirty["Photos"] is False
    assert scheduled == ["refresh"]


def test_track_edits_do_not_reload_photo_browser() -> None:
    browser, scheduled = _build_browser("Photos")

    MusicBrowser._on_tracks_changed(browser)

    assert browser._tab_dirty["Playlists"] is True
    assert browser._tab_dirty["Podcasts"] is True
    assert browser._tab_dirty["Photos"] is False
    assert scheduled == []


def test_context_menu_css_styles_disabled_rows_and_icon_gutter() -> None:
    css = context_menu_css()

    assert "padding: 4px 6px;" in css
    assert "padding: 6px 24px 6px 12px;" in css
    assert "QMenu::item:disabled" in css
    assert "QMenu::item:disabled:selected" in css
    assert f"color: {Colors.TEXT_DISABLED};" in css


def test_album_grid_context_menu_uses_shared_menu_style(monkeypatch) -> None:
    class _Action:
        def __init__(self) -> None:
            self._enabled = True

        def setIcon(self, _icon) -> None:
            pass

        def setEnabled(self, enabled: bool) -> None:
            self._enabled = enabled

        def isEnabled(self) -> bool:
            return self._enabled

    class _Menu:
        last: "_Menu | None" = None

        def __init__(self, _parent) -> None:
            self._style = ""
            self.exec_pos = None
            _Menu.last = self

        def setStyleSheet(self, style: str) -> None:
            self._style = style

        def styleSheet(self) -> str:
            return self._style

        def addAction(self, _label: str) -> _Action:
            return _Action()

        def exec(self, pos: QPoint):
            self.exec_pos = pos
            return None

    monkeypatch.setattr("iopenpod.gui.widgets.musicBrowser.QMenu", _Menu)
    monkeypatch.setattr("iopenpod.gui.widgets.musicBrowser.glyph_icon", lambda *_args: None)

    emitted: list[list[dict]] = []
    browser = SimpleNamespace(
        _current_category="Albums",
        _album_artwork_unify_context=lambda _item: None,
        album_conversion_requested=SimpleNamespace(emit=emitted.append),
    )

    pos = QPoint(12, 34)
    MusicBrowser._onGridItemContextRequested(
        cast(Any, browser),
        [{"category": "Albums", "track_count": 2}],
        pos,
    )

    assert _Menu.last is not None
    assert _Menu.last.styleSheet() == context_menu_css()
    assert _Menu.last.exec_pos == pos
    assert emitted == []


def test_album_grid_context_menu_edit_opens_album_tracks(monkeypatch) -> None:
    class _Action:
        def __init__(self, label: str) -> None:
            self.label = label
            self._enabled = True

        def setIcon(self, _icon) -> None:
            pass

        def setEnabled(self, enabled: bool) -> None:
            self._enabled = enabled

        def isEnabled(self) -> bool:
            return self._enabled

    class _Menu:
        def __init__(self, _parent) -> None:
            self.actions: list[_Action] = []

        def setStyleSheet(self, _style: str) -> None:
            pass

        def addAction(self, label: str) -> _Action:
            action = _Action(label)
            self.actions.append(action)
            return action

        def exec(self, _pos: QPoint):
            return next(action for action in self.actions if action.label == "Edit")

    monkeypatch.setattr("iopenpod.gui.widgets.musicBrowser.QMenu", _Menu)
    monkeypatch.setattr("iopenpod.gui.widgets.musicBrowser.glyph_icon", lambda *_args: None)

    edited: list[dict] = []
    browser = SimpleNamespace(
        _current_category="Albums",
        _album_artwork_unify_context=lambda _item: None,
        _edit_album_tracks=edited.append,
        album_conversion_requested=SimpleNamespace(emit=lambda _items: None),
    )
    album_item = {"category": "Albums", "track_count": 3, "title": "Album"}

    MusicBrowser._onGridItemContextRequested(
        cast(Any, browser),
        [album_item],
        QPoint(12, 34),
    )

    assert edited == [album_item]


def test_title_bar_palette_reuses_contrast_ensured_grid_color() -> None:
    display_rgb = (86, 112, 144)

    palette = _resolve_bar_palette(display_rgb, contrast_ensured=True)

    assert palette["bg"] == display_rgb


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
