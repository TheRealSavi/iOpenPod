"""Asynchronous, generation-scoped artwork cache behavior."""

from collections.abc import Callable
from threading import Event
from time import monotonic

import pytest
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
            cache_key=f"device:{request.artwork_id}:1061:{request.display_time_ms}",
            artwork_id=request.artwork_id,
            format_id=1061,
            width=2,
            height=2,
            rgb888=bytes(
                (0, 0, 255) if request.display_time_ms == 10000 else (255, 0, 0)
            )
            * 4,
            display_time_ms=request.display_time_ms,
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


def test_exact_time_requests_do_not_share_pending_work_or_cached_images() -> None:
    loader = _ArtworkLoader()
    controller = ArtworkController(loader)
    ready: list[ArtworkImage] = []
    controller.artworkReady.connect(ready.append)
    try:
        assert controller.request(64, 152, display_time_ms=0) is None
        assert controller.request(64, 152, display_time_ms=10000) is None
        assert controller.request(64, 152, display_time_ms=10000) is None
        _wait_until(lambda: len(ready) == 2)
        first = controller.request(64, 152, display_time_ms=0)
        later = controller.request(64, 152, display_time_ms=10000)
        assert first is not None and later is not None
        assert first.rgb888 == bytes((255, 0, 0)) * 4
        assert later.rgb888 == bytes((0, 0, 255)) * 4
        assert {request.display_time_ms for request in loader.requests} == {0, 10000}
        assert len(loader.requests) == 2
        # An ordinary cover request remains distinct from an exact-group request.
        assert controller.request(64, 152) is None
        _wait_until(lambda: len(ready) == 3)
        assert len(loader.requests) == 3
    finally:
        controller.shutdown()


def test_time_group_metadata_does_not_load_images_and_invalidates_with_source() -> None:
    loader = _ArtworkLoader()
    groups = {64: (0, 10000, 0xFFFFFFFF)}
    controller = ArtworkController(
        loader, display_times=lambda identity: groups.get(identity, ())
    )
    try:
        assert controller.display_times(64) == (0, 10000, 0xFFFFFFFF)
        assert controller.display_times(0) == ()
        assert loader.requests == []
        groups.clear()
        controller.invalidate()
        assert controller.display_times(64) == ()
    finally:
        controller.shutdown()
    assert controller.display_times(64) == ()


@pytest.mark.parametrize("value", (-1, 0x100000000, True))
def test_artwork_requests_reject_invalid_time_groups(value: int) -> None:
    with pytest.raises(ValueError, match="display time"):
        ArtworkRequest(64, 152, display_time_ms=value)


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
