"""Tests verifying Subsonic source resolution safety on SyncExecutor."""

from unittest.mock import MagicMock

from iOpenPod.app.sync_execution import SyncExecutionRequest, SyncExecutor
from iOpenPod.app.sync_plan import SyncPlan


def test_sync_executor_has_resolve_subsonic_sources() -> None:
    coordinator = MagicMock()
    executor = SyncExecutor(coordinator)
    assert hasattr(executor, "_resolve_subsonic_sources")

    # Safety net should be a callable on SyncExecutor
    assert callable(executor._resolve_subsonic_sources)

    # Calling with empty or normal plan items is a safe no-op
    request = MagicMock(spec=SyncExecutionRequest)
    request.plan = SyncPlan(items=())
    executor._resolve_subsonic_sources(request)
