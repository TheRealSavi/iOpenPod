from __future__ import annotations

import time
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from tests.iOpenPod.app.podcasts.podcast_test_support import active_ipod as _active_ipod
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.podcasts.controller import (
    PodcastController,
    PodcastOperation,
    PodcastOperationFailure,
)
from iOpenPod.app.podcasts.models import (
    PodcastEpisode,
    PodcastSearchResult,
    PodcastSnapshot,
    PodcastSubscription,
    PodcastSyncSettings,
    SubscriptionSource,
)
from iOpenPod.app.podcasts.store import LoadedPodcastState, PodcastStateRevision

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.podcasts.sync import PodcastSyncRequest
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator


class _Devices(QObject):
    activeIPodChanged = Signal(object)
    busyChanged = Signal(bool)
    deviceWritesAllowedChanged = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.busy = False
        self.read_only_operations = 0

    @property
    def device_writes_allowed(self) -> bool:
        return not self.busy and self.read_only_operations == 0

    def begin_read_only_operation(self) -> bool:
        if self.busy:
            return False
        was_allowed = self.device_writes_allowed
        self.read_only_operations += 1
        if was_allowed:
            self.deviceWritesAllowedChanged.emit(False)
        return True

    def finish_read_only_operation(self) -> None:
        if self.read_only_operations == 0:
            return
        self.read_only_operations -= 1
        if self.device_writes_allowed:
            self.deviceWritesAllowedChanged.emit(True)

    def begin_exclusive_operation(self) -> bool:
        if not self.device_writes_allowed:
            return False
        self.busy = True
        self.busyChanged.emit(True)
        self.deviceWritesAllowedChanged.emit(False)
        return True

    def finish_exclusive_operation(self) -> None:
        self.busy = False
        self.busyChanged.emit(False)
        self.deviceWritesAllowedChanged.emit(True)


class _Coordinator:
    def __init__(self, loaded: LoadedPodcastState) -> None:
        self.loaded = loaded
        self.saved: list[LoadedPodcastState] = []

    def load_podcast_state(self, _active: ActiveIPod) -> LoadedPodcastState:
        return self.loaded

    def save_podcast_state(
        self,
        _active: ActiveIPod,
        state: LoadedPodcastState,
    ) -> LoadedPodcastState:
        self.saved.append(state)
        self.loaded = state
        return state


class _Feeds:
    def __init__(self, subscription: PodcastSubscription) -> None:
        self.subscription = subscription

    def fetch(self, feed_url: str) -> PodcastSubscription:
        del feed_url
        return self.subscription


class _Directory:
    def search(self, query: str) -> tuple[PodcastSearchResult, ...]:
        del query
        return (
            PodcastSearchResult(
                "Found Show",
                "Network",
                "https://example.test/feed",
            ),
        )


def _controller(
    coordinator: _Coordinator,
    devices: _Devices,
    feed: PodcastSubscription,
) -> PodcastController:
    return PodcastController(
        cast("DeviceCoordinator", coordinator),
        cast("DeviceController", devices),
        feeds=_Feeds(feed),
        directory=_Directory(),
    )


def _wait_until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 2
    while not condition() and time.monotonic() < deadline:
        APPLICATION.processEvents()
        QTest.qWait(10)
    assert condition()


def test_controller_loads_then_saves_subscriptions_and_history_off_thread() -> None:
    feed = PodcastSubscription(
        "feed-1",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
        episodes=(
            PodcastEpisode(
                "episode-1",
                title="Episode",
                enclosure_url="https://example.test/episode.mp3",
            ),
        ),
    )
    loaded = LoadedPodcastState(
        PodcastSnapshot(writable=True),
        PodcastStateRevision(),
    )
    coordinator = _Coordinator(loaded)
    devices = _Devices()
    controller = _controller(coordinator, devices, feed)

    try:
        devices.activeIPodChanged.emit(_active_ipod())
        _wait_until(lambda: not controller.busy and controller.can_edit)

        controller.subscribe(feed.feed_url)
        _wait_until(
            lambda: not controller.busy and bool(controller.snapshot.subscriptions)
        )
        assert coordinator.saved[-1].snapshot.subscriptions == (feed,)

        controller.mark_listened("feed-1", ("episode-1",), True)
        _wait_until(lambda: not controller.busy and bool(controller.snapshot.history))
        assert controller.snapshot.history[0].listened is True
        assert controller.snapshot.subscriptions[0].episodes[0].listened is True
    finally:
        controller.shutdown()


