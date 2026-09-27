from dataclasses import replace

import pytest
from tests.iOpenPod.app.podcasts.podcast_test_support import (
    device_episode as _device_episode,
)

from iOpenPod.app.podcasts.catalog import (
    mark_episode_selection_listened,
    mark_episodes_automatically_cleared,
    mark_episodes_listened,
    merge_fetched_subscription,
    reconcile_device_podcasts,
    remove_subscription,
)
from iOpenPod.app.podcasts.identity import episode_identity, subscription_identity
from iOpenPod.app.podcasts.models import (
    ListeningRecord,
    PodcastEpisode,
    PodcastSnapshot,
    PodcastSubscription,
    PodcastSyncSettings,
    SubscriptionSource,
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


def test_feed_refresh_preserves_user_retention_choices() -> None:
    device = reconcile_device_podcasts(
        PodcastSnapshot(writable=True), (_device_episode(),)
    )
    configured = replace(
        device.subscriptions[0], sync_settings=PodcastSyncSettings(episode_slots=11)
    )
    device = replace(device, subscriptions=(configured,))
    fetched = replace(
        configured, title="New title", sync_settings=PodcastSyncSettings()
    )

    refreshed = merge_fetched_subscription(device, fetched)

    assert refreshed.subscriptions[0].title == "New title"
    assert refreshed.subscriptions[0].sync_settings.episode_slots == 11


def test_changed_enclosure_with_unique_guid_retains_device_and_history_identity() -> (
    None
):
    device = reconcile_device_podcasts(
        PodcastSnapshot(writable=True), (_device_episode(play_count=2),)
    )
    subscription = device.subscriptions[0]
    original = subscription.episodes[0]
    changed = replace(
        original,
        episode_id="new-enclosure",
        enclosure_url="https://new.example.test/episode.mp3",
        on_device=False,
        track_id=None,
        play_count=0,
    )
    fetched = replace(subscription, episodes=(changed,))

    refreshed = merge_fetched_subscription(device, fetched)

    assert len(refreshed.subscriptions[0].episodes) == 1
    retained = refreshed.subscriptions[0].episodes[0]
    assert retained.episode_id == original.episode_id
    assert retained.enclosure_url == changed.enclosure_url
    assert retained.track_id == 41
    assert retained.listened is True


def test_history_guid_retains_listened_state_after_removal_restart_and_url_change() -> (
    None
):
    device = reconcile_device_podcasts(
        PodcastSnapshot(writable=True), (_device_episode(play_count=2),)
    )
    subscription = replace(device.subscriptions[0], episodes=())
    restarted = replace(device, subscriptions=(subscription,))
    fetched_episode = PodcastEpisode(
        "new-url", guid="guid-1", enclosure_url="https://new.example.test/episode.mp3"
    )

    refreshed = merge_fetched_subscription(
        restarted, replace(subscription, episodes=(fetched_episode,))
    )

    episode = refreshed.subscriptions[0].episodes[0]
    assert episode.episode_id == device.history[0].episode_id
    assert episode.listened is True
    assert episode.on_device is False


def test_device_reconciliation_retains_unique_guid_when_url_changes() -> None:
    device = reconcile_device_podcasts(
        PodcastSnapshot(writable=True), (_device_episode(),)
    )
    previous = device.subscriptions[0].episodes[0]
    changed = replace(
        _device_episode(),
        metadata=replace(
            _device_episode().metadata,
            podcast_enclosure_url="https://new.example.test/episode.mp3",
        ),
    )

    reconciled = reconcile_device_podcasts(device, (changed,))

    assert len(reconciled.subscriptions[0].episodes) == 1
    assert reconciled.subscriptions[0].episodes[0].episode_id == previous.episode_id


def test_ambiguous_history_guids_do_not_transfer_listened_override() -> None:
    subscription = PodcastSubscription(
        "show", "https://example.test/feed", "Show", SubscriptionSource.USER
    )
    snapshot = PodcastSnapshot(
        (subscription,),
        history=(
            ListeningRecord("show", "one", guid="same", listened_override=True),
            ListeningRecord("show", "two", guid="same", listened_override=True),
        ),
        writable=True,
    )
    refreshed = merge_fetched_subscription(
        snapshot,
        replace(subscription, episodes=(PodcastEpisode("three", guid="same"),)),
    )
    assert refreshed.subscriptions[0].episodes[0].episode_id == "three"
    assert refreshed.subscriptions[0].episodes[0].listened is False


def test_repeated_feed_guids_keep_distinct_episode_identities() -> None:
    original = replace(_episode_from_fixture(), guid="shared")
    subscription = PodcastSubscription(
        "show",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
        episodes=(original,),
    )
    fetched = replace(
        subscription,
        episodes=(
            replace(
                original,
                episode_id="first-new-url",
                enclosure_url="https://example.test/one.mp3",
                on_device=False,
                track_id=None,
            ),
            replace(
                original,
                episode_id="second-new-url",
                enclosure_url="https://example.test/two.mp3",
                on_device=False,
                track_id=None,
            ),
        ),
    )
    refreshed = merge_fetched_subscription(
        PodcastSnapshot((subscription,), writable=True), fetched
    )
    assert len(refreshed.subscriptions[0].episodes) == 3


def _episode_from_fixture() -> PodcastEpisode:
    snapshot = reconcile_device_podcasts(
        PodcastSnapshot(writable=True), (_device_episode(),)
    )
    return snapshot.subscriptions[0].episodes[0]


def test_refresh_drops_absent_history_only_episode_without_deleting_history() -> None:
    episode = PodcastEpisode(
        "old", guid="old", title="Old", enclosure_url="https://example.test/old.mp3"
    )
    subscription = PodcastSubscription(
        "show",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
        episodes=(episode,),
    )
    history = ListeningRecord("show", "old", guid="old", listened_override=False)
    snapshot = PodcastSnapshot((subscription,), (history,), writable=True)

    refreshed = merge_fetched_subscription(snapshot, replace(subscription, episodes=()))

    assert refreshed.subscriptions[0].episodes == ()
    assert refreshed.history == (history,)


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


def test_automatic_clear_retains_unlistened_state_and_publication_metadata() -> None:
    snapshot = reconcile_device_podcasts(
        PodcastSnapshot(writable=True), (_device_episode(),)
    )
    subscription = snapshot.subscriptions[0]
    episode = subscription.episodes[0]

    cleared = mark_episodes_automatically_cleared(
        snapshot, ((subscription.subscription_id, episode.episode_id),)
    )

    record = cleared.history[0]
    assert record.automatically_cleared is True
    assert record.listened is False and record.listened_override is None
    assert record.observed_play_count == record.last_played == 0
    assert record.published_at == episode.published_at
    assert record.episode_number == episode.episode_number
    assert record.guid == episode.guid and record.enclosure_url == episode.enclosure_url
    projected = cleared.subscriptions[0].episodes[0]
    assert projected.automatically_cleared and not projected.listened
    # Planning desired history does not itself alter device membership or input.
    assert projected.on_device and not snapshot.history


@pytest.mark.parametrize("listened", (True, False))
def test_listened_edits_preserve_existing_automatic_clearance(listened: bool) -> None:
    snapshot = reconcile_device_podcasts(
        PodcastSnapshot(writable=True), (_device_episode(play_count=2),)
    )
    subscription = snapshot.subscriptions[0]
    episode = subscription.episodes[0]
    cleared = mark_episodes_automatically_cleared(
        snapshot, ((subscription.subscription_id, episode.episode_id),)
    )

    edited = mark_episodes_listened(
        cleared,
        subscription.subscription_id,
        (episode.episode_id,),
        listened,
        changed_at=1_720_000_000,
    )

    record = edited.history[0]
    assert record.automatically_cleared and record.listened is listened
    assert record.observed_play_count == 2
    assert record.published_at == episode.published_at
    assert record.episode_number == episode.episode_number
    assert edited.subscriptions[0].episodes[0].automatically_cleared


def test_automatic_clear_preserves_explicit_unlistened_override() -> None:
    snapshot = reconcile_device_podcasts(
        PodcastSnapshot(writable=True), (_device_episode(play_count=2),)
    )
    subscription = snapshot.subscriptions[0]
    episode = subscription.episodes[0]
    unlistened = mark_episodes_listened(
        snapshot,
        subscription.subscription_id,
        (episode.episode_id,),
        False,
        changed_at=1_720_000_000,
    )

    cleared = mark_episodes_automatically_cleared(
        unlistened, ((subscription.subscription_id, episode.episode_id),)
    )

    assert cleared.history[0] == replace(
        unlistened.history[0], automatically_cleared=True
    )
    assert cleared.history[0].listened is False


def test_automatic_clear_survives_restart_guid_url_change_and_manual_readdition() -> (
    None
):
    track = _device_episode()
    snapshot = reconcile_device_podcasts(PodcastSnapshot(writable=True), (track,))
    subscription = snapshot.subscriptions[0]
    episode = subscription.episodes[0]
    cleared = mark_episodes_automatically_cleared(
        snapshot, ((subscription.subscription_id, episode.episode_id),)
    )
    # Episode catalogs are not persisted. Only independent history survives restart.
    restarted = replace(cleared, subscriptions=(replace(subscription, episodes=()),))
    new_url = "https://updated.example.test/episode.mp3"
    fetched = replace(
        subscription,
        episodes=(
            replace(
                episode,
                episode_id="new-url",
                enclosure_url=new_url,
                on_device=False,
                track_id=None,
            ),
        ),
    )

    refreshed = merge_fetched_subscription(restarted, fetched)
    changed_track = replace(
        track, metadata=replace(track.metadata, podcast_enclosure_url=new_url)
    )
    readded = reconcile_device_podcasts(refreshed, (changed_track,))

    assert len(readded.subscriptions[0].episodes) == 1
    retained = readded.subscriptions[0].episodes[0]
    assert retained.episode_id == episode.episode_id and retained.on_device
    assert retained.automatically_cleared and not retained.listened
    assert readded.history[0].automatically_cleared
    assert readded.history[0].enclosure_url == new_url
    assert readded.history[0].published_at == episode.published_at


def test_feed_enriches_legacy_history_and_retains_order_after_episode_disappears() -> (
    None
):
    episode = _episode_from_fixture()
    subscription = PodcastSubscription(
        "show",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
    )
    record = ListeningRecord(
        "show",
        episode.episode_id,
        guid=episode.guid,
        listened_override=True,
    )
    snapshot = PodcastSnapshot((subscription,), (record,), writable=True)
    fetched = replace(
        subscription, episodes=(replace(episode, on_device=False, track_id=None),)
    )

    enriched = merge_fetched_subscription(snapshot, fetched)
    absent = merge_fetched_subscription(enriched, replace(subscription, episodes=()))

    assert absent.subscriptions[0].episodes == ()
    assert absent.history[0].published_at == episode.published_at
    assert absent.history[0].episode_number == episode.episode_number
    assert absent.history[0].listened and not absent.history[0].automatically_cleared


def test_device_reconciliation_enriches_legacy_history_ordering() -> None:
    track = _device_episode(play_count=1)
    snapshot = reconcile_device_podcasts(PodcastSnapshot(writable=True), (track,))
    legacy = replace(
        snapshot,
        history=(replace(snapshot.history[0], published_at=0, episode_number=None),),
    )

    refreshed = reconcile_device_podcasts(legacy, (track,))

    assert refreshed.history[0].published_at == track.metadata.release_date
    assert refreshed.history[0].episode_number == track.episode_number


@pytest.mark.parametrize("selections", ((), (("missing", "episode"),)))
def test_automatic_clear_rejects_missing_selections(
    selections: tuple[tuple[str, str], ...],
) -> None:
    snapshot = reconcile_device_podcasts(
        PodcastSnapshot(writable=True), (_device_episode(),)
    )

    with pytest.raises(ValueError):
        mark_episodes_automatically_cleared(snapshot, selections)
    assert not snapshot.history
