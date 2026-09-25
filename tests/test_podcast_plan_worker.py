from types import SimpleNamespace

from iopenpod.application.jobs import build_podcast_plan_for_sync


class _Store:
    def __init__(self) -> None:
        self.updated_feeds: list | None = None

    def update_feeds(self, feeds: list) -> None:
        self.updated_feeds = feeds


def test_build_podcast_plan_refreshes_feeds_before_building_plan() -> None:
    original = SimpleNamespace(feed_url="https://example.test/feed", title="Show")
    refreshed = SimpleNamespace(feed_url=original.feed_url, title="Show refreshed")
    store = _Store()
    ipod_tracks = [{"Title": "Episode"}]
    seen = {}

    def fetch_feed(feed_url: str, *, existing):
        seen["fetch"] = (feed_url, existing)
        return refreshed

    def build_plan(feeds, tracks, plan_store):
        seen["build"] = (feeds, tracks, plan_store)
        return SimpleNamespace(to_add=[], to_remove=[])

    plan = build_podcast_plan_for_sync(
        [original],
        ipod_tracks,
        store,
        fetch_feed_fn=fetch_feed,
        build_plan_fn=build_plan,
    )

    assert plan.to_add == []
    assert store.updated_feeds is None
    assert plan._refreshed_podcast_feeds == [refreshed]
    assert seen["fetch"] == (original.feed_url, original)
    assert seen["build"] == ([refreshed], ipod_tracks, store)


def test_build_podcast_plan_falls_back_to_existing_feed_on_refresh_failure() -> None:
    original = SimpleNamespace(feed_url="https://example.test/feed", title="Show")
    store = _Store()
    seen = {}

    def fetch_feed(feed_url: str, *, existing):
        raise RuntimeError("rss unavailable")

    def build_plan(feeds, tracks, plan_store):
        seen["build"] = (feeds, tracks, plan_store)
        return SimpleNamespace(to_add=["episode"], to_remove=[])

    plan = build_podcast_plan_for_sync(
        [original],
        [],
        store,
        fetch_feed_fn=fetch_feed,
        build_plan_fn=build_plan,
    )

    assert plan.to_add == ["episode"]
    assert store.updated_feeds is None
    assert plan._refreshed_podcast_feeds == [original]
    assert seen["build"] == ([original], [], store)


def test_build_podcast_plan_skips_when_device_lacks_podcast_support() -> None:
    original = SimpleNamespace(feed_url="https://example.test/feed", title="Show")
    store = _Store()

    def fetch_feed(*_args, **_kwargs):
        raise AssertionError("feed refresh should not run")

    def build_plan(*_args, **_kwargs):
        raise AssertionError("plan builder should not run")

    plan = build_podcast_plan_for_sync(
        [original],
        [],
        store,
        supports_podcast=False,
        fetch_feed_fn=fetch_feed,
        build_plan_fn=build_plan,
    )

    assert plan.has_changes is False
    assert store.updated_feeds is None
