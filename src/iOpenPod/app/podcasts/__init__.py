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
    PodcastClearAge,
    PodcastClearMethod,
    PodcastEpisode,
    PodcastFillMode,
    PodcastIssue,
    PodcastIssueCode,
    PodcastSearchResult,
    PodcastSnapshot,
    PodcastSubscription,
    PodcastSyncSettings,
    SubscriptionSource,
)

__all__ = [
    "ListeningRecord",
    "PodcastArtworkImage",
    "PodcastArtworkRequest",
    "PodcastClearAge",
    "PodcastClearMethod",
    "PodcastDocumentError",
    "PodcastEpisode",
    "PodcastFillMode",
    "PodcastIssue",
    "PodcastIssueCode",
    "PodcastSearchResult",
    "PodcastSnapshot",
    "PodcastSubscription",
    "PodcastSyncSettings",
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
