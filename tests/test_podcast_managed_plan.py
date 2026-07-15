from __future__ import annotations

import time

from iopenpod.podcasts.models import (
    STATUS_NOT_DOWNLOADED,
    STATUS_ON_IPOD,
    PodcastEpisode,
    PodcastFeed,
)
from iopenpod.podcasts.podcast_sync import build_podcast_managed_plan


def _episode(
    guid: str,
    title: str,
    pub_date: float,
    *,
    on_ipod: bool = False,
    db_track_id: int = 0,
    play_count: int = 0,
    listened_override: bool | None = None,
) -> PodcastEpisode:
    return PodcastEpisode(
        guid=guid,
        title=title,
        audio_url=f"https://example.test/{guid}.mp3",
        pub_date=pub_date,
        size_bytes=100,
        status=STATUS_ON_IPOD if on_ipod else STATUS_NOT_DOWNLOADED,
        ipod_db_track_id=db_track_id,
        play_count=play_count,
        listened_override=listened_override,
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


def _remove_ids(plan) -> list[int]:
    return [
        item.db_track_id
        for item in plan.to_remove
        if item.db_track_id is not None
    ]


def test_feed_serialization_keeps_played_not_downloaded_episode() -> None:
    episode = _episode(
        "played",
        "Played",
        100,
        play_count=1,
    )
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=[episode],
    )

    restored = PodcastFeed.from_dict(feed.to_dict())

    assert len(restored.episodes) == 1
    assert restored.episodes[0].guid == "played"
    assert restored.episodes[0].play_count == 1


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

    assert _remove_ids(plan) == [10]
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

    assert _remove_ids(plan) == [10]
    assert [item.pc_track.title for item in plan.to_add if item.pc_track] == ["Newer"]


# ── newest + replace + immediately: set-diff rotation ──────────────────────
# These cover the maintainer's recommended "always newest" preset from
# https://github.com/TheRealSavi/iOpenPod/issues/86 — the iPod should hold
# the top-N newest eligible episodes, swapping only what fell out of that
# set, not tearing down and refilling from older back-catalog entries.


def test_newest_replace_immediate_is_noop_when_already_holding_top_n() -> None:
    """If the on-iPod set already equals the top-N newest, do nothing.

    The pre-fix bug cleared all 5 and refilled from outside the on-iPod
    set, causing rotation into the back catalog on every sync.
    """
    eps = [
        _episode(f"e{i}", f"Ep {i}", pub_date=float(1000 - i),
                 on_ipod=True, db_track_id=i + 1)
        for i in range(5)
    ]
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=eps,
        episode_slots=5,
        fill_mode="newest",
        clear_when_listened=False,
        clear_older_than="immediate",
        clear_method="replace",
    )
    ipod_tracks = [_ipod_track(ep, feed) for ep in eps]

    plan = build_podcast_managed_plan([feed], ipod_tracks)

    assert plan.to_remove == []
    assert plan.to_add == []


def test_newest_replace_immediate_swaps_only_the_oldest_when_one_new_drops() -> None:
    """A single new episode → swap only the oldest on-iPod, keep the rest.

    This is the scenario from issue #86: with the broken algorithm,
    a single new episode caused 5 removes + 5 adds (1 newest + 4 from
    further down the feed).
    """
    on_ipod_eps = [
        _episode(f"on{i}", f"On {i}", pub_date=float(100 + i),
                 on_ipod=True, db_track_id=i + 1)
        for i in range(5)
    ]
    new_ep = _episode("new", "Brand New", pub_date=200.0)
    back_catalog = [
        _episode(f"old{i}", f"Old {i}", pub_date=float(50 - i))
        for i in range(5)
    ]
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=[new_ep, *on_ipod_eps, *back_catalog],
        episode_slots=5,
        fill_mode="newest",
        clear_when_listened=False,
        clear_older_than="immediate",
        clear_method="replace",
    )

    plan = build_podcast_managed_plan(
        [feed],
        [_ipod_track(ep, feed) for ep in on_ipod_eps],
    )

    assert _remove_ids(plan) == [1]  # "On 0", pub 100
    assert [item.pc_track.title for item in plan.to_add if item.pc_track] == ["Brand New"]


def test_newest_replace_initial_sync_adds_top_n() -> None:
    """First sync with an empty iPod → add the top-N newest episodes."""
    eps = [
        _episode(f"e{i}", f"Ep {i}", pub_date=float(100 - i))
        for i in range(10)
    ]
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=eps,
        episode_slots=5,
        fill_mode="newest",
        clear_when_listened=False,
        clear_older_than="immediate",
        clear_method="replace",
    )

    plan = build_podcast_managed_plan([feed], [])

    assert plan.to_remove == []
    titles = [item.pc_track.title for item in plan.to_add if item.pc_track]
    assert titles == ["Ep 0", "Ep 1", "Ep 2", "Ep 3", "Ep 4"]


