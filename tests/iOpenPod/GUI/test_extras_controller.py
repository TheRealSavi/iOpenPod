"""Extras workers retain connection ownership and discard stale GUI delivery."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event, get_ident
from time import monotonic, sleep

import pytest
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context
from whenever import Date

from device_registry import AlarmFormat, ExtrasSupport, FeatureSupport
from iOpenPod.app.context import AppContext
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.models.extras import ExtrasCatalog, ExtrasChange
from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinator,
    SyncRecoveryRequiredError,
)
from iPodDB.calendar import CalendarEditError, CalendarEntryDraft
from storage import HardwareIdentifiers, Storage
from storage.testing import VirtualStoragePlatform

SUPPORT = ExtrasSupport(True, AlarmFormat.CLASSIC, True, FeatureSupport.SUPPORTED)
DRAFT = CalendarEntryDraft(summary="New event", start=Date(2026, 11, 7))


def _wait_until(predicate: Callable[[], bool], *, timeout: float = 5) -> None:
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        # Yield the GIL to the real QThreadPool worker without blocking Qt.
        sleep(0.005)
    APPLICATION.processEvents()
    assert predicate()


def _context(tmp_path: Path) -> tuple[AppContext, ActiveIPod]:
    root = tmp_path / "device"
    metadata = root / "iPod_Control/Device"
    metadata.mkdir(parents=True)
    (metadata / "SysInfo").write_text(
        "ModelNumStr: MB565\nUpdaterFamilyID: 33\nvisibleBuildID: 2.0.1\n"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root, identifiers=HardwareIdentifiers(transport_serial="0011223344556677")
    )
    coordinator = DeviceCoordinator(
        Storage(platform), volume_presentation_enabled=False
    )
    active = coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    context = build_context(device_coordinator=coordinator)
    context.device_controller.finish_library_save(active)
    _wait_until(lambda: not context.podcast_controller.busy)
    assert context.device_controller.device_writes_allowed
    return context, active


def _load_ready(context: AppContext, monkeypatch: pytest.MonkeyPatch) -> ExtrasCatalog:
    initial = ExtrasCatalog(support=SUPPORT)

    def load(_expected: ActiveIPod, _cancelled: Event) -> ExtrasCatalog:
        return initial

    monkeypatch.setattr(context.device_coordinator, "load_extras", load)
    context.extras_controller.refresh()
    _wait_until(lambda: not context.extras_controller.busy)
    assert context.extras_controller.catalog is initial
    assert context.extras_controller.can_write
    return initial


@pytest.mark.parametrize("operation", ["read", "write"])
def test_workers_run_off_gui_thread_and_release_their_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    context, active = _context(tmp_path)
    controller = context.extras_controller
    devices = context.device_controller
    started, release = Event(), Event()
    worker_threads: list[int] = []
    signal_threads: list[int] = []
    result = ExtrasCatalog(
        support=SUPPORT, issues=("Date retained without interpretation",)
    )

    def changed() -> None:
        signal_threads.append(get_ident())

    def load(expected: ActiveIPod, _cancelled: Event) -> ExtrasCatalog:
        assert expected is active
        worker_threads.append(get_ident())
        started.set()
        assert release.wait(5)
        return result

    def save(
        expected: ActiveIPod,
        previous: ExtrasCatalog,
        _change: ExtrasChange,
        cancelled: Event,
    ) -> ExtrasCatalog:
        assert previous is initial
        return load(expected, cancelled)

    try:
        initial = _load_ready(context, monkeypatch)
        controller.changed.connect(changed)
        monkeypatch.setattr(context.device_coordinator, "load_extras", load)
        monkeypatch.setattr(context.device_coordinator, "save_extras", save)
        if operation == "read":
            controller.refresh()
        else:
            assert controller.save_calendar(DRAFT)
        assert started.wait(5)
        assert controller.busy
        assert devices.busy is (operation == "write")
        assert not devices.device_writes_allowed
        assert not devices.begin_exclusive_operation()
        assert not controller.save_calendar(DRAFT)
        assert len(worker_threads) == 1
        assert worker_threads[0] != get_ident()
        if operation == "write":
            assert any(
                status.source == "extras.write"
                for status in context.status.active_messages
            )
        release.set()
        _wait_until(lambda: not controller.busy)
        assert controller.catalog is result
        assert controller.can_write and devices.device_writes_allowed
        assert not devices.busy and not controller.message
        assert signal_threads and set(signal_threads) == {get_ident()}
        assert all(
            status.source != "extras.write" for status in context.status.active_messages
        )
        assert devices.begin_exclusive_operation()
        devices.finish_exclusive_operation()
    finally:
        release.set()
        context.shutdown()


@pytest.mark.parametrize("operation", ["read", "write"])
@pytest.mark.parametrize("failure", [False, True])
def test_old_device_completion_cannot_replace_catalog_or_gate_new_device(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    failure: bool,
) -> None:
    context, active = _context(tmp_path)
    controller = context.extras_controller
    devices = context.device_controller
    replacement = replace(active)
    started, release = Event(), Event()
    cancellations: list[Event] = []
    old = ExtrasCatalog(support=SUPPORT, issues=("Old device result",))
    fresh = ExtrasCatalog(support=SUPPORT, issues=("Replacement device result",))
    observed: list[ExtrasCatalog] = []

    def delayed(expected: ActiveIPod, cancelled: Event) -> ExtrasCatalog:
        assert expected is active
        cancellations.append(cancelled)
        started.set()
        assert release.wait(5)
        if failure:
            raise SyncRecoveryRequiredError("Old device retained journal")
        return old

    def load(expected: ActiveIPod, cancelled: Event) -> ExtrasCatalog:
        if expected is active and operation == "read":
            return delayed(expected, cancelled)
        assert expected is replacement
        return fresh

    def save(
        expected: ActiveIPod,
        _catalog: ExtrasCatalog,
        _change: ExtrasChange,
        cancelled: Event,
    ) -> ExtrasCatalog:
        return delayed(expected, cancelled)

    def changed() -> None:
        observed.append(controller.catalog)

    try:
        _load_ready(context, monkeypatch)
        monkeypatch.setattr(context.device_coordinator, "load_extras", load)
        monkeypatch.setattr(context.device_coordinator, "save_extras", save)
        controller.changed.connect(changed)
        if operation == "read":
            controller.refresh()
        else:
            assert controller.save_calendar(DRAFT)
        assert started.wait(5)
        devices.finish_library_save(replacement)
        assert cancellations[0].is_set()
        assert controller.catalog == ExtrasCatalog()
        release.set()
        _wait_until(lambda: not controller.busy and controller.catalog is fresh)
        _wait_until(lambda: not context.podcast_controller.busy)
        assert all(catalog is not old for catalog in observed)
        assert devices.active_ipod is replacement
        assert controller.can_write and devices.device_writes_allowed
        assert not controller.message
    finally:
        release.set()
        context.shutdown()


@pytest.mark.parametrize("operation", ["read", "write"])
def test_shutdown_cancels_and_releases_without_queued_completion_releasing_new_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    context, active = _context(tmp_path)
    controller = context.extras_controller
    devices = context.device_controller
    started, saw_cancellation = Event(), Event()
    result = ExtrasCatalog(support=SUPPORT, issues=("Must not publish after shutdown",))

    def load(expected: ActiveIPod, cancelled: Event) -> ExtrasCatalog:
        assert expected is active
        started.set()
        assert cancelled.wait(5)
        saw_cancellation.set()
        return result

    def save(
        expected: ActiveIPod,
        _catalog: ExtrasCatalog,
        _change: ExtrasChange,
        cancelled: Event,
    ) -> ExtrasCatalog:
        return load(expected, cancelled)

    try:
        initial = _load_ready(context, monkeypatch)
        monkeypatch.setattr(context.device_coordinator, "load_extras", load)
        monkeypatch.setattr(context.device_coordinator, "save_extras", save)
        if operation == "read":
            controller.refresh()
        else:
            assert controller.save_calendar(DRAFT)
        assert started.wait(5)
        assert not devices.device_writes_allowed
        controller.shutdown()
        assert saw_cancellation.is_set()
        assert not controller.busy
        assert devices.device_writes_allowed
        assert controller.catalog is initial
        assert not controller.can_write
        assert all(
            status.source != "extras.write" for status in context.status.active_messages
        )
        assert devices.begin_exclusive_operation()
        # The worker signal was queued while shutdown waited on the GUI thread.
        APPLICATION.processEvents()
        assert devices.busy
        assert controller.catalog is initial
        assert not controller.message
        devices.finish_exclusive_operation()
    finally:
        context.shutdown()


@pytest.mark.parametrize("failure", ["recovery", "datetime", "parse"])
def test_only_recovery_failure_gates_later_library_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    context, active = _context(tmp_path)
    controller = context.extras_controller
    devices = context.device_controller

    def save(
        expected: ActiveIPod,
        _catalog: ExtrasCatalog,
        _change: ExtrasChange,
        _cancelled: Event,
    ) -> ExtrasCatalog:
        assert expected is active
        if failure == "recovery":
            raise SyncRecoveryRequiredError("Retained transaction journal")
        if failure == "datetime":
            raise CalendarEditError("The entered event date is invalid")
        raise ValueError("Unsupported Calendar property encoding")

    try:
        initial = _load_ready(context, monkeypatch)
        monkeypatch.setattr(context.device_coordinator, "save_extras", save)
        assert controller.save_calendar(DRAFT)
        _wait_until(lambda: not controller.busy)
        assert controller.catalog is initial
        assert controller.message
        assert not devices.busy
        assert devices.device_writes_allowed is (failure != "recovery")
        assert controller.can_write is (failure != "recovery")
        assert all(
            status.source != "extras.write" for status in context.status.active_messages
        )
        assert devices.begin_library_save() is (failure != "recovery")
        if failure != "recovery":
            devices.finish_library_save(None)
    finally:
        context.shutdown()
