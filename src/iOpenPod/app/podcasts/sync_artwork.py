"""Prepare bounded publisher covers for the shared Library artwork writer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.library_write import PreparationCancelledError, WriteProgress
from iOpenPod.app.podcasts.feed_client import HttpPodcastArtworkLoader
from iOpenPod.app.podcasts.models import PodcastArtworkRequest
from iPodDB.library import ArtworkPixels, IssueSeverity, WriteIssue

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.podcasts.feed_client import PodcastArtworkLoader
    from iOpenPod.app.podcasts.models import PodcastSubscription

_MAX_BATCH_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PodcastCover:
    subscription_id: str
    pixels: ArtworkPixels


@dataclass(frozen=True, slots=True)
class PreparedPodcastCovers:
    covers: tuple[PodcastCover, ...] = ()
    issues: tuple[WriteIssue, ...] = ()


def prepare_podcast_covers(
    subscriptions: tuple[PodcastSubscription, ...],
    target_px: int,
    *,
    checkpoint: Callable[[], None],
    progress: Callable[[WriteProgress], None],
    loader: PodcastArtworkLoader | None = None,
) -> PreparedPodcastCovers:
    """Decode each publisher URL once; artwork failure never discards media."""
    client = loader or HttpPodcastArtworkLoader(checkpoint=checkpoint)
    by_url: dict[str, ArtworkPixels | None] = {}
    covers: list[PodcastCover] = []
    issues: list[WriteIssue] = []
    retained_bytes = 0
    for subscription in subscriptions:
        checkpoint()
        url = subscription.artwork_url
        if not url:
            continue
        if url not in by_url:
            progress(
                WriteProgress(
                    "sync.podcast_artwork",
                    f"Preparing artwork for {subscription.title}…",
                    current_item=subscription.title,
                )
            )
            by_url[url] = None
            try:
                image = client.load_artwork(PodcastArtworkRequest(url, target_px))
                checkpoint()
                if image is None:
                    raise ValueError(
                        "The publisher did not provide a usable HTTP(S) cover"
                    )
                if retained_bytes + image.byte_count > _MAX_BATCH_BYTES:
                    raise ValueError(
                        "Podcast covers exceed the 64 MiB preparation limit; sync fewer Podcasts at once"
                    )
                pixels = ArtworkPixels(image.width, image.height, image.rgb888)
                by_url[url] = pixels
                retained_bytes += len(pixels.rgb888)
            except PreparationCancelledError:
                raise
            except Exception as error:
                issues.append(
                    WriteIssue(
                        "sync.podcast_artwork_skipped",
                        f"Artwork for {subscription.title} could not be prepared. "
                        "Episodes can still sync. Sync this Podcast again to retry its artwork.",
                        severity=IssueSeverity.WARNING,
                        detail=str(error),
                        artifact=url,
                    )
                )
        cached_pixels = by_url[url]
        if cached_pixels is not None:
            covers.append(PodcastCover(subscription.subscription_id, cached_pixels))
    return PreparedPodcastCovers(tuple(covers), tuple(issues))
