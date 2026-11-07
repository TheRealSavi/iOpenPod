"""Visible Player artwork follows authored groups and exact chapter choices."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QListWidget, QSlider
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.chapter_index import ChapterIndexPopup
from iOpenPod.GUI.widgets.player_bar import PlayerBar
from iPodDB.library import MediaType, Track, TrackChapter, TrackMetadata


class _NoArtworkLoader:
    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        raise AssertionError(f"Unexpected image load: {request}")


class _RecordingProvider(ArtworkPixmapProvider):
    def __init__(self, controller: ArtworkController) -> None:
        super().__init__(controller)
        self.times: dict[int, tuple[int, ...]] = {7: (0, 30_000, 120_000, 0xFFFFFFFF)}
        self.requests: list[tuple[int, int | None]] = []
        self.time_requests: list[int] = []
        self.unavailable: set[tuple[int, int | None]] = set()

    def display_times(self, artwork_id: int) -> tuple[int, ...]:
        self.time_requests.append(artwork_id)
        return self.times.get(artwork_id, ())

    def pixmap(
        self,
        artwork_id: int,
        logical_size: int,
        device_pixel_ratio: float,
        *,
        display_time_ms: int | None = None,
    ) -> QPixmap | None:
        if artwork_id <= 0:
            return None
        self.requests.append((artwork_id, display_time_ms))
        if (artwork_id, display_time_ms) in self.unavailable:
            return None
        pixmap = QPixmap(logical_size, logical_size)
        pixmap.fill(
            QColor("red")
            if display_time_ms == 0
            else QColor("blue")
            if display_time_ms == 30_000
            else QColor("green")
        )
        return pixmap


@pytest.fixture
def player_artwork() -> Iterator[tuple[PlayerBar, _RecordingProvider]]:
    context = build_context()
    controller = ArtworkController(_NoArtworkLoader())
    provider = _RecordingProvider(controller)
    bar = PlayerBar(context.theme_manager, provider)
    bar.resize(1100, bar.height())
    try:
        yield bar, provider
    finally:
        bar.close()
        provider.shutdown()
        controller.shutdown()
        context.shutdown()


def _track(*, media_type: MediaType = MediaType.AUDIOBOOK) -> Track:
    return Track(
        1,
        "Chaptered Track",
        "Author",
        "Album",
        180_000,
        artwork_id=7,
        media_types=(media_type,),
    )


def _artwork_color(bar: PlayerBar) -> QColor:
    view = bar.findChild(ArtworkView, "playerArtwork")
    assert view is not None
    image = view.grab().toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2)


@pytest.mark.parametrize(
    "media_type", [MediaType.AUDIOBOOK, MediaType.PODCAST, MediaType.AUDIO]
)
def test_player_selects_artwork_on_playback_backward_seek_and_scrub(
    player_artwork: tuple[PlayerBar, _RecordingProvider], media_type: MediaType
) -> None:
    bar, provider = player_artwork
    bar.set_track(_track(media_type=media_type))
    assert _artwork_color(bar) == QColor("red")
    for position, expected in (
        (29_999, "red"),
        (30_000, "blue"),
        (119_999, "blue"),
        (120_000, "green"),
        (30_000, "blue"),
        (0, "red"),
    ):
        bar.set_position(position)
        assert _artwork_color(bar) == QColor(expected)
    progress = bar.findChild(QSlider, "playerProgress")
    assert progress is not None
    progress.setSliderDown(True)
    progress.setValue(120_000)
    assert _artwork_color(bar) == QColor("green")
    progress.setValue(0)
    assert _artwork_color(bar) == QColor("red")
    progress.setSliderDown(False)
    assert provider.time_requests == [7]
    assert {time for _, time in provider.requests} == {0, 30_000, 120_000}


def test_player_refreshes_timeline_on_clear_track_change_and_no_reached_frame(
    player_artwork: tuple[PlayerBar, _RecordingProvider],
) -> None:
    bar, provider = player_artwork
    bar.set_track(_track())
    bar.set_position(120_000)
    assert _artwork_color(bar) == QColor("green")
    provider.times[8] = (5000, 0xFFFFFFFF)
    bar.set_track(replace(_track(), track_id=2, artwork_id=8))
    provider.requests.clear()
    _artwork_color(bar)
    assert provider.requests == []
    bar.set_position(5000)
    _artwork_color(bar)
    assert provider.requests == [(8, 5000)]
    provider.times[8] = (10_000, 0xFFFFFFFF)
    provider.requests.clear()
    provider.cleared.emit()
    _artwork_color(bar)
    assert provider.requests == []
    bar.set_position(10_000)
    _artwork_color(bar)
    assert provider.requests == [(8, 10_000)]
    provider.times[8] = (0xFFFFFFFF,)
    provider.requests.clear()
    provider.cleared.emit()
    bar.set_position(180_000)
    _artwork_color(bar)
    bar.set_track(None)
    _artwork_color(bar)
    assert provider.requests == []


def test_player_keeps_missing_frame_placeholder_until_exact_frame_is_ready(
    player_artwork: tuple[PlayerBar, _RecordingProvider],
) -> None:
    bar, provider = player_artwork
    bar.set_track(_track())
    assert _artwork_color(bar) == QColor("red")
    provider.unavailable.add((7, 30_000))
    provider.requests.clear()
    bar.set_position(30_000)
    assert _artwork_color(bar) not in (QColor("red"), QColor("blue"))
    assert provider.requests == [(7, 30_000)]
    provider.unavailable.clear()
    provider.artworkChanged.emit(7)
    assert _artwork_color(bar) == QColor("blue")


def test_chapter_popup_loads_only_visible_exact_groups_and_refreshes_on_clear(
    player_artwork: tuple[PlayerBar, _RecordingProvider],
) -> None:
    bar, provider = player_artwork
    chapters = tuple(
        TrackChapter(f"Chapter {number}", 1 if number == 0 else number * 1000)
        for number in range(100)
    )
    # Chapter 1 has no exact image; it must not borrow the previous or next one.
    provider.times[7] = tuple(number * 1000 for number in range(100) if number != 1)
    bar.set_track(replace(_track(), metadata=TrackMetadata(chapters=chapters)))
    popup = bar.findChild(ChapterIndexPopup)
    assert popup is not None
    provider.requests.clear()
    popup.show_index(chapters, 0, artwork_id=7)
    popup.animation.setCurrentTime(popup.animation.duration())
    APPLICATION.processEvents()
    listing = popup.findChild(QListWidget, "playerChapterList")
    assert listing is not None
    listing.viewport().grab()
    visible_times = {time for _, time in provider.requests}
    assert 0 in visible_times and 2000 in visible_times
    assert 1000 not in visible_times and None not in visible_times
    assert len(visible_times) < 20
    before = len(provider.requests)
    for row in range(listing.count()):
        listing.sizeHintForRow(row)
        assert not listing.itemWidget(listing.item(row))
    assert len(provider.requests) == before

    listing.scrollToBottom()
    APPLICATION.processEvents()
    listing.viewport().grab()
    assert (7, 99_000) in provider.requests
    provider.times[7] = ()
    provider.requests.clear()
    provider.cleared.emit()
    listing.viewport().grab()
    assert provider.requests == []
    popup.dismiss()
