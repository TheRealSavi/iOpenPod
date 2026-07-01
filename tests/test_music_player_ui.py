from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from app_core.services import DeviceSessionService, SettingsService
from GUI.app import MainWindow, _playback_track_path_for_session, _track_artwork_id
from GUI.widgets.MBListView import MusicBrowserList
from GUI.widgets.musicPlayer import MusicPlayerBar
from infrastructure.settings_schema import AppSettings


class _SettingsService:
    def __init__(self) -> None:
        self.settings = AppSettings()

    def get_global_settings(self) -> AppSettings:
        return self.settings

    def get_effective_settings(self) -> AppSettings:
        return self.settings


class _DeviceSessions:
    def current_session(self):
        return SimpleNamespace(device_path="", identity=None, capabilities=None)


def _mount_track_list(qtbot) -> MusicBrowserList:
    view = MusicBrowserList(
        settings_service=cast(SettingsService, _SettingsService()),
        device_sessions=cast(DeviceSessionService, _DeviceSessions()),
        library_cache=None,
        show_art_override=False,
    )
    qtbot.addWidget(view)
    view.resize(700, 360)
    view.show()
    qtbot.wait(50)
    return view


def _load_tracks(qtbot, view: MusicBrowserList, tracks: list[dict]) -> None:
    view.clearTable()
    view._all_tracks = tracks
    view._tracks = tracks
    view._media_type_filter = 0x01
    view._is_playlist_mode = False
    view._setup_columns()
    view._populate_table()
    qtbot.waitUntil(lambda: view.table.rowCount() == len(tracks), timeout=2000)


def test_track_list_activation_emits_current_track(qtbot) -> None:
    view = _mount_track_list(qtbot)
    tracks = [
        {
            "Title": "Song A",
            "Artist": "Artist A",
            "Album": "Album A",
            "length": 180000,
        }
    ]
    _load_tracks(qtbot, view, tracks)

    view.table.setCurrentCell(0, 0)

    with qtbot.waitSignal(view.track_activated, timeout=1000) as signal:
        assert view._activate_current_track() is True

    assert signal.args == [tracks[0]]


def test_track_list_activation_emits_playback_queue_context(qtbot) -> None:
    view = _mount_track_list(qtbot)
    tracks = [
        {
            "Title": "Song A",
            "Artist": "Artist A",
            "Album": "Album A",
            "length": 180000,
        },
        {
            "Title": "Song B",
            "Artist": "Artist B",
            "Album": "Album B",
            "length": 181000,
        },
    ]
    _load_tracks(qtbot, view, tracks)

    view.table.setCurrentCell(1, 0)

    with qtbot.waitSignal(view.playback_requested, timeout=1000) as signal:
        assert view._activate_current_track() is True

    assert signal.args == [tracks[1], tracks, 1]


