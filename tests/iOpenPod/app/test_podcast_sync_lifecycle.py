"""Failed media Sync must not leave the Podcast editor on stale document revisions."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from PySide6.QtTest import QSignalSpy
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_library_write_controller import wait_for
from tests.iOpenPod.GUI.application_shell_test_support import build_context

from iOpenPod.app.podcasts.models import (
    PodcastSubscription,
    PodcastSyncSettings,
    SubscriptionSource,
)
from iOpenPod.app.podcasts.sync_preparation import prepare_podcast_sync
from iOpenPod.app.sync_controller import SyncController
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionResult,
    SyncExecutionStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from threading import Event

    from iOpenPod.app.library_write import WriteProgress
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator


class _Feeds:
    def __init__(self, show: PodcastSubscription) -> None:
        self.show = show

    def fetch(self, feed_url: str) -> PodcastSubscription:
        del feed_url
        return replace(self.show, last_refreshed=123)


class _InterruptedAfterRefresh:
    def __init__(
        self,
        coordinator: DeviceCoordinator,
        show: PodcastSubscription,
        status: SyncExecutionStatus,
    ) -> None:
        self.coordinator = coordinator
        self.feeds = _Feeds(show)
        self.status = status

    def execute(
        self,
        request: SyncExecutionRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: Event,
    ) -> SyncExecutionResult:
        del progress, cancelled
        assert request.podcasts is not None
        prepare_podcast_sync(
            request.podcasts,
            request.source,
            self.coordinator,
            lambda: None,
            feeds=self.feeds,
        )
        return SyncExecutionResult(self.status)


@pytest.mark.parametrize(
    "status", (SyncExecutionStatus.FAILED, SyncExecutionStatus.CANCELLED)
)
def test_unsuccessful_sync_reloads_podcast_state_before_the_next_edit(
    tmp_path: Path,
    status: SyncExecutionStatus,
) -> None:
    device = build_device(tmp_path)
    show = PodcastSubscription(
        "show",
        "https://publisher.example/feed",
        "Show",
        SubscriptionSource.USER,
    )
    loaded = device.coordinator.load_podcast_state(device.active)
    device.coordinator.save_podcast_state(
        device.active,
        replace(loaded, snapshot=replace(loaded.snapshot, subscriptions=(show,))),
    )
    context = build_context(device_coordinator=device.coordinator)
    context.library_workspace.active_ipod_changed(device.active)
    podcasts = context.podcast_controller
    podcasts.active_ipod_changed(device.active)
    controller = SyncController(
        _InterruptedAfterRefresh(device.coordinator, show, status),
        context.library_workspace,
        context.device_controller,
        context.settings,
    )
    controller.podcastStateInvalidated.connect(podcasts.reload)
    failures = QSignalSpy(podcasts.operationFailed)
    invalidations = QSignalSpy(controller.podcastStateInvalidated)
    try:
        wait_for(lambda: podcasts.can_sync)
        assert controller.start_podcasts(podcasts.sync_request(), device.active)
        wait_for(lambda: not controller.busy and podcasts.can_edit)
        assert invalidations.count() == 1
        assert podcasts.snapshot.subscriptions[0].last_refreshed == 123
        podcasts.set_sync_settings("show", PodcastSyncSettings(episode_slots=2))
        wait_for(lambda: podcasts.can_edit)
        assert failures.count() == 0
        current = device.coordinator.load_podcast_state(device.active)
        assert current.snapshot.subscriptions[0].sync_settings.episode_slots == 2
    finally:
        controller.shutdown()
        context.shutdown()
