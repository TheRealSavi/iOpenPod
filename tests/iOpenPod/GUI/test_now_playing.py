"""Now Playing shares runtime playback and restores the existing shell."""

from collections.abc import Iterator
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QLabel,
    QSlider,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from tests.iOpenPod.playback_test_support import FakePlaybackBackend

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.core.settings.definitions import (
    APPEARANCE_MODE,
    NAVIGATION_STYLE,
    PLAYER_POSITION,
    AppearanceMode,
    DarkTheme,
    LightTheme,
    NavigationStyle,
    PlayerPosition,
)
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.app.playback_controller import PlaybackController
from iOpenPod.GUI.main_window import MainWindow
from iOpenPod.GUI.pages.now_playing_page import NowPlayingPage
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.presentation.now_playing_background import now_playing_background
from iOpenPod.GUI.presentation.theme.tokens import (
    DARK_TOKENS,
    LIGHT_TOKENS,
    ThemeTokens,
    tokens_for,
)
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.now_playing_backdrop import NowPlayingBackdrop
from iOpenPod.GUI.widgets.page_fade import PageFade
from iOpenPod.GUI.widgets.playback_pane import PlaybackQueueView
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, IconButton
from iPodDB.library import Track, TrackChapter, TrackMetadata


def _track(number: int = 1) -> Track:
    return Track(
        number, f"Track {number}", "Artist", "Album", 180_000, artwork_id=number
    )


class _NoArtworkLoader:
    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        raise AssertionError(f"Unexpected device image load: {request}")


class _ArtworkProvider(ArtworkPixmapProvider):
    def __init__(self, controller: ArtworkController) -> None:
        super().__init__(controller)
        self.frames: dict[tuple[int, int | None], QPixmap] = {}
        for time, color in ((0, "red"), (30_000, "blue")):
            pixmap = QPixmap(96, 96)
            pixmap.fill(QColor(color))
            self.frames[1, time] = pixmap

    def display_times(self, artwork_id: int) -> tuple[int, ...]:
        return (0, 30_000) if artwork_id == 1 else ()

    def pixmap(
        self,
        artwork_id: int,
        logical_size: int,
        device_pixel_ratio: float,
        *,
        display_time_ms: int | None = None,
    ) -> QPixmap | None:
        return self.frames.get((artwork_id, display_time_ms))


@pytest.fixture
def player() -> Iterator[
    tuple[NowPlayingPage, PlaybackController, FakePlaybackBackend, _ArtworkProvider]
]:
    context = build_context()
    backend = FakePlaybackBackend()
    controller = PlaybackController(backend)
    artwork_controller = ArtworkController(_NoArtworkLoader())
    provider = _ArtworkProvider(artwork_controller)
    page = NowPlayingPage(controller, context.theme_manager, provider)
    page.resize(1100, 720)
    page.show()
    APPLICATION.processEvents()
    try:
        yield page, controller, backend, provider
    finally:
        page.close()
        controller.shutdown()
        provider.shutdown()
        artwork_controller.shutdown()
        context.shutdown()


def _child[T: QWidget](parent: QWidget, kind: type[T], name: str) -> T:
    result = parent.findChild(kind, name)
    assert result is not None
    return result