def test_music_player_bar_shows_track_metadata_and_transport_state(qtbot) -> None:
    player = MusicPlayerBar()
    qtbot.addWidget(player)
    player.show()

    player.setTrack(
        {
            "Title": "Song A",
            "Artist": "Artist A",
            "Album": "Album A",
            "length": 180000,
            "rating": 40,
        }
    )

    assert player.title_label.text() == "Song A"
    assert player.detail_label.text() == "Artist A - Album A"
    assert player.duration_label.text() == "3:00"
    assert player.progress_slider.maximum() == 180000
    assert player.progress_slider.isEnabled()
    assert player.rating_control.rating() == 40

    player.setQueueContext(1, 3)
    assert player.queue_label.text() == "Track 2 of 3"
    assert not player.queue_label.isVisible()

    with qtbot.waitSignal(player.play_pause_requested, timeout=1000) as signal:
        player.play_button.click()

    assert signal.args == [True]
    assert player.isPlaying() is True

    player.setPosition(61000)
    assert player.current_time_label.text() == "1:01"
    assert player.progress_slider.value() == 61000

    player.setDuration(181000)
    assert player.duration_label.text() == "3:01"
    assert player.progress_slider.maximum() == 181000

    player.setTransportAvailability(True, False)
    assert player.previous_button.isEnabled()
    assert not player.next_button.isEnabled()

    hover_pos = QPointF(player.rating_control.starCenter(1))
    player.rating_control.mouseMoveEvent(
        QMouseEvent(
            QEvent.Type.MouseMove,
            hover_pos,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert player.rating_control.previewRating() == 20
    assert player.rating_control.rating() == 40

    with qtbot.waitSignal(player.rating_changed, timeout=1000) as signal:
        qtbot.mouseClick(
            player.rating_control,
            Qt.MouseButton.LeftButton,
            pos=player.rating_control.starCenter(5),
        )

    assert signal.args == [100]
    assert player.rating_control.rating() == 100

    player.setVolumePercent(65)
    assert player.volumePercent() == 65
    assert player.volume_label.text() == "65%"

    with qtbot.waitSignal(player.volume_changed, timeout=1000) as signal:
        player.volume_slider.setValue(42)

    assert signal.args == [42]
    assert player.volume_label.text() == "42%"

    player.setArtworkData((1, 1, bytes([255, 0, 0, 255])))
    pixmap = player.art_label.pixmap()
    assert pixmap is not None
    assert not pixmap.isNull()
    assert round(pixmap.width() / pixmap.devicePixelRatio()) == player.art_label.width()
    assert round(pixmap.height() / pixmap.devicePixelRatio()) == player.art_label.height()
    rendered = pixmap.toImage()
    assert rendered.pixelColor(0, rendered.height() // 2).alpha() > 0
    assert rendered.pixelColor(rendered.width() // 2, 0).alpha() > 0

    with qtbot.waitSignal(player.close_requested, timeout=1000):
        player.close_button.click()


def test_music_player_artwork_contains_wide_images_without_cover_crop(qtbot) -> None:
    player = MusicPlayerBar()
    qtbot.addWidget(player)
    player.show()

    width = 4
    height = 1
    rgba = bytes(
        [
            255, 0, 0, 255,
            0, 255, 0, 255,
            0, 0, 255, 255,
            255, 255, 0, 255,
        ]
    )

    player.setArtworkData((width, height, rgba))

    pixmap = player.art_label.pixmap()
    assert pixmap is not None
    assert round(pixmap.width() / pixmap.devicePixelRatio()) == player.art_label.width()
    assert round(pixmap.height() / pixmap.devicePixelRatio()) == player.art_label.height()

    rendered = pixmap.toImage()
    top_middle = rendered.pixelColor(rendered.width() // 2, 0)
    center_middle = rendered.pixelColor(rendered.width() // 2, rendered.height() // 2)
    assert top_middle.alpha() == 0
    assert center_middle.alpha() > 0


def test_playback_path_resolves_itunesdb_location_from_ipod_root(tmp_path) -> None:
    track_file = tmp_path / "iPod_Control" / "Music" / "F00" / "SONG.m4a"
    track_file.parent.mkdir(parents=True)
    track_file.write_bytes(b"audio")
    session = SimpleNamespace(device_path=str(tmp_path))

    resolved = _playback_track_path_for_session(
        session,
        {"Location": ":iPod_Control:Music:F00:SONG.m4a"},
    )

    assert resolved == str(track_file)


def test_track_artwork_id_uses_itunesdb_artwork_fields() -> None:
    assert _track_artwork_id({"artwork_id_ref": "42"}) == 42
    assert _track_artwork_id({"mhii_link": 77}) == 77
    assert _track_artwork_id({"artwork_id_ref": 0, "mhiiLink": "12"}) == 12


def test_player_position_setting_moves_player_bar(qtbot) -> None:
    shell = QWidget()
    layout = QVBoxLayout(shell)
    content = QWidget()
    player = QWidget()
    settings = AppSettings()
    service = SimpleNamespace(get_effective_settings=lambda: settings)
    window = SimpleNamespace(
        appShellLayout=layout,
        centralStack=content,
        musicPlayer=player,
        settings_service=service,
    )
    window._current_player_position = MainWindow._current_player_position.__get__(
        window
    )
    qtbot.addWidget(shell)

    layout.addWidget(content, 1)
    layout.addWidget(player, 0)

    settings.player_position = "top"
    MainWindow._apply_player_position(cast(MainWindow, window))

    assert layout.itemAt(0).widget() is player
    assert layout.itemAt(1).widget() is content

    settings.player_position = "bottom"
    MainWindow._apply_player_position(cast(MainWindow, window))

    assert layout.itemAt(0).widget() is content
    assert layout.itemAt(1).widget() is player


def test_player_rating_change_updates_cache_track_edits() -> None:
    class _Cache:
        def __init__(self) -> None:
            self.updated: list[tuple[list[dict], dict[str, int]]] = []

        def is_ready(self) -> bool:
            return True

        def update_track_flags(self, tracks: list[dict], changes: dict[str, int]) -> None:
            self.updated.append((list(tracks), dict(changes)))
            for track in tracks:
                track.update(changes)

    track = {"db_track_id": 123, "Title": "Song A", "rating": 40}
    cache = _Cache()
    window = SimpleNamespace(
        _playback_tracks=[track],
        _playback_index=0,
        library_cache=cache,
    )

    MainWindow._onPlayerRatingChanged(cast(MainWindow, window), 100)

    assert cache.updated == [([track], {"rating": 100})]
    assert track["rating"] == 100
