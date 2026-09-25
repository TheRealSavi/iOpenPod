from iOpenPod.app.podcasts.catalog import (
    mark_episode_selection_listened,
    mark_episodes_listened,
    merge_fetched_subscription,
    reconcile_device_podcasts,
    remove_subscription,
)
from iOpenPod.app.podcasts.identity import episode_identity, subscription_identity
from iOpenPod.app.podcasts.models import (
    PodcastEpisode,
    PodcastSnapshot,
    PodcastSubscription,
    SubscriptionSource,
)
from iPodDB.library import MediaType, Track, TrackMetadata


def _device_episode(
    *,
    play_count: int = 0,
    feed_url: str = "HTTPS://EXAMPLE.test:443/feed.xml#fragment",
) -> Track:
    return Track(
        41,
        "The First Episode",
        "Example Network",
        "A Good Podcast",
        3_660_000,
        size_bytes=42_000_000,
        artwork_id=77,
        play_count=play_count,
        media_types=(MediaType.PODCAST,),
        episode="guid-1",
        episode_number=7,
        metadata=TrackMetadata(
            podcast=True,
            podcast_rss_url=feed_url,
            podcast_enclosure_url="https://cdn.example.test/episode-1.mp3",
            release_date=1_700_000_000,
            last_played=1_710_000_000 if play_count else 0,
        ),
    )


def test_device_tracks_create_subscriptions_and_explicit_membership() -> None:
    snapshot = reconcile_device_podcasts(
        PodcastSnapshot(writable=True),
        (_device_episode(),),
    )

    assert len(snapshot.subscriptions) == 1
    subscription = snapshot.subscriptions[0]
    assert subscription.feed_url == "https://example.test/feed.xml"
    assert subscription.source is SubscriptionSource.DEVICE
    assert subscription.title == "A Good Podcast"
    assert subscription.on_device_count == 1
    assert subscription.artwork_id == 77
    assert subscription.episodes[0].track_id == 41
    assert subscription.episodes[0].on_device is True
    assert subscription.episodes[0].listened is False


def test_observed_listening_history_survives_episode_removal_from_ipod() -> None:
    connected = reconcile_device_podcasts(
        PodcastSnapshot(writable=True),
        (_device_episode(play_count=2),),
    )
    disconnected = reconcile_device_podcasts(connected, ())

    assert len(disconnected.history) == 1
    assert disconnected.history[0].observed_play_count == 2
    episode = disconnected.subscriptions[0].episodes[0]
    assert episode.on_device is False
    assert episode.track_id is None
    assert episode.listened is True
    assert episode.play_count == 2


def test_feed_refresh_matches_an_existing_device_episode_by_enclosure_url() -> None:
    device = reconcile_device_podcasts(
        PodcastSnapshot(writable=True),
        (_device_episode(),),
    )
    subscription_id = device.subscriptions[0].subscription_id
    fetched = PodcastSubscription(
        subscription_id,
        "https://example.test/feed.xml",
        "A Good Podcast",
        SubscriptionSource.USER,
        description="Fresh show description",
        episodes=(
            PodcastEpisode(
                device.subscriptions[0].episodes[0].episode_id,
                guid="feed-guid-that-differs",
                title="Fresh Episode Title",
                enclosure_url="https://cdn.example.test/episode-1.mp3",
            ),
        ),
    )

    refreshed = merge_fetched_subscription(device, fetched)

    episode = refreshed.subscriptions[0].episodes[0]
    assert episode.title == "Fresh Episode Title"
    assert episode.on_device is True
    assert episode.track_id == 41
    assert refreshed.subscriptions[0].artwork_id == 77


