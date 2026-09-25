"""Focused GUI contracts for the Player and Playback pane."""

from dataclasses import replace
from typing import Any, cast

from PySide6.QtCore import (
    QAbstractAnimation,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QContextMenuEvent, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QLabel,
    QListView,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QStackedWidget,
    QStyleOptionToolButton,
    QTabWidget,
    QWidget,
)
from pytest import MonkeyPatch, mark
from tests.iOpenPod.GUI.application_shell_test_support import (
    APPLICATION,
    build_context,
)
from tests.iOpenPod.GUI.application_shell_test_support import (
    tracks as build_tracks,
)
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.core.settings.definitions import AppearanceMode
from iOpenPod.app.models.library_drag import (
    PlaylistSelectionMimeData,
    TrackSelectionMimeData,
)
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets import player_bar as player_bar_module
from iOpenPod.GUI.widgets.player_bar import PlayerBar
from iOpenPod.GUI.widgets.themed_buttons import IconButton, IconButtonKind
from iOpenPod.GUI.widgets.track_table import TrackTable
from iPodDB.library import LibrarySnapshot, Playlist, Track, playlist_entries


def test_double_click_enqueues_without_single_selection_starting_playback() -> None:
    context = build_context()
    tracks = build_tracks(3)
    context.track_model.replace_tracks(tracks)
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()
        tracks_button = next(
            button
            for button in window.findChildren(QPushButton)
            if button.property("pageId") == PageId.TRACKS.value
        )
        tracks_button.click()
        APPLICATION.processEvents()
        table = window.findChild(TrackTable, "tracksTrackTable")
        player_title = window.findChild(QLabel, "playerTrackTitle")
        assert table is not None
        assert player_title is not None
        first = table.model().index(0, 0)
        second = table.model().index(1, 0)

        table.setCurrentIndex(first)
        APPLICATION.processEvents()
        assert context.playback_controller.current_track is None
        assert player_title.text() == "Nothing playing"

        table.doubleClicked.emit(first)
        APPLICATION.processEvents()
        playing_track = context.playback_controller.current_track
        assert isinstance(playing_track, Track)
        assert playing_track == tracks[0]
        assert player_title.text() == "Track 00000"

        table.doubleClicked.emit(second)
        APPLICATION.processEvents()
        assert tuple(
            entry.track for entry in context.playback_controller.queue_model.entries
        ) == (tracks[1],)
    finally:
        window.close()
        context.shutdown()


