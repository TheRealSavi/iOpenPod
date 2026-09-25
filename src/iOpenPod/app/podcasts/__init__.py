"""Typed podcast catalog, persistence, and device reconciliation."""

from iOpenPod.app.podcasts.catalog import (
    mark_episode_selection_listened,
    mark_episodes_listened,
    merge_fetched_subscription,
    reconcile_device_podcasts,
    remove_subscription,
)
from iOpenPod.app.podcasts.documents import (
    PodcastDocumentError,
    decode_history,
    decode_subscriptions,
    encode_history,
    encode_subscriptions,
)
from iOpenPod.app.podcasts.models import (
    ListeningRecord,
    PodcastArtworkImage,
    PodcastArtworkRequest,
    PodcastEpisode,
    PodcastIssue,
    PodcastIssueCode,
    PodcastSearchResult,
    PodcastSnapshot,
    PodcastSubscription,
    SubscriptionSource,
)

__all__ = [
    "ListeningRecord",
    "PodcastArtworkImage",
    "PodcastArtworkRequest",
    "PodcastDocumentError",
    "PodcastEpisode",
    "PodcastIssue",
    "PodcastIssueCode",
    "PodcastSearchResult",
    "PodcastSnapshot",
    "PodcastSubscription",
    "SubscriptionSource",
    "decode_history",
    "decode_subscriptions",
    "encode_history",
    "encode_subscriptions",
    "mark_episode_selection_listened",
    "mark_episodes_listened",
    "merge_fetched_subscription",
    "reconcile_device_podcasts",
    "remove_subscription",
]
