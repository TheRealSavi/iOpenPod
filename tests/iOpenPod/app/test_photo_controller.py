"""Asynchronous, generation-scoped Photo RGB cache behavior."""

from collections import Counter
from collections.abc import Callable
from threading import Event
from time import monotonic

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iOpenPod.app.models.photos import (
    FULL_RESOLUTION_REQUEST_ID,
    PhotoImage,
    PhotoRequest,
)
from iOpenPod.app.photo_controller import PhotoController, PhotoUnavailable


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


class _PhotoLoader:
    def __init__(self, *, gate: Event | None = None) -> None:
        self.gate = gate
        self.started = Event()
        self.requests: list[PhotoRequest] = []

    def load_photo(self, request: PhotoRequest) -> PhotoImage:
        self.requests.append(request)
        self.started.set()
        if self.gate is not None:
            self.gate.wait(timeout=2)
        format_id = request.format_id or 1031
        return PhotoImage(
            cache_key=f"device:{request.photo_id}:{format_id}",
            photo_id=request.photo_id,
            format_id=format_id,
            width=2,
            height=2,
            rgb888=bytes((255, 0, 0)) * 4,
        )


def test_automatic_and_exact_format_requests_have_distinct_cache_keys() -> None:
    loader = _PhotoLoader()
    controller = PhotoController(loader)
    ready: list[PhotoImage] = []
    controller.photoReady.connect(ready.append)

    try:
        assert controller.request(64, 152) is None
        assert controller.request(64, 152) is None
        assert controller.request(64, 152, format_id=1040) is None
        assert controller.request(64, 152, format_id=1040) is None
        _wait_until(lambda: len(ready) == 2)

        assert Counter(loader.requests) == Counter(
            (PhotoRequest(64, 152), PhotoRequest(64, 152, 1040))
        )
        automatic = controller.request(64, 152)
        exact = controller.request(64, 152, format_id=1040)
        assert automatic is not None and automatic.format_id == 1031
        assert exact is not None and exact.format_id == 1040
        assert controller.cached_byte_count == 24
    finally:
        controller.shutdown()


def test_exact_format_reuses_stored_bytes_across_display_targets() -> None:
    loader = _PhotoLoader()
    controller = PhotoController(loader)
    ready: list[PhotoImage] = []
    controller.photoReady.connect(ready.append)

    try:
        assert controller.request(64, 44, format_id=1040) is None
        _wait_until(lambda: len(ready) == 1)

        retained = controller.request(64, 512, format_id=1040)

        assert retained is ready[0]
        assert loader.requests == [PhotoRequest(64, 44, 1040)]
    finally:
        controller.shutdown()


class _FullResolutionLoader:
    def __init__(self) -> None:
        self.requests: list[PhotoRequest] = []

    def load_photo(self, request: PhotoRequest) -> PhotoImage:
        self.requests.append(request)
        return PhotoImage(
            cache_key=f"full-resolution:{request.photo_id}:{request.target_px}",
            photo_id=request.photo_id,
            format_id=FULL_RESOLUTION_REQUEST_ID,
            width=request.target_px,
            height=1,
            rgb888=b"\x00\x00\x00" * request.target_px,
        )


def test_full_resolution_is_cached_per_display_target() -> None:
    loader = _FullResolutionLoader()
    controller = PhotoController(loader)
    ready: list[PhotoImage] = []
    controller.photoReady.connect(ready.append)

    try:
        controller.request(64, 44, format_id=FULL_RESOLUTION_REQUEST_ID)
        _wait_until(lambda: len(ready) == 1)
        controller.request(64, 512, format_id=FULL_RESOLUTION_REQUEST_ID)
        _wait_until(lambda: len(ready) == 2)

        assert loader.requests == [
            PhotoRequest(64, 44, FULL_RESOLUTION_REQUEST_ID),
            PhotoRequest(64, 512, FULL_RESOLUTION_REQUEST_ID),
        ]
        assert (
            controller.request(
                64,
                44,
                format_id=FULL_RESOLUTION_REQUEST_ID,
            )
            is ready[0]
        )
    finally:
        controller.shutdown()


def test_results_from_an_invalidated_device_generation_are_discarded() -> None:
    gate = Event()
    loader = _PhotoLoader(gate=gate)
    controller = PhotoController(loader)
    ready: list[PhotoImage] = []
    controller.photoReady.connect(ready.append)

    try:
        controller.request(64, 152, format_id=1040)
        assert loader.started.wait(timeout=1)
        controller.invalidate()
        gate.set()
        _wait_until(lambda: controller.pending_count == 0)
        QTest.qWait(25)
        APPLICATION.processEvents()

        assert ready == []
        assert controller.cached_byte_count == 0
    finally:
        gate.set()
        controller.shutdown()


