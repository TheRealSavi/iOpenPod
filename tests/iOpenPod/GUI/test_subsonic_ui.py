"""Tests for Subsonic GUI mapping dialog, settings widget, and sidebar integration."""

from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.subsonic.controller import SubsonicController
from iOpenPod.app.subsonic.models import (
    SubsonicPlaylist,
    SubsonicSyncMode,
)
from iOpenPod.app.subsonic.settings import (
    SUBSONIC_URL,
    SUBSONIC_USERNAME,
)
from iOpenPod.GUI.dialogs.subsonic_mapping import SubsonicPlaylistMappingDialog
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.widgets.sidebar import Sidebar
from iOpenPod.GUI.widgets.subsonic_settings import SubsonicSettings
from iPodDB.library import Playlist, PlaylistKind, PlaylistSortOrder


def test_subsonic_playlist_mapping_dialog() -> None:
    _app = APPLICATION
    sub_playlists = (
        SubsonicPlaylist(playlist_id="sub-1", name="Chill Vibes", song_count=12),
        SubsonicPlaylist(playlist_id="sub-2", name="Workout", song_count=30),
    )
    ipod_playlists = (
        Playlist(1, "Existing Playlist", PlaylistKind.PLAYLIST, sort_order=PlaylistSortOrder.MANUAL),
        Playlist(2, "Smart One", PlaylistKind.SMART, sort_order=PlaylistSortOrder.MANUAL),
        Playlist(3, "Folder One", PlaylistKind.FOLDER, sort_order=PlaylistSortOrder.DEFAULT),
    )

    dlg = SubsonicPlaylistMappingDialog(
        sub_playlists,
        ipod_playlists,
        saved_mappings={"sub-1": 1},
    )

    # Only PlaylistKind.PLAYLIST should be in target dropdowns (smart & folder excluded)
    assert len(dlg._ipod_playlists) == 1
    assert dlg._ipod_playlists[0].playlist_id == 1

    mappings = dlg.get_mappings()
    assert len(mappings) == 2
    assert mappings[0].subsonic_id == "sub-1"
    assert mappings[0].target_ipod_id == 1
    assert mappings[0].mode == SubsonicSyncMode.MERGE

    assert mappings[1].subsonic_id == "sub-2"
    assert mappings[1].target_ipod_id is None


def test_subsonic_settings_widget() -> None:
    _app = APPLICATION
    context = build_context()
    controller = SubsonicController(context.settings)
    context.settings.set_global(SUBSONIC_URL, "https://music.home.arpa")
    context.settings.set_global(SUBSONIC_USERNAME, "alice")

    widget = SubsonicSettings(context.settings, controller)
    assert widget._url_edit.text() == "https://music.home.arpa"
    assert widget._username_edit.text() == "alice"

    # Simulate playlist load
    playlists = (
        SubsonicPlaylist(playlist_id="p1", name="Favorites", song_count=5),
        SubsonicPlaylist(playlist_id="p2", name="Rock", song_count=10),
    )
    widget._on_playlists_loaded(playlists)
    assert len(widget._checkboxes) == 2

    widget._select_all()
    assert widget._checkboxes["p1"].isChecked()
    assert widget._checkboxes["p2"].isChecked()

    widget._deselect_all()
    assert not widget._checkboxes["p1"].isChecked()
    assert not widget._checkboxes["p2"].isChecked()


def test_main_window_has_subsonic_sync_button() -> None:
    _app = APPLICATION
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    sidebar = window.findChild(Sidebar)
    assert sidebar is not None
    assert hasattr(sidebar, "_subsonic_sync")
    assert sidebar._subsonic_sync.objectName() == "syncSubsonic"
