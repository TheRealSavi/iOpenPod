"""Prepare bounded publisher covers and pictures for the Library artwork writer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.display_text import source_text
from iOpenPod.app.library_write import PreparationCancelledError, WriteProgress
from iOpenPod.app.podcasts.chapter_artwork import fetch_chapter_images
from iOpenPod.app.podcasts.feed_client import HttpPodcastArtworkLoader
from iOpenPod.app.podcasts.models import PodcastArtworkRequest
from iPodDB.library import ArtworkPixels, IssueSeverity, TimedArtworkFrame, WriteIssue

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.podcasts.feed_client import PodcastArtworkLoader
    from iOpenPod.app.podcasts.models import PodcastEpisode, PodcastSubscription

MAX_PODCAST_COVER_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PodcastCover:
    subscription_id: str
    pixels: ArtworkPixels


@dataclass(frozen=True, slots=True)
class PreparedPodcastCovers:
    covers: tuple[PodcastCover, ...] = ()
    issues: tuple[WriteIssue, ...] = ()


class PodcastArtworkPreparation:
    """One byte-bounded, URL-deduplicated source resolver for a Sync batch."""

    def __init__(
        self,
        *,
        checkpoint: Callable[[], None],
        progress: Callable[[WriteProgress], None],
        retained_bytes: int = 0,
        loader: PodcastArtworkLoader | None = None,
    ) -> None:
        self.checkpoint = checkpoint
        self.progress = progress
        self.used_bytes = retained_bytes
        self.issues: list[WriteIssue] = []
        self._loader = loader or HttpPodcastArtworkLoader(checkpoint=checkpoint)
        self._images: dict[tuple[str, int, bool], ArtworkPixels | None] = {}

    @property
    def remaining_bytes(self) -> int:
        return max(0, MAX_PODCAST_COVER_BYTES - self.used_bytes)

    def _issue(self, title: str, url: str, error: Exception) -> None:
        self.issues.append(
            WriteIssue(
                "sync.podcast_artwork_skipped",
                source_text(
                    "Artwork for {title} could not be prepared. Episodes can still sync.",
                    title=title,
                ),
                severity=IssueSeverity.WARNING,
                detail=str(error),
                artifact=url,
            )
        )

    def _load(
        self, url: str, title: str, target_px: int, *, preserve_aspect: bool = False
    ) -> ArtworkPixels | None:
        self.checkpoint()
        if not url:
            return None
        key = (url, target_px, preserve_aspect)
        if key not in self._images:
            self._images[key] = None
            self.progress(
                WriteProgress(
                    "sync.podcast_artwork",
                    source_text("Preparing artwork for {title}…", title=title),
                    current_item=title,
                )
            )
            try:
                image = self._loader.load_artwork(
                    PodcastArtworkRequest(url, target_px, preserve_aspect)
                )
                self.checkpoint()
                if image is None:
                    raise ValueError(
                        "The publisher did not provide a usable HTTP(S) image"
                    )
                if image.byte_count > self.remaining_bytes:
                    raise ValueError(
                        "Podcast artwork exceeds the 64 MiB preparation limit; sync fewer Podcasts at once"
                    )
                self.used_bytes += image.byte_count
                self._images[key] = ArtworkPixels(
                    image.width, image.height, image.rgb888
                )
            except PreparationCancelledError:
                raise
            except Exception as error:
                self._issue(title, url, error)
        return self._images[key]

    def cover(
        self, subscription: PodcastSubscription, episode: PodcastEpisode, target_px: int
    ) -> ArtworkPixels | None:
        return self.episode_cover(episode, target_px) or self.show_cover(
            subscription, target_px
        )

    def episode_cover(
        self, episode: PodcastEpisode, target_px: int
    ) -> ArtworkPixels | None:
        """Resolve the Episode's own publisher image before other cover sources."""
        return self._load(episode.artwork_url, episode.title, target_px)

    def show_cover(
        self, subscription: PodcastSubscription, target_px: int
    ) -> ArtworkPixels | None:
        """Resolve a show's cover using this batch's cache and retained-pixel budget."""
        return self._load(subscription.artwork_url, subscription.title, target_px)

    def source_url(self, pixels: ArtworkPixels) -> str:
        return next(
            url
            for (url, _size, _aspect), cached in self._images.items()
            if cached is pixels
        )

    def chapter_images(
        self,
        episode: PodcastEpisode,
        duration_ms: int,
        target_px: int,
        embedded: tuple[TimedArtworkFrame, ...],
    ) -> tuple[TimedArtworkFrame, ...]:
        self.checkpoint()
        sources = episode.chapter_images
        if episode.chapter_document_url:
            try:
                sources = (
                    *sources,
                    *fetch_chapter_images(
                        episode.chapter_document_url, checkpoint=self.checkpoint
                    ),
                )
            except PreparationCancelledError:
                raise
            except Exception as error:
                self._issue(episode.title, episode.chapter_document_url, error)
        frames = {frame.display_time_ms: frame for frame in embedded}
        # Embedded pictures win at an identical time. Missing/broken publisher
        # images never remove already captured frames or chapter navigation.
        for source in sorted(sources, key=lambda item: item.display_time_ms):
            self.checkpoint()
            position = source.display_time_ms
            if position in frames:
                continue
            if duration_ms <= 0 or position >= duration_ms:
                self._issue(
                    episode.title,
                    source.source_url,
                    ValueError("Chapter image time is outside the prepared Episode"),
                )
                continue
            pixels = self._load(
                source.source_url, episode.title, target_px, preserve_aspect=True
            )
            if pixels is not None:
                frames[position] = TimedArtworkFrame(position, pixels)
        return tuple(frames[key] for key in sorted(frames))


def prepare_podcast_covers(
    subscriptions: tuple[PodcastSubscription, ...],
    target_px: int,
    *,
    checkpoint: Callable[[], None],
    progress: Callable[[WriteProgress], None],
    loader: PodcastArtworkLoader | None = None,
    retained_bytes: int = 0,
) -> PreparedPodcastCovers:
    """Prepare show covers through the same bounded batch as Episode sources."""
    batch = PodcastArtworkPreparation(
        checkpoint=checkpoint,
        progress=progress,
        retained_bytes=retained_bytes,
        loader=loader,
    )
    covers: list[PodcastCover] = []
    for subscription in subscriptions:
        pixels = batch.show_cover(subscription, target_px)
        if pixels is not None:
            covers.append(PodcastCover(subscription.subscription_id, pixels))
    return PreparedPodcastCovers(tuple(covers), tuple(batch.issues))