@pytest.mark.parametrize("navigation", tuple(NavigationStyle))
@pytest.mark.parametrize("position", tuple(PlayerPosition))
@pytest.mark.parametrize("sync", (False, True))
def test_artwork_opens_window_page_and_close_restores_shell(
    navigation: NavigationStyle,
    position: PlayerPosition,
    sync: bool,
) -> None:
    context = build_context()
    context.settings.set_global(NAVIGATION_STYLE, navigation.value)
    context.settings.set_global(PLAYER_POSITION, position.value)
    context.playback_controller.play_now((_track(), _track(2)))
    window = MainWindow(context, auto_discover=False)
    try:
        window.resize(1100, 720)
        window.show()
        window.activateWindow()
        APPLICATION.processEvents()
        workspaces = _child(window, QStackedWidget, "workspaceStack")
        if sync:
            workspaces.setCurrentWidget(_child(window, QWidget, "syncWorkspace"))
        prior_workspace = workspaces.currentWidget()
        queue_toggle = _child(window, IconButton, "playerQueueToggle")
        queue_toggle.click()
        tabs = _child(window, QTabWidget, "playbackTabs")
        tabs.setCurrentIndex(1)
        QTest.qWait(220)
        shell = _child(window, QWidget, "appShell")
        pages = _child(window, QStackedWidget, "pageStack")
        prior_page = pages.currentWidget()
        prior_size = window.size()
        artwork = _child(window, QToolButton, "playerArtworkButton")
        current_entry = context.playback_controller.current_entry_id
        artwork.click()
        APPLICATION.processEvents()
        page = _child(window, NowPlayingPage, "nowPlayingPage")
        assert page.isVisible() and not shell.isVisible()
        assert window.statusBar().isHidden()
        central = window.centralWidget()
        assert central is not None and page.size() == central.size()
        assert window.size() == prior_size
        assert not window.isFullScreen()
        assert context.playback_controller.current_entry_id == current_entry
        assert context.playback_controller.playing
        _child(page, IconButton, "nowPlayingClose").click()
        APPLICATION.processEvents()
        assert not page.isVisible() and shell.isVisible()
        assert not window.statusBar().isHidden()
        assert pages.currentWidget() is prior_page
        assert workspaces.currentWidget() is prior_workspace
        assert _child(window, QWidget, "playbackPane").isVisible()
        assert queue_toggle.isChecked() and tabs.currentIndex() == 1
        assert artwork.hasFocus()
        # Keyboard activation and Escape take the same path as the pointer.
        QTest.keyClick(artwork, Qt.Key.Key_Space)
        APPLICATION.processEvents()
        assert page.isVisible()
        if not sync and navigation is NavigationStyle.COMPACT_TOP_BAR:
            for width, height in ((1360, 900), (960, 620)):
                window.resize(width, height)
                APPLICATION.processEvents()
                assert window.width() == width and window.height() == height
        QTest.keyClick(_child(page, IconButton, "nowPlayingClose"), Qt.Key.Key_Escape)
        APPLICATION.processEvents()
        assert shell.isVisible()
    finally:
        window.close()
        context.shutdown()


def test_transport_and_seek_share_authoritative_controller(
    player: tuple[
        NowPlayingPage, PlaybackController, FakePlaybackBackend, _ArtworkProvider
    ],
) -> None:
    page, controller, backend, _provider = player
    first, second = _track(), _track(2)
    controller.play_now((first, second))
    assert _child(page, QLabel, "nowPlayingTitle").text() == first.title
    assert _child(page, QLabel, "nowPlayingArtist").text() == first.artist
    assert _child(page, QLabel, "nowPlayingAlbum").text() == first.album
    play = _child(page, IconButton, "nowPlayingPlayPause")
    assert play.accessibleName() == "Pause"
    play.click()
    assert not controller.playing and backend.pause_calls == 1
    play.click()
    assert controller.playing and backend.play_calls == 1
    slider = _child(page, QSlider, "nowPlayingProgress")
    backend.emit_position(40_000)
    assert slider.value() == 40_000 and backend.seeks == []
    slider.setSliderDown(True)
    slider.setValue(12_000)
    backend.emit_position(45_000)
    assert slider.value() == 12_000
    assert _child(page, QLabel, "nowPlayingElapsed").text() == "0:12"
    slider.setSliderDown(False)
    assert backend.seeks == [12_000]
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert backend.seeks[-1] == 13_000
    _child(page, IconButton, "nowPlayingNext").click()
    assert controller.current_track == second
    _child(page, IconButton, "nowPlayingPrevious").click()
    assert controller.current_track == first


