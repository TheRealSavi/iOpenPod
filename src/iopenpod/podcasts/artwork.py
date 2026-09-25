"""Podcast artwork cache and source resolution helpers.

Remote feed artwork is the source of truth.  The local cache is only an
optimization, so stale absolute paths must never block falling back to the
remote URL.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

import requests
from PIL import Image, UnidentifiedImageError

from iopenpod.device.metadata_write import guarded_device_metadata_session
from iopenpod.device.write_guard import DeviceWriteSafetyError

from .models import normalize_artwork_url

log = logging.getLogger(__name__)

_CACHE_DIRNAME = "artwork-cache"
_REQUEST_TIMEOUT = 15
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_REQUEST_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


class PodcastArtworkFeed(Protocol):
    """Mutable feed fields needed by the artwork cache helper."""

    feed_url: str
    artwork_url: str
    artwork_path: str


def is_remote_artwork_source(source: str) -> bool:
    """Return True when *source* is an HTTP(S) artwork URL."""
    parsed = urlparse(str(source or "").strip())
    return parsed.scheme.lower() in {"http", "https"}


def resolve_local_artwork_path(
    source: str,
    podcast_dir: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Resolve a local artwork path or ``file://`` URI.

    Relative cache paths are resolved against ``podcast_dir``.  Legacy
    absolute paths are returned as-is so older subscription files remain
    readable when the mount point has not changed.
    """
    text = str(source or "").strip()
    if not text:
        return None

    parsed = urlparse(text)
    scheme = parsed.scheme.lower()
    if scheme in {"http", "https"}:
        return None

    if scheme == "file":
        path_text = unquote(parsed.path or "")
        if (
            os.name == "nt"
            and path_text.startswith("/")
            and len(path_text) > 2
            and path_text[2] == ":"
        ):
            path_text = path_text[1:]
        if parsed.netloc and parsed.netloc.lower() != "localhost" and path_text:
            if os.name == "nt":
                return Path("\\\\" + parsed.netloc + path_text.replace("/", "\\"))
            return Path("//" + parsed.netloc + path_text)
        return Path(path_text)

    if re.match(r"^[a-zA-Z]:[\\/]", text):
        return Path(text)

    if text.startswith("\\\\") or text.startswith("//"):
        return Path(text)

    path = Path(text)
    if path.is_absolute() or not podcast_dir:
        return path

    parts = [part for part in re.split(r"[\\/]+", text) if part]
    return Path(podcast_dir, *parts)


def read_local_artwork_bytes(
    source: str,
    podcast_dir: str | os.PathLike[str] | None = None,
) -> bytes | None:
    """Read local artwork bytes.

    Returns ``None`` for remote sources, ``b""`` for missing/unreadable local
    paths, and non-empty bytes when a local cache file exists.
    """
    path = resolve_local_artwork_path(source, podcast_dir)
    if path is None:
        return None
    try:
        if not path.exists() or not path.is_file():
            return b""
        return path.read_bytes()
    except OSError:
        return b""


def load_artwork_bytes(
    source: str,
    podcast_dir: str | os.PathLike[str] | None = None,
) -> bytes | None:
    """Load artwork bytes from a local source or remote URL."""
    local_bytes = read_local_artwork_bytes(source, podcast_dir)
    if local_bytes is not None:
        return local_bytes or None

    if not is_remote_artwork_source(source):
        return None

    resp = requests.get(
        source,
        timeout=10,
        headers=_REQUEST_HEADERS,
    )
    resp.raise_for_status()
    return resp.content or None


def resolve_feed_artwork_source(
    feed: object,
    podcast_dir: str | os.PathLike[str] | None = None,
) -> str:
    """Return the best currently usable artwork source for a feed.

    The local cache wins only when it exists.  Otherwise the feed's remote
    artwork URL is returned so display and sync can recover from stale cache
    paths.
    """
    artwork_path = str(getattr(feed, "artwork_path", "") or "").strip()
    artwork_url = normalize_artwork_url(
        str(getattr(feed, "artwork_url", "") or "").strip()
    )

    local_path = resolve_local_artwork_path(artwork_path, podcast_dir)
    if local_path is not None:
        try:
            if local_path.exists() and local_path.is_file():
                return str(local_path)
        except OSError:
            pass

    if artwork_url:
        return artwork_url

    if is_remote_artwork_source(artwork_path):
        return artwork_path

    return ""


