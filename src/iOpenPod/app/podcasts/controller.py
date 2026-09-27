"""Qt adapter for asynchronous Podcast network and device operations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.display_text import source_text
from iOpenPod.app.podcasts.catalog import (
    mark_episode_selection_listened,
    merge_fetched_subscription,
    reconcile_device_podcasts,
    remove_subscription,
)
from iOpenPod.app.podcasts.feed_client import (
    ApplePodcastDirectoryClient,
    FeedparserPodcastClient,
    PodcastDirectoryClient,
    PodcastFeedClient,
    PodcastFeedError,
)
from iOpenPod.app.podcasts.identity import normalize_feed_url
from iOpenPod.app.podcasts.models import (
    PodcastIssue,
    PodcastIssueCode,
    PodcastSearchResult,
    PodcastSnapshot,
    PodcastSyncSettings,
    SubscriptionSource,
)
from iOpenPod.app.podcasts.store import LoadedPodcastState, PodcastStateRevision
from iOpenPod.app.podcasts.sync import PodcastSyncRequest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator
    from iPodDB.library import Track


class PodcastOperation(StrEnum):
    LOAD = "load"
    SEARCH = "search"
    SUBSCRIBE = "subscribe"
    REFRESH = "refresh"
    UNSUBSCRIBE = "unsubscribe"
    LISTENED = "listened"
    SETTINGS = "settings"
    SYNC = "sync"


@dataclass(frozen=True, slots=True)
class PodcastOperationFailure:
    operation: PodcastOperation
    message: str


@dataclass(frozen=True, slots=True)
class _StateResult:
    value: LoadedPodcastState


@dataclass(frozen=True, slots=True)
class _SearchResult:
    value: tuple[PodcastSearchResult, ...]


class _Signals(QObject):
    completed = Signal(int, object, object, str)


class _Work(QRunnable):
    def __init__(
        self,
        token: int,
        operation: PodcastOperation,
        action: Callable[[], _StateResult | _SearchResult],
    ) -> None:
        super().__init__()
        self.token = token
        self.operation = operation
        self.action = action
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.action()
        except Exception as error:
            self.signals.completed.emit(
                self.token,
                self.operation,
                None,
                str(error) or type(error).__name__,
            )
        else:
            self.signals.completed.emit(self.token, self.operation, result, "")


class PodcastController(QObject):
    """Publish one Podcast snapshot while hiding I/O and stale-work handling."""

    changed = Signal()
    busyChanged = Signal(bool)
    operationFailed = Signal(object)
    searchFinished = Signal(object)
    syncRequested = Signal(object)

    def __init__(
        self,
        coordinator: DeviceCoordinator,
        devices: DeviceController,
        parent: QObject | None = None,
        *,
        feeds: PodcastFeedClient | None = None,
        directory: PodcastDirectoryClient | None = None,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._devices = devices
        self._feeds = feeds or FeedparserPodcastClient()
        self._directory = directory or ApplePodcastDirectoryClient()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._source: ActiveIPod | None = None
        self._loaded = LoadedPodcastState(PodcastSnapshot(), PodcastStateRevision())
        self._token = 0
        self._jobs: dict[int, _Work] = {}
        self._device_reservation_token: int | None = None
        self._pending_load_source: ActiveIPod | None = None
        self._busy = False
        self._closed = False
        devices.activeIPodChanged.connect(self.active_ipod_changed)
        devices.deviceWritesAllowedChanged.connect(self._device_availability_changed)

    @property
    def snapshot(self) -> PodcastSnapshot:
        return self._loaded.snapshot

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def can_edit(self) -> bool:
        return (
            not self._closed
            and not self._busy
            and self._source is not None
            and self.snapshot.writable
            and self._devices.device_writes_allowed
        )

    @property
    def can_sync(self) -> bool:
        return (
            self.can_edit
            and self._source is not None
            and self._source.profile.capabilities.audio.supports_podcasts
        )

    def sync_request(self, subscription_id: str | None = None) -> PodcastSyncRequest:
        """Capture immutable Podcast intent for the shared Sync worker."""
        return PodcastSyncRequest(
            self.snapshot,
            subscription_ids=(subscription_id,)
            if subscription_id is not None
            else None,
        )

    @Slot()
    def reload(self) -> None:
        """Refresh document revisions after another workflow updates Podcast state."""
        if self._closed or self._source is None:
            return
        self._pending_load_source = self._source
        self._start_pending_load()

    def sync(self, subscription_id: str | None = None) -> None:
        if not self.can_sync:
            return
        if (
            subscription_id is not None
            and self.snapshot.subscription(subscription_id) is None
        ):
            self._fail(
                PodcastOperation.SYNC,
                "The Podcast Subscription is no longer available.",
            )
            return
        self.syncRequested.emit(self.sync_request(subscription_id))

    def add_episodes(self, identities: Iterable[tuple[str, str]]) -> None:
        """Explicit additions bypass automatic episode selection and retention."""
        self._request_episode_sync(identities, remove=False)

    def remove_episodes(self, identities: Iterable[tuple[str, str]]) -> None:
        self._request_episode_sync(identities, remove=True)

    def _request_episode_sync(
        self, identities: Iterable[tuple[str, str]], *, remove: bool
    ) -> None:
        if not self.can_sync:
            return
        selected = tuple(dict.fromkeys(identities))
        if not selected:
            return
        self.syncRequested.emit(
            PodcastSyncRequest(
                self.snapshot,
                additions=() if remove else selected,
                removals=selected if remove else (),
                automatic=False,
            )
        )

    def set_sync_settings(
        self, subscription_id: str, settings: PodcastSyncSettings
    ) -> None:
        source = self._require_editable_source()
        if source is None:
            return
        loaded = self._loaded
        if loaded.snapshot.subscription(subscription_id) is None:
            self._fail(
                PodcastOperation.SETTINGS,
                "The Podcast Subscription is no longer available.",
            )
            return

        def action() -> _StateResult:
            snapshot = replace(
                loaded.snapshot,
                subscriptions=tuple(
                    replace(item, sync_settings=settings)
                    if item.subscription_id == subscription_id
                    else item
                    for item in loaded.snapshot.subscriptions
                ),
            )
            return _StateResult(
                self._coordinator.save_podcast_state(
                    source, replace(loaded, snapshot=snapshot)
                )
            )

        self._begin_device_write(PodcastOperation.SETTINGS, action)

    def track_for_episode(self, track_id: int | None) -> Track | None:
        source = self._source
        if source is None or track_id is None:
            return None
        return next(
            (track for track in source.library.tracks if track.track_id == track_id),
            None,
        )

    @Slot(object)
    def active_ipod_changed(self, value: object) -> None:
        from iOpenPod.app.models.device import ActiveIPod

        self._invalidate()
        self._source = value if isinstance(value, ActiveIPod) else None
        self._pending_load_source = None
        self._loaded = LoadedPodcastState(PodcastSnapshot(), PodcastStateRevision())
        self.changed.emit()
        source = self._source
        if source is not None and source.profile.capabilities.audio.supports_podcasts:
            self._pending_load_source = source
            self._start_pending_load()

    def search(self, query: str) -> None:
        if self._closed or self._busy or not query.strip():
            return
        self._begin(
            PodcastOperation.SEARCH,
            lambda: _SearchResult(self._directory.search(query)),
        )

    def subscribe(self, feed_url: str) -> None:
        """Subscribe using metadata and artwork supplied by the publisher's feed."""
        source = self._require_editable_source()
        if source is None:
            return
        normalized = normalize_feed_url(feed_url)
        if not normalized:
            self._fail(
                PodcastOperation.SUBSCRIBE,
                "Enter a valid HTTP or HTTPS podcast feed URL.",
            )
            return
        loaded = self._loaded

        def action() -> _StateResult:
            fetched = self._feeds.fetch(normalized)
            snapshot = merge_fetched_subscription(
                loaded.snapshot,
                fetched,
                source=SubscriptionSource.USER,
            )
            return _StateResult(
                self._coordinator.save_podcast_state(
                    source,
                    replace(loaded, snapshot=snapshot),
                )
            )

        self._begin_device_write(PodcastOperation.SUBSCRIBE, action)

    def refresh(self, subscription_id: str | None = None) -> None:
        source = self._require_editable_source()
        if source is None:
            return
        loaded = self._loaded
        selected = (
            tuple(
                item
                for item in loaded.snapshot.subscriptions
                if item.subscription_id == subscription_id
            )
            if subscription_id is not None
            else loaded.snapshot.subscriptions
        )
        if not selected:
            return

        def action() -> _StateResult:
            snapshot = loaded.snapshot
            issues = tuple(
                issue
                for issue in snapshot.issues
                if issue.code is not PodcastIssueCode.FEED_REFRESH_FAILED
            )
            changed = False
            for subscription in selected:
                if not subscription.feed_url:
                    issues = (
                        *issues,
                        PodcastIssue(
                            PodcastIssueCode.FEED_REFRESH_FAILED,
                            source_text(
                                "{title} has no RSS feed URL and cannot be refreshed.",
                                title=subscription.title,
                            ),
                            subscription.subscription_id,
                        ),
                    )
                    continue
                try:
                    fetched = self._feeds.fetch(subscription.feed_url)
                except PodcastFeedError as error:
                    issues = (
                        *issues,
                        PodcastIssue(
                            PodcastIssueCode.FEED_REFRESH_FAILED,
                            source_text(
                                "Could not refresh {title}: {error}",
                                title=subscription.title,
                                error=str(error),
                            ),
                            subscription.subscription_id,
                        ),
                    )
                    continue
                snapshot = merge_fetched_subscription(snapshot, fetched)
                changed = True
            snapshot = replace(snapshot, issues=issues)
            if not changed:
                return _StateResult(replace(loaded, snapshot=snapshot))
            return _StateResult(
                self._coordinator.save_podcast_state(
                    source,
                    replace(loaded, snapshot=snapshot),
                )
            )

        self._begin_device_write(PodcastOperation.REFRESH, action)

    def unsubscribe(self, subscription_id: str) -> None:
        source = self._require_editable_source()
        if source is None:
            return
        loaded = self._loaded
        subscription = next(
            (
                item
                for item in loaded.snapshot.subscriptions
                if item.subscription_id == subscription_id
            ),
            None,
        )
        if subscription is not None and subscription.on_device_count:
            self._fail(
                PodcastOperation.UNSUBSCRIBE,
                "Remove this Podcast's episodes from the iPod before unsubscribing.",
            )
            return

        def action() -> _StateResult:
            snapshot = remove_subscription(loaded.snapshot, subscription_id)
            return _StateResult(
                self._coordinator.save_podcast_state(
                    source,
                    replace(loaded, snapshot=snapshot),
                )
            )

        self._begin_device_write(PodcastOperation.UNSUBSCRIBE, action)

    def mark_listened(
        self,
        subscription_id: str,
        episode_ids: Iterable[str],
        listened: bool,
    ) -> None:
        self.mark_listened_selection(
            ((subscription_id, episode_id) for episode_id in episode_ids),
            listened,
        )

    def mark_listened_selection(
        self,
        episode_identities: Iterable[tuple[str, str]],
        listened: bool,
    ) -> None:
        """Persist one listened choice for a possibly cross-show selection."""

        source = self._require_editable_source()
        if source is None:
            return
        loaded = self._loaded
        selected = tuple(episode_identities)

        def action() -> _StateResult:
            snapshot = mark_episode_selection_listened(
                loaded.snapshot,
                selected,
                listened,
            )
            return _StateResult(
                self._coordinator.save_podcast_state(
                    source,
                    replace(loaded, snapshot=snapshot),
                )
            )

        self._begin_device_write(PodcastOperation.LISTENED, action)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._devices.activeIPodChanged.disconnect(self.active_ipod_changed)
        self._devices.deviceWritesAllowedChanged.disconnect(
            self._device_availability_changed
        )
        self._invalidate()
        self._pool.clear()
        self._pool.waitForDone()
        self._jobs.clear()
        self._release_device_reservation()

    def _require_editable_source(self) -> ActiveIPod | None:
        if self.can_edit:
            return self._source
        self._fail(
            PodcastOperation.LOAD,
            "Podcast changes require a writable Active iPod and no operation in progress.",
        )
        return None

    def _begin(
        self,
        operation: PodcastOperation,
        action: Callable[[], _StateResult | _SearchResult],
    ) -> int | None:
        if self._closed:
            return None
        self._token += 1
        token = self._token
        job = _Work(token, operation, action)
        self._jobs[token] = job
        job.signals.completed.connect(
            self._completed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._set_busy(True)
        self._pool.start(job)
        return token

    def _begin_device_write(
        self,
        operation: PodcastOperation,
        action: Callable[[], _StateResult],
    ) -> None:
        if not self._devices.begin_exclusive_operation():
            self._fail(
                operation,
                "Podcast changes are unavailable while another iPod operation is in progress.",
            )
            return
        token = self._begin(operation, action)
        if token is None:
            self._devices.finish_exclusive_operation()
            return
        self._device_reservation_token = token

    @Slot(int, object, object, str)
    def _completed(
        self,
        token: int,
        operation: object,
        result: object,
        error: str,
    ) -> None:
        self._jobs.pop(token, None)
        owns_device_reservation = token == self._device_reservation_token
        try:
            if self._closed or token != self._token:
                return
            self._set_busy(False)
            resolved = (
                operation
                if isinstance(operation, PodcastOperation)
                else PodcastOperation.LOAD
            )
            if error:
                self._fail(resolved, error)
                return
            if isinstance(result, _StateResult):
                self._loaded = result.value
                self.changed.emit()
            elif isinstance(result, _SearchResult):
                self.searchFinished.emit(result.value)
        finally:
            if owns_device_reservation:
                self._release_device_reservation()

    def _invalidate(self) -> None:
        self._token += 1
        self._pending_load_source = None
        self._set_busy(False)

    @Slot(bool)
    def _device_availability_changed(self, _allowed: bool) -> None:
        self.changed.emit()
        self._start_pending_load()

    def _start_pending_load(self) -> None:
        source = self._pending_load_source
        if (
            source is None
            or source is not self._source
            or self._busy
            or not self._devices.device_writes_allowed
        ):
            return
        self._pending_load_source = None
        previous = self.snapshot

        def action() -> _StateResult:
            loaded = self._coordinator.load_podcast_state(source)
            if not previous.subscriptions:
                return _StateResult(loaded)
            # Reload fresh document revisions without hiding the feed Episodes
            # already being browsed after a failed or cancelled media transfer.
            subscriptions = tuple(
                replace(item, episodes=prior.episodes)
                if (prior := previous.subscription(item.subscription_id)) is not None
                and prior.feed_url == item.feed_url
                else item
                for item in loaded.snapshot.subscriptions
            )
            snapshot = reconcile_device_podcasts(
                replace(loaded.snapshot, subscriptions=subscriptions),
                source.library.tracks,
            )
            return _StateResult(replace(loaded, snapshot=snapshot))

        self._begin_device_write(
            PodcastOperation.LOAD,
            action,
        )

    def _release_device_reservation(self) -> None:
        if self._device_reservation_token is None:
            return
        self._device_reservation_token = None
        self._devices.finish_exclusive_operation()

    def _set_busy(self, busy: bool) -> None:
        if busy == self._busy:
            return
        self._busy = busy
        self.busyChanged.emit(busy)
        self.changed.emit()

    def _fail(self, operation: PodcastOperation, message: str) -> None:
        self.operationFailed.emit(PodcastOperationFailure(operation, message))


__all__ = [
    "PodcastController",
    "PodcastOperation",
    "PodcastOperationFailure",
]
