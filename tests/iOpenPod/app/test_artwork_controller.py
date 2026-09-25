"""Asynchronous, generation-scoped artwork cache behavior."""

from collections.abc import Callable
from threading import Event
from time import monotonic

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


class _ArtworkLoader:
    def __init__(self, *, gate: Event | None = None) -> None:
        self.gate = gate
        self.started = Event()
        self.requests: list[ArtworkRequest] = []

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage:
        self.requests.append(request)
        self.started.set()
        if self.gate is not None:
            self.gate.wait(timeout=2)
        return ArtworkImage(
            cache_key=f"device:{request.artwork_id}:1061",
            artwork_id=request.artwork_id,
            format_id=1061,
            width=2,
            height=2,
            rgb888=bytes((255, 0, 0)) * 4,
        )


def test_requests_are_deduplicated_then_served_from_the_rgb_lru() -> None:
    loader = _ArtworkLoader()
    controller = ArtworkController(loader)
    ready: list[ArtworkImage] = []
    controller.artworkReady.connect(ready.append)

    try:
        assert controller.request(64, 152) is None
        assert controller.request(64, 152) is None
        _wait_until(lambda: bool(ready))

        assert loader.requests == [ArtworkRequest(64, 152)]
        assert controller.request(64, 152) is ready[0]
        assert controller.cached_byte_count == 12
    finally:
        controller.shutdown()


def test_results_from_an_invalidated_device_generation_are_discarded() -> None:
    gate = Event()
    loader = _ArtworkLoader(gate=gate)
    controller = ArtworkController(loader)
    ready: list[ArtworkImage] = []
    controller.artworkReady.connect(ready.append)

    try:
        controller.request(64, 152)
        assert loader.started.wait(timeout=1)
        controller.invalidate()
        gate.set()
        _wait_until(lambda: controller.pending_count == 0)

        assert ready == []
        assert controller.cached_byte_count == 0
    finally:
        gate.set()
        controller.shutdown()


def test_image_larger_than_the_rgb_cache_limit_is_delivered_but_not_retained() -> None:
    loader = _ArtworkLoader()
    controller = ArtworkController(loader, cache_byte_limit=8)
    ready: list[ArtworkImage] = []
    controller.artworkReady.connect(ready.append)

    try:
        assert controller.request(64, 152) is None
        _wait_until(lambda: bool(ready))

        assert ready[0].byte_count == 12
        assert controller.cached_byte_count == 0
        _wait_until(lambda: controller.pending_count == 0)
        assert controller.request(64, 152) is None
        _wait_until(lambda: len(loader.requests) == 2)
    finally:
        controller.shutdown()


def _wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    APPLICATION.processEvents()
    assert predicate(), "Timed out waiting for asynchronous artwork work"