@pytest.mark.parametrize(
    "publisher_art", ("", "https://publisher.example.test/cover.jpg")
)
def test_subscribe_persists_only_current_publisher_feed_artwork(
    publisher_art: str,
) -> None:
    feed = PodcastSubscription(
        "feed-1",
        "https://example.test/feed",
        "Example Show",
        SubscriptionSource.USER,
        artwork_url=publisher_art,
        episodes=(PodcastEpisode("episode-1", title="Example Episode"),),
    )
    # A preview version could retain a directory fallback. A successful feed
    # refresh/subscription adopts current publisher metadata, even absent artwork.
    old = replace(feed, artwork_url="https://apple-cdn.example.test/old-cover.jpg")
    coordinator = _Coordinator(
        LoadedPodcastState(
            PodcastSnapshot((old,), writable=True),
            PodcastStateRevision(),
        )
    )
    devices = _Devices()
    controller = _controller(coordinator, devices, feed)
    try:
        devices.activeIPodChanged.emit(_active_ipod())
        _wait_until(lambda: controller.can_edit)
        controller.subscribe(feed.feed_url)
        _wait_until(lambda: not controller.busy and bool(coordinator.saved))
        assert (
            coordinator.saved[-1].snapshot.subscriptions[0].artwork_url == publisher_art
        )
    finally:
        controller.shutdown()


def test_controller_saves_a_cross_show_listened_selection_once() -> None:
    first = PodcastSubscription(
        "first-show",
        "https://example.test/first",
        "First Show",
        SubscriptionSource.USER,
        episodes=(PodcastEpisode("first-episode", title="First Episode"),),
    )
    second = PodcastSubscription(
        "second-show",
        "https://example.test/second",
        "Second Show",
        SubscriptionSource.USER,
        episodes=(PodcastEpisode("second-episode", title="Second Episode"),),
    )
    coordinator = _Coordinator(
        LoadedPodcastState(
            PodcastSnapshot((first, second), writable=True),
            PodcastStateRevision(),
        )
    )
    devices = _Devices()
    controller = _controller(coordinator, devices, first)

    try:
        devices.activeIPodChanged.emit(_active_ipod())
        _wait_until(lambda: not controller.busy and controller.can_edit)

        controller.mark_listened_selection(
            (("first-show", "first-episode"), ("second-show", "second-episode")),
            True,
        )
        _wait_until(
            lambda: not controller.busy and len(controller.snapshot.history) == 2
        )

        assert len(coordinator.saved) == 1
        assert all(
            episode.listened
            for subscription in controller.snapshot.subscriptions
            for episode in subscription.episodes
        )
    finally:
        controller.shutdown()


def test_read_only_device_reservation_blocks_podcast_writes() -> None:
    feed = PodcastSubscription(
        "feed-1",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
    )
    coordinator = _Coordinator(
        LoadedPodcastState(PodcastSnapshot(writable=True), PodcastStateRevision())
    )
    devices = _Devices()
    controller = _controller(coordinator, devices, feed)

    try:
        devices.activeIPodChanged.emit(_active_ipod())
        _wait_until(lambda: not controller.busy and controller.can_edit)

        assert devices.begin_read_only_operation() is True
        assert controller.can_edit is False
        controller.subscribe(feed.feed_url)
        assert coordinator.saved == []

        devices.finish_read_only_operation()
        assert controller.can_edit is True
    finally:
        devices.finish_read_only_operation()
        controller.shutdown()


def test_controller_publishes_typed_directory_results() -> None:
    feed = PodcastSubscription(
        "feed-1",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
    )
    coordinator = _Coordinator(
        LoadedPodcastState(PodcastSnapshot(writable=True), PodcastStateRevision())
    )
    devices = _Devices()
    controller = _controller(coordinator, devices, feed)
    results: list[tuple[PodcastSearchResult, ...]] = []
    controller.searchFinished.connect(results.append)

    try:
        devices.activeIPodChanged.emit(_active_ipod())
        _wait_until(lambda: not controller.busy)
        controller.search("found")
        _wait_until(lambda: bool(results))
        assert results[0][0].title == "Found Show"
    finally:
        controller.shutdown()


