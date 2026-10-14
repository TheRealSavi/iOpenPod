"""Completed image requests must release their loaders and native jobs."""

import gc
import weakref
from time import monotonic

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iOpenPod.app.artwork_controller import ArtworkController
from iOpenPod.app.photo_controller import PhotoController
from iOpenPod.app.podcasts.artwork_controller import PodcastArtworkController


class _Loader:
    def load_artwork(self, request: object) -> None:
        return None

    def load_photo(self, request: object) -> None:
        return None


@pytest.mark.parametrize("kind", ("artwork", "photo", "podcast"))
def test_completed_image_jobs_are_released_while_the_controller_stays_open(
    kind: str,
) -> None:
    application = QApplication.instance() or QApplication([])
    loader = _Loader()
    references: list[weakref.ReferenceType[object]] = []
    controller: ArtworkController | PhotoController | PodcastArtworkController
    if kind == "artwork":
        controller = ArtworkController(loader)
    elif kind == "photo":
        controller = PhotoController(loader)
    else:
        controller = PodcastArtworkController(loader)
    try:
        for identity in range(1, 9):
            if isinstance(controller, PodcastArtworkController):
                controller.request(f"https://example.test/{identity}.png", 64)
            else:
                controller.request(identity, 64)
            references.extend(
                weakref.ref(job)
                for job in controller._work_items.values()  # pyright: ignore[reportPrivateUsage]
            )
            deadline = monotonic() + 3
            while controller.pending_count and monotonic() < deadline:
                application.processEvents()
                QTest.qWait(10)
            assert controller.pending_count == 0
        deadline = monotonic() + 3
        while (
            any(reference() is not None for reference in references)
            and monotonic() < deadline
        ):
            application.processEvents()
            QTest.qWait(10)
            gc.collect()
        assert all(reference() is None for reference in references)
    finally:
        controller.shutdown()
