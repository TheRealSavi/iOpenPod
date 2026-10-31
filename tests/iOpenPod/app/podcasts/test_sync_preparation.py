"""Sync refresh failures preserve media and history publication gates removal."""

from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest
from tests.iOpenPod.app.podcasts.podcast_test_support import active_ipod, device_episode

from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.podcasts import feed_client
from iOpenPod.app.podcasts.catalog import reconcile_device_podcasts
from iOpenPod.app.podcasts.feed_client import PodcastFeedError
from iOpenPod.app.podcasts.identity import subscription_identity
from iOpenPod.app.podcasts.models import (
    PodcastEpisode,
    PodcastSnapshot,
    PodcastSubscription,
)
from iOpenPod.app.podcasts.store import LoadedPodcastState, PodcastStateRevision
from iOpenPod.app.podcasts.sync import PodcastSyncRequest
from iOpenPod.app.podcasts.sync_preparation import (
    prepare_podcast_sync,
    state_after_podcast_sync,
)
from iPodDB.library import LibrarySnapshot

if TYPE_CHECKING:
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator


class _Coordinator:
    def __init__(self, snapshot: PodcastSnapshot, *, fail_save: bool = False) -> None:
        self.loaded = LoadedPodcastState(snapshot, PodcastStateRevision())
        self.saved: list[LoadedPodcastState] = []
        self.fail_save = fail_save

    def load_podcast_state(self, _source: ActiveIPod) -> LoadedPodcastState:
        return self.loaded

    def save_podcast_state(
        self, _source: ActiveIPod, state: LoadedPodcastState
    ) -> LoadedPodcastState:
        if self.fail_save:
            raise ValueError("History changed on device")
        self.saved.append(state)
        return state


class _Feeds:
    def __init__(self, subscription: PodcastSubscription | None = None) -> None:
        self.subscription = subscription
        self.calls = 0

    def fetch(self, feed_url: str) -> PodcastSubscription:
        del feed_url
        self.calls += 1
        if self.subscription is None:
            raise PodcastFeedError("offline")
        return self.subscription


def _state() -> tuple[ActiveIPod, PodcastSnapshot]:
    tracks = (device_episode(play_count=1),)
    return (
        replace(active_ipod(), library=LibrarySnapshot(tracks)),
        reconcile_device_podcasts(PodcastSnapshot(writable=True), tracks),
    )


def test_failed_refresh_cannot_clear_a_listened_episode() -> None:
    source, snapshot = _state()
    coordinator = _Coordinator(snapshot)
    feeds = _Feeds()
    prepared = prepare_podcast_sync(
        PodcastSyncRequest(snapshot),
        source,
        cast("DeviceCoordinator", coordinator),
        lambda: None,
        feeds=feeds,
    )
    plan = prepared.plan
    assert feeds.calls == 1
    assert not plan.removals and not plan.additions
    assert plan.issues[0].code == "podcast.refresh_failed"
    assert coordinator.saved[0].snapshot.history[0].listened


def test_repeated_feed_ids_preserve_episodes_while_other_shows_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, snapshot = _state()
    retained = snapshot.subscriptions[0]
    healthy = replace(
        retained,
        subscription_id=subscription_identity(
            "https://example.test/healthy", "Healthy"
        ),
        feed_url="https://example.test/healthy",
        title="Healthy",
        episodes=(),
    )
    snapshot = replace(snapshot, subscriptions=(retained, healthy))
    coordinator = _Coordinator(snapshot)
    calls: list[str] = []

    def request_bytes(url: str, **kwargs: object) -> tuple[bytes, str]:
        calls.append(url)
        item = """<item><title>Incoming</title><guid>incoming</guid>
        <enclosure url="https://example.test/incoming.mp3" type="audio/mpeg" />
        </item>"""
        title = "Healthy" if url == healthy.feed_url else retained.title
        items = item if url == healthy.feed_url else item + item
        return (
            f"<rss><channel><title>{title}</title>{items}</channel></rss>".encode(),
            url,
        )

    monkeypatch.setattr(feed_client, "request_podcast_bytes", request_bytes)

    prepared = prepare_podcast_sync(
        PodcastSyncRequest(snapshot),
        source,
        cast("DeviceCoordinator", coordinator),
        lambda: None,
    )

    assert calls == [retained.feed_url, healthy.feed_url]
    assert prepared.refreshed_subscription_ids == (healthy.subscription_id,)
    assert not prepared.plan.removals
    assert len(prepared.plan.additions) == 1
    assert (
        prepared.plan.additions[0].subscription.subscription_id
        == healthy.subscription_id
    )
    assert prepared.state.snapshot.subscription(retained.subscription_id) == retained
    assert prepared.state.snapshot.history == snapshot.history
    issue = prepared.plan.issues[0]
    assert issue.code == "podcast.refresh_failed"
    assert retained.title in issue.message and retained.feed_url in issue.detail


