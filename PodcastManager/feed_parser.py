"""RSS/Atom feed parser for podcast feeds.

Uses feedparser to handle the wide variety of podcast RSS feed formats,
including Apple's itunes: namespace extensions.
"""

from __future__ import annotations

import logging
import time
import calendar

import feedparser
import requests

from .models import PodcastEpisode, PodcastFeed

log = logging.getLogger(__name__)

_TIMEOUT = 20  # seconds


def fetch_feed(url: str, existing: PodcastFeed | None = None) -> PodcastFeed:
    """Fetch and parse a podcast RSS/Atom feed.

    If *existing* is provided, new episodes are merged into it (preserving
    local state like download paths and on-iPod status for known episodes).

    Args:
        url: The RSS/Atom feed URL.
        existing: Optional existing PodcastFeed to merge into.

    Returns:
        A PodcastFeed with all episodes.

    Raises:
        requests.RequestException: On network errors.
        ValueError: If the feed contains no entries or is unparseable.
    """
    resp = requests.get(url, timeout=_TIMEOUT, headers={
        "User-Agent": "iOpenPod/1.0.0 (Podcast Manager)",
    })
    resp.raise_for_status()

    parsed = feedparser.parse(resp.content)

    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Feed parse error: {parsed.bozo_exception}")

    feed_info = parsed.feed

    # Build episode list from entries
    new_episodes = []
    for entry in parsed.entries:
        ep = _parse_episode(entry)
        if ep is not None:
            new_episodes.append(ep)

    if existing is not None:
        feed = _merge_feed(existing, feed_info, new_episodes)
    else:
        feed = PodcastFeed(
            feed_url=url,
            title=_get_text(feed_info, "title", "Unknown Podcast"),
            author=(_get_text(feed_info, "author")
                    or _get_itunes(feed_info, "author", "")),
            description=(_get_text(feed_info, "subtitle")
                         or _get_text(feed_info, "summary", "")),
            artwork_url=_get_artwork_url(feed_info),
            category=_get_itunes_category(feed_info),
            language=_get_text(feed_info, "language", ""),
            last_refreshed=time.time(),
            episodes=new_episodes,
        )

    return feed


def _merge_feed(
    existing: PodcastFeed,
    feed_info,
    new_episodes: list[PodcastEpisode],
) -> PodcastFeed:
    """Merge newly parsed episodes into an existing feed.

    Preserves local state (downloaded_path, status, ipod_dbid) for
    episodes that already exist (matched by guid).
    """
    existing_by_guid = {ep.guid: ep for ep in existing.episodes}

    merged: list[PodcastEpisode] = []
    for ep in new_episodes:
        old = existing_by_guid.pop(ep.guid, None)
        if old is not None:
            # Preserve local state, update RSS metadata
            ep.status = old.status
            ep.downloaded_path = old.downloaded_path
            ep.ipod_dbid = old.ipod_dbid
        merged.append(ep)

    # Keep any old episodes that disappeared from the feed but are
    # downloaded or on iPod (don't lose local data)
    for old_ep in existing_by_guid.values():
        if old_ep.downloaded_path or old_ep.ipod_dbid:
            merged.append(old_ep)

    existing.title = _get_text(feed_info, "title") or existing.title
    existing.author = (_get_text(feed_info, "author")
                       or _get_itunes(feed_info, "author", "")
                       or existing.author)
    existing.description = (_get_text(feed_info, "subtitle")
                            or _get_text(feed_info, "summary", "")
                            or existing.description)
    existing.artwork_url = _get_artwork_url(feed_info) or existing.artwork_url
    existing.category = _get_itunes_category(feed_info) or existing.category
    existing.language = _get_text(feed_info, "language", "") or existing.language
    existing.last_refreshed = time.time()
    existing.episodes = merged
    return existing


