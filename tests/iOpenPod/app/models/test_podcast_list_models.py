"""Tests for the aggregate Podcast feed projection."""

from PySide6.QtCore import Qt

from iOpenPod.app.models.podcast_list_models import (
    ALL_PODCASTS_SOURCE_ID,
    PodcastEpisodeFilter,
    PodcastEpisodeListModel,
    PodcastListRole,
    PodcastSubscriptionListModel,
)
from iOpenPod.app.podcasts.models import (
    PodcastEpisode,
    PodcastSubscription,
    SubscriptionSource,
)


def _subscriptions() -> tuple[PodcastSubscription, ...]:
    return (
        PodcastSubscription(
            "first-show",
            "https://example.test/first",
            "First Show",
            SubscriptionSource.USER,
            author="First Network",
            episodes=(
                PodcastEpisode(
                    "older",
                    title="An older episode",
                    published_at=100,
                ),
            ),
        ),
        PodcastSubscription(
            "second-show",
            "https://example.test/second",
            "Second Show",
            SubscriptionSource.USER,
            author="Second Network",
            episodes=(
                PodcastEpisode(
                    "newer",
                    title="A newer episode",
                    published_at=200,
                    on_device=True,
                    track_id=42,
                ),
            ),
        ),
    )


def test_subscription_model_can_prepend_an_all_podcasts_source() -> None:
    model = PodcastSubscriptionListModel()
    subscriptions = _subscriptions()

    model.replace(subscriptions, include_all=True)

    aggregate = model.index(0, 0)
    assert model.rowCount() == 3
    assert aggregate.data(Qt.ItemDataRole.DisplayRole) == "All Podcasts"
    assert aggregate.data(PodcastListRole.IDENTITY) == ALL_PODCASTS_SOURCE_ID
    assert aggregate.data(PodcastListRole.IS_AGGREGATE) is True
    assert aggregate.data(PodcastListRole.EPISODE_COUNT) == 2
    assert aggregate.data(PodcastListRole.ON_DEVICE_COUNT) == 1
    assert aggregate.data(PodcastListRole.SUBSCRIPTIONS) == subscriptions
    assert model.subscription_at(0) is None
    assert model.subscription_at(1) is subscriptions[0]
    assert model.row_for_id(None) == 0
    assert model.row_for_id("second-show") == 2


def test_all_podcasts_feed_is_newest_first_and_keeps_show_identities() -> None:
    model = PodcastEpisodeListModel()
    subscriptions = _subscriptions()

    model.replace_all(subscriptions)

    assert model.rowCount() == 2
    assert model.index(0, 0).data() == "A newer episode"
    assert model.identity_at(0) == ("second-show", "newer")
    assert model.index(0, 0).data(PodcastListRole.SUBSCRIPTION_TITLE) == "Second Show"
    assert model.index(1, 0).data() == "An older episode"


def test_all_podcasts_feed_searches_show_metadata_and_reuses_filters() -> None:
    model = PodcastEpisodeListModel()
    subscriptions = _subscriptions()

    model.replace_all(subscriptions, "Second Network")
    assert model.rowCount() == 1
    assert model.identity_at(0) == ("second-show", "newer")

    model.replace_all(
        subscriptions,
        episode_filter=PodcastEpisodeFilter(include_on_ipod=False),
    )
    assert model.rowCount() == 1
    assert model.identity_at(0) == ("first-show", "older")
