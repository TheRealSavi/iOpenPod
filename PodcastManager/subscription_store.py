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
import tempfile

from .models import PodcastFeed

log = logging.getLogger(__name__)


class SubscriptionStore:
    """Manages podcast subscriptions for a single iPod device.

    Args:
        ipod_path: Mount root of the iPod (e.g. ``"D:\\"`` or
                   ``"/Volumes/iPod"``).
    """

    def __init__(self, ipod_path: str):
        self._ipod_path = ipod_path
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

    def _ensure_loaded(self) -> None:
        """Load subscriptions lazily on first access."""
        if not self._loaded:
            self.load()

    # ── Public API ───────────────────────────────────────────────────────

    def load(self) -> list[PodcastFeed]:
        """Load subscriptions from disk.  Returns the feed list."""
        if not os.path.exists(self._json_path):
            self._feeds = []
            self._loaded = True
            return self._feeds

        try:
            with open(self._json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load subscriptions: %s", exc)
            self._feeds = []
            self._loaded = True
            return self._feeds

        self._feeds = [PodcastFeed.from_dict(d) for d in data.get("feeds", [])]
        self._loaded = True
        return self._feeds

    def save(self) -> None:
        """Write subscriptions to disk atomically."""
        os.makedirs(self._podcast_dir, exist_ok=True)

        payload = {
            "version": 1,
            "feeds": [f.to_dict() for f in self._feeds],
        }

        # Atomic write: temp file in same directory, then rename
        fd, tmp = tempfile.mkstemp(
            dir=self._podcast_dir, suffix=".tmp", prefix="subs_",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._json_path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

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
            Number of feed entries that changed.
        """
        self._ensure_loaded()
        if not feeds:
            return 0

        by_url: dict[str, PodcastFeed] = {
            feed.feed_url: feed for feed in self._feeds
        }

        changed = 0
        for feed in feeds:
            existing = by_url.get(feed.feed_url)
            if existing != feed:
                by_url[feed.feed_url] = feed
                changed += 1

        if changed:
            # Keep insertion order stable for existing feeds;
            # new feeds are appended at the end.
            self._feeds = list(by_url.values())
            self.save()

        return changed

    def feed_dir(self, feed: PodcastFeed) -> str:
        """Return the PC-local download directory for a feed's episodes.

        Episodes are downloaded here first, then copied to the iPod
        during the sync process.  Uses the transcode cache directory
        from settings, falling back to ~/iOpenPod/cache.
        """
        import hashlib
        url_hash = hashlib.sha256(feed.feed_url.encode()).hexdigest()[:16]
        try:
            from settings import get_settings
            base = get_settings().transcode_cache_dir
        except Exception:
            base = ""
        if not base:
            base = os.path.join(os.path.expanduser("~"), "iOpenPod", "cache")
        return os.path.join(base, "podcasts", url_hash)