def test_newest_replace_trims_when_slot_count_is_reduced() -> None:
    """If the user reduces episode_slots, trim down even without a new episode."""
    on_ipod_eps = [
        _episode(f"e{i}", f"Ep {i}", pub_date=float(100 - i),
                 on_ipod=True, db_track_id=i + 1)
        for i in range(5)
    ]
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=on_ipod_eps,
        episode_slots=3,
        fill_mode="newest",
        clear_when_listened=False,
        clear_older_than="immediate",
        clear_method="replace",
    )
    base = time.time()
    ipod_tracks = [
        _ipod_track(ep, feed, date_added=base - (5 - i))
        for i, ep in enumerate(on_ipod_eps)
    ]

    plan = build_podcast_managed_plan([feed], ipod_tracks)

    # Top-3 newest are Ep 0, Ep 1, Ep 2 (db_track_ids 1, 2, 3).
    # Ep 3 and Ep 4 (ids 4, 5) fell out and should be removed.
    assert sorted(_remove_ids(plan)) == [4, 5]
    assert plan.to_add == []


def test_newest_replace_clear_when_listened_swaps_played_for_unheard() -> None:
    """clear_when_listened skips played episodes from "wanted"."""
    on_ipod_eps = [
        _episode(f"e{i}", f"Ep {i}", pub_date=float(100 - i),
                 on_ipod=True, db_track_id=i + 1)
        for i in range(5)
    ]
    next_unheard = _episode("next", "Next Unheard", pub_date=10.0)
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=[*on_ipod_eps, next_unheard],
        episode_slots=5,
        fill_mode="newest",
        clear_when_listened=True,
        clear_older_than="never",
        clear_method="replace",
    )
    # Mark the *newest* on-iPod episode as listened.
    ipod_tracks = [
        _ipod_track(ep, feed, play_count=1 if ep.guid == "e0" else 0)
        for ep in on_ipod_eps
    ]

    plan = build_podcast_managed_plan([feed], ipod_tracks)

    assert _remove_ids(plan) == [1]  # "Ep 0"
    assert [item.pc_track.title for item in plan.to_add if item.pc_track] == ["Next Unheard"]


def test_newest_clear_when_listened_does_not_readd_previously_played_episode() -> None:
    """A removed played episode should not become a top-N add on the next sync."""
    played_removed = _episode(
        "e0",
        "Already Played",
        pub_date=100.0,
        play_count=1,
    )
    staying_eps = [
        _episode(f"e{i}", f"Ep {i}", pub_date=float(100 - i),
                 on_ipod=True, db_track_id=i)
        for i in range(1, 4)
    ]
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=[played_removed, *staying_eps],
        episode_slots=3,
        fill_mode="newest",
        clear_when_listened=True,
        clear_older_than="never",
        clear_method="replace",
    )

    plan = build_podcast_managed_plan(
        [feed],
        [_ipod_track(ep, feed) for ep in staying_eps],
    )

    assert plan.to_remove == []
    assert plan.to_add == []


def test_newest_manual_unlistened_override_keeps_played_on_ipod_episode() -> None:
    episode = _episode(
        "current",
        "Current",
        100,
        on_ipod=True,
        db_track_id=10,
        listened_override=False,
    )
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=[episode],
        episode_slots=1,
        fill_mode="newest",
        clear_when_listened=True,
        clear_method="replace",
    )

    plan = build_podcast_managed_plan(
        [feed],
        [_ipod_track(episode, feed, play_count=1)],
    )

    assert plan.to_remove == []
    assert plan.to_add == []


def test_newest_manual_listened_override_replaces_unplayed_on_ipod_episode() -> None:
    current = _episode(
        "current",
        "Current",
        100,
        on_ipod=True,
        db_track_id=10,
        listened_override=True,
    )
    replacement = _episode("replacement", "Replacement", 90)
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=[current, replacement],
        episode_slots=1,
        fill_mode="newest",
        clear_when_listened=True,
        clear_method="replace",
    )

    plan = build_podcast_managed_plan(
        [feed],
        [_ipod_track(current, feed, play_count=0)],
    )

    assert _remove_ids(plan) == [10]
    assert [item.pc_track.title for item in plan.to_add if item.pc_track] == [
        "Replacement"
    ]


def test_newest_remove_immediate_is_noop_when_already_holding_top_n() -> None:
    """Same bug also affected ``newest + remove + immediate``.

    With set-diff semantics it becomes a no-op when the iPod already
    holds the top-N newest, instead of removing all 5 and refilling
    with the next 5 from the back catalog.
    """
    on_ipod_eps = [
        _episode(f"e{i}", f"Ep {i}", pub_date=float(100 - i),
                 on_ipod=True, db_track_id=i + 1)
        for i in range(5)
    ]
    back_catalog = [
        _episode(f"old{i}", f"Old {i}", pub_date=float(50 - i))
        for i in range(5)
    ]
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        episodes=[*on_ipod_eps, *back_catalog],
        episode_slots=5,
        fill_mode="newest",
        clear_when_listened=False,
        clear_older_than="immediate",
        clear_method="remove",
    )

    plan = build_podcast_managed_plan(
        [feed],
        [_ipod_track(ep, feed) for ep in on_ipod_eps],
    )

    assert plan.to_remove == []
    assert plan.to_add == []
