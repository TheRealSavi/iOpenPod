"""Selected publisher fields survive parsing, refresh, persistence and import."""

import json
from dataclasses import replace

import pytest

from iOpenPod.app.podcasts import feed_client
from iOpenPod.app.podcasts.catalog import (
    merge_fetched_subscription,
    reconcile_device_podcasts,
)
from iOpenPod.app.podcasts.documents import (
    PodcastDocumentError,
    decode_subscriptions,
    encode_subscriptions,
)
from iOpenPod.app.podcasts.feed_client import FeedparserPodcastClient
from iOpenPod.app.podcasts.media import episode_track
from iOpenPod.app.podcasts.models import (
    PodcastChapterImage,
    PodcastEpisodeType,
    PodcastShowType,
    PodcastSnapshot,
    PodcastSubscription,
    PodcastSyncSettings,
)
from iOpenPod.app.podcasts.sync import PodcastEpisodeAddition

FEED = b"""<rss version="2.0" xmlns:apple="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:p="https://podcastindex.org/namespace/1.0" xmlns:c="http://podlove.org/simple-chapters">
<channel><title>Show</title><apple:author>Studio</apple:author><copyright>Publisher copyright</copyright><link>https://publisher.test/show</link><apple:type>serial</apple:type>
<apple:category text="Technology"><apple:category text="Gadgets"/></apple:category><apple:category text="Education"/><category>Technology</category><apple:image href="https://publisher.test/show.jpg"/>
<item><guid isPermaLink="false">opaque-guid</guid><title>Episode</title><apple:author>Guest &amp; Host</apple:author><author>mail@example.test</author><apple:episodeType>bonus</apple:episodeType><link>https://publisher.test/episode#notes</link>
<description>&lt;p&gt;Notes: &lt;a href="/source#section"&gt;Read &amp;amp; learn&lt;/a&gt; &lt;a href="javascript:alert(1)"&gt;bad&lt;/a&gt;&lt;/p&gt;</description>
<enclosure url="https://publisher.test/episode.mp3" type="audio/mpeg" length="5"/><apple:image href="episode.jpg"/>
<p:chapters url="images.json" type="application/json+chapters"/><c:chapters version="1.2"><c:chapter start="00:00:01.125" title="Do not import this chapter" image="slide.jpg"/><c:chapter start="NaN" image="bad.jpg"/></c:chapters></item></channel></rss>"""


def fetch(
    monkeypatch: pytest.MonkeyPatch, payload: bytes = FEED
) -> PodcastSubscription:
    def request(url: str, **_kwargs: object) -> tuple[bytes, str]:
        return payload, "https://publisher.test/feed.xml"

    monkeypatch.setattr(feed_client, "request_podcast_bytes", request)
    return FeedparserPodcastClient().fetch("https://publisher.test/feed.xml")


def test_publisher_fields_reach_typed_catalog_and_supported_native_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    show = fetch(monkeypatch)
    episode = show.episodes[0]
    assert show.categories == ("Technology", "Gadgets", "Education")
    assert show.category == "Technology"
    assert show.copyright == "Publisher copyright"
    assert show.website_url == "https://publisher.test/show"
    assert show.show_type is PodcastShowType.SERIAL
    assert episode.author == "Guest & Host"
    assert episode.episode_type is PodcastEpisodeType.BONUS
    assert episode.website_url == "https://publisher.test/episode#notes"
    assert [link.url for link in episode.links] == [
        episode.website_url,
        "https://publisher.test/source#section",
    ]
    assert episode.links[1].title == "Read & learn"
    assert episode.artwork_url == "https://publisher.test/episode.jpg"
    assert episode.chapter_document_url == "https://publisher.test/images.json"
    assert episode.chapter_images == (
        PodcastChapterImage(1125, "https://publisher.test/slide.jpg"),
    )
    track = episode_track(PodcastEpisodeAddition(show, episode))
    assert track.artist == "Guest & Host"
    assert track.album_artist == "Studio"
    assert track.metadata.copyright == "Publisher copyright"
    assert track.metadata.category == "Technology"
    assert not track.metadata.chapters


def test_refresh_and_reconciliation_keep_extended_fields_and_user_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    show = fetch(monkeypatch)
    episode = show.episodes[0]
    settings = PodcastSyncSettings(episode_slots=7)
    old = replace(
        show,
        sync_settings=settings,
        episodes=(replace(episode, on_device=True, track_id=1, listened=True),),
    )
    snapshot = merge_fetched_subscription(PodcastSnapshot(subscriptions=(old,)), show)
    assert snapshot.subscriptions[0].sync_settings == settings
    assert snapshot.subscriptions[0].episodes[0].links == episode.links
    track = replace(episode_track(PodcastEpisodeAddition(show, episode)), track_id=1)
    reconciled = (
        reconcile_device_podcasts(snapshot, (track,)).subscriptions[0].episodes[0]
    )
    assert reconciled.author == episode.author
    assert reconciled.artwork_url == episode.artwork_url
    assert reconciled.chapter_images == episode.chapter_images
    assert reconciled.on_device


def test_refreshed_author_survives_a_legacy_show_artist_on_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    show = fetch(monkeypatch)
    episode = show.episodes[0]
    track = replace(
        episode_track(PodcastEpisodeAddition(show, episode)),
        track_id=1,
        artist=show.author,
    )
    snapshot = reconcile_device_podcasts(
        PodcastSnapshot(subscriptions=(show,)), (track,)
    )
    assert snapshot.subscriptions[0].episodes[0].author == episode.author


def test_subscription_v3_roundtrip_and_v2_migration_preserve_retention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    show = replace(
        fetch(monkeypatch), sync_settings=PodcastSyncSettings(episode_slots=9)
    )
    encoded = encode_subscriptions((show,))
    assert decode_subscriptions(encoded) == (replace(show, episodes=()),)
    document = json.loads(encoded)
    document["version"] = 2
    for name in ("categories", "copyright", "website_url", "show_type"):
        document["subscriptions"][0].pop(name)
    restored = decode_subscriptions(json.dumps(document).encode())[0]
    assert restored.sync_settings == show.sync_settings
    assert not restored.categories and not restored.copyright
    assert restored.show_type is PodcastShowType.UNSPECIFIED


@pytest.mark.parametrize(
    "field,value",
    [
        ("categories", "Technology"),
        ("categories", [False]),
        ("show_type", "unknown"),
        ("copyright", 5),
    ],
)
def test_malformed_extended_saved_metadata_fails_closed(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    document = json.loads(encode_subscriptions((fetch(monkeypatch),)))
    document["subscriptions"][0][field] = value
    with pytest.raises(PodcastDocumentError):
        decode_subscriptions(json.dumps(document).encode())


def test_missing_optional_metadata_has_no_invented_artist_or_website(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    show = fetch(
        monkeypatch,
        b'<rss><channel><title>Show</title><item><guid isPermaLink="false">opaque</guid><author>mail@example.test</author><enclosure url="https://publisher.test/episode.mp3" type="audio/mpeg"/></item></channel></rss>',
    )
    episode = show.episodes[0]
    assert not episode.author and not episode.website_url
    assert not episode.artwork_url and not episode.links
    assert episode.episode_type is PodcastEpisodeType.UNSPECIFIED
