"""Music Video groups use Album artwork, layouts, and media-scoped actions."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QDrag
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QToolButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.core.settings.definitions import (
    LIBRARY_DOUBLE_CLICK_SHORTCUT,
    LibraryDoubleClickShortcut,
)
from iOpenPod.app.models.album_list_model import AlbumRole, AlbumSummary
from iOpenPod.app.models.library_drag import dropped_tracks
from iOpenPod.app.models.track_table_model import TrackRole
from iOpenPod.GUI.delegates.album_card_delegate import AlbumCardDelegate
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.navigation import PageId
from iOpenPod.GUI.pages.library_page import LibraryPage
from iOpenPod.GUI.widgets.album_grid import AlbumGridView
from iOpenPod.GUI.widgets.compact_top_bar import CompactTopBar
from iOpenPod.GUI.widgets.inline_album_panel import InlineAlbumPanel
from iOpenPod.GUI.widgets.track_actions import TrackActions
from iPodDB.library import LibrarySnapshot, MediaType, Track


@pytest.mark.parametrize("action", ("Play", "PlayNext", "Queue"))
def test_music_video_album_artwork_and_actions_exclude_matching_audio(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    context = build_context()
    videos = tuple(
        Track(
            n,
            f"Video {n}",
            "Artist",
            "Shared Album",
            180_000,
            track_number=n,
            artwork_id=70 + n,
            media_types=(MediaType.MUSIC_VIDEO,),
        )
        for n in (1, 2)
    )
    audio = Track(
        10, "Audio version", "Artist", "Shared Album", 180_000, artwork_id=999
    )
    pending = Track(11, "Pending", "Artist", "Other", 180_000)
    context.library_workspace.load(LibrarySnapshot((audio, *videos, pending)))
    context.track_model.reset_tracks(context.library_workspace.tracks)
    context.settings.set_global(
        LIBRARY_DOUBLE_CLICK_SHORTCUT, LibraryDoubleClickShortcut.PLAY_NOW.value
    )
    window = MainWindow(context, auto_discover=False)
    drags: list[QDrag] = []

    def record_drag(drag: QDrag, _action: Qt.DropAction) -> Qt.DropAction:
        drags.append(drag)
        return Qt.DropAction.CopyAction

    monkeypatch.setattr(QDrag, "exec", record_drag)
    try:
        window.resize(1500, 900)
        window.show()
        bar = window.findChild(CompactTopBar)
        page = window.findChild(LibraryPage, "music-videosPage")
        assert bar is not None and page is not None
        bar.pageRequested.emit(PageId.MUSIC_VIDEOS.value)
        APPLICATION.processEvents()
        grid = page.findChild(AlbumGridView)
        panel = page.findChild(InlineAlbumPanel)
        actions = window.findChild(TrackActions)
        heading = page.findChild(QLabel, "music-videosTitle")
        assert grid is not None and panel is not None and actions is not None
        assert heading is not None and heading.text() == "Music Videos"
        assert grid.findChild(AlbumCardDelegate) is not None
        assert grid.model().rowCount() == 1
        index = grid.model().index(0, 0)
        summary = index.data(AlbumRole.SUMMARY)
        assert isinstance(summary, AlbumSummary)
        assert summary.artwork_id == 71 and summary.track_ids == (1, 2)
        assert summary.track_count == 2 and summary.duration_ms == 360_000
        QTest.mouseMove(grid.viewport(), grid.visualRect(index).center())
        QTest.mouseClick(
            grid.viewport(),
            Qt.MouseButton.LeftButton,
            pos=grid.visualRect(index).center(),
        )
        QTest.qWait(250)
        assert panel.isVisible()
        assert actions.selection(grid).tracks == videos
        grid.startDrag(Qt.DropAction.CopyAction)
        assert len(drags) == 1
        assert dropped_tracks(drags[0].mimeData(), context.library_workspace) == videos
        playback = context.playback_controller
        playback.play_now((audio, pending))
        button = panel.findChild(QToolButton, f"inlineAlbum{action}")
        assert button is not None and button.isEnabled()
        button.click()
        expected: tuple[Track, ...]
        if action == "Play":
            assert playback.current_track == videos[0]
            expected = (videos[1], pending)
        else:
            assert playback.current_track == audio
            expected = (
                (*videos, pending) if action == "PlayNext" else (pending, *videos)
            )
        assert tuple(entry.track for entry in playback.queue_model.entries) == expected
        cells = panel.track_view
        second = cells.model().index(0, 1)
        assert second.data(TrackRole.TRACK_ID) == 2
        cells.doubleClicked.emit(second)
        assert playback.current_track == videos[1]
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