def prepare_artwork_bytes(data: bytes) -> bytes | None:
    """Decode arbitrary image bytes and return iPod-friendly JPEG bytes."""
    if not data or len(data) < 64:
        return None

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            rgba = img.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError):
        return None

    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    background.alpha_composite(rgba)
    rgb = background.convert("RGB")
    if max(rgb.size) > 1400:
        rgb.thumbnail((1400, 1400), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    rgb.save(out, format="JPEG", quality=90, optimize=True)
    prepared = out.getvalue()
    return prepared if len(prepared) >= 64 else None


def cache_feed_artwork(
    feed: PodcastArtworkFeed,
    podcast_dir: str | os.PathLike[str],
    fallback_urls: Iterable[str] = (),
    *,
    write_bytes: Callable[[Path, bytes], Path] | None = None,
    reported_volume_format: str = "",
    expected_volume_identity_key: str = "",
) -> str:
    """Ensure a feed has a usable local artwork cache.

    ``feed.artwork_path`` is written as a path relative to ``podcast_dir`` for
    new caches.  Legacy absolute paths are still read by
    :func:`resolve_feed_artwork_source`.
    """
    if not podcast_dir:
        return ""

    existing_source = resolve_feed_artwork_source(feed, podcast_dir)
    if existing_source and not is_remote_artwork_source(existing_source):
        return existing_source

    feed_url = str(feed.feed_url or "")
    primary_url = normalize_artwork_url(str(feed.artwork_url or ""))
    candidates: list[str] = []

    def _add_candidate(url: str) -> None:
        normalized = normalize_artwork_url(url)
        if (
            normalized
            and is_remote_artwork_source(normalized)
            and normalized not in candidates
        ):
            candidates.append(normalized)

    _add_candidate(primary_url)
    for url in fallback_urls:
        _add_candidate(str(url or ""))

    if not primary_url and candidates:
        feed.artwork_url = candidates[0]

    if not candidates:
        return ""

    for url in candidates:
        key_seed = f"{feed_url}|{url}" if feed_url else url
        rel_path = Path(_CACHE_DIRNAME) / (
            hashlib.sha256(key_seed.encode()).hexdigest()[:24] + ".jpg"
        )
        cache_path = Path(podcast_dir) / rel_path

        try:
            cached_size = cache_path.stat().st_size
        except FileNotFoundError:
            cached_size = 0
        except OSError:
            # A device read failure is not equivalent to a cache miss. Let the
            # guarded caller stop and alert the user instead of writing onward.
            raise
        if cached_size > 0:
            feed.artwork_path = rel_path.as_posix()
            return str(cache_path)

        try:
            resp = requests.get(url, timeout=_REQUEST_TIMEOUT, headers=_REQUEST_HEADERS)
            resp.raise_for_status()
            prepared = prepare_artwork_bytes(resp.content)
            if not prepared:
                continue
        except Exception as exc:
            log.debug("Failed to cache podcast artwork from %s: %s", url, exc)
            continue

        try:
            installed = (
                write_bytes(rel_path, prepared)
                if write_bytes is not None
                else _write_artwork_bytes_guarded(
                    podcast_dir,
                    rel_path,
                    prepared,
                    reported_volume_format=reported_volume_format,
                    expected_volume_identity_key=expected_volume_identity_key,
                )
            )
        except (DeviceWriteSafetyError, OSError):
            raise
        except Exception as exc:
            log.debug("Failed to store podcast artwork from %s: %s", url, exc)
            continue

        feed.artwork_path = rel_path.as_posix()
        return str(installed)

    return ""


def _write_artwork_bytes_guarded(
    podcast_dir: str | os.PathLike[str],
    relative_path: Path,
    data: bytes,
    *,
    reported_volume_format: str,
    expected_volume_identity_key: str,
) -> Path:
    """Install artwork only when *podcast_dir* is the canonical iPod subtree."""
    podcast_path = Path(os.path.realpath(podcast_dir))
    if (
        podcast_path.name.casefold() != "iopenpodpodcasts"
        or podcast_path.parent.name.casefold() != "ipod_control"
    ):
        raise DeviceWriteSafetyError(
            "The podcast artwork destination is outside the expected iPod "
            "metadata directory. iOpenPod stopped before writing artwork."
        )

    mount_path = podcast_path.parent.parent
    subtree = Path("iPod_Control") / "iOpenPodPodcasts"
    with guarded_device_metadata_session(
        mount_path,
        reported_volume_format=reported_volume_format,
        expected_volume_identity_key=expected_volume_identity_key,
    ) as writer:
        return writer.write_bytes_atomic(
            subtree / relative_path,
            data,
            allowed_subtree=subtree,
        )
