"""GUI-thread conversion of lazy RGB artwork into display pixmaps."""

from collections.abc import Callable
from time import monotonic

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


class _Loader:
    def __init__(self) -> None:
        self.requests: list[ArtworkRequest] = []

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage:
        self.requests.append(request)
        return ArtworkImage(
            cache_key=f"generation:{request.artwork_id}:1061",
            artwork_id=request.artwork_id,
            format_id=1061,
            width=2,
            height=2,
            rgb888=bytes((0, 255, 0)) * 4,
        )


def test_provider_requests_physical_pixels_and_caches_owned_qpixmap() -> None:
    loader = _Loader()
    controller = ArtworkController(loader)
    provider = ArtworkPixmapProvider(controller)
    changed: list[int] = []
    provider.artworkChanged.connect(changed.append)

    try:
        assert provider.pixmap(64, 44, 2.0) is None
        _wait_until(lambda: changed == [64])

        pixmap = provider.pixmap(64, 44, 2.0)
        assert pixmap is not None
        assert not pixmap.isNull()
        assert pixmap.toImage().pixelColor(0, 0).green() == 255
        pixels = provider.pixels(64, 44, 2.0)
        assert pixels is not None
        assert pixels.rgb888 == bytes((0, 255, 0)) * 4
        assert provider.dominant_color(64, 44, 2.0) is None
        _wait_until(lambda: provider.dominant_color(64, 44, 2.0) == (0, 216, 0))
        assert loader.requests == [ArtworkRequest(64, 88)]
    finally:
        provider.shutdown()
        controller.shutdown()


def test_provider_notifies_views_for_64_bit_host_artwork_identity() -> None:
    artwork_id = 4_668_449_358_420_290_499
    loader = _Loader()
    controller = ArtworkController(loader)
    provider = ArtworkPixmapProvider(controller)
    changed: list[int] = []
    provider.artworkChanged.connect(changed.append)

    try:
        assert provider.pixmap(artwork_id, 44, 1.0) is None
        _wait_until(lambda: changed == [artwork_id])
    finally:
        provider.shutdown()
        controller.shutdown()


class _VariableLoader:
    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage:
        color = (255, 0, 0) if request.artwork_id == 1 else (0, 0, 255)
        return ArtworkImage(
            cache_key=f"generation:{request.artwork_id}:{request.target_px}",
            artwork_id=request.artwork_id,
            format_id=1061,
            width=2,
            height=2,
            rgb888=bytes(color) * 4,
        )


def test_provider_derives_colors_asynchronously_in_a_bounded_lru() -> None:
    controller = ArtworkController(_VariableLoader())
    provider = ArtworkPixmapProvider(controller, color_cache_limit=1)

    try:
        assert provider.dominant_color(1, 44, 1.0) is None
        _wait_until(lambda: provider.dominant_color(1, 44, 1.0) == (216, 0, 0))

        assert provider.dominant_color(2, 44, 1.0) is None
        _wait_until(lambda: provider.dominant_color(2, 44, 1.0) == (0, 0, 216))

        # The one-entry LRU evicted artwork 1 even though its decoded RGB remains
        # available in the controller's independently bounded cache.
        assert provider.dominant_color(1, 44, 1.0) is None
        _wait_until(lambda: provider.dominant_color(1, 44, 1.0) == (216, 0, 0))
    finally:
        provider.shutdown()
        controller.shutdown()


def _wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    APPLICATION.processEvents()
    assert predicate(), "Timed out waiting for artwork pixmap"
