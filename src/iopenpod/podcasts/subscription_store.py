"""Persistent storage for podcast subscriptions.

Subscription data lives on the iPod itself at:
    <iPod>/iPod_Control/iOpenPodPodcasts

This keeps podcast state tied to the device rather than the PC.
All writes use atomic temp-file + rename to prevent corruption.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from iopenpod.device.durability import durable_unlink
from iopenpod.device.metadata_write import (
    DeviceMetadataWriteSession,
    guarded_device_metadata_session,
)
from iopenpod.device.path_safety import UnsafeHostPathError, resolve_host_path
from iopenpod.device.write_guard import DeviceWriteSafetyError

from .models import PodcastFeed

log = logging.getLogger(__name__)

_PODCAST_SUBTREE = Path("iPod_Control") / "iOpenPodPodcasts"
_SUBSCRIPTIONS_PATH = _PODCAST_SUBTREE / "subscriptions.json"


class SubscriptionStore:
    """Manages podcast subscriptions for a single iPod device.

    Args:
        ipod_path: Mount root of the iPod (e.g. ``"D:\\"`` or
                   ``"/Volumes/iPod"``).
    """

    def __init__(
        self,
        ipod_path: str,
        download_cache_dir: str = "",
        *,
        reported_volume_format: str = "",
        expected_volume_identity_key: str = "",
        metadata_write_session: DeviceMetadataWriteSession | None = None,
    ):
        self._ipod_path = ipod_path
        self._download_cache_dir = download_cache_dir
        self._reported_volume_format = reported_volume_format
        self._expected_volume_identity_key = expected_volume_identity_key
        self._metadata_write_session = metadata_write_session
        self._podcast_dir = os.path.join(
            ipod_path, "iPod_Control", "iOpenPodPodcasts",
        )
        self._json_path = os.path.join(self._podcast_dir, "subscriptions.json")
        self._feeds: list[PodcastFeed] = []
        self._loaded = False

    @property
    def podcast_dir(self) -> str:
        """The podcast directory on the iPod."""
        return self._podcast_dir

    @property
    def download_cache_root(self) -> Path:
        """Return the configured host directory containing podcast downloads."""
        base = self._download_cache_dir
        if not base:
            from iopenpod.infrastructure.settings_paths import default_cache_dir

            base = default_cache_dir()
        return Path(os.path.abspath(base)) / "podcasts"

    def remove_episode_download(self, downloaded_path: str | Path) -> None:
        """Durably remove one file contained by the host podcast cache."""
        try:
            candidate = resolve_host_path(self.download_cache_root, downloaded_path)
        except (OSError, TypeError, UnsafeHostPathError) as exc:
            raise DeviceWriteSafetyError(
                "The stored episode path is outside the configured podcast "
                "download cache or passes through a link/reparse point. "
                "iOpenPod refused to remove it."
            ) from exc
        durable_unlink(candidate, missing_ok=True)

    def _ensure_loaded(self) -> None:
        """Load subscriptions lazily on first access."""
        if not self._loaded:
            self.load()

    # ── Public API ───────────────────────────────────────────────────────

    def load(self) -> list[PodcastFeed]:
        """Load subscriptions from disk.  Returns the feed list."""
        try:
            with open(self._json_path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            self._feeds = []
            self._loaded = True
            return self._feeds
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            raise DeviceWriteSafetyError(
                "The existing podcast subscriptions file could not be read "
                f"safely. iOpenPod left it unchanged: {exc}"
            ) from exc

        if not isinstance(data, dict) or not isinstance(data.get("feeds", []), list):
            raise DeviceWriteSafetyError(
                "The existing podcast subscriptions file is malformed. "
                "iOpenPod left it unchanged instead of replacing podcast state."
            )

        try:
            feeds = [PodcastFeed.from_dict(d) for d in data.get("feeds", [])]
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise DeviceWriteSafetyError(
                "The existing podcast subscriptions contain malformed feed "
                f"data. iOpenPod left the file unchanged: {exc}"
            ) from exc

        self._feeds = feeds
        self._loaded = True
        return self._feeds

    def save(self) -> None:
        """Write subscriptions through the guarded, durable metadata writer."""
        self._ensure_loaded()
        payload = {
            "version": 1,
            "feeds": [f.to_dict() for f in self._feeds],
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        with self._writer() as writer:
            writer.write_text_atomic(
                _SUBSCRIPTIONS_PATH,
                text,
                allowed_subtree=_PODCAST_SUBTREE,
            )

    def cache_feed_artwork(
        self,
        feed,
        fallback_urls=(),
    ) -> str:
        """Cache feed artwork using the same guarded device writer policy."""
        from .artwork import cache_feed_artwork

        return cache_feed_artwork(
            feed,
            self._podcast_dir,
            fallback_urls=fallback_urls,
            write_bytes=self._write_artwork_bytes,
        )

    def _write_artwork_bytes(self, relative_path: Path, data: bytes) -> Path:
        with self._writer() as writer:
            return writer.write_bytes_atomic(
                _PODCAST_SUBTREE / relative_path,
                data,
                allowed_subtree=_PODCAST_SUBTREE,
            )

    @contextmanager
    def _writer(self) -> Iterator[DeviceMetadataWriteSession]:
        if self._metadata_write_session is not None:
            yield self._metadata_write_session
            return

        with guarded_device_metadata_session(
            self._ipod_path,
            reported_volume_format=self._reported_volume_format,
            expected_volume_identity_key=self._expected_volume_identity_key,
        ) as writer:
            yield writer

    def get_feeds(self) -> list[PodcastFeed]:
        """Return the current feed list (loads from disk if needed)."""
        self._ensure_loaded()
        return list(self._feeds)

    def get_feed(self, feed_url: str) -> PodcastFeed | None:
        """Look up a feed by URL."""
        self._ensure_loaded()
        for f in self._feeds:
            if f.feed_url == feed_url:
                return f
        return None

    def add_feed(self, feed: PodcastFeed) -> None:
        """Add or replace a feed subscription.  Saves immediately."""
        self._ensure_loaded()
        # Replace existing if same feed_url
        self._feeds = [f for f in self._feeds if f.feed_url != feed.feed_url]
        self._feeds.append(feed)
        self.save()

    def remove_feed(self, feed_url: str) -> PodcastFeed | None:
        """Remove a feed subscription.  Returns the removed feed or None."""
        self._ensure_loaded()
        removed = None
        new_feeds = []
        for f in self._feeds:
            if f.feed_url == feed_url:
                removed = f
            else:
                new_feeds.append(f)
        self._feeds = new_feeds
        if removed:
            self.save()
        return removed

    def update_feed(self, feed: PodcastFeed) -> None:
        """Update an existing feed in-place.  Saves immediately."""
        self._ensure_loaded()
        for i, f in enumerate(self._feeds):
            if f.feed_url == feed.feed_url:
                self._feeds[i] = feed
                self.save()
                return
        # Not found — add it instead
        self.add_feed(feed)

    def update_feeds(self, feeds: list[PodcastFeed]) -> int:
        """Batch-update multiple feeds and save once.

        Returns:
            Number of feed entries that were provided.
        """
        self._ensure_loaded()
        if not feeds:
            return 0

        by_url: dict[str, PodcastFeed] = {
            feed.feed_url: feed for feed in self._feeds
        }

        for feed in feeds:
            by_url[feed.feed_url] = feed

        # Always save — callers often modify feed objects in-place
        # (e.g. RSS merge, reconciliation), making value-based change
        # detection unreliable when the same objects are passed back.
        self._feeds = list(by_url.values())
        self.save()

        return len(feeds)

    def feed_dir(self, feed: PodcastFeed) -> str:
        """Return the PC-local download directory for a feed's episodes.

        Episodes are downloaded here first, then copied to the iPod
        during the sync process.  Uses the transcode cache directory
        from settings, falling back to the platform default cache directory.
        """
        import hashlib
        url_hash = hashlib.sha256(feed.feed_url.encode()).hexdigest()[:16]
        return str(self.download_cache_root / url_hash)
