"""Bounded HTTP clients for podcast feeds and directory discovery."""

from __future__ import annotations

import calendar
import hashlib
import html
import io
import json
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import feedparser  # type: ignore[import-untyped]
from PIL import Image, ImageOps, UnidentifiedImageError

from iOpenPod.app.podcasts.identity import (
    episode_identity,
    normalize_feed_url,
)
from iOpenPod.app.podcasts.models import (
    PodcastArtworkImage,
    PodcastArtworkRequest,
    PodcastEpisode,
    PodcastSearchResult,
    PodcastSubscription,
    SubscriptionSource,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_USER_AGENT = "iOpenPod/2 Podcast Browser"
_FEED_LIMIT = 16 * 1024 * 1024
_SEARCH_LIMIT = 2 * 1024 * 1024
_ARTWORK_LIMIT = 8 * 1024 * 1024
_ARTWORK_PIXEL_LIMIT = 40_000_000
_ARTWORK_TARGET_LIMIT = 1200
_TIMEOUT_SECONDS = 20
_DIRECTORY_URL = "https://itunes.apple.com/search"
_MEDIA_EXTENSIONS = (
    ".aac",
    ".aiff",
    ".flac",
    ".m4a",
    ".m4v",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
)


class PodcastFeedError(ValueError):
    """A feed or directory request could not produce safe podcast data."""


class PodcastFeedClient(Protocol):
    def fetch(self, feed_url: str) -> PodcastSubscription: ...


class PodcastDirectoryClient(Protocol):
    def search(self, query: str) -> tuple[PodcastSearchResult, ...]: ...


class PodcastArtworkLoader(Protocol):
    def load_artwork(
        self, request: PodcastArtworkRequest
    ) -> PodcastArtworkImage | None: ...


class _FeedparserApi(Protocol):
    def parse(
        self,
        url_file_stream_or_string: object,
        *,
        response_headers: Mapping[str, str],
    ) -> object: ...


_FEEDPARSER = cast("_FeedparserApi", feedparser)


@dataclass(frozen=True, slots=True)
class FeedparserPodcastClient:
    """Fetch and normalize varied RSS/Atom feeds behind one typed interface."""

    timeout_seconds: int = _TIMEOUT_SECONDS

    def fetch(self, feed_url: str) -> PodcastSubscription:
        normalized = normalize_feed_url(feed_url)
        if not normalized:
            raise PodcastFeedError("Enter a valid HTTP or HTTPS podcast feed URL")
        payload, final_url = _request_bytes(
            normalized,
            limit=_FEED_LIMIT,
            timeout_seconds=self.timeout_seconds,
            accept="application/rss+xml, application/atom+xml, application/xml, text/xml",
        )
        parsed = _mapping(
            _FEEDPARSER.parse(
                io.BytesIO(payload),
                response_headers={"content-location": final_url},
            )
        )
        entries = _sequence(parsed.get("entries", ()))
        if parsed.get("bozo") and not entries:
            detail = str(parsed.get("bozo_exception", "malformed feed"))
            raise PodcastFeedError(f"The podcast feed could not be parsed: {detail}")
        feed = _mapping(parsed.get("feed", {}))
        title = _text(feed.get("title")) or "Unknown Podcast"
        author = _text(feed.get("author")) or _text(feed.get("itunes_author"))
        episodes = tuple(
            episode
            for raw in entries
            if (episode := _episode(_mapping(raw))) is not None
        )
        if not episodes:
            raise PodcastFeedError(
                "The feed does not contain playable podcast episodes"
            )
        from iOpenPod.app.podcasts.identity import subscription_identity

        return PodcastSubscription(
            subscription_identity(normalized, title, author),
            normalized,
            title,
            SubscriptionSource.USER,
            author=author,
            description=_plain_text(
                _text(feed.get("subtitle")) or _text(feed.get("summary"))
            ),
            artwork_url=_artwork_url(feed),
            category=_category(feed),
            language=_text(feed.get("language")),
            last_refreshed=int(time.time()),
            episodes=tuple(
                sorted(
                    episodes,
                    key=lambda item: (-item.published_at, item.episode_id),
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class ApplePodcastDirectoryClient:
    """Read text and feed links without retaining Apple's promotional artwork."""

    country: str = "US"
    result_limit: int = 25
    timeout_seconds: int = _TIMEOUT_SECONDS

    def search(self, query: str) -> tuple[PodcastSearchResult, ...]:
        term = query.strip()
        if not term:
            return ()
        parameters = urlencode(
            {
                "term": term,
                "media": "podcast",
                "entity": "podcast",
                "country": self.country.upper(),
                "limit": max(1, min(50, self.result_limit)),
            }
        )
        payload, _ = _request_bytes(
            f"{_DIRECTORY_URL}?{parameters}",
            limit=_SEARCH_LIMIT,
            timeout_seconds=self.timeout_seconds,
            accept="application/json",
        )
        try:
            document: object = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PodcastFeedError(
                "The podcast directory returned an unreadable response"
            ) from error
        root = _mapping(document)
        rows = _required_sequence(
            root.get("results", ()),
            "The podcast directory response is malformed",
        )
        results: list[PodcastSearchResult] = []
        for value in rows:
            row = _mapping(value)
            feed_url = normalize_feed_url(_text(row.get("feedUrl")))
            title = _text(row.get("collectionName"))
            if not feed_url or not title:
                continue
            count = row.get("trackCount", 0)
            results.append(
                PodcastSearchResult(
                    title,
                    _text(row.get("artistName")),
                    feed_url,
                    category=_text(row.get("primaryGenreName")),
                    episode_count=(
                        count
                        if isinstance(count, int)
                        and not isinstance(count, bool)
                        and count >= 0
                        else 0
                    ),
                )
            )
        return tuple(results)


@dataclass(frozen=True, slots=True)
class HttpPodcastArtworkLoader:
    """Fetch and safely normalize Podcast cover art for GUI presentation."""

    timeout_seconds: int = _TIMEOUT_SECONDS

    def load_artwork(
        self,
        request: PodcastArtworkRequest,
    ) -> PodcastArtworkImage | None:
        normalized = normalize_feed_url(request.source_url)
        if not normalized:
            return None
        payload, _final_url = _request_bytes(
            normalized,
            limit=_ARTWORK_LIMIT,
            timeout_seconds=self.timeout_seconds,
            accept="image/avif, image/webp, image/png, image/jpeg, image/*",
        )
        target_px = min(request.target_px, _ARTWORK_TARGET_LIMIT)
        try:
            with Image.open(io.BytesIO(payload)) as opened:
                width, height = opened.size
                if width <= 0 or height <= 0 or width * height > _ARTWORK_PIXEL_LIMIT:
                    raise PodcastFeedError("The Podcast artwork dimensions are unsafe")
                oriented = ImageOps.exif_transpose(opened)
                square = ImageOps.fit(
                    oriented.convert("RGB"),
                    (target_px, target_px),
                    method=Image.Resampling.LANCZOS,
                )
                rgb888 = square.tobytes()
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
            raise PodcastFeedError(
                "The Podcast artwork could not be decoded"
            ) from error
        digest = hashlib.sha256(payload).hexdigest()
        return PodcastArtworkImage(
            cache_key=f"{digest}/{target_px}",
            source_url=request.source_url,
            width=target_px,
            height=target_px,
            rgb888=rgb888,
        )


def _request_bytes(
    url: str,
    *,
    limit: int,
    timeout_seconds: int,
    accept: str,
) -> tuple[bytes, str]:
    request = Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": accept,
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            final_url = normalize_feed_url(response.geturl())
            if not final_url:
                raise PodcastFeedError("The request redirected outside HTTP or HTTPS")
            length = response.headers.get("Content-Length")
            if length and length.isascii() and length.isdigit() and int(length) > limit:
                raise PodcastFeedError("The response is larger than iOpenPod accepts")
            payload = response.read(limit + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise PodcastFeedError(f"The podcast request failed: {error}") from error
    if len(payload) > limit:
        raise PodcastFeedError("The response is larger than iOpenPod accepts")
    if not payload:
        raise PodcastFeedError("The podcast request returned an empty response")
    return payload, final_url


def _episode(entry: Mapping[str, object]) -> PodcastEpisode | None:
    enclosure_url = ""
    size_bytes = 0
    for name in ("enclosures", "links"):
        for value in _sequence(entry.get(name, ())):
            link = _mapping(value)
            relation = _text(link.get("rel"))
            if name == "links" and relation != "enclosure":
                continue
            candidate = _text(link.get("href"))
            mime = _text(link.get("type")).casefold()
            if not candidate or not (
                mime.startswith(("audio/", "video/"))
                or candidate.split("?", 1)[0].casefold().endswith(_MEDIA_EXTENSIONS)
            ):
                continue
            enclosure_url = candidate
            size_bytes = _nonnegative_integer(link.get("length"))
            break
        if enclosure_url:
            break
    if not enclosure_url:
        return None

    published_at = 0
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if isinstance(published, time.struct_time):
        try:
            published_at = max(0, calendar.timegm(published))
        except (OverflowError, ValueError):
            published_at = 0
    title = _text(entry.get("title")) or "Untitled Episode"
    guid = _text(entry.get("id"))
    episode_number = _positive_integer(entry.get("itunes_episode"))
    season_number = _positive_integer(entry.get("itunes_season"))
    return PodcastEpisode(
        episode_identity(
            enclosure_url=enclosure_url,
            guid=guid,
            title=title,
            published_at=published_at,
            episode_number=episode_number,
            season_number=season_number,
        ),
        guid=guid,
        title=title,
        description=_plain_text(
            _text(entry.get("subtitle")) or _text(entry.get("summary"))
        ),
        enclosure_url=enclosure_url,
        published_at=published_at,
        duration_seconds=_duration(_text(entry.get("itunes_duration"))),
        size_bytes=size_bytes,
        episode_number=episode_number,
        season_number=season_number,
    )


def _artwork_url(feed: Mapping[str, object]) -> str:
    for name in ("image", "itunes_image"):
        image = _mapping(feed.get(name))
        url = _text(image.get("href")) or _text(image.get("url"))
        if url:
            return url
    return ""


def _category(feed: Mapping[str, object]) -> str:
    for value in _sequence(feed.get("tags", ())):
        tag = _mapping(value)
        if term := _text(tag.get("term")):
            return term
    return ""


def _duration(value: str) -> int:
    if value.isascii() and value.isdigit():
        return int(value)
    parts = value.split(":")
    if len(parts) not in {2, 3} or any(not part.isdigit() for part in parts):
        return 0
    numbers = tuple(int(part) for part in parts)
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def _positive_integer(value: object) -> int | None:
    result = _nonnegative_integer(value)
    return result if result > 0 else None


def _nonnegative_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        return {}
    mapping = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in mapping):
        return {}
    return cast("Mapping[str, object]", mapping)


def _sequence(value: object) -> Sequence[object]:
    return cast("Sequence[object]", value) if isinstance(value, list) else ()


def _required_sequence(value: object, message: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise PodcastFeedError(message)
    return cast("Sequence[object]", value)


def _text(value: object) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _plain_text(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", value)).split())


__all__ = [
    "ApplePodcastDirectoryClient",
    "FeedparserPodcastClient",
    "HttpPodcastArtworkLoader",
    "PodcastArtworkLoader",
    "PodcastDirectoryClient",
    "PodcastFeedClient",
    "PodcastFeedError",
]
