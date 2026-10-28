"""Chapter-aware Player presentation over semantic iTunesDB metadata."""

from dataclasses import replace
from html import escape

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QSlider, QStyle, QStyleOptionSlider, QToolTip
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.widgets.themed_buttons import IconButton
from iPodDB.library import Track, TrackChapter, TrackMetadata


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
        metadata=TrackMetadata(chapters=(TrackChapter("", 30_000),)),
    )
    controller = context.playback_controller
    try:
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
