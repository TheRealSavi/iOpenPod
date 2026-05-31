from types import SimpleNamespace
from typing import Any, cast

from PyQt6.QtCore import QPoint

from GUI.styles import Colors, context_menu_css
from GUI.widgets.musicBrowser import MusicBrowser


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

    monkeypatch.setattr("GUI.widgets.musicBrowser.QMenu", _Menu)
    monkeypatch.setattr("GUI.widgets.musicBrowser.glyph_icon", lambda *_args: None)

    emitted: list[list[dict]] = []
    browser = SimpleNamespace(
        _current_category="Albums",
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
