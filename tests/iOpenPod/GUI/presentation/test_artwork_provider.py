"""GUI-thread conversion of lazy RGB artwork into display pixmaps."""

from collections.abc import Callable
from threading import Event
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


class _TimedLoader:
    def __init__(self) -> None:
        self.release_default = Event()

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage:
        if request.display_time_ms is None:
            assert self.release_default.wait(3)
        color = (0, 255, 0) if request.display_time_ms is None else (0, 0, 255)
        return ArtworkImage(
            cache_key=f"timed-provider:{request.artwork_id}:{request.display_time_ms}",
            artwork_id=request.artwork_id,
            format_id=1029,
            width=2,
            height=2,
            rgb888=bytes(color) * 4,
            display_time_ms=request.display_time_ms,
        )


def test_selected_timed_preview_does_not_supply_the_default_artwork_color() -> None:
    loader = _TimedLoader()
    controller = ArtworkController(loader, display_times=lambda _id: (0, 10_000))
    provider = ArtworkPixmapProvider(controller)
    try:
        assert provider.display_times(101) == (0, 10_000)
        assert provider.dominant_color(101, 44, 1.0) is None
        assert provider.pixmap(101, 44, 1.0, display_time_ms=10_000) is None
        _wait_until(
            lambda: provider.pixels(101, 44, 1.0, display_time_ms=10_000) is not None
        )
        timed = provider.pixels(101, 44, 1.0, display_time_ms=10_000)
        assert timed is not None and timed.rgb888 == bytes((0, 0, 255)) * 4
        assert provider.dominant_color(101, 44, 1.0) is None
        loader.release_default.set()
        _wait_until(lambda: provider.dominant_color(101, 44, 1.0) == (0, 216, 0))
    finally:
        loader.release_default.set()
        provider.shutdown()
        controller.shutdown()


def test_unavailable_timed_preview_keeps_pending_default_color_request() -> None:
    class Loader:
        def __init__(self) -> None:
            self.ordinary = _TimedLoader()
            self.release_default = self.ordinary.release_default

        def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
            if request.display_time_ms is not None:
                return None
            return self.ordinary.load_artwork(request)

    loader = Loader()
    controller = ArtworkController(loader)
    provider = ArtworkPixmapProvider(controller)
    changed: list[int] = []
    provider.artworkChanged.connect(changed.append)
    try:
        assert provider.dominant_color(101, 44, 1.0) is None
        assert provider.pixmap(101, 44, 1.0, display_time_ms=10_000) is None
        _wait_until(lambda: changed == [101] and controller.pending_count == 1)
        loader.release_default.set()
        # Missing preview, ordinary image, then derived color. Do not request the
        # color again while waiting: that would hide lost request interest.
        _wait_until(lambda: changed == [101, 101, 101])
        assert provider.dominant_color(101, 44, 1.0) == (0, 216, 0)
    finally:
        loader.release_default.set()
        provider.shutdown()
        controller.shutdown()


def _wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    APPLICATION.processEvents()
    assert predicate(), "Timed out waiting for artwork pixmap"
