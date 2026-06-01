from __future__ import annotations

import time

from PodcastManager.models import (
    STATUS_NOT_DOWNLOADED,
    STATUS_ON_IPOD,
    PodcastEpisode,
    PodcastFeed,
)
from PodcastManager.podcast_sync import build_podcast_managed_plan


def _episode(
    guid: str,
    title: str,
    pub_date: float,
    *,
    on_ipod: bool = False,
    db_track_id: int = 0,
) -> PodcastEpisode:
    return PodcastEpisode(
        guid=guid,
        title=title,
        audio_url=f"https://example.test/{guid}.mp3",
        pub_date=pub_date,
        size_bytes=100,
        status=STATUS_ON_IPOD if on_ipod else STATUS_NOT_DOWNLOADED,
        ipod_db_track_id=db_track_id,
    )


def _ipod_track(
    episode: PodcastEpisode,
    feed: PodcastFeed,
    *,
    play_count: int = 0,
    date_added: float | None = None,
) -> dict:
    return {
        "media_type": 0x04,
        "db_track_id": episode.ipod_db_track_id,
        "Podcast Enclosure URL": episode.audio_url,
        "Title": episode.title,
        "Album": feed.title,
        "play_count_1": play_count,
        "date_added": date_added if date_added is not None else time.time(),
        "size": 100,
    }


def test_replace_mode_does_not_clear_listened_episode_without_next_episode() -> None:
    older = _episode("older", "Older", 100)
    current = _episode("current", "Current", 200, on_ipod=True, db_track_id=10)
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=[older, current],
        episode_slots=1,
        fill_mode="next",
        clear_when_listened=True,
        clear_method="replace",
    )

    plan = build_podcast_managed_plan(
        [feed],
        [_ipod_track(current, feed, play_count=1)],
    )

    assert plan.to_remove == []
    assert plan.to_add == []


def test_replace_mode_clears_listened_episode_when_next_episode_exists() -> None:
    current = _episode("current", "Current", 200, on_ipod=True, db_track_id=10)
    newer = _episode("newer", "Newer", 300)
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=[current, newer],
        episode_slots=1,
        fill_mode="next",
        clear_when_listened=True,
        clear_method="replace",
    )

    plan = build_podcast_managed_plan(
        [feed],
        [_ipod_track(current, feed, play_count=1)],
    )

    assert [item.db_track_id for item in plan.to_remove] == [10]
    assert [item.pc_track.title for item in plan.to_add if item.pc_track] == ["Newer"]


def test_replace_mode_does_not_clear_aged_episode_without_replacement() -> None:
    current = _episode("current", "Current", 200, on_ipod=True, db_track_id=10)
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=[current],
        episode_slots=1,
        fill_mode="newest",
        clear_when_listened=False,
        clear_older_than="1_day",
        clear_method="replace",
    )

    plan = build_podcast_managed_plan(
        [feed],
        [
            _ipod_track(
                current,
                feed,
                date_added=time.time() - (3 * 86400),
            )
        ],
    )

    assert plan.to_remove == []
    assert plan.to_add == []


def test_immediate_age_rule_replaces_with_newest_available_episode() -> None:
    current = _episode("current", "Current", 200, on_ipod=True, db_track_id=10)
    older = _episode("older", "Older", 100)
    newer = _episode("newer", "Newer", 300)
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=[older, current, newer],
        episode_slots=1,
        fill_mode="newest",
        clear_when_listened=False,
        clear_older_than="immediate",
        clear_method="replace",
    )

    plan = build_podcast_managed_plan(
        [feed],
        [_ipod_track(current, feed, date_added=time.time() - 1)],
    )

    assert [item.db_track_id for item in plan.to_remove] == [10]
    assert [item.pc_track.title for item in plan.to_add if item.pc_track] == ["Newer"]
