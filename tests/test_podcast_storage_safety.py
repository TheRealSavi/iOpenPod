from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from iopenpod.device.write_guard import DeviceWriteSafetyError
from iopenpod.gui.widgets.podcastBrowser import PodcastBrowser
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.podcasts.artwork import cache_feed_artwork
from iopenpod.podcasts.models import (
    STATUS_DOWNLOADED,
    STATUS_NOT_DOWNLOADED,
    STATUS_ON_IPOD,
    PodcastEpisode,
    PodcastFeed,
)
from iopenpod.podcasts.subscription_store import SubscriptionStore
from iopenpod.sync.contracts import SyncAction, SyncItem, SyncPlan
from iopenpod.sync.mapping import MappingFile
from iopenpod.sync.sync_executor import SyncExecutor, _SyncContext


def _virtual_ipod(root: Path) -> None:
    (root / "iPod_Control" / "iTunes").mkdir(parents=True)
    (root / "iPodInfo.json").write_text("{}", encoding="utf-8")


def test_subscription_store_uses_guarded_metadata_writer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[tuple[Path, Path]] = []

    class _Writer:
        def write_text_atomic(
            self,
            relative_path: Path,
            _text: str,
            *,
            allowed_subtree: Path,
        ) -> Path:
            events.append((relative_path, allowed_subtree))
            return tmp_path / relative_path

    @contextmanager
    def guarded(*_args, **_kwargs):
        yield _Writer()

    monkeypatch.setattr(
        "iopenpod.podcasts.subscription_store.guarded_device_metadata_session",
        guarded,
    )
    store = SubscriptionStore(
        str(tmp_path),
        expected_volume_identity_key="scan-volume",
    )

    store.add_feed(PodcastFeed(feed_url="https://example.test/feed.xml"))

    expected = Path("iPod_Control") / "iOpenPodPodcasts"
    assert events == [(expected / "subscriptions.json", expected)]


def test_subscription_store_round_trip_on_virtual_ipod(tmp_path: Path) -> None:
    _virtual_ipod(tmp_path)
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Example",
    )

    store = SubscriptionStore(str(tmp_path))
    store.add_feed(feed)

    path = (
        tmp_path
        / "iPod_Control"
        / "iOpenPodPodcasts"
        / "subscriptions.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    loaded = SubscriptionStore(str(tmp_path)).get_feed(feed.feed_url)

    assert payload["feeds"][0]["title"] == "Example"
    assert loaded is not None
    assert loaded.title == "Example"


def test_corrupt_subscription_file_blocks_mutation_without_overwrite(
    tmp_path: Path,
) -> None:
    path = (
        tmp_path
        / "iPod_Control"
        / "iOpenPodPodcasts"
        / "subscriptions.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    original = path.read_bytes()
    store = SubscriptionStore(str(tmp_path))

    with pytest.raises(DeviceWriteSafetyError, match="left it unchanged"):
        store.add_feed(PodcastFeed(feed_url="https://example.test/new.xml"))

    assert path.read_bytes() == original


def test_remove_download_refuses_file_outside_host_podcast_cache(
    tmp_path: Path,
) -> None:
    ipod = tmp_path / "ipod"
    cache = tmp_path / "cache"
    unrelated = tmp_path / "personal-recording.mp3"
    unrelated.write_bytes(b"keep me")
    store = SubscriptionStore(str(ipod), download_cache_dir=str(cache))

    with pytest.raises(DeviceWriteSafetyError, match="podcast download cache"):
        store.remove_episode_download(unrelated)

    assert unrelated.read_bytes() == b"keep me"


def test_remove_download_refuses_legacy_ipod_resident_file(
    tmp_path: Path,
) -> None:
    ipod = tmp_path / "ipod"
    cache = tmp_path / "cache"
    legacy = (
        ipod
        / "iPod_Control"
        / "iOpenPodPodcasts"
        / "legacy-cache"
        / "episode.mp3"
    )
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"keep me")
    store = SubscriptionStore(str(ipod), download_cache_dir=str(cache))

    with pytest.raises(DeviceWriteSafetyError, match="podcast download cache"):
        store.remove_episode_download(legacy)

    assert legacy.read_bytes() == b"keep me"


def test_remove_download_removes_file_inside_host_podcast_cache(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    downloaded = cache / "podcasts" / "feed-id" / "episode.mp3"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_bytes(b"episode")
    store = SubscriptionStore(
        str(tmp_path / "ipod"),
        download_cache_dir=str(cache),
    )

    store.remove_episode_download(downloaded)

    assert not downloaded.exists()


def test_remove_feed_removes_host_podcast_downloads(tmp_path: Path) -> None:
    ipod = tmp_path / "ipod"
    _virtual_ipod(ipod)
    cache = tmp_path / "cache"
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Cached Show",
    )
    store = SubscriptionStore(str(ipod), download_cache_dir=str(cache))
    feed_dir = Path(store.feed_dir(feed))
    downloaded = feed_dir / "episode.mp3"
    stale = feed_dir / "stale-episode.mp3"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_bytes(b"episode")
    stale.write_bytes(b"old episode")
    feed.episodes.append(
        PodcastEpisode(
            guid="episode-1",
            status=STATUS_DOWNLOADED,
            downloaded_path=str(downloaded),
        )
    )
    store.add_feed(feed)

    removed = store.remove_feed(feed.feed_url)

    assert removed is not None
    assert not downloaded.exists()
    assert not stale.exists()
    assert not feed_dir.exists()
    assert store.get_feeds() == []


def test_prune_download_cache_removes_only_unreferenced_staging_files(
    tmp_path: Path,
) -> None:
    ipod = tmp_path / "ipod"
    _virtual_ipod(ipod)
    cache = tmp_path / "cache"
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Cached Show",
    )
    store = SubscriptionStore(str(ipod), download_cache_dir=str(cache))
    feed_dir = Path(store.feed_dir(feed))
    retained = feed_dir / "pending.mp3"
    stale = feed_dir / ".iop-interrupted.part"
    orphan_dir = cache / "podcasts" / "0123456789abcdef"
    orphaned = orphan_dir / "orphan.mp3"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"pending")
    stale.write_bytes(b"partial")
    orphan_dir.mkdir()
    orphaned.write_bytes(b"orphan")
    feed.episodes.append(
        PodcastEpisode(
            guid="episode-1",
            status=STATUS_DOWNLOADED,
            downloaded_path=str(retained),
        )
    )

    removed = store.prune_download_cache([feed])

    assert removed == 2
    assert retained.exists()
    assert not stale.exists()
    assert not orphaned.exists()
    assert not orphan_dir.exists()


