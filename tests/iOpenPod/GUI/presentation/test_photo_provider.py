"""GUI-thread conversion of lazy Photo RGB pixels into display pixmaps."""

from collections.abc import Callable
from threading import Event
from time import monotonic
from typing import cast

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iOpenPod.app.models.photos import (
    FULL_RESOLUTION_REQUEST_ID,
    PhotoImage,
    PhotoRequest,
)
from iOpenPod.app.photo_controller import PhotoController
from iOpenPod.GUI.presentation.photo_provider import (
    PhotoPixmapProvider,
    PhotoPixmapState,
)


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()


class _Loader:
    def __init__(self, photo_id: int = 64) -> None:
        self.photo_id = photo_id
        self.requests: list[PhotoRequest] = []
        self.source = bytearray(bytes((0, 255, 0)) * 4)

    def load_photo(self, request: PhotoRequest) -> PhotoImage:
        self.requests.append(request)
        format_id = 1031 if request.format_id is None else request.format_id
        return PhotoImage(
            cache_key=f"photo-provider:{self.photo_id}:{format_id}",
            photo_id=self.photo_id,
            format_id=format_id,
            width=2,
            height=2,
            # Deliberately retain mutable storage behind the bytes protocol. The
            # presentation provider must copy it before caching a Qt pixmap.
            rgb888=cast("bytes", self.source),
        )


def test_provider_requests_exact_physical_format_and_owns_source_pixels() -> None:
    loader = _Loader()
    controller = PhotoController(loader)
    provider = PhotoPixmapProvider(controller)
    changed: list[int] = []
    provider.photoChanged.connect(changed.append)

    try:
        assert provider.pixmap(64, 44, 2.0, format_id=1040) is None
        _wait_until(lambda: changed == [64])

        loader.source[:] = bytes((0, 0, 255)) * 4
        pixmap = provider.pixmap(64, 44, 2.0, format_id=1040)
        assert pixmap is not None
        assert not pixmap.isNull()
        assert (pixmap.width(), pixmap.height()) == (2, 2)
        assert pixmap.toImage().pixelColor(0, 0).green() == 255
        assert loader.requests == [PhotoRequest(64, 88, 1040)]
    finally:
        provider.shutdown()
        controller.shutdown()


def test_provider_notifies_views_for_64_bit_host_photo_identity() -> None:
    photo_id = 4_668_449_358_420_290_499
    loader = _Loader(photo_id)
    controller = PhotoController(loader)
    provider = PhotoPixmapProvider(controller)
    changed: list[int] = []
    provider.photoChanged.connect(changed.append)

    try:
        assert provider.pixmap(photo_id, 44, 1.0) is None
        _wait_until(lambda: changed == [photo_id])
    finally:
        provider.shutdown()
        controller.shutdown()


def test_provider_requests_a_full_resolution_display_copy() -> None:
    loader = _Loader()
    controller = PhotoController(loader)
    provider = PhotoPixmapProvider(controller)
    changed: list[int] = []
    provider.photoChanged.connect(changed.append)

    try:
        assert (
            provider.pixmap(
                64,
                44,
                2.0,
                format_id=FULL_RESOLUTION_REQUEST_ID,
            )
            is None
        )
        _wait_until(lambda: changed == [64])

        pixmap = provider.pixmap(
            64,
            44,
            2.0,
            format_id=FULL_RESOLUTION_REQUEST_ID,
        )
        assert pixmap is not None and not pixmap.isNull()
        assert loader.requests == [PhotoRequest(64, 88, FULL_RESOLUTION_REQUEST_ID)]
    finally:
        provider.shutdown()
        controller.shutdown()


def test_provider_clears_cached_pixmaps_with_the_controller_generation() -> None:
    loader = _Loader()
    controller = PhotoController(loader)
    provider = PhotoPixmapProvider(controller)
    changed: list[int] = []
    cleared: list[None] = []
    provider.photoChanged.connect(changed.append)
    provider.cleared.connect(lambda: cleared.append(None))

    try:
        assert provider.pixmap(64, 44, 1.0) is None
        _wait_until(lambda: changed == [64])
        assert provider.pixmap(64, 44, 1.0) is not None

        controller.invalidate()

        assert cleared == [None]
        assert provider.pixmap(64, 44, 1.0) is None
        _wait_until(lambda: len(loader.requests) == 2)
    finally:
        provider.shutdown()
        controller.shutdown()