def test_rgb_cache_evicts_least_recently_used_images_by_byte_count() -> None:
    loader = _PhotoLoader()
    controller = PhotoController(loader, cache_byte_limit=12)
    ready: list[PhotoImage] = []
    controller.photoReady.connect(ready.append)

    try:
        controller.request(1, 44)
        _wait_until(lambda: len(ready) == 1)
        controller.request(2, 44)
        _wait_until(lambda: len(ready) == 2)

        assert controller.cached_byte_count == 12
        assert controller.request(1, 44) is None
        _wait_until(lambda: len(loader.requests) == 3)
        assert loader.requests.count(PhotoRequest(1, 44)) == 2
    finally:
        controller.shutdown()


class _WrongFormatLoader:
    def load_photo(self, request: PhotoRequest) -> PhotoImage:
        return PhotoImage(
            cache_key="wrong-format",
            photo_id=request.photo_id,
            format_id=1031,
            width=1,
            height=1,
            rgb888=b"\x00\x00\x00",
        )


def test_exact_format_request_rejects_a_different_loader_result() -> None:
    controller = PhotoController(_WrongFormatLoader())
    unavailable: list[PhotoUnavailable] = []
    ready: list[PhotoImage] = []
    controller.photoUnavailable.connect(unavailable.append)
    controller.photoReady.connect(ready.append)

    try:
        controller.request(64, 152, format_id=1040)
        _wait_until(lambda: unavailable == [PhotoUnavailable(64, 1040)])

        assert ready == []
        assert controller.cached_byte_count == 0
        assert controller.request(64, 152, format_id=1040) is None
    finally:
        controller.shutdown()


def test_capacity_signal_retries_a_request_rejected_by_the_pending_cap() -> None:
    gate = Event()
    loader = _PhotoLoader(gate=gate)
    controller = PhotoController(loader, max_pending=1)
    ready: list[PhotoImage] = []
    capacity_events: list[None] = []
    controller.photoReady.connect(ready.append)

    def retry_second_photo() -> None:
        capacity_events.append(None)
        controller.request(2, 44)

    controller.capacityAvailable.connect(retry_second_photo)

    try:
        assert controller.request(1, 44) is None
        assert loader.started.wait(timeout=1)
        assert controller.request(2, 44) is None
        assert loader.requests == [PhotoRequest(1, 44)]

        gate.set()
        _wait_until(lambda: {image.photo_id for image in ready} == {1, 2})

        assert capacity_events == [None]
        assert loader.requests == [PhotoRequest(1, 44), PhotoRequest(2, 44)]
    finally:
        gate.set()
        controller.shutdown()


class _UnavailableThenReadyLoader:
    def __init__(self) -> None:
        self.requests: list[PhotoRequest] = []

    def load_photo(self, request: PhotoRequest) -> PhotoImage | None:
        self.requests.append(request)
        if len(self.requests) == 1:
            return None
        format_id = request.format_id or 1031
        return PhotoImage(
            cache_key=f"retry:{request.photo_id}:{format_id}",
            photo_id=request.photo_id,
            format_id=format_id,
            width=1,
            height=1,
            rgb888=b"\x00\x00\x00",
        )


def test_user_retry_clears_an_exact_formats_terminal_unavailable_state() -> None:
    loader = _UnavailableThenReadyLoader()
    controller = PhotoController(loader)
    unavailable: list[PhotoUnavailable] = []
    ready: list[PhotoImage] = []
    controller.photoUnavailable.connect(unavailable.append)
    controller.photoReady.connect(ready.append)

    try:
        controller.request(64, 152, format_id=1040)
        _wait_until(lambda: unavailable == [PhotoUnavailable(64, 1040)])

        controller.retry(64, format_id=1040)
        assert controller.request(64, 152, format_id=1040) is None
        _wait_until(lambda: len(ready) == 1)

        assert ready[0].format_id == 1040
        assert loader.requests == [
            PhotoRequest(64, 152, 1040),
            PhotoRequest(64, 152, 1040),
        ]
    finally:
        controller.shutdown()


def test_immediate_retry_is_not_lost_before_the_failed_work_finishes() -> None:
    loader = _UnavailableThenReadyLoader()
    controller = PhotoController(loader)
    ready: list[PhotoImage] = []
    controller.photoReady.connect(ready.append)

    def retry_immediately(unavailable: PhotoUnavailable) -> None:
        controller.retry(unavailable.photo_id, format_id=unavailable.format_id)
        controller.request(
            unavailable.photo_id,
            152,
            format_id=unavailable.format_id,
        )

    controller.photoUnavailable.connect(retry_immediately)

    try:
        controller.request(64, 152, format_id=1040)
        _wait_until(lambda: len(ready) == 1)

        assert loader.requests == [
            PhotoRequest(64, 152, 1040),
            PhotoRequest(64, 152, 1040),
        ]
    finally:
        controller.shutdown()


def _wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    APPLICATION.processEvents()
    assert predicate(), "Timed out waiting for asynchronous Photo work"