def test_remove_download_refuses_symlink_inside_host_podcast_cache(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    feed_dir = cache / "podcasts" / "feed-id"
    feed_dir.mkdir(parents=True)
    target = feed_dir / "actual-episode.mp3"
    target.write_bytes(b"episode")
    linked = feed_dir / "stored-episode.mp3"
    try:
        linked.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    store = SubscriptionStore(
        str(tmp_path / "ipod"),
        download_cache_dir=str(cache),
    )

    with pytest.raises(DeviceWriteSafetyError, match="link|reparse"):
        store.remove_episode_download(linked)

    assert linked.is_symlink()
    assert target.read_bytes() == b"episode"


def test_remove_download_refuses_windows_reparse_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache = tmp_path / "cache"
    downloaded = cache / "podcasts" / "feed-id" / "episode.mp3"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_bytes(b"episode")
    real_lstat = os.lstat

    def reparse_lstat(path):
        result = real_lstat(path)
        if Path(path) == downloaded:
            return SimpleNamespace(
                st_mode=result.st_mode,
                st_file_attributes=0x400,
            )
        return result

    monkeypatch.setattr("iopenpod.device.path_safety.os.lstat", reparse_lstat)
    store = SubscriptionStore(
        str(tmp_path / "ipod"),
        download_cache_dir=str(cache),
    )

    with pytest.raises(DeviceWriteSafetyError, match="link/reparse"):
        store.remove_episode_download(downloaded)

    assert downloaded.read_bytes() == b"episode"


def test_browser_remove_download_preserves_episode_when_path_is_refused(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cache = tmp_path / "cache"
    unrelated = tmp_path / "personal-recording.mp3"
    unrelated.write_bytes(b"keep me")
    episode = PodcastEpisode(
        guid="episode-1",
        status=STATUS_DOWNLOADED,
        downloaded_path=str(unrelated),
    )
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        episodes=[episode],
    )

    class _Browser:
        _store = SubscriptionStore(
            str(tmp_path / "ipod"),
            download_cache_dir=str(cache),
        )
        _showing_combined_feed = False
        _selected_feed = feed

        def __init__(self) -> None:
            self.statuses: list[str] = []

        def _show_episodes(self, _feed) -> None:
            pass

        def _refresh_feed_list(self) -> None:
            pass

        def _set_action_status(self, text: str) -> None:
            self.statuses.append(text)

        def _persist_subscription_change(self, _action, _operation) -> bool:
            return True

    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "iopenpod.gui.widgets.podcastBrowser.QMessageBox.warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    browser = _Browser()

    PodcastBrowser._remove_download_refs(
        cast(PodcastBrowser, browser),
        [(0, episode, feed)],
    )

    assert unrelated.read_bytes() == b"keep me"
    assert episode.downloaded_path == str(unrelated)
    assert episode.status == STATUS_DOWNLOADED
    assert browser.statuses == ["1 download was not removed"]
    assert warnings and warnings[0][0] == "Download Not Removed"


def test_sync_update_removes_download_for_listened_podcast_removal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ipod = tmp_path / "ipod"
    cache = tmp_path / "cache"
    downloaded = cache / "podcasts" / "feed-id" / "episode.mp3"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_bytes(b"episode")
    episode = PodcastEpisode(
        guid="episode-1",
        title="Played Episode",
        audio_url="https://example.test/episode.mp3",
        status=STATUS_ON_IPOD,
        downloaded_path=str(downloaded),
        ipod_db_track_id=123,
    )
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Played Show",
        clear_when_listened=True,
        episodes=[episode],
    )
    updated_feeds: list[list[PodcastFeed]] = []

    class _Store:
        def __init__(self, *_args, **kwargs) -> None:
            assert kwargs["download_cache_dir"] == str(cache)
            self._real = SubscriptionStore(
                str(ipod),
                download_cache_dir=kwargs["download_cache_dir"],
            )

        def get_feeds(self) -> list[PodcastFeed]:
            return [feed]

        def cache_feed_artwork(self, _feed) -> None:
            pass

        def remove_episode_download(self, path: str) -> None:
            self._real.remove_episode_download(path)

        def prune_download_cache(self, feeds: list[PodcastFeed]) -> int:
            return self._real.prune_download_cache(feeds)

        def update_feeds(self, feeds: list[PodcastFeed]) -> int:
            updated_feeds.append(feeds)
            return len(feeds)

    monkeypatch.setattr(
        "iopenpod.podcasts.subscription_store.SubscriptionStore",
        _Store,
    )

    executor = SyncExecutor.__new__(SyncExecutor)
    executor.ipod_path = ipod
    executor.device_storage = SimpleNamespace(
        reported_volume_format="",
        volume_identity_key="",
    )
    executor.transcode_cache = cast(Any, SimpleNamespace(cache_dir=cache))
    executor._filesystem_profile = None
    ctx = _SyncContext(
        filesystem_profile=cast(Any, SimpleNamespace()),
        new_tracks=[],
        plan=SyncPlan(
            to_remove=[
                SyncItem(
                    action=SyncAction.REMOVE_FROM_IPOD,
                    db_track_id=123,
                    ipod_track={
                        "media_type": 0x04,
                        "Podcast Enclosure URL": episode.audio_url,
                        "play_count_1": 1,
                    },
                )
            ],
        ),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )

    executor._update_podcast_subscriptions(ctx)

    assert not downloaded.exists()
    assert episode.downloaded_path == ""
    assert episode.status == STATUS_NOT_DOWNLOADED
    assert updated_feeds == [[feed]]


