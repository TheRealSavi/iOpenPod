"""Draft artwork previews retain source meaning and reject stale generations."""

from collections.abc import Callable
from threading import Event
from time import monotonic

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.draft_artwork import DraftArtworkLoader
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iPodDB.library import (
    ArtworkAsset,
    ArtworkGroupReference,
    ArtworkPixels,
    TimedArtworkAsset,
    TimedArtworkFrame,
)

RED = ArtworkPixels(4, 2, b"\xff\x00\x00" * 8)
BLUE = ArtworkPixels(2, 4, b"\x00\x00\xff" * 8)


def _application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


APPLICATION = _application()


class _Source:
    def __init__(self, *, gate: Event | None = None) -> None:
        self.requests: list[ArtworkRequest] = []
        self.started = Event()
        self.gate = gate
        self.unavailable = False

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        assert request.artwork_id > 0, "Draft identities must not reach device reads"
        self.requests.append(request)
        self.started.set()
        if self.gate is not None:
            assert self.gate.wait(3)
        if self.unavailable:
            return None
        return ArtworkImage(
            cache_key=f"source/{request.artwork_id}/{request.display_time_ms}",
            artwork_id=request.artwork_id,
            format_id=1061,
            width=RED.width,
            height=RED.height,
            rgb888=RED.rgb888,
            display_time_ms=request.display_time_ms,
        )


