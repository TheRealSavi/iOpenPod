"""Read publisher chapter-image times without importing chapter navigation."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from iOpenPod.app.podcasts.feed_client import PodcastFeedError, request_podcast_bytes
from iOpenPod.app.podcasts.feed_extensions import (
    MAX_CHAPTER_IMAGES,
    image_time_ms,
    publisher_url,
)
from iOpenPod.app.podcasts.identity import normalize_feed_url
from iOpenPod.app.podcasts.models import PodcastChapterImage

if TYPE_CHECKING:
    from collections.abc import Callable


def fetch_chapter_images(
    url: str, *, checkpoint: Callable[[], None]
) -> tuple[PodcastChapterImage, ...]:
    url = normalize_feed_url(url)
    if not url:
        raise PodcastFeedError("The chapter artwork document requires an HTTP(S) URL")
    payload, final_url = request_podcast_bytes(
        url,
        limit=1024 * 1024,
        timeout_seconds=20,
        accept="application/json+chapters, application/json",
        checkpoint=checkpoint,
    )
    checkpoint()
    return parse_chapter_images(payload, final_url)


def parse_chapter_images(
    payload: bytes, base_url: str
) -> tuple[PodcastChapterImage, ...]:
    """Only finite millisecond positions and public HTTP(S) image URLs escape."""
    try:
        document: object = json.loads(payload, parse_float=Decimal)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise PodcastFeedError(
            "The chapter artwork document is not valid JSON"
        ) from error
    if not isinstance(document, dict):
        raise PodcastFeedError("The chapter artwork document must be an object")
    root = cast("dict[str, object]", document)
    version, chapters = root.get("version"), root.get("chapters")
    if (
        not isinstance(version, str)
        or not version.startswith("1.")
        or not isinstance(chapters, list)
    ):
        raise PodcastFeedError(
            "The chapter artwork document uses an unsupported format"
        )
    rows = cast("list[object]", chapters)
    if len(rows) > 4096:
        raise PodcastFeedError("The chapter artwork document contains too many entries")
    images: list[PodcastChapterImage] = []
    for value in rows:
        if not isinstance(value, dict):
            continue
        row = cast("dict[str, object]", value)
        start, image = row.get("startTime"), row.get("img")
        if (
            isinstance(start, bool)
            or not isinstance(start, (int, Decimal))
            or not isinstance(image, str)
        ):
            continue
        position = image_time_ms(str(start))
        url = publisher_url(image, base_url)
        if position is not None and url:
            images.append(PodcastChapterImage(position, url))
    if len(images) > MAX_CHAPTER_IMAGES:
        raise PodcastFeedError("The Episode contains too many chapter images")
    return tuple(sorted(images, key=lambda item: item.display_time_ms))