def test_sync_update_removes_staging_download_after_podcast_add(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ipod = tmp_path / "ipod"
    cache = tmp_path / "cache"
    downloaded = cache / "podcasts" / "feed-id" / "episode.mp3"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_bytes(b"episode")
    episode = PodcastEpisode(
        guid="episode-1",
        title="Synced Episode",
        audio_url="https://example.test/episode.mp3",
        status=STATUS_DOWNLOADED,
        downloaded_path=str(downloaded),
    )
    feed = PodcastFeed(feed_url="https://example.test/feed.xml", episodes=[episode])
    updated_feeds: list[list[PodcastFeed]] = []

    class _Store:
        def __init__(self, *_args, **kwargs) -> None:
            self._real = SubscriptionStore(str(ipod), download_cache_dir=str(cache))

        def get_feeds(self) -> list[PodcastFeed]:
            return [feed]

        def cache_feed_artwork(self, _feed) -> None:
            pass

        def remove_episode_download(self, path: str) -> None:
            self._real.remove_episode_download(path)

        def prune_download_cache(self, feeds: list[PodcastFeed]) -> int:
            return self._real.prune_download_cache(feeds)

        def update_feeds(self, feeds: list[PodcastFeed]) -> int:
            updated_feeds.append(feeds)
            return len(feeds)

    monkeypatch.setattr("iopenpod.podcasts.subscription_store.SubscriptionStore", _Store)

    executor = SyncExecutor.__new__(SyncExecutor)
    executor.ipod_path = ipod
    executor.device_storage = SimpleNamespace(reported_volume_format="", volume_identity_key="")
    executor.transcode_cache = cast(Any, SimpleNamespace(cache_dir=cache))
    executor._filesystem_profile = None
    ctx = _SyncContext(
        filesystem_profile=cast(Any, SimpleNamespace()),
        new_tracks=[
            TrackInfo(
                title="Synced Episode",
                location=":iPod_Control:Music:F00:episode.mp3",
                media_type=0x04,
                podcast_enclosure_url=episode.audio_url,
                db_track_id=321,
            )
        ],
        plan=SyncPlan(),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )

    executor._update_podcast_subscriptions(ctx)

    assert not downloaded.exists()
    assert episode.downloaded_path == ""
    assert episode.status == STATUS_ON_IPOD
    assert episode.ipod_db_track_id == 321
    assert updated_feeds == [[feed]]


def test_artwork_cache_read_error_is_not_treated_as_cache_miss(
    monkeypatch,
    tmp_path: Path,
) -> None:
    original_stat = Path.stat

    def failing_stat(path: Path, *args, **kwargs):
        if path.suffix == ".jpg":
            raise OSError("simulated device I/O error")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", failing_stat)
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        artwork_url="https://example.test/cover.jpg",
    )

    with pytest.raises(OSError, match="device I/O error"):
        cache_feed_artwork(feed, tmp_path / "iPod_Control" / "iOpenPodPodcasts")