def test_open_close_crossfade_includes_status_bar_and_can_reverse() -> None:
    context = build_context()
    context.playback_controller.play_now((_track(),))
    window = MainWindow(context, auto_discover=False)
    try:
        window.resize(1100, 720)
        window.show()
        APPLICATION.processEvents()
        fade = _child(window, PageFade, "nowPlayingPageFade")
        animation = fade.findChild(QVariantAnimation)
        assert animation is not None
        original = window.grab().toImage()
        entry = context.playback_controller.current_entry_id
        _child(window, QToolButton, "playerArtworkButton").click()
        animation.pause()
        assert fade.isVisible() and fade.geometry() == window.rect()
        assert window.grab().toImage() == original
        assert window.statusBar().isHidden()
        animation.setCurrentTime(animation.duration() // 2)
        midway = window.grab().toImage()
        assert midway != original
        # Closing partway through starts from exactly the current visible blend.
        _child(window, IconButton, "nowPlayingClose").click()
        animation.pause()
        assert fade.isVisible() and not window.statusBar().isHidden()
        assert window.grab().toImage() == midway
        assert context.playback_controller.current_entry_id == entry
        assert context.playback_controller.playing
        animation.setCurrentTime(animation.duration())
        assert not fade.isVisible()
        assert _child(window, QToolButton, "playerArtworkButton").hasFocus()
        _child(window, QToolButton, "playerArtworkButton").click()
        animation.pause()
        animation.setCurrentTime(animation.duration())
        assert not fade.isVisible()
        assert _child(window, NowPlayingPage, "nowPlayingPage").isVisible()
        _child(window, IconButton, "nowPlayingClose").click()
        assert fade.isVisible()
        window.resize(1200, 800)
        APPLICATION.processEvents()
        assert not fade.isVisible()
        assert _child(window, QWidget, "appShell").isVisible()
    finally:
        window.close()
        context.shutdown()


def test_queue_reorder_remove_and_clear_preserve_current_entry(
    player: tuple[
        NowPlayingPage, PlaybackController, FakePlaybackBackend, _ArtworkProvider
    ],
) -> None:
    page, controller, _backend, _provider = player
    first, second = _track(), _track(2)
    controller.play_now((first, second, second, _track(3)))
    listing = _child(page, PlaybackQueueView, "nowPlayingQueueView")
    assert listing.model() is controller.queue_model
    entry = controller.current_entry_id
    pending = controller.queue_model.entries
    listing.setCurrentIndex(listing.model().index(1, 0))
    QTest.keyClick(listing, Qt.Key.Key_Up, Qt.KeyboardModifier.AltModifier)
    assert controller.queue_model.entries[0].entry_id == pending[1].entry_id
    QTest.keyClick(listing, Qt.Key.Key_Delete)
    assert controller.queue_model.entries[0].entry_id == pending[0].entry_id
    _child(page, ActionButton, "nowPlayingClearQueue").click()
    assert controller.queue_model.rowCount() == 0
    assert controller.current_entry_id == entry and controller.playing
    assert _child(page, QLabel, "nowPlayingQueueEmpty").isVisible()


def _background_pixel(page: QWidget) -> QColor:
    # Existing artwork routing assertions inspect the completed transition.
    QTest.qWait(1250)
    image = page.grab().toImage()
    return image.pixelColor(0, 0)


def test_artwork_follows_timed_frames_late_loading_and_session_clear(
    player: tuple[
        NowPlayingPage, PlaybackController, FakePlaybackBackend, _ArtworkProvider
    ],
) -> None:
    page, controller, backend, provider = player
    fallback = _background_pixel(page)
    controller.play_now((_track(),))
    red = _background_pixel(page)
    assert red != fallback
    missing = provider.frames.pop((1, 30_000))
    backend.emit_position(30_000)
    assert _background_pixel(page) == fallback
    provider.frames[1, 30_000] = missing
    provider.artworkChanged.emit(1)
    blue = _background_pixel(page)
    assert blue != red and blue != fallback
    controller.seek(0)
    assert _background_pixel(page) == red
    provider.frames.clear()
    provider.cleared.emit()
    assert _background_pixel(page) == fallback
    controller.clear_session()
    assert _background_pixel(page) == fallback
    assert not _child(page, IconButton, "nowPlayingPlayPause").isEnabled()
    assert _child(page, QLabel, "nowPlayingTitle").text() == "Nothing playing"


def test_chapter_navigation_and_track_change_cancel_in_progress_scrub(
    player: tuple[
        NowPlayingPage, PlaybackController, FakePlaybackBackend, _ArtworkProvider
    ],
) -> None:
    page, controller, backend, _provider = player
    chaptered = replace(
        _track(),
        metadata=TrackMetadata(
            chapters=(
                TrackChapter("First", 0),
                TrackChapter("Second", 30_000),
            )
        ),
    )
    controller.play_now((chaptered,))
    next_button = _child(page, IconButton, "nowPlayingNext")
    assert next_button.accessibleName() == "Next Chapter"
    next_button.click()
    assert controller.current_track == chaptered
    assert backend.seeks[-1] == 30_000
    assert "Second" in _child(page, QLabel, "nowPlayingTitle").text()
    slider = _child(page, QSlider, "nowPlayingProgress")
    slider.setSliderDown(True)
    slider.setValue(50_000)
    controller.play_now((_track(2),))
    assert not slider.isSliderDown() and slider.value() == 0
    assert backend.seeks == [30_000]


def test_timed_artwork_and_track_changes_fade_from_the_current_background(
    player: tuple[
        NowPlayingPage, PlaybackController, FakePlaybackBackend, _ArtworkProvider
    ],
) -> None:
    page, controller, backend, provider = player
    backdrop = _child(page, NowPlayingBackdrop, "nowPlayingBackdrop")
    timer = backdrop.findChild(QTimer)
    assert timer is not None
    controller.play_now((_track(),))
    QTest.qWait(1250)
    red = backdrop.grab().toImage()
    backend.emit_position(30_000)
    assert backdrop.grab().toImage() == red
    QTest.qWait(600)
    partial = backdrop.grab().toImage()
    assert partial != red
    # A rapid track change must not clear the visible raster or finish the old fade.
    controller.play_now((replace(_track(2), artwork_id=1),))
    assert backdrop.grab().toImage() == partial
    QTest.qWait(1250)
    assert backdrop.grab().toImage() == red
    backend.emit_position(30_000)
    QTest.qWait(600)
    provider.frames.clear()
    provider.cleared.emit()
    assert not timer.isActive()
    assert backdrop.grab().toImage() != red


@pytest.mark.parametrize("mode", (AppearanceMode.LIGHT, AppearanceMode.DARK))
def test_page_layout_fits_desktop_sizes_and_long_metadata(mode: AppearanceMode) -> None:
    context = build_context()
    context.settings.set_global(APPEARANCE_MODE, mode.value)
    provider = ArtworkPixmapProvider(context.artwork_controller)
    page = NowPlayingPage(context.playback_controller, context.theme_manager, provider)
    track = replace(
        _track(), title="Long title " * 80, artist="Artist " * 60, album="Album " * 60
    )
    context.playback_controller.play_now((track,) * 30)
    try:
        for width, height in ((960, 620), (1360, 820), (1920, 1080), (960, 620)):
            page.resize(width, height)
            page.show()
            APPLICATION.processEvents()
            assert page.width() == width and page.height() == height
            cover = _child(page, ArtworkView, "nowPlayingArtwork")
            queue = _child(page, PlaybackQueueView, "nowPlayingQueueView")
            controls = _child(page, QWidget, "nowPlayingControls")
            assert cover.width() == cover.height() >= 220
            assert controls.geometry().right() < queue.mapTo(page, QPoint()).x()
            for name, kind in (
                ("nowPlayingClose", IconButton),
                ("nowPlayingNext", IconButton),
                ("nowPlayingProgress", QSlider),
            ):
                widget = _child(page, kind, name)
                assert page.rect().contains(
                    widget.mapTo(page, widget.rect().bottomRight())
                )
            assert queue.verticalScrollBar().maximum() > 0
            assert queue.horizontalScrollBar().maximum() == 0
    finally:
        page.close()
        provider.shutdown()
        context.shutdown()


@pytest.mark.parametrize("tokens", (LIGHT_TOKENS, DARK_TOKENS))
def test_blurred_background_keeps_spatial_colors_without_hard_edges(
    tokens: ThemeTokens,
) -> None:
    image = QImage(600, 600, QImage.Format.Format_RGB888)
    painter = QPainter(image)
    painter.fillRect(0, 0, 300, 600, QColor("red"))
    painter.fillRect(300, 0, 300, 600, QColor("blue"))
    painter.end()
    blurred = now_playing_background(image, tokens)
    assert blurred.size().width() == blurred.size().height() == 96
    left, right = blurred.pixelColor(0, 48), blurred.pixelColor(95, 48)
    assert left.red() > right.red() and right.blue() > left.blue()
    for x in range(1, 96):
        before, after = blurred.pixelColor(x - 1, 48), blurred.pixelColor(x, 48)
        # No pixel crosses more than 1/16 of the color range (plus quantization).
        assert abs(before.red() - after.red()) <= max(
            3, 1 + abs(left.red() - right.red()) / 16
        )
        assert abs(before.blue() - after.blue()) <= max(
            3, 1 + abs(left.blue() - right.blue()) / 16
        )
    assert image.pixelColor(0, 0) == QColor("red")


@pytest.mark.parametrize("height", (620, 1140))
def test_wide_windows_keep_columns_at_capped_edge_margins(
    player: tuple[
        NowPlayingPage, PlaybackController, FakePlaybackBackend, _ArtworkProvider
    ],
    height: int,
) -> None:
    page, controller, _backend, _provider = player
    controller.play_now((_track(), _track(2)))
    cover = _child(page, ArtworkView, "nowPlayingArtwork")
    queue = _child(page, QWidget, "nowPlayingQueue")
    previous: tuple[int, int, int, int] | None = None
    for width in (1704, 2200, 2800, 1704):
        page.resize(width, height)
        APPLICATION.processEvents()
        artwork_left = cover.mapTo(page, QPoint()).x()
        queue_left = queue.mapTo(page, QPoint()).x()
        right_margin = width - queue_left - queue.width()
        gap = queue_left - artwork_left - cover.width()
        assert right_margin == 300
        if height == 1140:
            assert artwork_left == 320
        if previous is not None:
            old_width, old_left, old_margin, old_gap = previous
            assert artwork_left == old_left
            assert right_margin == old_margin
            assert gap - old_gap == width - old_width
        previous = width, artwork_left, right_margin, gap


def _luminance(color: QColor) -> float:
    linear = tuple(
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in (color.redF(), color.greenF(), color.blueF())
    )
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


@pytest.mark.parametrize("theme", (*LightTheme, *DarkTheme))
def test_background_preserves_text_contrast_in_every_theme(
    theme: LightTheme | DarkTheme,
) -> None:
    tokens = tokens_for(theme)
    image = QImage(96, 96, QImage.Format.Format_RGB888)
    painter = QPainter(image)
    for x, color in enumerate(("black", "white", "yellow", "blue")):
        painter.fillRect(x * 24, 0, 24, 96, QColor(color))
    painter.end()
    result = now_playing_background(image, tokens)
    for x in range(96):
        background = _luminance(result.pixelColor(x, 48))
        for color in (tokens.text, tokens.text_secondary):
            ink = _luminance(QColor(color))
            assert (max(background, ink) + 0.05) / (min(background, ink) + 0.05) >= 4.5
