"""Qt-thread adapter for lazy, bounded Photo image loading."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.models.photos import (
    FULL_RESOLUTION_REQUEST_ID,
    PhotoImage,
    PhotoRequest,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class PhotoLoader(Protocol):
    """Minimal Application seam required by the asynchronous adapter."""

    def load_photo(self, request: PhotoRequest) -> PhotoImage | None: ...


@dataclass(frozen=True, slots=True)
class PhotoLoadFailure:
    """Serializable failure detail for one asynchronous Photo request."""

    photo_id: int
    format_id: int | None
    message: str
    error_type: str


@dataclass(frozen=True, slots=True)
class PhotoUnavailable:
    """Identity of one automatic or exact Photo request with no usable pixels."""

    photo_id: int
    format_id: int | None


@dataclass(frozen=True, slots=True)
class _RequestKey:
    generation: int
    photo_id: int
    target_px: int
    format_id: int | None


class _PhotoWorkerSignals(QObject):
    succeeded = Signal(int, object, object)
    failed = Signal(int, object, object)
    finished = Signal(int, object)


class _PhotoWork(QRunnable):
    def __init__(
        self,
        token: int,
        key: _RequestKey,
        work: Callable[[], PhotoImage | None],
    ) -> None:
        super().__init__()
        self.token = token
        self.key = key
        self.work = work
        self.signals = _PhotoWorkerSignals()
        # Python retains each runnable until its queued ``finished`` signal is
        # handled. Qt auto-deletion could otherwise leave a dead Shiboken wrapper
        # in the retention map during device invalidation or shutdown.
        self.setAutoDelete(False)

    def run(self) -> None:
        try:
            result = self.work()
        except Exception as error:
            self.signals.failed.emit(self.token, self.key, error)
        else:
            self.signals.succeeded.emit(self.token, self.key, result)
        finally:
            self.signals.finished.emit(self.token, self.key)


class PhotoController(QObject):
    """Deduplicate Photo requests and retain decoded RGB in a byte-bounded LRU."""

    photoReady = Signal(object)
    photoUnavailable = Signal(object)
    photoFailed = Signal(object)
    generationChanged = Signal(int)
    capacityAvailable = Signal()

    def __init__(
        self,
        loader: PhotoLoader,
        parent: QObject | None = None,
        *,
        cache_byte_limit: int = 64 * 1024 * 1024,
        max_pending: int = 32,
    ) -> None:
        super().__init__(parent)
        if cache_byte_limit <= 0:
            raise ValueError("Photo cache size must be positive")
        if max_pending <= 0:
            raise ValueError("Photo pending-request limit must be positive")
        self._loader = loader
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(2)
        self._cache_byte_limit = cache_byte_limit
        self._max_pending = max_pending
        self._cache_bytes = 0
        self._images: OrderedDict[str, PhotoImage] = OrderedDict()
        self._request_cache_keys: dict[_RequestKey, str] = {}
        self._pending: set[_RequestKey] = set()
        self._unavailable: set[_RequestKey] = set()
        self._retryable_pending: set[_RequestKey] = set()
        self._deferred_retries: dict[_RequestKey, PhotoRequest] = {}
        self._work_items: dict[int, _PhotoWork] = {}
        self._generation = 0
        self._next_token = 0
        self._capacity_blocked = False
        self._closed = False

    @property
    def cached_byte_count(self) -> int:
        return self._cache_bytes

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def request(
        self,
        photo_id: int,
        target_px: int,
        *,
        format_id: int | None = None,
    ) -> PhotoImage | None:
        """Return cached pixels now or queue one non-blocking decode.

        An omitted ``format_id`` asks the loader to choose a suitable display
        representation. Supplying one requests that exact retained format.
        """

        if (
            self._closed
            or photo_id <= 0
            or target_px <= 0
            or (format_id is not None and format_id < 0)
        ):
            return None
        # An exact iTHMB format has the same pixels at every display size. Automatic
        # and full-resolution requests are size-specific because the latter is
        # downsampled before entering the bounded RGB cache.
        cache_target = (
            target_px if format_id in (None, FULL_RESOLUTION_REQUEST_ID) else 0
        )
        key = _RequestKey(self._generation, photo_id, cache_target, format_id)
        cache_key = self._request_cache_keys.get(key)
        if cache_key is not None:
            image = self._images.get(cache_key)
            if image is not None:
                self._images.move_to_end(cache_key)
                return image
            self._request_cache_keys.pop(key, None)
        if key in self._pending:
            if key in self._retryable_pending:
                self._deferred_retries[key] = PhotoRequest(
                    photo_id=photo_id,
                    target_px=target_px,
                    format_id=format_id,
                )
            return None
        if key in self._unavailable:
            return None
        if len(self._pending) >= self._max_pending:
            self._capacity_blocked = True
            return None

        self._next_token += 1
        token = self._next_token
        request = PhotoRequest(
            photo_id=photo_id,
            target_px=target_px,
            format_id=format_id,
        )
        item = _PhotoWork(token, key, lambda: self._loader.load_photo(request))
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
        self._thread_pool.start(item)
        return None

    @Slot(object)
    def active_ipod_changed(self, _active_ipod: object) -> None:
        self.invalidate()

    def invalidate(self) -> None:
        """Drop all state when the Active iPod connection generation changes."""

        if self._closed:
            return
        self._generation += 1
        self._cancel_queued_work()
        self._images.clear()
        self._request_cache_keys.clear()
        self._pending.clear()
        self._unavailable.clear()
        self._retryable_pending.clear()
        self._deferred_retries.clear()
        self._cache_bytes = 0
        self._capacity_blocked = False
        self.generationChanged.emit(self._generation)

    def retry(self, photo_id: int, *, format_id: int | None = None) -> None:
        """Allow a user-requested retry after an unavailable exact format."""

        if self._closed or photo_id <= 0 or (format_id is not None and format_id < 0):
            return
        retryable = {
            key
            for key in self._unavailable
            if key.generation == self._generation
            and key.photo_id == photo_id
            and key.format_id == format_id
        }
        self._unavailable.difference_update(retryable)
        self._retryable_pending.update(retryable & self._pending)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        self._cancel_queued_work()
        self._thread_pool.waitForDone()
        self._work_items.clear()
        self._pending.clear()
        self._images.clear()
        self._request_cache_keys.clear()
        self._unavailable.clear()
        self._retryable_pending.clear()
        self._deferred_retries.clear()
        self._cache_bytes = 0
        self._capacity_blocked = False

    @Slot(int, object, object)
    def _work_succeeded(self, token: int, key: object, result: object) -> None:
        if not isinstance(key, _RequestKey):
            return
        if self._closed or key.generation != self._generation:
            return
        if not isinstance(result, PhotoImage) or not _matches_request(key, result):
            self._unavailable.add(key)
            self.photoUnavailable.emit(PhotoUnavailable(key.photo_id, key.format_id))
            return
        self._store(key, result)
        self.photoReady.emit(result)

    @Slot(int, object, object)
    def _work_failed(self, token: int, key: object, error: object) -> None:
        if not isinstance(key, _RequestKey):
            return
        if self._closed or key.generation != self._generation:
            return
        self._unavailable.add(key)
        self.photoUnavailable.emit(PhotoUnavailable(key.photo_id, key.format_id))
        self.photoFailed.emit(
            PhotoLoadFailure(
                photo_id=key.photo_id,
                format_id=key.format_id,
                message=str(error),
                error_type=type(error).__name__,
            )
        )

    @Slot(int, object)
    def _work_finished(self, token: int, key: object) -> None:
        self._work_items.pop(token, None)
        was_pending = isinstance(key, _RequestKey) and key in self._pending
        deferred: PhotoRequest | None = None
        if isinstance(key, _RequestKey):
            self._pending.discard(key)
            self._retryable_pending.discard(key)
            deferred = self._deferred_retries.pop(key, None)
        if deferred is not None and not self._closed:
            self.request(
                deferred.photo_id,
                deferred.target_px,
                format_id=deferred.format_id,
            )
        if was_pending and self._capacity_blocked and not self._closed:
            self._capacity_blocked = False
            self.capacityAvailable.emit()

    def _store(self, request_key: _RequestKey, image: PhotoImage) -> None:
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
        for token, item in tuple(self._work_items.items()):
            if self._thread_pool.tryTake(item):
                self._work_items.pop(token, None)
                self._pending.discard(item.key)


def _matches_request(key: _RequestKey, image: PhotoImage) -> bool:
    return image.photo_id == key.photo_id and (
        key.format_id is None or image.format_id == key.format_id
    )


__all__ = [
    "PhotoController",
    "PhotoLoadFailure",
    "PhotoLoader",
    "PhotoUnavailable",
]
