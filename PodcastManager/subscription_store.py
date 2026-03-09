"""Persistent storage for podcast subscriptions.

Each iPod device gets its own subscription file so different iPods can
have independent podcast libraries.  Data is stored as JSON at:
    ~/iOpenPod/podcasts/<device_serial>/subscriptions.json

All writes use atomic temp-file + rename to prevent corruption.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

from .models import PodcastFeed

log = logging.getLogger(__name__)


def _default_podcast_dir() -> str:
    """Base podcast storage directory: ~/iOpenPod/podcasts."""
    return os.path.join(os.path.expanduser("~"), "iOpenPod", "podcasts")


class SubscriptionStore:
    """Manages podcast subscriptions for a single iPod device.

    Args:
        device_serial: Unique identifier for the iPod (e.g. FireWire GUID
                       or serial number from SysInfo).  Used as directory name.
        base_dir: Override the base podcast directory (for testing).
    """

    def __init__(self, device_serial: str, base_dir: str = ""):
        if not device_serial:
            device_serial = "_default"
        self._device_serial = device_serial
        self._base_dir = base_dir or _default_podcast_dir()
        self._device_dir = os.path.join(self._base_dir, device_serial)
        self._json_path = os.path.join(self._device_dir, "subscriptions.json")
        self._feeds: list[PodcastFeed] = []
        self._loaded = False

    @property
    def device_dir(self) -> str:
        """The per-device podcast directory (for episode downloads)."""
        return self._device_dir

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
        os.makedirs(self._device_dir, exist_ok=True)

        payload = {
            "version": 1,
            "feeds": [f.to_dict() for f in self._feeds],
        }

        # Atomic write: temp file in same directory, then rename
        fd, tmp = tempfile.mkstemp(
            dir=self._device_dir, suffix=".tmp", prefix="subs_",
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
        if not self._loaded:
            self.load()
        return list(self._feeds)

    def get_feed(self, feed_url: str) -> PodcastFeed | None:
        """Look up a feed by URL."""
        if not self._loaded:
            self.load()
        for f in self._feeds:
            if f.feed_url == feed_url:
                return f
        return None

    def add_feed(self, feed: PodcastFeed) -> None:
        """Add or replace a feed subscription.  Saves immediately."""
        if not self._loaded:
            self.load()
        # Replace existing if same feed_url
        self._feeds = [f for f in self._feeds if f.feed_url != feed.feed_url]
        self._feeds.append(feed)
        self.save()

    def remove_feed(self, feed_url: str) -> PodcastFeed | None:
        """Remove a feed subscription.  Returns the removed feed or None."""
        if not self._loaded:
            self.load()
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
        if not self._loaded:
            self.load()
        for i, f in enumerate(self._feeds):
            if f.feed_url == feed.feed_url:
                self._feeds[i] = feed
                self.save()
                return
        # Not found — add it instead
        self.add_feed(feed)

    def feed_dir(self, feed: PodcastFeed) -> str:
        """Return the download directory for a specific feed's episodes."""
        # Use a filesystem-safe hash of the feed URL as directory name
        import hashlib
        url_hash = hashlib.sha256(feed.feed_url.encode()).hexdigest()[:16]
        return os.path.join(self._device_dir, url_hash)
