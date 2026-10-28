"""Chapter-aware Player presentation over semantic iTunesDB metadata."""

from dataclasses import replace
from html import escape

import pytest
from PySide6.QtCore import QEasingCurve, QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QToolTip,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.widgets.animated_popup import AnimatedPopup, PopupDirection
from iOpenPod.GUI.widgets.chapter_index import ChapterIndexPopup
from iOpenPod.GUI.widgets.player_bar import PlayerBar
from iOpenPod.GUI.widgets.themed_buttons import IconButton
from iPodDB.library import MediaType, Track, TrackChapter, TrackMetadata


def _finish_chapter_animation(popup: ChapterIndexPopup) -> None:
    popup.animation.setCurrentTime(popup.animation.duration())
    APPLICATION.processEvents()


def _track() -> Track:
    return Track(
        1,
        "An audiobook",
        "Author",
        "Book",
        180_000,
        metadata=TrackMetadata(
            chapters=(
                TrackChapter("Introduction", 0),
                TrackChapter("Chapter <Two> & more", 60_123),
                TrackChapter("", 120_000),
            )
        ),
    )


def test_chapter_index_bounces_down_and_reverses_interrupted_transitions() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        context.playback_controller.enqueue(
            replace(_track(), media_types=(MediaType.AUDIOBOOK,))
        )
        context.playback_controller.pause()
        APPLICATION.processEvents()
        button = window.findChild(IconButton, "playerChapters")
        popup = window.findChild(ChapterIndexPopup)
        assert button is not None and popup is not None
        button.click()
        animation = popup.animation
        surface = popup.surface
        assert popup.direction is PopupDirection.DOWN
        assert animation.duration() == 280
        assert animation.easingCurve().type() is QEasingCurve.Type.OutBack
        assert animation.easingCurve().overshoot() == 0.8
        start, rest = animation.startValue(), animation.endValue()
        host_pos = popup.pos()
        assert start == QPoint(0, -surface.height())
        assert rest == QPoint(0, 0)
        animation.setCurrentTime(0)
        image = popup.grab().toImage()
        assert image.pixelColor(popup.width() // 2, popup.height() // 2).alpha() == 0
        animation.setCurrentTime(animation.duration() // 3)
        assert start.y() < surface.y() < rest.y()
        assert popup.pos() == host_pos
        animation.setCurrentTime(animation.duration() * 3 // 4)
        assert surface.y() > rest.y()  # The downward entrance overshoots, then settles.
        _finish_chapter_animation(popup)
        assert surface.pos() == rest

        button.click()
        assert popup.isVisible() and not popup.is_open
        assert animation.duration() == 190
        assert animation.easingCurve().type() is QEasingCurve.Type.InCubic
        assert animation.endValue() == start
        animation.setCurrentTime(animation.duration() // 2)
        exiting_at = surface.pos()
        button.click()
        assert popup.is_open and button.isChecked()
        assert animation.startValue() == exiting_at and animation.endValue() == rest
        _finish_chapter_animation(popup)
        assert popup.isVisible() and surface.pos() == rest

        # A press on the book retains the popup's grab until release, just like
        # the status button, so the same click cannot dismiss and reopen it.
        over_book = popup.mapFromGlobal(button.mapToGlobal(button.rect().center()))
        QTest.mousePress(popup, Qt.MouseButton.LeftButton, pos=over_book)
        assert popup.is_open
        QTest.mouseRelease(popup, Qt.MouseButton.LeftButton, pos=over_book)
        _finish_chapter_animation(popup)
        assert not popup.isVisible() and not button.isChecked()

        button.click()
        animation.setCurrentTime(animation.duration() // 3)
        entering_at = surface.pos()
        button.click()
        assert animation.startValue() == entering_at
        _finish_chapter_animation(popup)
        assert not popup.isVisible()
    finally:
        window.close()
        context.shutdown()


def test_chapter_index_respects_disabled_widget_animation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def animations_disabled(_popup: AnimatedPopup) -> bool:
        return False

    monkeypatch.setattr(AnimatedPopup, "_animations_enabled", animations_disabled)
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        window.show()
        context.playback_controller.enqueue(
            replace(_track(), media_types=(MediaType.AUDIOBOOK,))
        )
        APPLICATION.processEvents()
        button = window.findChild(IconButton, "playerChapters")
        popup = window.findChild(ChapterIndexPopup)
        assert button is not None and popup is not None
        button.click()
        assert popup.isVisible() and popup.surface.pos() == QPoint(0, 0)
        button.click()
        assert not popup.isVisible()
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize("paused", (False, True))
def test_audiobook_book_action_opens_index_and_click_seeks_without_restarting(
    paused: bool,
) -> None:
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    window = MainWindow(context, auto_discover=False)
    controller = context.playback_controller
    audiobook = replace(_track(), media_types=(MediaType.AUDIOBOOK,))
    try:
        window.show()
        controller.play_now((audiobook, _track()))
        if paused:
            controller.pause()
        APPLICATION.processEvents()
        button = window.findChild(IconButton, "playerChapters")
        player = window.findChild(PlayerBar)
        popup = window.findChild(ChapterIndexPopup)
        chapters = window.findChild(QListWidget, "playerChapterList")
        assert button is not None and player is not None
        assert popup is not None and chapters is not None
        assert window.findChild(IconButton, "playerVisualizer") is None
        assert button.accessibleName() == "Show Chapters"
        visualizer_requests: list[bool] = []
        player.visualizerRequested.connect(lambda: visualizer_requests.append(True))
        history, queue = (
            controller.history_model.entries,
            controller.queue_model.entries,
        )
        entry_id = controller.current_entry_id

        button.click()
        APPLICATION.processEvents()
        _finish_chapter_animation(popup)
        assert popup.isVisible() and button.isChecked()
        assert chapters.count() == 3
        assert chapters.currentRow() == 0
        assert chapters.item(1).text() == "2. Chapter <Two> & more\n1:00.123"
        assert chapters.item(2).text() == "3. Untitled Chapter\n2:00.000"
        assert (
            popup.geometry().top() >= button.mapToGlobal(button.rect().bottomLeft()).y()
        )
        item = chapters.item(1)
        QTest.mouseClick(
            chapters.viewport(),
            Qt.MouseButton.LeftButton,
            pos=chapters.visualItemRect(item).center(),
        )
        assert backend.seeks == [60_123]
        _finish_chapter_animation(popup)
        assert controller.current_entry_id == entry_id
        assert controller.history_model.entries == history
        assert controller.queue_model.entries == queue
        assert controller.playing is not paused
        assert backend.started == [audiobook]
        assert not popup.isVisible() and not button.isChecked()
        assert visualizer_requests == []

        button.click()
        _finish_chapter_animation(popup)
        assert chapters.currentRow() == 1
        backend.emit_position(130_000)
        assert chapters.currentRow() == 2
        QTest.keyClick(chapters, Qt.Key.Key_Escape)
        _finish_chapter_animation(popup)
        assert not popup.isVisible() and not button.isChecked()
        assert backend.seeks == [60_123]
    finally:
        window.close()
        context.shutdown()


def test_audiobook_index_keyboard_toggle_track_changes_and_empty_state() -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    controller = context.playback_controller
    audiobook = replace(_track(), media_types=(MediaType.AUDIOBOOK,))
    try:
        window.show()
        controller.enqueue(audiobook)
        controller.pause()
        APPLICATION.processEvents()
        button = window.findChild(IconButton, "playerChapters")
        popup = window.findChild(ChapterIndexPopup)
        chapters = window.findChild(QListWidget, "playerChapterList")
        player = window.findChild(PlayerBar)
        assert button is not None and popup is not None
        assert chapters is not None and player is not None
        book_icon = button.icon().pixmap(18, 18).toImage()
        button.click()
        button.click()
        _finish_chapter_animation(popup)
        assert not popup.isVisible() and not button.isChecked()
        button.click()
        _finish_chapter_animation(popup)
        QTest.keyClick(chapters, Qt.Key.Key_Down)
        QTest.keyClick(chapters, Qt.Key.Key_Return)
        assert controller.position_ms == 60_123
        _finish_chapter_animation(popup)
        assert not popup.isVisible()

        button.click()
        controller.play_now((_track(),))
        assert not popup.isVisible()
        visualizer = window.findChild(IconButton, "playerVisualizer")
        assert visualizer is not None
        assert visualizer is button
        assert visualizer.icon().pixmap(18, 18).toImage() != book_icon
        requests: list[bool] = []
        # Exercise the Player intent without opening a real visualizer page.
        player.visualizerRequested.disconnect()
        player.visualizerRequested.connect(lambda: requests.append(True))
        visualizer.click()
        assert requests == [True]

        controller.play_now((replace(audiobook, metadata=TrackMetadata()),))
        button.click()
        APPLICATION.processEvents()
        _finish_chapter_animation(popup)
        empty = window.findChild(QLabel, "playerChaptersEmpty")
        assert empty is not None and empty.isVisible()
        assert chapters.count() == 0
        assert empty.text() == "No chapters available"
        QTest.keyClick(popup, Qt.Key.Key_Escape)
        _finish_chapter_animation(popup)
        assert not popup.isVisible()
        button.click()
        controller.clear_session()
        assert not popup.isVisible()
    finally:
        window.close()
        context.shutdown()


def test_long_audiobook_index_scrolls_to_current_chapter_and_closes_on_metadata_change() -> (
    None
):
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    controller = context.playback_controller
    audiobook = replace(
        _track(),
        length_ms=4_000_000,
        media_types=(MediaType.AUDIOBOOK,),
        metadata=TrackMetadata(
            chapters=tuple(
                TrackChapter(f"Chapter {index}", index * 60_000) for index in range(60)
            )
        ),
    )
    try:
        window.show()
        controller.enqueue(audiobook)
        controller.pause()
        controller.seek(3_000_000)
        APPLICATION.processEvents()
        button = window.findChild(IconButton, "playerChapters")
        popup = window.findChild(ChapterIndexPopup)
        chapters = window.findChild(QListWidget, "playerChapterList")
        assert button is not None and popup is not None and chapters is not None
        button.click()
        APPLICATION.processEvents()
        _finish_chapter_animation(popup)
        assert chapters.count() == 60 and chapters.currentRow() == 50
        assert chapters.verticalScrollBar().maximum() > 0
        assert (
            chapters.viewport()
            .rect()
            .intersects(chapters.visualItemRect(chapters.item(50)))
        )
        assert popup.screen().availableGeometry().contains(popup.geometry())
        controller.reconcile_library(
            (
                replace(
                    audiobook,
                    metadata=TrackMetadata(chapters=(TrackChapter("Replacement", 0),)),
                ),
            )
        )
        assert not popup.isVisible()
        button.click()
        assert chapters.count() == 1 and "Replacement" in chapters.item(0).text()
    finally:
        window.close()
        context.shutdown()


def test_player_title_follows_chapters_during_playback_seeks_and_scrubbing() -> None:
    backend = FakePlaybackBackend()
    context = build_context(playback_backend=backend)
    window = MainWindow(context, auto_discover=False)
    controller = context.playback_controller
    track = _track()
    try:
        window.show()
        controller.enqueue(track)
        controller.pause()
        APPLICATION.processEvents()
        title = window.findChild(QLabel, "playerTrackTitle")
        progress = window.findChild(QSlider, "playerProgress")
        next_button = window.findChild(IconButton, "playerNext")
        previous_button = window.findChild(IconButton, "playerPrevious")
        assert title is not None and progress is not None
        assert next_button is not None and previous_button is not None
        assert title.text() == "An audiobook — Introduction"
        assert next_button.accessibleName() == "Next Chapter"
        assert previous_button.accessibleName() == "Previous Chapter"
        backend.emit_position(60_122)
        assert title.text() == "An audiobook — Introduction"
        backend.emit_position(60_123)
        assert title.text() == "An audiobook — Chapter <Two> & more"
        assert title.accessibleName() == title.text()
        next_button.click()
        assert controller.position_ms == 120_000
        assert title.text() == "An audiobook — Untitled Chapter"
        previous_button.click()
        assert controller.position_ms == 60_123
        assert title.text() == "An audiobook — Chapter <Two> & more"

        progress.setSliderDown(True)
        progress.setValue(130_000)
        assert title.text() == "An audiobook — Untitled Chapter"
        backend.emit_position(1_000)
        assert title.text() == "An audiobook — Untitled Chapter"
        progress.setSliderDown(False)
        assert controller.position_ms == 130_000

        renamed = replace(
            track,
            metadata=replace(track.metadata, chapters=(TrackChapter("Renamed", 0),)),
        )
        controller.reconcile_library((renamed,))
        assert title.text() == "An audiobook — Renamed"
        assert progress.value() == 130_000
        plain = replace(track, metadata=TrackMetadata())
        controller.play_now((plain,))
        assert title.text() == "An audiobook"
        assert next_button.accessibleName() == "Next Track"
        controller.clear_session()
        assert title.text() == "Nothing playing"
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize(
    ("language", "untitled", "next_label"),
    (
        ("de", "Unbenanntes Kapitel", "Nächstes Kapitel"),
        ("es", "Capítulo sin título", "Capítulo siguiente"),
    ),
)
def test_chapter_labels_retranslate_without_changing_track_metadata(
    language: str,
    untitled: str,
    next_label: str,
) -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    track = replace(
        _track(),
        title="Book %2 {chapter}",
        media_types=(MediaType.AUDIOBOOK,),
        metadata=TrackMetadata(chapters=(TrackChapter("", 30_000),)),
    )
    controller = context.playback_controller
    try:
        window.show()
        controller.enqueue(track)
        controller.pause()
        title = window.findChild(QLabel, "playerTrackTitle")
        next_button = window.findChild(IconButton, "playerNext")
        assert title is not None and next_button is not None
        assert title.text() == track.title  # The introduction has no chapter yet.
        controller.next()
        assert title.text() == track.title + " — Untitled Chapter"
        context.i18n_manager.set_language(language)
        APPLICATION.processEvents()
        assert title.text() == track.title + " — " + untitled
        assert next_button.accessibleName() == next_label
        assert controller.current_track == track
        assert controller.position_ms == 30_000
        book = window.findChild(IconButton, "playerChapters")
        chapters = window.findChild(QListWidget, "playerChapterList")
        assert book is not None and chapters is not None
        assert book.accessibleName() == (
            "Kapitel anzeigen" if language == "de" else "Mostrar capítulos"
        )
        book.click()
        popup = window.findChild(ChapterIndexPopup)
        assert popup is not None
        _finish_chapter_animation(popup)
        assert untitled in chapters.item(0).text()
    finally:
        window.close()
        context.shutdown()


@pytest.mark.parametrize("right_to_left", (False, True))
@pytest.mark.parametrize(
    ("chapter_start", "timestamp"),
    ((60_123, "1:00.123"), (3_661_007, "1:01:01.007")),
)
def test_chapter_markers_paint_and_show_exact_title_timestamp_tooltips(
    right_to_left: bool,
    chapter_start: int,
    timestamp: str,
) -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    controller = context.playback_controller
    track = replace(
        _track(),
        length_ms=chapter_start * 3,
        metadata=TrackMetadata(
            chapters=(TrackChapter("Chapter <Two> & more", chapter_start),)
        ),
    )
    try:
        window.show()
        controller.enqueue(track)
        controller.pause()
        APPLICATION.processEvents()
        progress = window.findChild(QSlider, "playerProgress")
        assert progress is not None
        progress.setFixedSize(360, 24)
        progress.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
            if right_to_left
            else Qt.LayoutDirection.LeftToRight
        )
        APPLICATION.processEvents()
        option = QStyleOptionSlider()
        progress.initStyleOption(option)
        option.sliderPosition = chapter_start
        marker_center = (
            progress.style()
            .subControlRect(
                QStyle.ComplexControl.CC_Slider,
                option,
                QStyle.SubControl.SC_SliderHandle,
                progress,
            )
            .center()
        )
        chaptered_image = progress.grab().toImage()
        event = QHelpEvent(
            QEvent.Type.ToolTip, marker_center, progress.mapToGlobal(marker_center)
        )
        APPLICATION.sendEvent(progress, event)
        assert escape("Chapter <Two> & more") in QToolTip.text()
        assert timestamp in QToolTip.text()
        assert controller.position_ms == 0

        empty_point = QPoint(progress.width() // 2, progress.height() // 2)
        empty_event = QHelpEvent(
            QEvent.Type.ToolTip, empty_point, progress.mapToGlobal(empty_point)
        )
        APPLICATION.sendEvent(progress, empty_event)
        assert not empty_event.isAccepted()
        QTest.qWait(350)
        assert not QToolTip.isVisible()

        controller.reconcile_library((replace(track, metadata=TrackMetadata()),))
        plain_image = progress.grab().toImage()
        assert chaptered_image != plain_image
        # The thin marker extends above the four-pixel groove at the chapter time.
        assert chaptered_image.pixelColor(
            marker_center.x(), marker_center.y() - 4
        ) != plain_image.pixelColor(marker_center.x(), marker_center.y() - 4)
        cleared_event = QHelpEvent(
            QEvent.Type.ToolTip, marker_center, progress.mapToGlobal(marker_center)
        )
        APPLICATION.sendEvent(progress, cleared_event)
        assert not cleared_event.isAccepted()
    finally:
        QToolTip.hideText()
        window.close()
        context.shutdown()