def test_manual_add_uses_captured_episode_metadata_without_feed_refresh() -> None:
    source, snapshot = _state()
    subscription = snapshot.subscriptions[0]
    episode = PodcastEpisode(
        "new", title="New", enclosure_url="https://example.test/new.mp3"
    )
    captured = replace(
        snapshot,
        subscriptions=(
            replace(subscription, episodes=(*subscription.episodes, episode)),
        ),
    )
    coordinator = _Coordinator(snapshot)
    feeds = _Feeds()
    prepared = prepare_podcast_sync(
        PodcastSyncRequest(
            captured,
            additions=((subscription.subscription_id, "new"),),
            automatic=False,
        ),
        source,
        cast("DeviceCoordinator", coordinator),
        lambda: None,
        feeds=feeds,
    )
    plan = prepared.plan
    assert not feeds.calls
    assert len(plan.additions) == 1 and plan.additions[0].episode == episode
    assert not plan.removals


def test_manual_remove_preserves_history_without_refreshing_feed() -> None:
    source, snapshot = _state()
    subscription = snapshot.subscriptions[0]
    coordinator = _Coordinator(snapshot)
    feeds = _Feeds()
    prepared = prepare_podcast_sync(
        PodcastSyncRequest(
            snapshot,
            removals=(
                (subscription.subscription_id, subscription.episodes[0].episode_id),
            ),
            automatic=False,
        ),
        source,
        cast("DeviceCoordinator", coordinator),
        lambda: None,
        feeds=feeds,
    )
    plan = prepared.plan
    assert not feeds.calls and plan.removals == (41,)
    assert coordinator.saved[0].snapshot.history[0].observed_play_count == 1


def test_unsubscribe_is_staged_only_after_all_episodes_leave_the_draft() -> None:
    source, snapshot = _state()
    subscription = snapshot.subscriptions[0]
    prepared = prepare_podcast_sync(
        PodcastSyncRequest(
            snapshot,
            subscription_ids=(subscription.subscription_id,),
            removals=(
                (subscription.subscription_id, subscription.episodes[0].episode_id),
            ),
            automatic=False,
            unsubscribe_subscription_id=subscription.subscription_id,
        ),
        source,
        cast("DeviceCoordinator", _Coordinator(snapshot)),
        lambda: None,
        feeds=_Feeds(),
    )
    assert (
        state_after_podcast_sync(
            prepared,
            prepared.plan,
            source.library,
            unsubscribe_subscription_id=subscription.subscription_id,
        )
        is None
    )
    staged = state_after_podcast_sync(
        prepared,
        prepared.plan,
        LibrarySnapshot(),
        unsubscribe_subscription_id=subscription.subscription_id,
    )
    assert staged is not None
    assert staged.snapshot.subscription(subscription.subscription_id) is None
    assert staged.snapshot.history == prepared.state.snapshot.history
    assert (
        state_after_podcast_sync(
            prepared,
            replace(prepared.plan, removals=()),
            LibrarySnapshot(),
            unsubscribe_subscription_id=subscription.subscription_id,
        )
        is None
    )


def test_history_failure_stops_retention_planning() -> None:
    source, snapshot = _state()
    coordinator = _Coordinator(snapshot, fail_save=True)
    with pytest.raises(ValueError, match="History changed"):
        prepare_podcast_sync(
            PodcastSyncRequest(snapshot),
            source,
            cast("DeviceCoordinator", coordinator),
            lambda: None,
            feeds=_Feeds(snapshot.subscriptions[0]),
        )


def test_only_requested_subscription_is_refreshed() -> None:
    source, snapshot = _state()
    subscription = snapshot.subscriptions[0]
    other = replace(
        subscription,
        subscription_id="other",
        feed_url="https://example.test/other",
        episodes=(),
    )
    snapshot = replace(snapshot, subscriptions=(subscription, other))
    feeds = _Feeds(other)
    coordinator = _Coordinator(snapshot)
    prepared = prepare_podcast_sync(
        PodcastSyncRequest(snapshot, subscription_ids=("other",)),
        source,
        cast("DeviceCoordinator", coordinator),
        lambda: None,
        feeds=feeds,
    )
    plan = prepared.plan
    assert feeds.calls == 1 and not plan.removals


def test_automatic_clear_history_only_stages_for_actual_podcast_removals() -> None:
    source, snapshot = _state()
    coordinator = _Coordinator(snapshot)
    prepared = prepare_podcast_sync(
        PodcastSyncRequest(snapshot),
        source,
        cast("DeviceCoordinator", coordinator),
        lambda: None,
        feeds=_Feeds(snapshot.subscriptions[0]),
    )
    assert prepared.plan.removals == (41,)
    assert not prepared.state.snapshot.history[0].automatically_cleared
    # A failed replacement retains its Track, and Host-only removals are not
    # automatic Podcast clears even when they remove the same Track.
    assert state_after_podcast_sync(prepared, prepared.plan, source.library) is None
    assert (
        state_after_podcast_sync(
            prepared, replace(prepared.plan, removals=()), LibrarySnapshot()
        )
        is None
    )
    staged = state_after_podcast_sync(prepared, prepared.plan, LibrarySnapshot())
    assert staged is not None
    assert staged.snapshot.history[0].automatically_cleared
    assert staged.revision == prepared.state.revision
    assert not prepared.state.snapshot.history[0].automatically_cleared
