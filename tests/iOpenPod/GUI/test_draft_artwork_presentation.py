"""Applied artwork drafts remain visible before receiving device identities."""

from collections.abc import Callable
from time import monotonic

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iPodDB.library import (
    ArtworkAsset,
    ArtworkPixels,
    TimedArtworkAsset,
    TimedArtworkFrame,
)

_RED = ArtworkPixels(1, 1, b"\xff\0\0")
_BLUE = ArtworkPixels(1, 1, b"\0\0\xff")
_GREEN = ArtworkPixels(1, 1, b"\0\xff\0")


class _SourceLoader:
    def __init__(self) -> None:
        self.requests: list[ArtworkRequest] = []

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage:
        self.requests.append(request)
        assert request.artwork_id > 0
        return ArtworkImage(
            cache_key=f"source:{request.artwork_id}:{request.target_px}:{request.display_time_ms}",
            artwork_id=request.artwork_id,
            format_id=1029,
            width=1,
            height=1,
            rgb888=_GREEN.rgb888,
            display_time_ms=request.display_time_ms,
        )


def _wait_until(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 3
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(1)
    APPLICATION.processEvents()
    assert predicate(), "Timed out waiting for draft artwork"


def test_provider_keeps_draft_default_and_exact_groups_separate_in_pixels_and_colors() -> (
    None
):
    source = _SourceLoader()
    controller = ArtworkController(source)
    controller.set_draft_assets(
        (
            TimedArtworkAsset(
                -1, (TimedArtworkFrame(0, _RED), TimedArtworkFrame(10_000, _BLUE))
            ),
        )
    )
    provider = ArtworkPixmapProvider(controller)
    changed: list[int] = []
    provider.artworkChanged.connect(changed.append)
    try:
        assert provider.display_times(-1) == (0, 10_000)
        assert provider.pixmap(-1, 44, 2.0, display_time_ms=10_000) is None
        _wait_until(
            lambda: provider.pixels(-1, 44, 2.0, display_time_ms=10_000) is not None
        )
        pixmap = provider.pixmap(-1, 44, 2.0, display_time_ms=10_000)
        assert pixmap is not None and pixmap.toImage().pixelColor(0, 0) == QColor(
            "blue"
        )
        pixels = provider.pixels(-1, 44, 2.0, display_time_ms=10_000)
        assert pixels is not None and pixels.rgb888[:3] == _BLUE.rgb888
        assert provider.dominant_color(-1, 44, 2.0) is None
        _wait_until(lambda: provider.dominant_color(-1, 44, 2.0) == (216, 0, 0))
        assert changed and all(identity == -1 for identity in changed)
        assert source.requests == []

        controller.set_draft_assets((ArtworkAsset(-1, _GREEN),))
        assert provider.dominant_color(-1, 44, 2.0) is None
        _wait_until(lambda: provider.dominant_color(-1, 44, 2.0) == (0, 216, 0))
        fresh = provider.pixmap(-1, 44, 2.0)
        assert fresh is not None and fresh.toImage().pixelColor(0, 0) == QColor("lime")
        assert provider.display_times(-1) == (0,)
        assert source.requests == []
    finally:
        provider.shutdown()
        controller.shutdown()


def test_zero_identity_remains_empty_while_negative_and_positive_ids_have_separate_cache_entries() -> (
    None
):
    source = _SourceLoader()
    controller = ArtworkController(source)
    controller.set_draft_assets((ArtworkAsset(-7, _RED),))
    provider = ArtworkPixmapProvider(controller)
    try:
        assert provider.pixmap(0, 44, 1.0) is None
        assert provider.pixels(0, 44, 1.0) is None
        assert provider.dominant_color(0, 44, 1.0) is None
        assert source.requests == []
        assert provider.pixmap(-7, 44, 1.0) is None
        assert provider.pixmap(7, 44, 1.0) is None
        _wait_until(lambda: controller.pending_count == 0)
        draft = provider.pixmap(-7, 44, 1.0)
        retained = provider.pixmap(7, 44, 1.0)
        assert draft is not None and retained is not None
        assert draft.toImage().pixelColor(0, 0) == QColor("red")
        assert retained.toImage().pixelColor(0, 0) == QColor("lime")
        assert source.requests == [ArtworkRequest(7, 44)]
    finally:
        provider.shutdown()
        controller.shutdown()


def test_artwork_view_preserves_draft_identity_accessibility_and_collection_mode() -> (
    None
):
    context = build_context()
    source = _SourceLoader()
    controller = ArtworkController(source)
    controller.set_draft_assets(
        (
            TimedArtworkAsset(
                -1, (TimedArtworkFrame(0, _RED), TimedArtworkFrame(10_000, _BLUE))
            ),
        )
    )
    provider = ArtworkPixmapProvider(controller)
    view = ArtworkView(context.theme_manager, provider)
    view.resize(100, 100)

    def color() -> QColor:
        image = view.grab().toImage()
        return image.pixelColor(image.width() // 2, image.height() // 2)

    try:
        view.set_artwork_id(-1, display_time_ms=10_000)
        assert view.accessibleName() == "Album artwork"
        APPLICATION.sendEvent(view, QEvent(QEvent.Type.LanguageChange))
        assert view.accessibleName() == "Album artwork"
        _wait_until(lambda: color() == QColor("blue"))
        view.set_artwork_id(-1)
        _wait_until(lambda: color() == QColor("red"))
        assert source.requests == []
        view.set_artwork_ids((7, 0, 0, 0))
        assert view.accessibleName() == "Collection artwork"
        view.grab()
        _wait_until(lambda: controller.pending_count == 0)
        assert source.requests and source.requests[-1].display_time_ms is None
        assert view.grab().toImage().pixelColor(25, 25) == QColor("lime")
        view.set_artwork_id(0)
        assert view.accessibleName() == "Placeholder artwork"
        view.set_artwork_id(-1, display_time_ms=10_000)
        assert view.accessibleName() == "Album artwork"
        _wait_until(lambda: color() == QColor("blue"))
    finally:
        view.close()
        provider.shutdown()
        controller.shutdown()
        context.shutdown()
