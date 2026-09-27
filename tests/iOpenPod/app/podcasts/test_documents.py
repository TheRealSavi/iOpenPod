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
    PodcastClearAge,
    PodcastClearMethod,
    PodcastEpisode,
    PodcastFillMode,
    PodcastSubscription,
    PodcastSyncSettings,
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
            published_at=1_600_000_000,
            episode_number=12,
            automatically_cleared=True,
        ),
    )

    encoded = encode_history(records)

    assert decode_history(encoded) == records
    assert json.loads(encoded)["schema"] == "iopenpod.podcast-listening-history"
    assert json.loads(encoded)["version"] == 2


def test_legacy_history_loads_without_invented_publication_or_clear_state() -> None:
    payload = b'{"schema":"iopenpod.podcast-listening-history","version":1,"records":[{"subscription_id":"show","episode_id":"episode","listened_override":false,"observed_play_count":2,"last_played":17}]}'

    records = decode_history(payload)

    assert records == (
        ListeningRecord(
            "show",
            "episode",
            listened_override=False,
            observed_play_count=2,
            last_played=17,
        ),
    )
    assert records[0].published_at == 0
    assert records[0].episode_number is None
    assert records[0].automatically_cleared is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("published_at", -1),
        ("published_at", True),
        ("published_at", 1.5),
        ("published_at", "123"),
        ("episode_number", -1),
        ("episode_number", True),
        ("episode_number", 1.5),
        ("episode_number", "7"),
        ("automatically_cleared", 1),
        ("automatically_cleared", None),
        ("automatically_cleared", "false"),
    ),
)
def test_invalid_version_two_history_fields_fail_closed(
    field: str, value: object
) -> None:
    document = json.loads(encode_history((ListeningRecord("show", "episode"),)))
    document["records"][0][field] = value

    with pytest.raises(PodcastDocumentError):
        decode_history(json.dumps(document).encode())


@pytest.mark.parametrize(
    "field", ("published_at", "episode_number", "automatically_cleared")
)
def test_version_two_history_requires_clearance_and_ordering_fields(field: str) -> None:
    document = json.loads(encode_history((ListeningRecord("show", "episode"),)))
    del document["records"][0][field]

    with pytest.raises(PodcastDocumentError):
        decode_history(json.dumps(document).encode())


def test_version_two_history_does_not_silently_discard_unknown_fields() -> None:
    document = json.loads(encode_history((ListeningRecord("show", "episode"),)))
    document["records"][0]["future_retention_rule"] = True

    with pytest.raises(PodcastDocumentError):
        decode_history(json.dumps(document).encode())


@pytest.mark.parametrize("version", (True, 1.0, 2.0, "2", 99))
def test_history_version_must_be_a_supported_integer(version: object) -> None:
    payload = json.dumps(
        {
            "schema": "iopenpod.podcast-listening-history",
            "version": version,
            "records": [],
        }
    ).encode()

    with pytest.raises(PodcastDocumentError):
        decode_history(payload)


@pytest.mark.parametrize(
    "payload",
    (
        b"not json",
        b'{"schema":"wrong","version":1,"subscriptions":[]}',
        b'{"schema":"iopenpod.podcast-subscriptions","version":3,"subscriptions":[]}',
        b'{"schema":"iopenpod.podcast-subscriptions","version":1,"subscriptions":{}}',
    ),
)
def test_invalid_subscription_documents_fail_closed(payload: bytes) -> None:
    with pytest.raises(PodcastDocumentError):
        decode_subscriptions(payload)


def test_subscription_settings_round_trip_in_version_two() -> None:
    subscription = PodcastSubscription(
        "show",
        "https://example.test/feed",
        "Show",
        SubscriptionSource.USER,
        sync_settings=PodcastSyncSettings(
            episode_slots=7,
            fill_mode=PodcastFillMode.NEXT,
            clear_when_listened=False,
            clear_older_than=PodcastClearAge.WEEK,
            clear_method=PodcastClearMethod.REPLACE,
        ),
    )

    encoded = encode_subscriptions((subscription,))

    assert json.loads(encoded)["version"] == 2
    assert decode_subscriptions(encoded) == (subscription,)


def test_version_one_subscriptions_receive_original_defaults() -> None:
    payload = b'{"schema":"iopenpod.podcast-subscriptions","version":1,"subscriptions":[{"id":"show","title":"Show","source":"user"}]}'

    restored = decode_subscriptions(payload)

    assert restored[0].sync_settings == PodcastSyncSettings()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("episode_slots", 0),
        ("episode_slots", 51),
        ("episode_slots", True),
        ("episode_slots", 1.5),
        ("fill_mode", "surprise"),
        ("clear_when_listened", 1),
        ("clear_older_than", "tomorrow"),
        ("clear_method", "erase"),
    ),
)
def test_unsupported_retention_settings_fail_closed(field: str, value: object) -> None:
    subscription = PodcastSubscription("show", "", "Show", SubscriptionSource.USER)
    document = json.loads(encode_subscriptions((subscription,)))
    document["subscriptions"][0]["sync_settings"][field] = value

    with pytest.raises(PodcastDocumentError):
        decode_subscriptions(json.dumps(document).encode())


def test_version_two_requires_explicit_retention_settings() -> None:
    payload = b'{"schema":"iopenpod.podcast-subscriptions","version":2,"subscriptions":[{"id":"show","title":"Show","source":"user"}]}'

    with pytest.raises(PodcastDocumentError):
        decode_subscriptions(payload)


@pytest.mark.parametrize("version", (True, 1.0, 2.0, "2"))
def test_subscription_version_must_be_an_actual_integer(version: object) -> None:
    payload = json.dumps(
        {
            "schema": "iopenpod.podcast-subscriptions",
            "version": version,
            "subscriptions": [],
        }
    ).encode()
    with pytest.raises(PodcastDocumentError):
        decode_subscriptions(payload)
