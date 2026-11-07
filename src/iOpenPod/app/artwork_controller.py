"""Qt-thread adapter for lazy, bounded artwork loading."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from weakref import ref

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.draft_artwork import DraftArtworkLoader
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest

if TYPE_CHECKING:
    from collections.abc import Callable

    from iPodDB.library import ArtworkAsset, TimedArtworkAsset


class ArtworkLoader(Protocol):
    """Minimal Application seam required by the asynchronous adapter."""

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None: ...


@dataclass(frozen=True, slots=True)
class ArtworkLoadFailure:
    artwork_id: int
    message: str
    error_type: str


@dataclass(frozen=True, slots=True)
class _RequestKey:
    generation: int
    artwork_id: int
    target_px: int
    display_time_ms: int | None


class _ArtworkWorkerSignals(QObject):
    succeeded = Signal(int, object, object)
    failed = Signal(int, object, object)
    finished = Signal(int, object)


class _ArtworkWork:
    def __init__(
        self,
        token: int,
        key: _RequestKey,
        work: Callable[[], ArtworkImage | None],
    ) -> None:
        self.token = token
        self.key = key
        self.work = work
        self.signals = _ArtworkWorkerSignals()

    def run(self) -> None:
        try:
            result = self.work()
        except Exception as error:
            self.signals.failed.emit(self.token, self.key, error)
        else:
            self.signals.succeeded.emit(self.token, self.key, result)
        finally:
            self.signals.finished.emit(self.token, self.key)


class ArtworkController(QObject):
    """Deduplicate visible requests and retain decoded RGB in a byte-bounded LRU."""

    artworkReady = Signal(object)
    artworkUnavailable = Signal(object)
    artworkFailed = Signal(object)
    generationChanged = Signal(int)

    def __init__(
        self,
        loader: ArtworkLoader,
        parent: QObject | None = None,
        *,
        cache_byte_limit: int = 64 * 1024 * 1024,
        max_pending: int = 32,
        display_times: Callable[[int], tuple[int, ...]] | None = None,
    ) -> None:
        super().__init__(parent)
        if cache_byte_limit <= 0:
            raise ValueError("Artwork cache size must be positive")
        if max_pending <= 0:
            raise ValueError("Artwork pending-request limit must be positive")
        self._loader = DraftArtworkLoader(loader, display_times)
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(2)
        self._cache_byte_limit = cache_byte_limit
        self._max_pending = max_pending
        self._cache_bytes = 0
        self._images: OrderedDict[str, ArtworkImage] = OrderedDict()
        self._request_cache_keys: dict[_RequestKey, str] = {}
        self._pending: set[_RequestKey] = set()
        self._unavailable: set[_RequestKey] = set()
        self._work_items: dict[int, _ArtworkWork] = {}
        self._generation = 0
        self._next_token = 0
        self._closed = False

    @property
    def cached_byte_count(self) -> int:
        return self._cache_bytes

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def set_draft_assets(
        self, assets: tuple[ArtworkAsset | TimedArtworkAsset, ...]
    ) -> None:
        """Publish draft image sources before their Track identities reach views."""

        if not self._closed and self._loader.replace_assets(assets):
            self.invalidate()

    def display_times(self, artwork_id: int) -> tuple[int, ...]:
        """List retained time groups without loading any image pixels."""

        if self._closed or artwork_id == 0:
            return ()
        return self._loader.display_times(artwork_id)

    def request(
        self,
        artwork_id: int,
        target_px: int,
        *,
        display_time_ms: int | None = None,
    ) -> ArtworkImage | None:
        """Return cached pixels now or queue one non-blocking decode."""

        if self._closed or artwork_id == 0 or target_px <= 0:
            return None
        request = ArtworkRequest(
            artwork_id=artwork_id,
            target_px=target_px,
            display_time_ms=display_time_ms,
        )
        key = _RequestKey(self._generation, artwork_id, target_px, display_time_ms)
        cache_key = self._request_cache_keys.get(key)
        if cache_key is not None:
            image = self._images.get(cache_key)
            if image is not None:
                self._images.move_to_end(cache_key)
                return image
            self._request_cache_keys.pop(key, None)
        if key in self._pending or key in self._unavailable:
            return None
        if len(self._pending) >= self._max_pending:
            return None

        self._next_token += 1
        token = self._next_token
        item = _ArtworkWork(
            token,
            key,
            lambda: self._loader.load_artwork(request),
        )
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
        # The callable overload avoids PySide retaining deleted QRunnable wrappers
        # on the pool when short jobs finish during submission. Keep only a weak
        # reference in the callable so clearing queued work releases its payload.
        work_ref = ref(item)

        def run() -> None:
            if (work := work_ref()) is not None:
                work.run()

        self._thread_pool.start(run)
        return None

    @Slot(object)
    def active_ipod_changed(self, active_ipod: object) -> None:
        if active_ipod is None:
            self._loader.replace_assets(())
        self.invalidate()

    def invalidate(self) -> None:
        """Drop stale work and pixels when device or draft artwork sources change."""

        if self._closed:
            return
        self._generation += 1
        self._cancel_queued_work()
        self._images.clear()
        self._request_cache_keys.clear()
        self._pending.clear()
        self._unavailable.clear()
        self._cache_bytes = 0
        self.generationChanged.emit(self._generation)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        self._cancel_queued_work()
        self._loader.replace_assets(())
        self._thread_pool.waitForDone()
        self._work_items.clear()
        self._pending.clear()
        self._images.clear()
        self._request_cache_keys.clear()
        self._unavailable.clear()
        self._cache_bytes = 0

    @Slot(int, object, object)
    def _work_succeeded(self, token: int, key: object, result: object) -> None:
        if not isinstance(key, _RequestKey):
            return
        if self._closed or key.generation != self._generation:
            return
        if not isinstance(result, ArtworkImage):
            self._unavailable.add(key)
            self.artworkUnavailable.emit(key.artwork_id)
            return
        self._store(key, result)
        self.artworkReady.emit(result)

    @Slot(int, object, object)
    def _work_failed(self, token: int, key: object, error: object) -> None:
        if not isinstance(key, _RequestKey):
            return
        if self._closed or key.generation != self._generation:
            return
        self._unavailable.add(key)
        self.artworkUnavailable.emit(key.artwork_id)
        self.artworkFailed.emit(
            ArtworkLoadFailure(
                artwork_id=key.artwork_id,
                message=str(error),
                error_type=type(error).__name__,
            )
        )

    @Slot(int, object)
    def _work_finished(self, token: int, key: object) -> None:
        self._work_items.pop(token, None)
        if isinstance(key, _RequestKey):
            self._pending.discard(key)

    def _store(self, request_key: _RequestKey, image: ArtworkImage) -> None:
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

    def _cancel_queued_work(self) -> None:
        # Never dereference retained wrappers here: completed native jobs may
        # already be deleted while their queued completion signal is pending.
        self._thread_pool.clear()
        self._work_items.clear()


__all__ = ["ArtworkController", "ArtworkLoadFailure", "ArtworkLoader"]
