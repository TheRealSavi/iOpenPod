"""Stable identities for feeds and episodes from unequal metadata sources."""

from __future__ import annotations

import hashlib
from urllib.parse import SplitResult, urlsplit, urlunsplit


def normalize_feed_url(value: str) -> str:
    """Return a conservative canonical HTTP(S) feed URL."""

    raw = value.strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return ""
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    host = parsed.hostname.casefold()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    authority = host if port is None or default_port else f"{host}:{port}"
    return urlunsplit(
        SplitResult(
            scheme,
            authority,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def subscription_identity(feed_url: str, title: str, author: str = "") -> str:
    """Prefer a feed identity, with a show-name fallback for retained Tracks."""

    normalized = normalize_feed_url(feed_url)
    if normalized:
        return "feed-" + _digest(normalized)
    show = "\x1f".join((title.strip().casefold(), author.strip().casefold()))
    return "device-" + _digest(show or "unknown-podcast")


def episode_identity(
    *,
    enclosure_url: str,
    guid: str,
    title: str,
    published_at: int,
    episode_number: int | None = None,
    season_number: int | None = None,
) -> str:
    """Match RSS episodes to iTunesDB Tracks using their shared enclosure first."""

    enclosure = normalize_media_url(enclosure_url)
    if enclosure:
        key = "enclosure\x1f" + enclosure
    elif guid.strip():
        key = "guid\x1f" + guid.strip()
    else:
        key = "fallback\x1f" + "\x1f".join(
            (
                title.strip().casefold(),
                str(published_at),
                str(season_number or 0),
                str(episode_number or 0),
            )
        )
    return "episode-" + _digest(key)


def normalize_media_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return raw
    host = parsed.hostname.casefold()
    try:
        port = parsed.port
    except ValueError:
        return raw
    scheme = parsed.scheme.casefold()
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    authority = host if port is None or default_port else f"{host}:{port}"
    return urlunsplit(
        SplitResult(scheme, authority, parsed.path or "/", parsed.query, "")
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


__all__ = [
    "episode_identity",
    "normalize_feed_url",
    "normalize_media_url",
    "subscription_identity",
]