def test_playback_pane_toggles_and_operates_on_pending_queue_only() -> None:
    context = build_context()
    tracks = build_tracks(4)
    context.track_model.replace_tracks(tracks)
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()
        pane = window.findChild(QWidget, "playbackPane")
        queue_toggle = window.findChild(IconButton, "playerQueueToggle")
        tabs = window.findChild(QTabWidget, "playbackTabs")
        queue_view = window.findChild(QListView, "playbackQueueView")
        history_view = window.findChild(QListView, "playbackHistoryView")
        clear_queue = window.findChild(QPushButton, "playbackClearQueue")
        assert pane is not None
        assert queue_toggle is not None
        assert tabs is not None
        assert queue_view is not None
        assert history_view is not None
        assert clear_queue is not None
        assert pane.isHidden()

        queue_toggle.click()
        APPLICATION.processEvents()
        assert pane.isVisible()
        assert pane.width() == LAYOUT.playback_pane_width
        tab_bar = tabs.tabBar()
        assert tab_bar.expanding()
        assert [tabs.tabText(index) for index in range(tabs.count())] == [
            "Queue",
            "History",
            "Lyrics",
        ]
        for index in range(tabs.count()):
            assert abs(tab_bar.tabRect(index).width() - tab_bar.width() / 3) <= 1

        lyrics = window.findChild(QPlainTextEdit, "playbackLyricsText")
        assert lyrics is not None
        tabs.setCurrentIndex(2)
        assert lyrics.isVisible()
        assert lyrics.isReadOnly()
        assert lyrics.placeholderText() == "Play a track to see its lyrics."
        QTest.keyClicks(lyrics, "Cannot edit lyrics")
        assert lyrics.toPlainText() == ""
        tabs.setCurrentIndex(0)

        context.playback_controller.enqueue(tracks[0])
        context.playback_controller.enqueue(tracks[1])
        context.playback_controller.enqueue(tracks[2])
        APPLICATION.processEvents()
        assert history_view.model().rowCount() == 1
        assert queue_view.model().rowCount() == 2

        queue_view.setCurrentIndex(queue_view.model().index(0, 0))
        QTest.keyClick(queue_view, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
        assert tuple(
            entry.track for entry in context.playback_controller.queue_model.entries
        ) == (tracks[2], tracks[1])

        QTest.keyClick(queue_view, Qt.Key.Key_Delete)
        assert tuple(
            entry.track for entry in context.playback_controller.queue_model.entries
        ) == (tracks[2],)
        assert context.playback_controller.current_track == tracks[0]
        assert history_view.model().rowCount() == 1

        clear_queue.click()
        assert queue_view.model().rowCount() == 0
        assert context.playback_controller.current_track == tracks[0]
        assert history_view.model().rowCount() == 1

        context.playback_controller.enqueue(tracks[3])
        APPLICATION.processEvents()
        queued = queue_view.model().index(0, 0)
        queued_rect = queue_view.visualRect(queued)
        remove_center = QPoint(
            queued_rect.right() - LAYOUT.space_xs - (LAYOUT.minimum_touch_target // 2),
            queued_rect.center().y(),
        )
        QTest.mouseClick(
            queue_view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=remove_center,
        )
        assert queue_view.model().rowCount() == 0
        assert context.playback_controller.current_track == tracks[0]

        tabs.setCurrentIndex(1)
        assert tabs.tabText(1) == "History"
        queue_toggle.click()
        QTest.qWait(LAYOUT.playback_pane_animation_ms + 40)
        assert pane.isHidden()
    finally:
        window.close()
        context.shutdown()


@mark.parametrize("pane_open", (False, True))
@mark.parametrize("pending_count", (0, 2))
def test_player_queue_context_menu_clears_only_pending_tracks(
    pane_open: bool,
    pending_count: int,
) -> None:
    context = build_context()
    controller = context.playback_controller
    tracks = build_tracks(3)
    controller.enqueue(tracks[0])
    window = MainWindow(context, auto_discover=False)
    menus: list[list[tuple[str, bool]]] = []

    try:
        window.show()
        queue_toggle = window.findChild(IconButton, "playerQueueToggle")
        pane = window.findChild(QWidget, "playbackPane")
        assert queue_toggle is not None
        assert pane is not None
        style_option = QStyleOptionToolButton()
        queue_toggle.initStyleOption(style_option)
        assert (
            not style_option.features & QStyleOptionToolButton.ToolButtonFeature.HasMenu
        )
        for track in tracks[1 : pending_count + 1]:
            controller.enqueue(track)
        controller.seek(45_000)
        history = controller.history_model.entries
        if pane_open:
            QTest.mouseClick(queue_toggle, Qt.MouseButton.LeftButton)
            QTest.qWait(LAYOUT.playback_pane_animation_ms + 40)
        APPLICATION.processEvents()

        def use_and_close_menu() -> None:
            menu = APPLICATION.activePopupWidget()
            if not isinstance(menu, QMenu):
                return
            actions = menu.actions()
            menus.append([(action.text(), action.isEnabled()) for action in actions])
            if actions and actions[0].isEnabled():
                QTest.mouseClick(
                    menu,
                    Qt.MouseButton.LeftButton,
                    pos=menu.actionGeometry(actions[0]).center(),
                )
            menu.close()

        # Qt's offscreen platform requires the context event explicitly.
        point = queue_toggle.rect().center()
        for _ in range(2):
            QTimer.singleShot(0, use_and_close_menu)
            APPLICATION.sendEvent(
                queue_toggle,
                QContextMenuEvent(
                    QContextMenuEvent.Reason.Mouse,
                    point,
                    queue_toggle.mapToGlobal(point),
                ),
            )

        assert menus == [[("Clear Queue", pending_count > 0)], [("Clear Queue", False)]]
        assert controller.queue_model.rowCount() == 0
        assert controller.current_track == tracks[0]
        assert controller.playing
        assert controller.position_ms == 45_000
        assert controller.history_model.entries == history
        assert queue_toggle.isChecked() is pane_open
        assert pane.isVisible() is pane_open

        QTest.mouseClick(queue_toggle, Qt.MouseButton.LeftButton)
        QTest.qWait(LAYOUT.playback_pane_animation_ms + 40)
        assert queue_toggle.isChecked() is not pane_open
        assert pane.isVisible() is not pane_open
    finally:
        window.close()
        context.shutdown()


def test_empty_queue_surface_accepts_a_table_track_drop() -> None:
    context = build_context()
    track = build_tracks(1)[0]
    context.library_workspace.load(LibrarySnapshot(tracks=(track,)))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()
        queue_stack = window.findChild(QStackedWidget, "playbackQueueStack")
        assert queue_stack is not None
        empty = queue_stack.currentWidget()
        assert empty is not None
        data = TrackSelectionMimeData(
            context.library_workspace,
            (track.track_id,),
        )
        event = QDropEvent(
            QPointF(8, 8),
            Qt.DropAction.CopyAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        cast("Any", empty).dropEvent(event)

        assert context.playback_controller.current_track == track
    finally:
        window.close()
        context.shutdown()


def test_player_playlist_drop_starts_first_and_prepends_the_rest() -> None:
    context = build_context()
    tracks = build_tracks(5)
    playlist = Playlist(10, "Road Mix", entries=playlist_entries((1, 2, 3)))
    context.library_workspace.load(
        LibrarySnapshot(tracks=tracks, playlists=(playlist,))
    )
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        controller = context.playback_controller
        controller.enqueue(tracks[0])
        controller.enqueue(tracks[4])
        APPLICATION.processEvents()
        player = window.findChild(PlayerBar)
        assert player is not None
        data = PlaylistSelectionMimeData(
            context.library_workspace,
            playlist.playlist_id,
        )
        event = QDropEvent(
            QPointF(player.rect().center()),
            Qt.DropAction.CopyAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        player.dropEvent(event)

        assert controller.current_track == tracks[1]
        assert tuple(entry.track for entry in controller.queue_model.entries) == (
            tracks[2],
            tracks[3],
            tracks[4],
        )
    finally:
        window.close()
        context.shutdown()


def test_player_track_drop_starts_that_track_immediately() -> None:
    context = build_context()
    tracks = build_tracks(2)
    context.library_workspace.load(LibrarySnapshot(tracks=tracks))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        context.playback_controller.enqueue(tracks[0])
        APPLICATION.processEvents()
        player = window.findChild(PlayerBar)
        assert player is not None
        data = TrackSelectionMimeData(
            context.library_workspace,
            (tracks[1].track_id,),
        )
        event = QDropEvent(
            QPointF(player.rect().center()),
            Qt.DropAction.CopyAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        player.dropEvent(event)

        assert context.playback_controller.current_track == tracks[1]
    finally:
        window.close()
        context.shutdown()


def test_now_playing_details_drag_the_shared_track_payload(
    monkeypatch: MonkeyPatch,
) -> None:
    context = build_context()
    track = build_tracks(1)[0]
    context.library_workspace.load(LibrarySnapshot(tracks=(track,)))
    window = MainWindow(context, auto_discover=False)
    captured: list[object] = []

    class FakeDrag:
        def __init__(self, _source: object) -> None:
            pass

        def setMimeData(self, data: object) -> None:
            captured.append(data)

        def setPixmap(self, _pixmap: object) -> None:
            pass

        def setHotSpot(self, _point: object) -> None:
            pass

        def exec(self, _actions: object) -> Qt.DropAction:
            return Qt.DropAction.CopyAction

    monkeypatch.setattr(player_bar_module, "QDrag", FakeDrag)
    try:
        window.show()
        context.playback_controller.enqueue(track)
        APPLICATION.processEvents()
        details = window.findChild(QLabel, "playerTrackTitle")
        assert details is not None
        start = QPointF(1, 1)
        end = QPointF(APPLICATION.startDragDistance() + 2, 1)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            start,
            QPointF(details.mapToGlobal(start.toPoint())),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            end,
            QPointF(details.mapToGlobal(end.toPoint())),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        APPLICATION.sendEvent(details, press)
        APPLICATION.sendEvent(details, move)

        assert len(captured) == 1
        data = captured[0]
        assert isinstance(data, TrackSelectionMimeData)
        assert data.track_ids == (track.track_id,)
        assert data.belongs_to(
            context.library_workspace,
            require_editable=False,
        )
    finally:
        window.close()
        context.shutdown()


def test_now_playing_details_show_the_current_tracks_shared_context_menu() -> None:
    context = build_context()
    tracks = build_tracks(2)
    context.library_workspace.load(LibrarySnapshot(tracks=tracks))
    window = MainWindow(context, auto_discover=False)
    opened: list[bool] = []

    try:
        window.show()
        context.playback_controller.enqueue(tracks[1])
        APPLICATION.processEvents()
        details = window.findChild(QLabel, "playerTrackDetail")
        assert details is not None
        point = details.rect().center()

        def use_and_close_menu() -> None:
            menu = window.findChild(QMenu, "trackContextMenu")
            opened.append(menu is not None and menu.isVisible())
            if menu is None:
                return
            copy = next(
                action for action in menu.actions() if action.text() == "Copy as Text"
            )
            copy.trigger()
            menu.close()

        QTimer.singleShot(0, use_and_close_menu)
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse,
            point,
            details.mapToGlobal(point),
        )

        APPLICATION.sendEvent(details, event)

        assert opened == [True]
        assert APPLICATION.clipboard().text() == "\t".join(
            (tracks[1].title, tracks[1].artist, tracks[1].album)
        )
    finally:
        window.close()
        context.shutdown()


def test_queue_and_history_share_surfaces_and_artwork_rows() -> None:
    context = build_context()
    original_mode = context.theme_manager.mode
    tracks = build_tracks(2)
    window = MainWindow(context, auto_discover=False)

    try:
        context.theme_manager.set_mode(AppearanceMode.LIGHT)
        window.show()
        queue_toggle = window.findChild(IconButton, "playerQueueToggle")
        queue_stack = window.findChild(QStackedWidget, "playbackQueueStack")
        tabs = window.findChild(QTabWidget, "playbackTabs")
        queue_view = window.findChild(QListView, "playbackQueueView")
        history_view = window.findChild(QListView, "playbackHistoryView")
        assert queue_toggle is not None
        assert queue_stack is not None
        assert tabs is not None
        assert queue_view is not None
        assert history_view is not None

        queue_toggle.click()
        QTest.qWait(LAYOUT.playback_pane_animation_ms + 40)
        APPLICATION.processEvents()

        def sampled_surface() -> QColor:
            sample_point = QPoint(
                LAYOUT.space_md,
                queue_stack.height() - LAYOUT.space_md,
            )
            return queue_stack.grab().toImage().pixelColor(sample_point)

        empty_surface = sampled_surface()

        context.playback_controller.enqueue(tracks[0])
        context.playback_controller.enqueue(tracks[1])
        APPLICATION.processEvents()
        populated_surface = sampled_surface()

        expected_surface = QColor(context.theme_manager.tokens.surface)
        assert empty_surface == expected_surface
        assert populated_surface == expected_surface

        artwork_colors = {
            QColor(value).rgba()
            for value in (
                context.theme_manager.tokens.artwork_blue,
                context.theme_manager.tokens.artwork_green,
                context.theme_manager.tokens.artwork_gold,
                context.theme_manager.tokens.artwork_coral,
                context.theme_manager.tokens.artwork_violet,
                context.theme_manager.tokens.artwork_slate,
            )
        }
        for tab_index, view in enumerate((queue_view, history_view)):
            tabs.setCurrentIndex(tab_index)
            APPLICATION.processEvents()
            index = view.model().index(0, 0)
            row_rect = view.visualRect(index)
            artwork_left = row_rect.left() + LAYOUT.space_xs
            artwork_top = row_rect.top() + (
                (row_rect.height() - LAYOUT.playback_row_artwork_size) // 2
            )
            rendered = view.viewport().grab().toImage()
            assert row_rect.height() == LAYOUT.playback_row_height
            assert any(
                rendered.pixelColor(x, y).rgba() in artwork_colors
                for y in range(
                    artwork_top,
                    artwork_top + LAYOUT.playback_row_artwork_size,
                )
                for x in range(
                    artwork_left,
                    artwork_left + LAYOUT.playback_row_artwork_size,
                )
            )
    finally:
        context.theme_manager.set_mode(original_mode)
        window.close()
        context.shutdown()


def test_playback_pane_animates_inside_its_final_reserved_layout() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()
        pages = window.findChild(QStackedWidget, "pageStack")
        pane = window.findChild(QWidget, "playbackPane")
        host = window.findChild(QWidget, "playbackPaneHost")
        queue_toggle = window.findChild(IconButton, "playerQueueToggle")
        assert pages is not None
        assert pane is not None
        assert host is not None
        assert queue_toggle is not None
        closed_page_width = pages.width()

        queue_toggle.click()
        APPLICATION.processEvents()
        open_page_width = pages.width()
        assert open_page_width == closed_page_width - LAYOUT.playback_pane_width
        assert pane.x() > 0

        QTest.qWait(LAYOUT.playback_pane_animation_ms // 2)
        assert pages.width() == open_page_width
        QTest.qWait(LAYOUT.playback_pane_animation_ms)
        assert pane.x() == 0
        assert pages.width() == open_page_width

        queue_toggle.click()
        APPLICATION.processEvents()
        assert pages.width() == open_page_width
        QTest.qWait(LAYOUT.playback_pane_animation_ms // 2)
        assert pages.width() == open_page_width
        QTest.qWait(LAYOUT.playback_pane_animation_ms)
        assert host.isHidden()
        assert pages.width() == closed_page_width
    finally:
        window.close()
        context.shutdown()


def test_player_remains_centered_and_controls_breathe_at_supported_widths() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)

    try:
        context.playback_controller.enqueue(build_tracks(1)[0])
        window.show()
        APPLICATION.processEvents()
        player = window.findChild(PlayerBar)
        surface = window.findChild(QWidget, "nowPlayingSurface")
        left_zone = window.findChild(QWidget, "playerLeftZone")
        center_zone = window.findChild(QWidget, "playerCenterZone")
        right_zone = window.findChild(QWidget, "playerRightZone")
        previous = window.findChild(IconButton, "playerPrevious")
        play = window.findChild(IconButton, "playerPlayPause")
        next_button = window.findChild(IconButton, "playerNext")
        mute = window.findChild(IconButton, "playerMute")
        volume = window.findChild(QWidget, "volumeSlider")
        queue_toggle = window.findChild(IconButton, "playerQueueToggle")
        visualizer = window.findChild(IconButton, "playerVisualizer")
        rating = window.findChild(QLabel, "playerRating")
        title = window.findChild(QLabel, "playerTrackTitle")
        detail = window.findChild(QLabel, "playerTrackDetail")
        assert player is not None
        assert surface is not None
        assert left_zone is not None
        assert center_zone is not None
        assert right_zone is not None
        assert previous is not None
        assert play is not None
        assert next_button is not None
        assert mute is not None
        assert volume is not None
        assert queue_toggle is not None
        assert visualizer is not None
        assert rating is not None
        assert title is not None
        assert detail is not None

        assert previous.kind is IconButtonKind.SUBTLE
        assert play.kind is IconButtonKind.QUIET
        assert next_button.kind is IconButtonKind.SUBTLE
        assert mute.kind is IconButtonKind.SUBTLE
        assert previous.size().width() == LAYOUT.minimum_touch_target
        assert play.size().width() == LAYOUT.minimum_touch_target
        assert next_button.size().width() == LAYOUT.minimum_touch_target
        assert mute.size().width() == LAYOUT.minimum_touch_target
        assert queue_toggle.size().width() == LAYOUT.minimum_touch_target
        assert previous.iconSize().width() == LAYOUT.player_skip_icon_size
        assert play.iconSize().width() == LAYOUT.player_play_icon_size
        assert next_button.iconSize().width() == LAYOUT.player_skip_icon_size

        for width in (960, 1360, 1720, 2560):
            window.resize(width, 760)
            APPLICATION.processEvents()
            surface_center = surface.mapTo(player, surface.rect().center()).x()
            assert abs(surface_center - player.rect().center().x()) <= 1
            assert left_zone.width() == right_zone.width()
            assert left_zone.width() == max(
                left_zone.sizeHint().width(),
                right_zone.sizeHint().width(),
            )
            assert center_zone.width() == player.width() - (2 * left_zone.width())
            assert surface.width() == min(
                center_zone.width(),
                LAYOUT.player_surface_maximum_width,
            )
            surface_left_in_center = surface.mapTo(
                center_zone,
                surface.rect().topLeft(),
            ).x()
            surface_right_in_center = surface.mapTo(
                center_zone,
                surface.rect().topRight(),
            ).x()
            assert (
                abs(
                    surface_left_in_center
                    - (center_zone.rect().right() - surface_right_in_center)
                )
                <= 1
            )
            assert surface.height() == player.height()
            assert surface.height() == LAYOUT.player_surface_height
            assert surface.y() == 0
            assert (
                previous.mapTo(player, previous.rect().center()).y()
                == play.mapTo(player, play.rect().center()).y()
            )
            assert (
                next_button.mapTo(player, next_button.rect().center()).y()
                == play.mapTo(player, play.rect().center()).y()
            )
            assert visualizer.geometry().bottom() < rating.geometry().top()
            assert (
                abs(visualizer.geometry().center().x() - rating.geometry().center().x())
                <= 1
            )

            previous_center = previous.mapTo(player, previous.rect().center()).x()
            previous_left = previous.mapTo(player, previous.rect().topLeft()).x()
            play_center = play.mapTo(player, play.rect().center()).x()
            next_center = next_button.mapTo(player, next_button.rect().center()).x()
            mute_center = mute.mapTo(player, mute.rect().center()).x()
            volume_left = volume.mapTo(player, volume.rect().topLeft()).x()
            surface_left = surface.mapTo(player, surface.rect().topLeft()).x()
            surface_right = surface.mapTo(player, surface.rect().topRight()).x()
            queue_left = queue_toggle.mapTo(
                player,
                queue_toggle.rect().topLeft(),
            ).x()
            queue_right = queue_toggle.mapTo(
                player,
                queue_toggle.rect().topRight(),
            ).x()
            assert previous_center < play_center < next_center < surface_left
            assert previous_left == LAYOUT.space_md
            assert surface_right < mute_center < volume_left < queue_left
            assert player.rect().right() - queue_right == LAYOUT.space_lg

        assert surface.width() == LAYOUT.player_surface_maximum_width

        assert LAYOUT.player_volume_minimum_width <= volume.width()
        assert volume.width() <= LAYOUT.player_volume_width
        assert title.height() >= title.fontMetrics().height()
        assert detail.height() >= detail.fontMetrics().height()
        assert visualizer.isEnabled()
        assert window.findChild(QLabel, "playerPrototypeNote") is None

        rating.setStyleSheet("font-size: 40pt;")
        QTest.qWait(20)
        assert surface.height() > LAYOUT.player_surface_height
        assert player.height() > LAYOUT.player_height
        assert visualizer.geometry().bottom() < rating.geometry().top()
        assert rating.height() >= rating.sizeHint().height()

        queue_toggle.click()
        APPLICATION.processEvents()
        surface_center = surface.mapTo(player, surface.rect().center()).x()
        assert abs(surface_center - player.rect().center().x()) <= 1
    finally:
        window.close()
        context.shutdown()


def test_player_idle_state_collapses_until_a_track_is_current() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        APPLICATION.processEvents()
        player = window.findChild(PlayerBar)
        surface = window.findChild(QWidget, "nowPlayingSurface")
        left_zone = window.findChild(QWidget, "playerLeftZone")
        artwork = window.findChild(QWidget, "playerArtwork")
        timeline = window.findChild(QWidget, "playerTimeline")
        rating = window.findChild(QLabel, "playerRating")
        title = window.findChild(QLabel, "playerTrackTitle")
        detail = window.findChild(QLabel, "playerTrackDetail")
        right_zone = window.findChild(QWidget, "playerRightZone")
        queue_toggle = window.findChild(IconButton, "playerQueueToggle")
        queue_pane = window.findChild(QWidget, "playbackPane")
        animation = window.findChild(QPropertyAnimation, "playerHeightAnimation")
        assert player is not None
        assert surface is not None
        assert left_zone is not None
        assert artwork is not None
        assert timeline is not None
        assert rating is not None
        assert title is not None
        assert detail is not None
        assert right_zone is not None
        assert queue_toggle is not None
        assert queue_pane is not None
        assert animation is not None
        assert player.height() == LAYOUT.player_idle_height
        assert LAYOUT.player_idle_height == 0
        assert surface.height() == LAYOUT.player_idle_surface_height
        assert surface.property("playbackState") == "idle"
        assert left_zone.isHidden()
        assert surface.isHidden()
        assert right_zone.isHidden()
        assert title.text() == "Nothing playing"
        assert detail.text() == "Drop a Track or Playlist to play it"

        context.playback_controller.enqueue(build_tracks(1)[0])
        APPLICATION.processEvents()
        assert animation.state() is QAbstractAnimation.State.Running
        assert surface.property("playbackState") == "active"
        assert left_zone.isVisible()
        assert surface.isVisible()
        assert right_zone.isVisible()
        assert artwork.isVisible()
        assert timeline.isVisible()
        assert rating.isVisible()
        assert title.isVisible()
        assert left_zone.width() == right_zone.width()
        assert right_zone.width() == max(
            left_zone.sizeHint().width(),
            right_zone.sizeHint().width(),
        )

        QTest.qWait(LAYOUT.player_transition_ms + 40)
        assert player.height() == LAYOUT.player_height
        assert surface.height() == LAYOUT.player_surface_height
        assert surface.height() == player.height()

        queue_toggle.click()
        QTest.qWait(LAYOUT.playback_pane_animation_ms + 40)
        assert queue_toggle.isChecked()
        assert queue_pane.isVisible()

        context.playback_controller.clear_session()
        APPLICATION.processEvents()
        assert animation.state() is QAbstractAnimation.State.Running
        QTest.qWait(LAYOUT.player_transition_ms + 40)
        assert player.height() == LAYOUT.player_idle_height
        assert surface.height() == LAYOUT.player_idle_surface_height
        assert not queue_toggle.isChecked()
        assert queue_pane.isHidden()
    finally:
        window.close()
        context.shutdown()


def test_player_rating_stars_edit_the_current_track_draft() -> None:
    context = build_context()
    track = build_tracks(1)[0]
    context.library_workspace.load(LibrarySnapshot(tracks=(track,)))
    context.track_model.replace_tracks((track,))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        context.playback_controller.enqueue(track)
        QTest.qWait(LAYOUT.player_transition_ms + 40)
        rating = window.findChild(QLabel, "playerRating")
        assert rating is not None
        assert rating.isEnabled()
        assert rating.text() == "☆☆☆☆☆"

        QTest.mouseMove(rating, rating.rect().center())
        assert rating.text() == "★★★☆☆"
        assert rating.property("ratingHover") is True
        draft_track = context.library_workspace.track(track.track_id)
        assert draft_track is not None
        assert draft_track.rating == 0
        APPLICATION.sendEvent(rating, QEvent(QEvent.Type.Leave))
        assert rating.text() == "☆☆☆☆☆"
        assert rating.property("ratingHover") is False

        QTest.mouseClick(rating, Qt.MouseButton.LeftButton, pos=rating.rect().center())
        draft_track = context.library_workspace.track(track.track_id)
        assert draft_track is not None
        assert draft_track.rating == 60
        current_track = context.playback_controller.current_track
        assert current_track is not None
        assert current_track.rating == 60
        assert rating.text() == "★★★☆☆"

        QTest.mouseClick(rating, Qt.MouseButton.LeftButton, pos=rating.rect().center())
        draft_track = context.library_workspace.track(track.track_id)
        assert draft_track is not None
        assert draft_track.rating == 0
        assert rating.text() == "☆☆☆☆☆"

        rating.setFocus()
        QTest.keyClick(rating, Qt.Key.Key_5)
        draft_track = context.library_workspace.track(track.track_id)
        assert draft_track is not None
        assert draft_track.rating == 100
        QTest.keyClick(rating, Qt.Key.Key_Left)
        draft_track = context.library_workspace.track(track.track_id)
        assert draft_track is not None
        assert draft_track.rating == 80
        QTest.keyClick(rating, Qt.Key.Key_0)
        draft_track = context.library_workspace.track(track.track_id)
        assert draft_track is not None
        assert draft_track.rating == 0

        context.library_workspace.set_locked(True)
        assert not rating.isEnabled()
        QTest.mouseClick(rating, Qt.MouseButton.LeftButton, pos=rating.rect().center())
        draft_track = context.library_workspace.track(track.track_id)
        assert draft_track is not None
        assert draft_track.rating == 0

        context.library_workspace.set_locked(False)
        context.playback_controller.reconcile_library(
            (replace(track, title="Another source with the same Track ID"),)
        )
        assert not rating.isEnabled()
    finally:
        window.close()
        context.shutdown()


def test_clicking_player_rating_keeps_focus_on_rating() -> None:
    context = build_context()
    track = build_tracks(1)[0]
    context.library_workspace.load(LibrarySnapshot(tracks=(track,)))
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        context.playback_controller.enqueue(track)
        QTest.qWait(LAYOUT.player_transition_ms + 40)
        rating = window.findChild(QLabel, "playerRating")
        mute = window.findChild(IconButton, "playerMute")
        assert rating is not None
        assert mute is not None

        mute.setFocus()
        assert mute.hasFocus()
        QTest.mouseClick(rating, Qt.MouseButton.LeftButton, pos=rating.rect().center())
        APPLICATION.processEvents()

        assert rating.hasFocus()
        assert not mute.hasFocus()
        draft_track = context.library_workspace.track(track.track_id)
        assert draft_track is not None
        assert draft_track.rating == 60
    finally:
        window.close()
        context.shutdown()


def test_player_and_playback_pane_render_in_light_and_dark_themes() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    original_mode = context.theme_manager.mode

    try:
        window.show()
        queue_toggle = window.findChild(IconButton, "playerQueueToggle")
        pane = window.findChild(QWidget, "playbackPane")
        assert queue_toggle is not None
        assert pane is not None
        queue_toggle.click()
        tracks = build_tracks(2)
        context.playback_controller.enqueue(tracks[0])
        context.playback_controller.enqueue(tracks[1])

        samples: dict[AppearanceMode, QColor] = {}
        for mode in (AppearanceMode.LIGHT, AppearanceMode.DARK):
            context.theme_manager.set_mode(mode)
            APPLICATION.processEvents()
            image = pane.grab().toImage()
            assert not image.isNull()
            samples[mode] = image.pixelColor(pane.rect().center())

        assert samples[AppearanceMode.LIGHT] != samples[AppearanceMode.DARK]
    finally:
        context.theme_manager.set_mode(original_mode)
        window.close()
        context.shutdown()


def test_player_preserves_controller_state_during_metadata_reconciliation(
    monkeypatch: MonkeyPatch,
) -> None:
    # Metadata reconciliation must preserve the position anchor. Freeze only the
    # display clock so a normal interpolation tick cannot race exact assertions.
    monkeypatch.setattr(player_bar_module, "monotonic_ns", lambda: 0)
    context = build_context()
    track = build_tracks(1)[0]
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        progress = window.findChild(QSlider, "playerProgress")
        volume = window.findChild(QSlider, "volumeSlider")
        mute = window.findChild(IconButton, "playerMute")
        title = window.findChild(QLabel, "playerTrackTitle")
        assert progress is not None
        assert volume is not None
        assert mute is not None
        assert title is not None

        context.playback_controller.enqueue(track)
        context.playback_controller.seek(45_000)
        APPLICATION.processEvents()
        assert progress.value() == 45_000
        assert volume.value() == context.playback_controller.volume_percent == 64

        updated = replace(track, title="Updated title")
        context.playback_controller.reconcile_library((updated,))
        APPLICATION.processEvents()
        assert title.text() == "Updated title"
        assert progress.value() == 45_000

        volume.setValue(37)
        assert context.playback_controller.volume_percent == 37
        mute.click()
        mute_fade = window.findChild(QPropertyAnimation, "playerMuteFadeAnimation")
        assert mute_fade is not None
        assert mute_fade.duration() == 180
        assert mute_fade.state() is QAbstractAnimation.State.Running
        assert 0 < context.playback_controller.volume_percent <= 37
        QTest.qWait(mute_fade.duration() + 40)
        assert context.playback_controller.volume_percent == 0
        mute.click()
        assert context.playback_controller.volume_percent == 37
    finally:
        window.close()
        context.shutdown()


def test_player_progress_advances_between_backend_updates() -> None:
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        context.playback_controller.enqueue(build_tracks(1)[0])
        progress = window.findChild(QSlider, "playerProgress")
        assert progress is not None
        backend.emit_position(10_000)
        QTest.qWait(80)
        assert progress.value() > 10_000
        assert context.playback_controller.position_ms == 10_000
        assert backend.seeks == []
    finally:
        window.close()
        context.shutdown()


@mark.parametrize("mode", [AppearanceMode.LIGHT, AppearanceMode.DARK])
def test_player_progress_paints_between_whole_pixel_positions(
    monkeypatch: MonkeyPatch,
    mode: AppearanceMode,
) -> None:
    now_ns = 0
    monkeypatch.setattr(player_bar_module, "monotonic_ns", lambda: now_ns)
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    window = MainWindow(context, auto_discover=False)
    original_mode = context.theme_manager.mode

    try:
        context.theme_manager.set_mode(mode)
        context.playback_controller.enqueue(build_tracks(1)[0])
        progress = window.findChild(QSlider, "playerProgress")
        timer = window.findChild(QTimer, "playerProgressTimer")
        assert progress is not None
        assert timer is not None
        progress.setFixedSize(320, 24)
        backend.emit_position(10_000)
        previous = progress.grab().toImage()
        changed_frames = 0
        for frame in range(1, 21):
            now_ns = frame * 16_000_000
            timer.timeout.emit()
            current = progress.grab().toImage()
            changed_frames += current != previous
            previous = current

        # A three-minute Track advances less than one logical pixel in 20 frames.
        # The painted handle must still move instead of waiting for a pixel tick.
        assert changed_frames == 20
        assert context.playback_controller.position_ms == 10_000
        assert backend.seeks == []
    finally:
        context.theme_manager.set_mode(original_mode)
        window.close()
        context.shutdown()


def test_player_progress_moves_continuously_across_backend_timing_jitter(
    monkeypatch: MonkeyPatch,
) -> None:
    now_ns = 0
    monkeypatch.setattr(player_bar_module, "monotonic_ns", lambda: now_ns)
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    window = MainWindow(context, auto_discover=False)

    try:
        context.playback_controller.enqueue(build_tracks(1)[0])
        progress = window.findChild(QSlider, "playerProgress")
        timer = window.findChild(QTimer, "playerProgressTimer")
        assert progress is not None
        assert timer is not None
        backend.emit_position(10_000)
        previous = progress.value()
        for frame in range(1, 101):
            elapsed_ms = frame * 16
            now_ns = elapsed_ms * 1_000_000
            if frame % 5 == 0:
                jitter_ms = 24 if frame % 10 == 0 else -24
                backend.emit_position(10_000 + elapsed_ms + jitter_ms)
            timer.timeout.emit()
            current = progress.value()
            assert 8 <= current - previous <= 24
            assert abs(current - (10_000 + elapsed_ms)) <= 50
            previous = current

        # Even a tiny explicit seek must relocate immediately, not be smoothed.
        seek_position = progress.value() - 20
        context.playback_controller.seek(seek_position)
        assert progress.value() == seek_position
        assert backend.seeks == [seek_position]
    finally:
        window.close()
        context.shutdown()


def test_player_progress_clock_respects_pause_seek_and_track_changes(
    monkeypatch: MonkeyPatch,
) -> None:
    now_ns = 0
    monkeypatch.setattr(player_bar_module, "monotonic_ns", lambda: now_ns)
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    window = MainWindow(context, auto_discover=False)

    try:
        track = build_tracks(1)[0]
        context.playback_controller.enqueue(track)
        progress = window.findChild(QSlider, "playerProgress")
        timer = window.findChild(QTimer, "playerProgressTimer")
        assert progress is not None
        assert timer is not None
        backend.emit_position(10_000)

        for frame in range(1, 6):
            now_ns = frame * 16_000_000
            timer.timeout.emit()
            assert progress.value() == 10_000 + frame * 16
        assert context.playback_controller.position_ms == 10_000
        assert backend.seeks == []

        backend.emit_playing(False)
        assert not timer.isActive()
        now_ns += 5_000_000_000
        timer.timeout.emit()
        assert progress.value() == 10_080
        backend.emit_playing(True)
        now_ns += 16_000_000
        timer.timeout.emit()
        assert progress.value() == 10_096

        # Seeking to the last reported position still resets the display clock,
        # even when the controller has no changed position to publish.
        context.playback_controller.seek(10_000)
        assert progress.value() == 10_000
        now_ns += 16_000_000
        timer.timeout.emit()
        assert progress.value() == 10_016

        context.playback_controller.seek(2_000)
        assert progress.value() == 2_000
        context.playback_controller.seek(80_000)
        assert progress.value() == 80_000

        # Metadata reconciliation preserves progress within the same entry.
        context.playback_controller.reconcile_library((replace(track, title="New"),))
        assert progress.value() == 80_000
        context.playback_controller.enqueue(track)
        backend.finish()
        assert progress.value() == 0
        now_ns += 16_000_000
        timer.timeout.emit()
        assert progress.value() == 16

        context.playback_controller.clear_session()
        assert progress.value() == 0
        assert not timer.isActive()
    finally:
        window.close()
        context.shutdown()


def test_player_progress_bounds_prediction_and_recovers_on_backend_update(
    monkeypatch: MonkeyPatch,
) -> None:
    now_ns = 0
    monkeypatch.setattr(player_bar_module, "monotonic_ns", lambda: now_ns)
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    window = MainWindow(context, auto_discover=False)

    try:
        track = build_tracks(1)[0]
        context.playback_controller.enqueue(track)
        progress = window.findChild(QSlider, "playerProgress")
        timer = window.findChild(QTimer, "playerProgressTimer")
        assert progress is not None
        assert timer is not None
        backend.emit_position(10_000)
        now_ns += 5_000_000_000
        timer.timeout.emit()
        assert progress.value() == 10_500
        assert not timer.isActive()

        backend.emit_position(10_100)
        assert progress.value() == 10_100
        assert timer.isActive()
        now_ns += 16_000_000
        timer.timeout.emit()
        assert progress.value() == 10_116

        backend.emit_position(track.length_ms - 10)
        now_ns += 16_000_000
        timer.timeout.emit()
        assert progress.value() == track.length_ms
        assert not timer.isActive()
        assert context.playback_controller.position_ms == track.length_ms - 10
        assert context.playback_controller.current_track == track
        assert backend.seeks == []
    finally:
        window.close()
        context.shutdown()


def test_player_progress_scrubbing_ignores_backend_updates_and_clicks_to_seek() -> None:
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    track = build_tracks(1)[0]
    window = MainWindow(context, auto_discover=False)

    try:
        window.show()
        context.playback_controller.enqueue(track)
        APPLICATION.processEvents()
        progress = window.findChild(QSlider, "playerProgress")
        assert progress is not None

        drag_start = QPoint(progress.width() // 4, progress.height() // 2)
        drag_end = QPoint(progress.width() * 2 // 3, progress.height() // 2)
        QTest.mousePress(
            progress,
            Qt.MouseButton.LeftButton,
            pos=drag_start,
        )
        move = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(drag_end),
            QPointF(progress.mapToGlobal(drag_end)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        APPLICATION.sendEvent(progress, move)
        dragged_position = progress.value()
        assert abs(dragged_position - 120_000) <= 4_000

        backend.emit_position(10_000)
        QTest.qWait(80)
        assert progress.value() == dragged_position
        QTest.mouseRelease(
            progress,
            Qt.MouseButton.LeftButton,
            pos=drag_end,
        )
        assert backend.seeks[-1] == dragged_position

        backend.seeks.clear()
        click = QPoint(progress.width() * 3 // 4, progress.height() // 2)
        QTest.mouseClick(progress, Qt.MouseButton.LeftButton, pos=click)
        APPLICATION.processEvents()
        expected = track.length_ms * 3 // 4
        assert backend.seeks
        assert abs(backend.seeks[-1] - expected) <= 4_000
    finally:
        window.close()
        context.shutdown()
