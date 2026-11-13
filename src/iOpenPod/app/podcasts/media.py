"""Bounded Podcast enclosure downloads into Storage-owned private Host captures."""

from __future__ import annotations

import time
from contextlib import contextmanager, suppress
from http.client import HTTPException
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request

from whenever import Instant

from iOpenPod.app.podcasts.http_client import open_podcast_request
from iOpenPod.app.podcasts.identity import normalize_feed_url
from iPodDB.library import MediaType, Track, TrackMetadata
from storage.media_processing import media_workspace

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from typing import BinaryIO

    from iOpenPod.app.podcasts.credentials import PodcastAccess
    from iOpenPod.app.podcasts.sync import PodcastEpisodeAddition
    from storage import HostPath

MAX_EPISODE_BYTES = 4 * 1024 * 1024 * 1024
_TIMEOUT_SECONDS = 20
_DEADLINE_SECONDS = 60 * 60
_SUFFIXES = frozenset(
    (
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
)


@contextmanager
def download_episode(
    addition: PodcastEpisodeAddition,
    *,
    checkpoint: Callable[[], None],
    progress: Callable[[int, int | None], None] | None = None,
    access: PodcastAccess | None = None,
) -> Generator[HostPath]:
    """Stream an enclosure without trusting RSS size, filenames, or media types."""
    url = normalize_feed_url(addition.episode.enclosure_url)
    if not url:
        raise ValueError("This episode has no valid HTTP or HTTPS media enclosure")
    started = time.monotonic()

    def check() -> None:
        checkpoint()
        if time.monotonic() - started > _DEADLINE_SECONDS:
            raise TimeoutError("The Podcast download exceeded its one-hour deadline")

    suffix = PurePosixPath(urlsplit(url).path).suffix.casefold()
    if suffix not in _SUFFIXES:
        suffix = ".media"
    request = Request(
        url,
        headers={
            "User-Agent": "iOpenPod/2 Podcast Sync",
            "Accept": "audio/*, video/*, application/octet-stream",
            "Accept-Encoding": "identity",
        },
    )
    check()
    try:
        with (
            open_podcast_request(
                request,
                timeout=_TIMEOUT_SECONDS,
                feed_url=addition.subscription.feed_url,
                access=access,
            ) as response,
            media_workspace(checkpoint=check) as workspace,
        ):
            if not normalize_feed_url(response.url):
                raise ValueError("The Podcast download returned an unsupported URL")
            encoding = str(response.headers.get("Content-Encoding", "identity"))
            if encoding.casefold() not in ("", "identity"):
                raise ValueError("The Podcast download used an unsupported encoding")
            length = response.headers.get("Content-Length")
            expected = int(length) if length is not None else None
            captured = workspace.capture_stream(
                cast("BinaryIO", response),
                suffix,
                max_bytes=MAX_EPISODE_BYTES,
                expected_size=expected,
                progress=(
                    (lambda size: progress(size, expected))
                    if progress is not None
                    else None
                ),
            )
            yield captured.snapshot
    except (URLError, HTTPException):
        raise OSError(
            "The Podcast media download failed. Check your connection and try again."
        ) from None


def episode_track(addition: PodcastEpisodeAddition, *, video: bool = False) -> Track:
    """Translate publisher metadata into the common incoming Track contract."""
    subscription, episode = addition.subscription, addition.episode
    year = 0
    if episode.published_at:
        with suppress(OverflowError, OSError, ValueError):
            year = Instant.from_timestamp(episode.published_at).to_fixed_offset().year
    return Track(
        0,
        episode.title or "Untitled Episode",
        episode.author or subscription.author,
        subscription.title,
        episode.duration_seconds * 1000,
        genre="Podcast",
        year=year,
        track_number=episode.episode_number or 0,
        play_count=episode.play_count,
        media_types=(MediaType.VIDEO_PODCAST,) if video else (MediaType.PODCAST,),
        show=subscription.title,
        episode=episode.guid,
        album_artist=subscription.author,
        season_number=episode.season_number or 0,
        episode_number=episode.episode_number or 0,
        metadata=TrackMetadata(
            podcast=True,
            podcast_guid=episode.guid or episode.enclosure_url,
            podcast_rss_url=subscription.feed_url,
            description=episode.description,
            subtitle=episode.subtitle or episode.description[:255],
            content_advisory=episode.content_advisory,
            last_modified=Instant.now().timestamp(),
            release_date=episode.published_at,
            category=subscription.category,
            copyright=subscription.copyright,
            skip_shuffle=True,
            remember_position=True,
            played=episode.listened,
            last_played=episode.last_played,
        ),
    )
