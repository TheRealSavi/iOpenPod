from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from iopenpod.podcasts.downloader import (
    DownloadedEpisodeInfo,
    download_and_probe_episode,
    embed_feed_artwork,
)
from iopenpod.podcasts.models import STATUS_DOWNLOADED, PodcastEpisode, PodcastFeed
from iopenpod.podcasts.podcast_sync import episode_to_pc_track
from iopenpod.podcasts.subscription_store import SubscriptionStore
from iopenpod.sync.fingerprint_diff_engine import SyncAction, SyncItem, SyncPlan
from iopenpod.sync.sync_executor import SyncExecutor


def test_episode_to_pc_track_reuses_predicted_download_and_hashes_folder_art(
    tmp_path: Path,
) -> None:
    feed = PodcastFeed(
        feed_url="https://example.test/feed.xml",
        title="Show",
        author="Host",
    )
    episode = PodcastEpisode(
        guid="https://cdn.example.test/episode-1.mp3",
        title="Episode 1",
        audio_url="https://cdn.example.test/episode-1.mp3",
        size_bytes=123,
    )
    store = SubscriptionStore(str(tmp_path / "ipod"), download_cache_dir=str(tmp_path / "cache"))
    dest_dir = Path(store.feed_dir(feed))
    dest_dir.mkdir(parents=True)

    from iopenpod.podcasts.downloader import _safe_filename

    predicted = dest_dir / _safe_filename(episode)
    predicted.write_bytes(b"not-real-audio")
    (dest_dir / "cover.jpg").write_bytes(b"folder-art")

    pc_track = episode_to_pc_track(episode, feed, store)

    assert pc_track.path == str(predicted)
    assert pc_track.size == len(b"not-real-audio")
    assert pc_track.art_hash is not None
    assert episode.downloaded_path == str(predicted)
    assert episode.status == STATUS_DOWNLOADED


def test_embed_feed_artwork_treats_missing_local_path_as_no_artwork(
    tmp_path: Path,
    monkeypatch,
) -> None:
    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"not-real-audio")

    def _unexpected_request(*_args, **_kwargs):
        raise AssertionError("missing local artwork path should not be requested")

    monkeypatch.setattr("iopenpod.podcasts.downloader.requests.get", _unexpected_request)

    assert embed_feed_artwork(str(audio_path), str(tmp_path / "missing-cover.jpg")) is False


def test_download_and_probe_episode_forwards_byte_progress(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class _CancelToken:
        def is_cancelled(self) -> bool:
            return False

    progress_events: list[tuple[int, int]] = []
    token = _CancelToken()
    downloaded = tmp_path / "downloaded.mp3"

    def fake_download_episode(episode, dest_dir, progress_cb=None, cancel_token=None):
        assert cancel_token is token
        assert progress_cb is not None
        progress_cb(128, 512)
        progress_events.append((128, 512))
        downloaded.write_bytes(b"audio")
        return str(downloaded)

    monkeypatch.setattr(
        "iopenpod.podcasts.downloader.download_episode",
        fake_download_episode,
    )
    monkeypatch.setattr(
        "iopenpod.podcasts.downloader.probe_episode_file",
        lambda path, artwork_url="": DownloadedEpisodeInfo(
            path=path,
            size=4,
            mtime=1.0,
            extension=".mp3",
        ),
    )

    info = download_and_probe_episode(
        "https://example.test/episode.mp3",
        "Episode",
        str(tmp_path),
        progress_cb=lambda *_args: None,
        cancel_token=token,
    )

    assert info.path == str(downloaded)
    assert progress_events == [(128, 512)]


def test_sync_podcast_download_progress_uses_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ipod_root = tmp_path / "ipod"
    host_cache = tmp_path / "cache"
    host_cache.mkdir()
    downloaded = host_cache / "episode.mp3"
    pc_track = SimpleNamespace(
        is_podcast=True,
        path=str(host_cache / "missing.mp3"),
        podcast_enclosure_url="https://example.test/episode.mp3",
        podcast_url="",
        title="Episode",
        size=1000,
        bitrate=None,
        sample_rate=None,
        duration_ms=0,
        art_hash=None,
        needs_transcoding=False,
    )
    item = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        pc_track=cast(Any, pc_track),
        estimated_size=1000,
        description="Episode",
    )
    progress_events = []

    class _Ctx:
        plan = SyncPlan(to_add=[item])

        def progress(
            self,
            stage,
            current,
            total,
            current_item=None,
            message="",
            **kwargs,
        ) -> None:
            progress_events.append(
                (stage, current, total, current_item, message, kwargs)
            )

        def cancelled(self) -> bool:
            return False

    def fake_download_and_probe_episode(
        *,
        audio_url,
        title,
        dest_dir,
        artwork_url="",
        progress_cb=None,
        cancel_token=None,
        **_kwargs,
    ):
        assert progress_cb is not None
        progress_cb(250, 1000)
        progress_cb(1000, 1000)
        downloaded.write_bytes(b"x" * 1000)
        return DownloadedEpisodeInfo(
            path=str(downloaded),
            size=1000,
            mtime=2.0,
            extension=".mp3",
            art_hash="hash",
        )

    monkeypatch.setattr(
        "iopenpod.podcasts.downloader.download_and_probe_episode",
        fake_download_and_probe_episode,
    )

    SyncExecutor(ipod_root)._download_podcast_episodes(cast(Any, _Ctx()))

    byte_events = [
        event for event in progress_events
        if event[0] == "podcast_download"
    ]
    assert (byte_events[0][1], byte_events[0][2]) == (0, 1000)
    assert any(event[1] == 250 and event[2] == 1000 for event in byte_events)
    assert any(event[1] == 1000 and event[2] == 1000 for event in byte_events)
    assert byte_events[-1][5]["size_progress"] == 1.0
    assert pc_track.path == str(downloaded)
    assert pc_track.art_hash == "hash"