def test_controller_does_not_unsubscribe_a_device_backed_show() -> None:
    feed = PodcastSubscription(
        "feed-1",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
        episodes=(
            PodcastEpisode(
                "episode-1",
                title="Episode",
                on_device=True,
                track_id=42,
            ),
        ),
    )
    coordinator = _Coordinator(
        LoadedPodcastState(
            PodcastSnapshot((feed,), writable=True), PodcastStateRevision()
        )
    )
    devices = _Devices()
    controller = _controller(coordinator, devices, feed)
    failures: list[PodcastOperationFailure] = []
    controller.operationFailed.connect(failures.append)

    try:
        devices.activeIPodChanged.emit(_active_ipod())
        _wait_until(lambda: not controller.busy and controller.can_edit)
        controller.unsubscribe(feed.subscription_id)

        assert coordinator.saved == []
        assert failures[-1].operation is PodcastOperation.UNSUBSCRIBE
    finally:
        controller.shutdown()


def test_sync_intent_is_captured_and_manual_selection_does_not_apply_retention() -> (
    None
):
    feed = PodcastSubscription(
        "feed-1",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
        episodes=(
            PodcastEpisode("episode-1", enclosure_url="https://example.test/e.mp3"),
        ),
    )
    coordinator = _Coordinator(
        LoadedPodcastState(
            PodcastSnapshot((feed,), writable=True), PodcastStateRevision()
        )
    )
    devices = _Devices()
    controller = _controller(coordinator, devices, feed)
    requests: list[PodcastSyncRequest] = []
    controller.syncRequested.connect(requests.append)
    try:
        devices.activeIPodChanged.emit(_active_ipod())
        _wait_until(lambda: controller.can_sync)
        controller.sync()
        controller.sync("feed-1")
        controller.add_episodes((("feed-1", "episode-1"),) * 2)
        controller.remove_episodes((("feed-1", "episode-1"),))
        assert len(requests) == 4
        assert requests[0].snapshot is controller.snapshot
        assert requests[0].automatic and requests[0].subscription_ids is None
        assert requests[1].subscription_ids == ("feed-1",)
        assert requests[2].additions == (("feed-1", "episode-1"),)
        assert requests[3].removals == (("feed-1", "episode-1"),)
        assert not requests[2].automatic and not requests[3].automatic
        assert not coordinator.saved
        assert devices.begin_read_only_operation()
        controller.sync()
        controller.add_episodes((("feed-1", "episode-1"),))
        assert len(requests) == 4
    finally:
        devices.finish_read_only_operation()
        controller.shutdown()


def test_sync_settings_are_saved_for_only_the_selected_show() -> None:
    feed = PodcastSubscription(
        "feed-1", "https://example.test/feed", "Show", SubscriptionSource.USER
    )
    other = replace(
        feed, subscription_id="feed-2", feed_url="https://example.test/other"
    )
    coordinator = _Coordinator(
        LoadedPodcastState(
            PodcastSnapshot((feed, other), writable=True), PodcastStateRevision()
        )
    )
    devices = _Devices()
    controller = _controller(coordinator, devices, feed)
    try:
        devices.activeIPodChanged.emit(_active_ipod())
        _wait_until(lambda: controller.can_edit)
        settings = PodcastSyncSettings(episode_slots=7)
        controller.set_sync_settings("feed-1", settings)
        _wait_until(lambda: not controller.busy and bool(coordinator.saved))
        selected = controller.snapshot.subscription("feed-1")
        assert selected is not None and selected.sync_settings == settings
        assert controller.snapshot.subscription("feed-2") == other
    finally:
        controller.shutdown()


def test_reload_preserves_browsed_feed_episodes_with_fresh_document_settings() -> None:
    feed = PodcastSubscription(
        "feed-1",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
        episodes=(
            PodcastEpisode("episode-1", enclosure_url="https://example.test/e.mp3"),
        ),
    )
    coordinator = _Coordinator(
        LoadedPodcastState(
            PodcastSnapshot((feed,), writable=True), PodcastStateRevision()
        )
    )
    devices = _Devices()
    controller = _controller(coordinator, devices, feed)
    try:
        devices.activeIPodChanged.emit(_active_ipod())
        _wait_until(lambda: controller.can_edit)
        settings = PodcastSyncSettings(episode_slots=8)
        coordinator.loaded = replace(
            coordinator.loaded,
            snapshot=replace(
                coordinator.loaded.snapshot,
                subscriptions=(replace(feed, episodes=(), sync_settings=settings),),
            ),
        )
        controller.reload()
        _wait_until(lambda: controller.can_edit)
        assert controller.snapshot.subscriptions[0].episodes == feed.episodes
        assert controller.snapshot.subscriptions[0].sync_settings == settings
    finally:
        controller.shutdown()