class _TerminalLoader:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.requests: list[PhotoRequest] = []

    def load_photo(self, request: PhotoRequest) -> PhotoImage | None:
        self.requests.append(request)
        if len(self.requests) == 1:
            if self.fail:
                raise OSError("unreadable iTHMB")
            return None
        format_id = request.format_id or 1031
        return PhotoImage(
            cache_key=f"terminal-retry:{request.photo_id}:{format_id}",
            photo_id=request.photo_id,
            format_id=format_id,
            width=1,
            height=1,
            rgb888=b"\x00\x00\x00",
        )


def test_provider_exposes_unavailable_state_and_explicit_retry() -> None:
    loader = _TerminalLoader(fail=False)
    controller = PhotoController(loader)
    provider = PhotoPixmapProvider(controller)

    try:
        assert provider.pixmap(64, 44, 1.0, format_id=1040) is None
        _wait_until(
            lambda: provider.state(64, format_id=1040) is PhotoPixmapState.UNAVAILABLE
        )

        provider.retry(64, format_id=1040)
        assert provider.state(64, format_id=1040) is PhotoPixmapState.IDLE
        assert provider.pixmap(64, 44, 1.0, format_id=1040) is None
        _wait_until(
            lambda: provider.state(64, format_id=1040) is PhotoPixmapState.READY
        )
        assert provider.pixmap(64, 44, 1.0, format_id=1040) is not None
    finally:
        provider.shutdown()
        controller.shutdown()


def test_provider_distinguishes_loader_failures_from_unavailable_formats() -> None:
    loader = _TerminalLoader(fail=True)
    controller = PhotoController(loader)
    provider = PhotoPixmapProvider(controller)

    try:
        assert provider.pixmap(64, 44, 1.0, format_id=1040) is None
        _wait_until(
            lambda: provider.state(64, format_id=1040) is PhotoPixmapState.FAILED
        )

        provider.retry(64, format_id=1040)
        assert provider.pixmap(64, 44, 1.0, format_id=1040) is None
        _wait_until(
            lambda: provider.state(64, format_id=1040) is PhotoPixmapState.READY
        )
    finally:
        provider.shutdown()
        controller.shutdown()


class _CapacityLoader:
    def __init__(self) -> None:
        self.gate = Event()
        self.started = Event()
        self.requests: list[PhotoRequest] = []

    def load_photo(self, request: PhotoRequest) -> PhotoImage:
        self.requests.append(request)
        self.started.set()
        self.gate.wait(timeout=2)
        format_id = request.format_id or 1031
        return PhotoImage(
            cache_key=f"capacity:{request.photo_id}:{format_id}",
            photo_id=request.photo_id,
            format_id=format_id,
            width=1,
            height=1,
            rgb888=b"\x00\x00\x00",
        )


def test_provider_notifies_painters_to_retry_after_pending_capacity_frees() -> None:
    loader = _CapacityLoader()
    controller = PhotoController(loader, max_pending=1)
    provider = PhotoPixmapProvider(controller)
    capacity_events: list[None] = []

    def repaint_second_photo() -> None:
        capacity_events.append(None)
        provider.pixmap(2, 44, 1.0)

    provider.capacityAvailable.connect(repaint_second_photo)

    try:
        assert provider.pixmap(1, 44, 1.0) is None
        assert loader.started.wait(timeout=1)
        assert provider.pixmap(2, 44, 1.0) is None

        loader.gate.set()
        _wait_until(lambda: provider.state(2) is PhotoPixmapState.READY)

        assert capacity_events == [None]
        assert loader.requests == [PhotoRequest(1, 44), PhotoRequest(2, 44)]
    finally:
        loader.gate.set()
        provider.shutdown()
        controller.shutdown()


def _wait_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> None:
    deadline = monotonic() + timeout_ms / 1000
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    APPLICATION.processEvents()
    assert predicate(), "Timed out waiting for Photo pixmap"
