"""A no-media-change Sync still publishes pending native artwork correction."""

from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_artwork_geometry_repair_save import (
    install_legacy_geometry,
)
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_sync_execution import (
    _host,  # pyright: ignore[reportPrivateUsage]
    _MissingTools,  # pyright: ignore[reportPrivateUsage]
    _prepare_genius_baseline,  # pyright: ignore[reportPrivateUsage]
    _request,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.sync_execution import SyncExecutionStatus, SyncExecutor


@pytest.mark.parametrize("cancel", [False, True])
def test_sync_without_media_changes_repairs_geometry(
    tmp_path: Path, cancel: bool
) -> None:
    device = build_device(tmp_path)
    try:
        _prepare_genius_baseline(device)
        install_legacy_geometry(device)
        assert device.active.artwork_repairs_pending
        database = device.root / "iPod_Control/iTunes/iTunesDB"
        original = database.read_bytes()
        request = _request(device, _host(tmp_path))
        assert not request.plan.change_count
        cancelled = Event()
        if cancel:
            cancelled.set()
        result = SyncExecutor(device.coordinator, transcoder=_MissingTools()).execute(
            request, lambda _: None, cancelled
        )
        if cancel:
            assert result.status is SyncExecutionStatus.CANCELLED
            assert device.active.artwork_repairs_pending
            assert (
                device.root / "iPod_Control/Artwork/ArtworkDB"
            ).read_bytes() == device.original["iPod_Control/Artwork/ArtworkDB"]
        else:
            assert result.status is SyncExecutionStatus.SUCCESS, result.issues
            assert result.active is not None
            assert not result.active.artwork_repairs_pending
            assert not result.completed
            assert database.read_bytes() == original
    finally:
        device.coordinator.close()
