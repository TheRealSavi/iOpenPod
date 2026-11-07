"""Device scan progress stays responsive even when cached results arrive rapidly."""

from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app import ipod_media_controller
from iOpenPod.app.library_sync_helper import (
    IPodMediaCacheStats,
    IPodMediaLibrary,
    IPodMediaScanProgress,
    IPodMediaScanStage,
)
from iOpenPod.app.models.device import ActiveIPod


def test_scan_worker_bounds_queued_progress_and_preserves_phase_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    now = 0.0
    monkeypatch.setattr(ipod_media_controller, "monotonic", lambda: now, raising=False)
    result = IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
    events: list[IPodMediaScanProgress] = []
    outcomes: list[tuple[object, str]] = []

    def scan(
        expected: ActiveIPod,
        progress: Callable[[IPodMediaScanProgress], None],
        cancelled: Event,
    ) -> IPodMediaLibrary:
        nonlocal now
        assert expected is device.active and not cancelled.is_set()
        progress(IPodMediaScanProgress(IPodMediaScanStage.LOADING, 0, 0, "Loading"))
        for stage in (IPodMediaScanStage.TRACKS, IPodMediaScanStage.IMAGES):
            for index in range(1, 10_001):
                now += 0.0001
                progress(IPodMediaScanProgress(stage, index, 10_000, "Reusing"))
        progress(
            IPodMediaScanProgress(IPodMediaScanStage.COMPLETE, 20_000, 20_000, "Done")
        )
        return result

    def record_progress(_token: int, value: object) -> None:
        assert isinstance(value, IPodMediaScanProgress)
        events.append(value)

    def record_completion(_token: int, value: object, error: str) -> None:
        outcomes.append((value, error))

    monkeypatch.setattr(device.coordinator, "scan_ipod_media", scan)
    job = ipod_media_controller._IPodScan(1, device.active, device.coordinator)  # pyright: ignore[reportPrivateUsage]
    job.signals.progress.connect(record_progress)
    job.signals.completed.connect(record_completion)
    try:
        job.run()
        APPLICATION.processEvents()
        assert outcomes == [(result, "")]
        assert len(events) < 30
        assert events[0].stage is IPodMediaScanStage.LOADING
        assert events[-1].stage is IPodMediaScanStage.COMPLETE
        assert events[-1].completed == 20_000
        for stage in (IPodMediaScanStage.TRACKS, IPodMediaScanStage.IMAGES):
            phase = [event for event in events if event.stage is stage]
            assert phase[0].completed == 1
            assert phase[-1].completed == phase[-1].total == 10_000
            assert len(phase) >= 10  # Long phases still publish live progress.
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("fails", [False, True])
def test_cancellation_discards_already_queued_progress_and_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    device = build_device(tmp_path)
    context = build_context(device_coordinator=device.coordinator)
    context.device_controller.finish_library_save(device.active)
    controller = context.ipod_media_controller
    result = IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
    finished: list[object] = []
    failed: list[str] = []
    cancelled: list[bool] = []
    progress_events: list[object] = []
    released: list[bool] = []
    native_release = context.device_controller.finish_exclusive_operation

    def release() -> None:
        released.append(True)
        native_release()

    def scan(
        expected: ActiveIPod,
        progress: Callable[[IPodMediaScanProgress], None],
        cancelled: Event,
    ) -> IPodMediaLibrary:
        progress(IPodMediaScanProgress(IPodMediaScanStage.COMPLETE, 1, 1, "Done"))
        if fails:
            raise OSError("Read failed before the user cancelled")
        return result

    monkeypatch.setattr(device.coordinator, "scan_ipod_media", scan)
    monkeypatch.setattr(
        context.device_controller, "finish_exclusive_operation", release
    )
    controller.finished.connect(finished.append)
    controller.failed.connect(failed.append)
    controller.cancelled.connect(lambda: cancelled.append(True))
    controller.progressChanged.connect(progress_events.append)
    try:
        assert controller.start()
        # Complete the worker without delivering its queued GUI events yet.
        assert controller._pool.waitForDone(5000)  # pyright: ignore[reportPrivateUsage]
        controller.cancel()
        assert controller.busy and context.device_controller.busy
        APPLICATION.processEvents()
        assert finished == failed == progress_events == []
        assert cancelled == released == [True]
        assert not controller.busy and not context.device_controller.busy

        fails = False
        assert controller.start()
        assert controller._pool.waitForDone(5000)  # pyright: ignore[reportPrivateUsage]
        APPLICATION.processEvents()
        assert finished == [result]
        assert failed == []
        assert cancelled == [True]
        assert released == [True, True]
    finally:
        context.shutdown()
