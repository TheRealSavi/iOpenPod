"""Recover shows from captured Finder-style Track metadata, not group links."""

from dataclasses import replace

import pytest
from tests.iPodDB.library.test_finder_podcasts import finder_source

from iOpenPod.app.podcasts.catalog import (
    merge_fetched_subscription,
    reconcile_device_podcasts,
)
from iOpenPod.app.podcasts.models import PodcastEpisode, PodcastSnapshot


@pytest.mark.parametrize("compressed", (False, True))
def test_missing_native_group_links_do_not_merge_recovered_subscriptions(
    compressed: bool,
) -> None:
    library = finder_source(compressed=compressed)
    snapshot = reconcile_device_podcasts(PodcastSnapshot(), library.snapshot.tracks)
    assert len(snapshot.subscriptions) == 2
    for subscription in snapshot.subscriptions:
        assert subscription.title in ("1", "2")
        assert (
            subscription.feed_url
            == f"https://publisher.example/{subscription.title}.rss"
        )
        assert subscription.artwork_id == 0
        assert len(subscription.episodes) == 1
        episode = subscription.episodes[0]
        assert episode.on_device
        assert episode.track_id == int(subscription.title)
        assert episode.enclosure_url == ""
        assert episode.guid == f"episode-guid-{subscription.title}"


@pytest.mark.parametrize("changed_guid", (False, True))
def test_refresh_matches_guid_or_unique_publication_without_duplicating_device_episode(
    changed_guid: bool,
) -> None:
    library = finder_source()
    track = library.snapshot.tracks[0]
    track = replace(
        track,
        title="An episode",
        metadata=replace(track.metadata, release_date=1_700_000_000),
    )
    state = reconcile_device_podcasts(PodcastSnapshot(), (track,))
    show = state.subscriptions[0]
    old = show.episodes[0]
    fetched = replace(
        show,
        episodes=(
            replace(
                old,
                episode_id="new-download-identity",
                guid="new-publisher-guid" if changed_guid else old.guid,
                enclosure_url="https://publisher.example/new.mp3",
                on_device=False,
                track_id=None,
            ),
        ),
    )
    merged = merge_fetched_subscription(state, fetched)
    merged = reconcile_device_podcasts(merged, (track,))
    assert len(merged.subscriptions[0].episodes) == 1
    episode = merged.subscriptions[0].episodes[0]
    assert episode.episode_id == old.episode_id
    assert episode.on_device and episode.track_id == track.track_id
    assert episode.guid == fetched.episodes[0].guid
    assert episode.enclosure_url == fetched.episodes[0].enclosure_url


@pytest.mark.parametrize(
    "ambiguity", ("same_title", "missing_date", "episode_conflict", "different_feed")
)
def test_publication_fallback_does_not_guess_ambiguous_identity(ambiguity: str) -> None:
    track = finder_source().snapshot.tracks[0]
    track = replace(
        track,
        title="An episode",
        episode_number=7,
        metadata=replace(
            track.metadata,
            release_date=0 if ambiguity == "missing_date" else 1_700_000_000,
        ),
    )
    state = reconcile_device_podcasts(PodcastSnapshot(), (track,))
    show = state.subscriptions[0]
    old = show.episodes[0]
    incoming = PodcastEpisode(
        "incoming",
        title=old.title,
        guid="changed",
        published_at=old.published_at,
        episode_number=8 if ambiguity == "episode_conflict" else 7,
        enclosure_url="https://publisher.example/new.mp3",
    )
    fetched = replace(
        show,
        feed_url="https://different.example/feed"
        if ambiguity == "different_feed"
        else show.feed_url,
        episodes=(
            incoming,
            replace(
                incoming,
                episode_id="other",
                guid="other",
                enclosure_url="https://publisher.example/other.mp3",
            ),
        )
        if ambiguity == "same_title"
        else (incoming,),
    )
    merged = merge_fetched_subscription(state, fetched)
    assert sum(episode.on_device for episode in merged.subscriptions[0].episodes) == 1
    assert len(merged.subscriptions[0].episodes) == len(fetched.episodes) + 1