def _parse_episode(entry) -> PodcastEpisode | None:
    """Parse a single feed entry into a PodcastEpisode."""
    # Need at least a guid and an audio enclosure
    audio_url = ""
    size_bytes = 0

    for link in entry.get("links", []):
        if link.get("rel") == "enclosure":
            href = link.get("href", "")
            mime = link.get("type", "")
            if href and ("audio" in mime or _looks_like_audio(href)):
                audio_url = href
                try:
                    size_bytes = int(link.get("length", 0))
                except (ValueError, TypeError):
                    size_bytes = 0
                break

    # Also check entry.enclosures (feedparser normalises here)
    if not audio_url:
        for enc in entry.get("enclosures", []):
            href = enc.get("href", "")
            mime = enc.get("type", "")
            if href and ("audio" in mime or _looks_like_audio(href)):
                audio_url = href
                try:
                    size_bytes = int(enc.get("length", 0))
                except (ValueError, TypeError):
                    size_bytes = 0
                break

    if not audio_url:
        return None  # Skip non-audio entries (e.g. show notes only)

    guid = entry.get("id") or audio_url

    # Parse publication date
    pub_date = 0.0
    if entry.get("published_parsed"):
        try:
            pub_date = calendar.timegm(entry.published_parsed)
        except (TypeError, OverflowError, ValueError):
            pass

    # Parse duration (itunes:duration can be "HH:MM:SS", "MM:SS", or seconds)
    duration = _parse_duration(
        _get_itunes(entry, "duration", "")
    )

    # Episode/season numbers
    ep_num = None
    season_num = None
    try:
        ep_num = int(_get_itunes(entry, "episode", "0")) or None
    except (ValueError, TypeError):
        pass
    try:
        season_num = int(_get_itunes(entry, "season", "0")) or None
    except (ValueError, TypeError):
        pass

    return PodcastEpisode(
        guid=guid,
        title=_get_text(entry, "title", "Untitled Episode"),
        description=(_get_text(entry, "subtitle")
                     or _get_text(entry, "summary", "")),
        audio_url=audio_url,
        pub_date=pub_date,
        duration_seconds=duration,
        size_bytes=size_bytes,
        episode_number=ep_num,
        season_number=season_num,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_text(obj, attr: str, default: str = "") -> str:
    """Safely get a text attribute from a feedparser object."""
    val = getattr(obj, attr, None) or obj.get(attr) if hasattr(obj, 'get') else getattr(obj, attr, None)
    return str(val).strip() if val else default


def _get_itunes(obj, key: str, default: str = "") -> str:
    """Get an itunes: namespace value from a feedparser entry."""
    # feedparser stores itunes:X as itunes_X
    val = obj.get(f"itunes_{key}") if hasattr(obj, 'get') else getattr(obj, f"itunes_{key}", None)
    return str(val).strip() if val else default


def _get_artwork_url(feed_info) -> str:
    """Extract the best artwork URL from feed metadata."""
    # itunes:image href attribute
    img = feed_info.get("image") if hasattr(feed_info, 'get') else getattr(feed_info, "image", None)
    if img:
        href = img.get("href", "") if isinstance(img, dict) else getattr(img, "href", "")
        if href:
            return href

    # Also check itunes_image (feedparser normalisation)
    itunes_img = feed_info.get("itunes_image") if hasattr(feed_info, 'get') else None
    if itunes_img:
        href = itunes_img.get("href", "") if isinstance(itunes_img, dict) else ""
        if href:
            return href

    return ""


def _get_itunes_category(feed_info) -> str:
    """Extract the primary iTunes category."""
    tags = feed_info.get("tags") if hasattr(feed_info, 'get') else getattr(feed_info, "tags", None)
    if tags:
        for tag in tags:
            term = tag.get("term", "") if isinstance(tag, dict) else getattr(tag, "term", "")
            if term:
                return term
    return ""


_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".flac", ".wma"}


def _looks_like_audio(url: str) -> bool:
    """Heuristic check if a URL points to an audio file."""
    # Strip query params for extension check
    path = url.split("?")[0].lower()
    return any(path.endswith(ext) for ext in _AUDIO_EXTS)


def _parse_duration(raw: str) -> int:
    """Parse itunes:duration into seconds.

    Handles: "3600", "60:00", "1:00:00", "01:00:00".
    """
    if not raw:
        return 0

    # Pure integer (seconds)
    if raw.isdigit():
        return int(raw)

    # HH:MM:SS or MM:SS
    parts = raw.split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return 0

    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return 0