def _wait_until(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 3
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    APPLICATION.processEvents()
    assert predicate(), "Timed out waiting for draft artwork"


def test_draft_loader_resizes_owned_pixels_and_selects_only_exact_groups() -> None:
    source = _Source()
    loader = DraftArtworkLoader(source, lambda _identity: (0, 5000))
    assert loader.replace_assets(
        (
            TimedArtworkAsset(
                -1,
                (TimedArtworkFrame(2000, BLUE), TimedArtworkFrame(0, RED)),
            ),
        )
    )
    assert loader.display_times(-1) == (0, 2000)
    assert loader.display_times(41) == (0, 5000)
    assert loader.display_times(-2) == ()
    assert loader.display_times(0) == ()
    default = loader.load_artwork(ArtworkRequest(-1, 2))
    exact_zero = loader.load_artwork(ArtworkRequest(-1, 2, display_time_ms=0))
    later = loader.load_artwork(ArtworkRequest(-1, 2, display_time_ms=2000))
    assert default is not None and exact_zero is not None and later is not None
    assert (default.width, default.height, default.rgb888) == (2, 1, b"\xff\0\0" * 2)
    assert (later.width, later.height, later.rgb888) == (1, 2, b"\0\0\xff" * 2)
    assert default.cache_key != exact_zero.cache_key
    assert default.display_time_ms is None and exact_zero.display_time_ms == 0
    assert later.artwork_id == -1 and later.display_time_ms == 2000
    assert later.format_id == 1
    assert loader.load_artwork(ArtworkRequest(-1, 2, display_time_ms=1000)) is None
    assert loader.load_artwork(ArtworkRequest(-2, 2)) is None
    assert source.requests == []


def test_retained_groups_read_the_source_time_and_rebind_to_draft_request() -> None:
    source = _Source()
    loader = DraftArtworkLoader(source)
    loader.replace_assets(
        (
            TimedArtworkAsset(
                -1,
                (
                    TimedArtworkFrame(0, ArtworkGroupReference(41, 0)),
                    TimedArtworkFrame(2000, ArtworkGroupReference(41, 5000)),
                    TimedArtworkFrame(
                        0xFFFFFFFF, ArtworkGroupReference(41, 0xFFFFFFFF)
                    ),
                ),
            ),
        )
    )
    assert loader.display_times(-1) == (0, 2000, 0xFFFFFFFF)
    assert source.requests == []
    image = loader.load_artwork(ArtworkRequest(-1, 44, display_time_ms=2000))
    assert source.requests == [ArtworkRequest(41, 44, display_time_ms=5000)]
    assert (
        image is not None and image.artwork_id == -1 and image.display_time_ms == 2000
    )
    assert image.rgb888 == RED.rgb888 and image.format_id == 1061
    retained = loader.load_artwork(ArtworkRequest(41, 44, display_time_ms=5000))
    assert retained is not None and retained.artwork_id == 41
    assert retained.display_time_ms == 5000 and retained.cache_key != image.cache_key
    source.unavailable = True
    assert loader.load_artwork(ArtworkRequest(-1, 44, display_time_ms=2000)) is None
    assert source.requests[-1] == ArtworkRequest(41, 44, display_time_ms=5000)


def test_static_drafts_have_only_zero_time_and_cache_keys_isolate_snapshots() -> None:
    source = _Source()
    first, second = DraftArtworkLoader(source), DraftArtworkLoader(source)
    asset = ArtworkAsset(-1, RED)
    assert first.replace_assets((asset,))
    assert not first.replace_assets((ArtworkAsset(-1, RED),))
    assert first.display_times(-1) == (0,)
    assert first.load_artwork(ArtworkRequest(-1, 2, display_time_ms=1)) is None
    old = first.load_artwork(ArtworkRequest(-1, 2))
    assert first.replace_assets(())
    assert first.display_times(-1) == ()
    assert first.load_artwork(ArtworkRequest(-1, 2)) is None
    assert first.replace_assets((asset,))
    fresh = first.load_artwork(ArtworkRequest(-1, 2))
    second.replace_assets((asset,))
    independent = second.load_artwork(ArtworkRequest(-1, 2))
    assert old is not None and fresh is not None and independent is not None
    assert len({old.cache_key, fresh.cache_key, independent.cache_key}) == 3


@pytest.mark.parametrize(
    "assets",
    [(ArtworkAsset(0, RED),), (ArtworkAsset(1, RED),), (ArtworkAsset(-1, RED),) * 2],
)
def test_draft_snapshot_rejects_ambiguous_or_source_identities(
    assets: tuple[ArtworkAsset, ...],
) -> None:
    loader = DraftArtworkLoader(_Source())
    with pytest.raises(ValueError, match="unique negative"):
        loader.replace_assets(assets)


def test_unchanged_assets_preserve_pending_requests_and_cached_images() -> None:
    controller = ArtworkController(_Source())
    generations: list[int] = []
    ready: list[ArtworkImage] = []
    controller.generationChanged.connect(generations.append)
    controller.artworkReady.connect(ready.append)
    asset = ArtworkAsset(-1, RED)
    try:
        controller.set_draft_assets((asset,))
        assert controller.request(-1, 2) is None
        controller.set_draft_assets((ArtworkAsset(-1, RED),))
        _wait_until(lambda: controller.pending_count == 0)
        assert len(ready) == 1 and generations == [1]
        controller.set_draft_assets((asset,))
        assert controller.request(-1, 2) is ready[0]
        assert generations == [1]
        controller.set_draft_assets(())
        assert controller.display_times(-1) == ()
        assert controller.cached_byte_count == 0
        controller.set_draft_assets((ArtworkAsset(-1, BLUE),))
        assert controller.request(-1, 2) is None
        _wait_until(lambda: controller.pending_count == 0)
        assert ready[-1].rgb888 == b"\0\0\xff" * 2
        assert ready[-1].cache_key != ready[0].cache_key
    finally:
        controller.shutdown()


@pytest.mark.parametrize("disconnect", (False, True))
def test_old_draft_workers_cannot_publish_after_reset_or_disconnect(
    disconnect: bool,
) -> None:
    gate = Event()
    source = _Source(gate=gate)
    controller = ArtworkController(source)
    ready: list[ArtworkImage] = []
    unavailable: list[int] = []
    controller.artworkReady.connect(ready.append)
    controller.artworkUnavailable.connect(unavailable.append)
    try:
        controller.set_draft_assets(
            (
                TimedArtworkAsset(
                    -1, (TimedArtworkFrame(0, ArtworkGroupReference(41, 0)),)
                ),
            )
        )
        assert controller.request(-1, 2, display_time_ms=0) is None
        assert source.started.wait(1)
        if disconnect:
            controller.active_ipod_changed(None)
        else:
            controller.set_draft_assets(())
        assert controller.pending_count == 0 and controller.display_times(-1) == ()
        # The next draft can reuse -1 while the previous source read still runs.
        controller.set_draft_assets((ArtworkAsset(-1, BLUE),))
        assert controller.request(-1, 2, display_time_ms=0) is None
        _wait_until(lambda: bool(ready))
        assert ready[0].rgb888 == b"\0\0\xff" * 2
        gate.set()
        pool = controller.findChild(QThreadPool)
        assert pool is not None and pool.waitForDone(1000)
        APPLICATION.processEvents()
        assert len(ready) == 1 and unavailable == []
        assert controller.request(-1, 2, display_time_ms=0) is ready[0]
        assert controller.pending_count == 0
    finally:
        gate.set()
        controller.shutdown()


def test_presentation_models_accept_signed_nonzero_identities_only() -> None:
    assert ArtworkRequest(-1, 2).artwork_id == -1
    with pytest.raises(ValueError, match="nonzero"):
        ArtworkRequest(0, 2)
    with pytest.raises(ValueError, match="nonzero"):
        ArtworkImage("absent", 0, 1, 1, 1, b"\0\0\0")
    # iPodDB's retained reference contract remains positive-only.
    with pytest.raises(ValueError, match="retained image ID"):
        ArtworkGroupReference(-1, 0)
