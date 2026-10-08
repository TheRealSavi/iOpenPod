"""Shared Podcast Sync inputs and bounded publisher download doubles."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_sync_helper import IPodMediaCacheStats, IPodMediaLibrary
from iOpenPod.app.podcasts.models import (
    PodcastEpisode,
    PodcastSnapshot,
    PodcastSubscription,
    SubscriptionSource,
)
from iOpenPod.app.podcasts.sync import (
    PodcastEpisodeAddition,
    PodcastSyncPlan,
    PodcastSyncRequest,
)
from iOpenPod.app.podcasts.sync_preparation import PreparedPodcastSync
from iOpenPod.app.sync_execution import SyncExecutionRequest
from iOpenPod.app.sync_plan import SyncPlan
from iPodDB.library import LibrarySnapshot

if TYPE_CHECKING:
    from collections.abc import Callable
    from urllib.request import Request

    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator


def podcast_addition() -> PodcastEpisodeAddition:
    episode = PodcastEpisode(
        "episode",
        guid="publisher-guid",
        title="Downloaded Episode",
        description="Publisher description",
        enclosure_url="https://publisher.example/episode.m4a",
        published_at=1_700_000_000,
        episode_number=7,
        season_number=2,
    )
    show = PodcastSubscription(
        "show",
        "https://publisher.example/feed",
        "Show",
        SubscriptionSource.USER,
        author="Publisher",
        episodes=(episode,),
    )
    return PodcastEpisodeAddition(show, episode)


class PodcastResponse(io.BytesIO):
    def __init__(self, content: bytes, length: int | None = None) -> None:
        super().__init__(content)
        self.headers = {
            "Content-Length": str(len(content) if length is None else length)
        }

    def geturl(self) -> str:
        return "https://publisher.example/media.m4a"


class PodcastOpener:
    def __init__(self, content: bytes, length: int | None = None) -> None:
        self.content = content
        self.length = length

    def open(self, request: Request, *, timeout: int) -> PodcastResponse:
        assert request.full_url.startswith("https://publisher.example/")
        assert timeout > 0
        return PodcastResponse(self.content, self.length)


@dataclass(frozen=True)
class PodcastOpenerFactory:
    content: bytes
    length: int | None = None

    def __call__(self, *_handlers: object) -> PodcastOpener:
        return PodcastOpener(self.content, self.length)


@dataclass(frozen=True)
class FixedPodcastPlan:
    plan: PodcastSyncPlan

    def __call__(
        self,
        request: PodcastSyncRequest,
        source: ActiveIPod,
        coordinator: DeviceCoordinator,
        checkpoint: Callable[[], None],
    ) -> PreparedPodcastSync:
        del request
        checkpoint()
        return PreparedPodcastSync(self.plan, coordinator.load_podcast_state(source))


def podcast_request(source: ActiveIPod) -> SyncExecutionRequest:
    addition = podcast_addition()
    return SyncExecutionRequest(
        SyncPlan(()),
        HostMediaLibrary(LibrarySnapshot(), (), (), HostMediaCacheStats()),
        IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False),
        source,
        1,
        1,
        reconcile_playlists=False,
        podcasts=PodcastSyncRequest(
            PodcastSnapshot(subscriptions=(addition.subscription,), writable=True),
            automatic=False,
            additions=(
                (addition.subscription.subscription_id, addition.episode.episode_id),
            ),
        ),
    )
