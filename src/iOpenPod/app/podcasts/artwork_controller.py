"""Qt-thread adapter for bounded remote Podcast artwork loading."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.podcasts.models import PodcastArtworkImage, PodcastArtworkRequest

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.podcasts.feed_client import (
        PodcastArtworkLoader,
        PodcastFeedClient,
    )


@dataclass(frozen=True, slots=True)
class PodcastArtworkFailure:
    source_url: str
    message: str
    error_type: str


@dataclass(frozen=True, slots=True)
class _RequestKey:
    source_url: str
    target_px: int
    from_feed: bool = False


class _ArtworkSignals(QObject):
    succeeded = Signal(int, object, object)
    failed = Signal(int, object, object)
    finished = Signal(int, object)


class _ArtworkWork(QRunnable):
    def __init__(
        self,
        token: int,
        key: _RequestKey,
        work: Callable[[], PodcastArtworkImage | None],
    ) -> None:
        super().__init__()
        self.token = token
        self.key = key
        self.work = work
        self.signals = _ArtworkSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.work()
        except Exception as error:
            self.signals.failed.emit(self.token, self.key, error)
        else:
            self.signals.succeeded.emit(self.token, self.key, result)
        finally:
            self.signals.finished.emit(self.token, self.key)


class PodcastArtworkController(QObject):
    """Deduplicate visible cover requests and retain decoded pixels in an LRU."""

    artworkReady = Signal(object)
    artworkUnavailable = Signal(str)
    artworkFailed = Signal(object)
    feedArtworkChanged = Signal(str)

    def __init__(
        self,
        loader: PodcastArtworkLoader,
        parent: QObject | None = None,
        *,
        cache_byte_limit: int = 32 * 1024 * 1024,
        max_pending: int = 24,
        feed_client: PodcastFeedClient | None = None,
    ) -> None:
        super().__init__(parent)
        if cache_byte_limit <= 0 or max_pending <= 0:
            raise ValueError("Podcast artwork cache limits must be positive")
        self._loader = loader
        self._feed_client = feed_client
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(3)
        self._cache_byte_limit = cache_byte_limit
        self._max_pending = max_pending
        self._cache_bytes = 0
        self._images: OrderedDict[str, PodcastArtworkImage] = OrderedDict()
        self._request_cache_keys: dict[_RequestKey, str] = {}
        self._pending: set[_RequestKey] = set()
        self._unavailable: set[_RequestKey] = set()
        self._work_items: dict[int, _ArtworkWork] = {}
        self._next_token = 0
        self._closed = False

    @property
    def cached_byte_count(self) -> int:
        return self._cache_bytes

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def request(self, source_url: str, target_px: int) -> PodcastArtworkImage | None:
        """Return retained pixels now or queue one non-blocking download."""
        return self._request(source_url, target_px, from_feed=False)

    def request_feed(self, feed_url: str, target_px: int) -> PodcastArtworkImage | None:
        """Resolve a visible directory result's publisher cover off the GUI thread.

        Discovery never subscribes, saves feed metadata, or uses Apple artwork.
        The normal pending limit and decoded-pixel budget also cover this work.
        """
        return (
            self._request(feed_url, target_px, from_feed=True)
            if self._feed_client is not None
            else None
        )

    def _request(
        self, source_url: str, target_px: int, *, from_feed: bool
    ) -> PodcastArtworkImage | None:

        normalized = source_url.strip()
        if self._closed or not normalized or target_px <= 0:
            return None
        key = _RequestKey(normalized, target_px, from_feed)
        cache_key = self._request_cache_keys.get(key)
        if cache_key is not None:
            image = self._images.get(cache_key)
            if image is not None:
                self._images.move_to_end(cache_key)
                return image
            self._request_cache_keys.pop(key, None)
        if (
            key in self._pending
            or key in self._unavailable
            or len(self._pending) >= self._max_pending
        ):
            return None

        self._next_token += 1
        token = self._next_token

        def load() -> PodcastArtworkImage | None:
            url = (
                self._feed_client.fetch(normalized).artwork_url
                if from_feed and self._feed_client is not None
                else normalized
            )
            return (
                self._loader.load_artwork(PodcastArtworkRequest(url, target_px))
                if url
                else None
            )

        item = _ArtworkWork(token, key, load)
        item.signals.succeeded.connect(
            self._work_succeeded,
            Qt.ConnectionType.QueuedConnection,
        )
        item.signals.failed.connect(
            self._work_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        item.signals.finished.connect(
            self._work_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._pending.add(key)
        self._work_items[token] = item
        self._pool.start(item)
        return None

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pool.clear()
        self._pool.waitForDone()
        self._work_items.clear()
        self._pending.clear()
        self._images.clear()
        self._request_cache_keys.clear()
        self._unavailable.clear()
        self._cache_bytes = 0

    @Slot(int, object, object)
    def _work_succeeded(self, _token: int, key: object, result: object) -> None:
        if self._closed or not isinstance(key, _RequestKey):
            return
        if not isinstance(result, PodcastArtworkImage):
            self._unavailable.add(key)
            self.artworkUnavailable.emit(key.source_url)
            return
        self._store(key, result)
        self.artworkReady.emit(result)
        if key.from_feed:
            self.feedArtworkChanged.emit(key.source_url)

    @Slot(int, object, object)
    def _work_failed(self, _token: int, key: object, error: object) -> None:
        if self._closed or not isinstance(key, _RequestKey):
            return
        self._unavailable.add(key)
        self.artworkUnavailable.emit(key.source_url)
        self.artworkFailed.emit(
            PodcastArtworkFailure(
                source_url=key.source_url,
                message=str(error),
                error_type=type(error).__name__,
            )
        )

    @Slot(int, object)
    def _work_finished(self, token: int, key: object) -> None:
        self._work_items.pop(token, None)
        if isinstance(key, _RequestKey):
            self._pending.discard(key)

    def _store(self, request_key: _RequestKey, image: PodcastArtworkImage) -> None:
        if image.byte_count > self._cache_byte_limit:
            return
        retained = self._images.pop(image.cache_key, None)
        if retained is not None:
            self._cache_bytes -= retained.byte_count
        self._images[image.cache_key] = image
        self._request_cache_keys[request_key] = image.cache_key
        self._cache_bytes += image.byte_count

        evicted: set[str] = set()
        while self._cache_bytes > self._cache_byte_limit:
            cache_key, discarded = self._images.popitem(last=False)
            evicted.add(cache_key)
            self._cache_bytes -= discarded.byte_count
        if evicted:
            self._request_cache_keys = {
                key: cache_key
                for key, cache_key in self._request_cache_keys.items()
                if cache_key not in evicted
            }


__all__ = ["PodcastArtworkController", "PodcastArtworkFailure"]
