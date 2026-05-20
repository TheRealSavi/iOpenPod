from types import SimpleNamespace
from typing import Any, cast

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
