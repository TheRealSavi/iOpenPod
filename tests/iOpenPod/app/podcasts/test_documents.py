import json
from dataclasses import replace

import pytest

from iOpenPod.app.podcasts.documents import (
    PodcastDocumentError,
    decode_history,
    decode_subscriptions,
    encode_history,
    encode_subscriptions,
)
from iOpenPod.app.podcasts.models import (
    ListeningRecord,
    PodcastEpisode,
    PodcastSubscription,
    SubscriptionSource,
)


def test_subscription_document_contains_show_metadata_but_not_episodes() -> None:
    episode = PodcastEpisode(
        "episode-1",
        guid="guid",
        title="Episode",
        enclosure_url="https://example.test/episode.mp3",
        on_device=True,
        track_id=92,
        listened=True,
        play_count=4,
    )
    subscription = PodcastSubscription(
        "feed-1",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
        episodes=(episode,),
    )

    encoded = encode_subscriptions((subscription,))
    document = json.loads(encoded)
    decoded = decode_subscriptions(encoded)

    assert "episodes" not in document["subscriptions"][0]
    assert decoded == (replace(subscription, episodes=()),)


def test_listening_history_has_its_own_versioned_document() -> None:
    records = (
        ListeningRecord(
            "feed-1",
            "episode-1",
            title="Episode",
            listened_override=True,
            observed_play_count=3,
            last_played=1_700_000_000,
        ),
    )

    encoded = encode_history(records)

    assert decode_history(encoded) == records
    assert json.loads(encoded)["schema"] == "iopenpod.podcast-listening-history"


@pytest.mark.parametrize(
    "payload",
    (
        b"not json",
        b'{"schema":"wrong","version":1,"subscriptions":[]}',
        b'{"schema":"iopenpod.podcast-subscriptions","version":2,"subscriptions":[]}',
        b'{"schema":"iopenpod.podcast-subscriptions","version":1,"subscriptions":{}}',
    ),
)
def test_invalid_subscription_documents_fail_closed(payload: bytes) -> None:
    with pytest.raises(PodcastDocumentError):
        decode_subscriptions(payload)