def test_device_episode_matches_a_subscription_when_its_feed_url_changed() -> None:
    enclosure_url = _device_episode().metadata.podcast_enclosure_url
    subscription = PodcastSubscription(
        subscription_identity("https://old.example.test/feed", "A Good Podcast"),
        "https://old.example.test/feed",
        "A Good Podcast",
        SubscriptionSource.USER,
        author="Example Network",
        episodes=(
            PodcastEpisode(
                episode_identity(
                    enclosure_url=enclosure_url,
                    guid="",
                    title="",
                    published_at=0,
                ),
                title="Cached title",
                enclosure_url=enclosure_url,
            ),
        ),
    )

    reconciled = reconcile_device_podcasts(
        PodcastSnapshot((subscription,), writable=True),
        (_device_episode(),),
    )

    assert len(reconciled.subscriptions) == 1
    retained = reconciled.subscriptions[0]
    assert retained.subscription_id == subscription.subscription_id
    assert retained.source is SubscriptionSource.USER
    assert retained.episodes[0].on_device is True


def test_feed_refresh_merges_with_a_device_only_show_by_episode_evidence() -> None:
    device_track = _device_episode(feed_url="")
    device = reconcile_device_podcasts(
        PodcastSnapshot(writable=True),
        (device_track,),
    )
    existing = device.subscriptions[0]
    fetched = PodcastSubscription(
        subscription_identity("https://example.test/new-feed", "A Good Podcast"),
        "https://example.test/new-feed",
        "A Good Podcast",
        SubscriptionSource.USER,
        episodes=(
            PodcastEpisode(
                existing.episodes[0].episode_id,
                title="Fresh title",
                enclosure_url=device_track.metadata.podcast_enclosure_url,
            ),
        ),
    )

    merged = merge_fetched_subscription(
        device,
        fetched,
        source=SubscriptionSource.USER,
    )

    assert len(merged.subscriptions) == 1
    assert merged.subscriptions[0].subscription_id == existing.subscription_id
    assert merged.subscriptions[0].source is SubscriptionSource.USER
    assert merged.subscriptions[0].feed_url == "https://example.test/new-feed"
    assert merged.subscriptions[0].episodes[0].on_device is True


def test_manual_listened_state_is_independent_of_subscription_lifetime() -> None:
    connected = reconcile_device_podcasts(
        PodcastSnapshot(writable=True),
        (_device_episode(),),
    )
    subscription = connected.subscriptions[0]
    episode = subscription.episodes[0]

    marked = mark_episodes_listened(
        connected,
        subscription.subscription_id,
        (episode.episode_id,),
        True,
        changed_at=1_720_000_000,
    )
    removed = remove_subscription(marked, subscription.subscription_id)

    assert marked.subscriptions[0].episodes[0].listened is True
    assert marked.subscriptions[0].episodes[0].on_device is True
    assert removed.subscriptions == ()
    assert removed.history[0].listened is True
    assert removed.history[0].last_played == 1_720_000_000


def test_unlistened_override_survives_later_device_reconciliation() -> None:
    connected = reconcile_device_podcasts(
        PodcastSnapshot(writable=True),
        (_device_episode(play_count=2),),
    )
    subscription = connected.subscriptions[0]
    episode = subscription.episodes[0]
    marked = mark_episodes_listened(
        connected,
        subscription.subscription_id,
        (episode.episode_id,),
        False,
        changed_at=1_720_000_000,
    )

    reconciled = reconcile_device_podcasts(marked, (_device_episode(play_count=2),))

    assert reconciled.subscriptions[0].episodes[0].listened is False
    assert reconciled.history[0].listened_override is False


def test_listened_selection_updates_episodes_from_multiple_subscriptions() -> None:
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

    updated = mark_episode_selection_listened(
        PodcastSnapshot((first, second), writable=True),
        (("second-show", "second-episode"), ("first-show", "first-episode")),
        True,
        changed_at=1_720_000_000,
    )

    assert all(
        episode.listened
        for subscription in updated.subscriptions
        for episode in subscription.episodes
    )
    assert len(updated.history) == 2
    assert {record.last_played for record in updated.history} == {1_720_000_000}


def test_feed_identity_is_stable_across_default_port_and_fragment_changes() -> None:
    first = subscription_identity("https://Example.test:443/feed#one", "Ignored")
    second = subscription_identity("https://example.test/feed#two", "Also ignored")

    assert first == second
