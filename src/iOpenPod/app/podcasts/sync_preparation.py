"""Refresh Podcast intent and preserve Listening History before media changes."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from iOpenPod.app.podcasts.catalog import (
    mark_episodes_automatically_cleared,
    merge_fetched_subscription,
    reconcile_device_podcasts,
)
from iOpenPod.app.podcasts.feed_client import (
    FeedparserPodcastClient,
    PodcastFeedError,
)
from iOpenPod.app.podcasts.sync import PodcastSyncPlan, plan_podcast_sync
from iPodDB.library import WriteIssue

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.podcasts.feed_client import PodcastFeedClient
    from iOpenPod.app.podcasts.models import PodcastSubscription
    from iOpenPod.app.podcasts.store import LoadedPodcastState
    from iOpenPod.app.podcasts.sync import PodcastSyncRequest
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator
    from iPodDB.library import LibrarySnapshot


@dataclass(frozen=True, slots=True)
class PreparedPodcastSync:
    plan: PodcastSyncPlan
    state: LoadedPodcastState
    refreshed_subscription_ids: tuple[str, ...] = ()


def prepare_podcast_sync(
    request: PodcastSyncRequest,
    source: ActiveIPod,
    coordinator: DeviceCoordinator,
    checkpoint: Callable[[], None],
    *,
    feeds: PodcastFeedClient | None = None,
) -> PreparedPodcastSync:
    """Run inside the Sync reservation, never on the GUI thread.

    Fresh device documents supply settings and history. Captured catalog metadata
    supplies explicitly selected downloads, whose device membership is reconciled
    again. A failed feed cannot authorize retention removals for that show.
    """
    checkpoint()
    if not source.profile.capabilities.audio.supports_podcasts:
        raise ValueError("The Active iPod does not support Podcasts.")
    loaded = coordinator.load_podcast_state(source)
    if not loaded.snapshot.writable:
        raise ValueError(
            "Podcast state is not safely writable. Resolve its reported document "
            "problem before syncing Podcasts."
        )
    subscriptions: list[PodcastSubscription] = []
    for saved in loaded.snapshot.subscriptions:
        captured = request.snapshot.subscription(saved.subscription_id)
        subscriptions.append(
            replace(saved, episodes=captured.episodes)
            if captured is not None and saved.feed_url == captured.feed_url
            else saved
        )
    snapshot = reconcile_device_podcasts(
        replace(loaded.snapshot, subscriptions=tuple(subscriptions)),
        source.library.tracks,
    )
    issues: list[WriteIssue] = []
    selected_ids = (
        request.subscription_ids
        if request.subscription_ids is not None
        else tuple(item.subscription_id for item in snapshot.subscriptions)
    )
    refreshed: list[str] = []
    if request.automatic:
        client = feeds or FeedparserPodcastClient()
        for subscription_id in selected_ids:
            checkpoint()
            subscription = snapshot.subscription(subscription_id)
            if subscription is None:
                issues.append(
                    WriteIssue(
                        "podcast.subscription_missing",
                        "A selected Podcast Subscription is no longer available.",
                        detail=subscription_id,
                    )
                )
                continue
            try:
                fetched = client.fetch(subscription.feed_url)
            except PodcastFeedError as error:
                issues.append(
                    WriteIssue(
                        "podcast.refresh_failed",
                        f"Could not refresh {subscription.title}. Its episodes were "
                        "kept unchanged; check the feed and retry Sync.",
                        detail=str(error),
                    )
                )
                continue
            snapshot = merge_fetched_subscription(snapshot, fetched)
            refreshed.append(subscription_id)
    checkpoint()
    # Keep observed and explicit listening facts even when the Track is removed.
    # Failure here stops publication, so retention cannot discard the sole copy.
    persisted = coordinator.save_podcast_state(
        source, replace(loaded, snapshot=snapshot)
    )
    checkpoint()
    plan = plan_podcast_sync(
        replace(
            request,
            snapshot=persisted.snapshot,
            subscription_ids=tuple(refreshed) if request.automatic else selected_ids,
        ),
        source.library,
    )
    return PreparedPodcastSync(
        replace(plan, issues=(*issues, *plan.issues)), persisted, tuple(refreshed)
    )


def history_after_podcast_sync(
    prepared: PreparedPodcastSync,
    plan: PodcastSyncPlan,
    library: LibrarySnapshot,
) -> LoadedPodcastState | None:
    """Stage exclusions only for automatic clears present in the final Draft.

    The returned history must publish in the Library's Storage Transaction. A
    failed replacement, Host-only removal, or cancelled publication must not skip
    an Episode for future automatic Syncs.
    """
    automatic_tracks = set(plan.removals) | {
        addition.replaces_track_id
        for addition in plan.additions
        if addition.replaces_track_id is not None
    }
    retained_tracks = {track.track_id for track in library.tracks}
    selections: list[tuple[str, str]] = []
    for subscription_id, episode_id in plan.automatic_removals:
        subscription = prepared.state.snapshot.subscription(subscription_id)
        if subscription is None:
            continue
        episode = next(
            (item for item in subscription.episodes if item.episode_id == episode_id),
            None,
        )
        if (
            episode is not None
            and episode.track_id in automatic_tracks
            and episode.track_id not in retained_tracks
        ):
            selections.append((subscription_id, episode_id))
    if not selections:
        return None
    return replace(
        prepared.state,
        snapshot=mark_episodes_automatically_cleared(
            prepared.state.snapshot, tuple(selections)
        ),
    )
