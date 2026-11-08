"""Preference workers retain connection ownership and report verified saves."""

from collections.abc import Callable
from pathlib import Path
from threading import Event, get_ident
from time import monotonic, sleep

import pytest
from PySide6.QtCore import QTranslator
from PySide6.QtWidgets import QLabel, QPushButton
from tests.iOpenPod.app.services.test_firmware_preferences import (
    EDIT,
    build_preferences_device,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app import developer_flags
from iOpenPod.app.context import AppContext
from iOpenPod.app.display_text import source_text
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.models.ipod_preferences import (
    IPodPreferenceEdit,
    IPodPreferencesCatalog,
)
from iOpenPod.app.services.device_coordinator import (
    DeviceAccessError,
    SyncRecoveryRequiredError,
)
from iOpenPod.GUI.widgets.ipod_preferences import IPodPreferencesView

pytestmark = pytest.mark.usefixtures("enable_ipod_preferences_writes")


def _wait(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 5
    while not predicate() and monotonic() < deadline:
        APPLICATION.processEvents()
        sleep(0.005)
    APPLICATION.processEvents()
    assert predicate()


def _context(tmp_path: Path) -> tuple[AppContext, ActiveIPod]:
    _, coordinator = build_preferences_device(tmp_path)
    active = coordinator.active_ipod
    assert active is not None
    context = build_context(device_coordinator=coordinator)
    context.device_controller.finish_library_save(active)
    _wait(lambda: not context.podcast_controller.busy)
    context.preferences_controller.refresh()
    _wait(lambda: not context.preferences_controller.busy)
    assert context.preferences_controller.can_write
    return context, active


def test_preferences_flag_keeps_inspection_and_blocks_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, active = _context(tmp_path)
    controller = context.preferences_controller
    monkeypatch.setattr(developer_flags, "ENABLE_IPOD_PREFERENCES_WRITES", False)
    view = IPodPreferencesView(controller=controller)
    try:
        refresh = view.findChild(QPushButton, "ipodPreferencesRefresh")
        assert refresh is not None and refresh.isEnabled()
        refresh.click()
        _wait(lambda: not controller.busy)
        assert controller.catalog.document is not None
        assert view.findChild(QLabel, "ipodPreference_device_sound_check") is not None
        apply = view.findChild(QPushButton, "ipodPreferencesApply")
        revert = view.findChild(QPushButton, "ipodPreferencesRevert")
        assert apply is not None and apply.isHidden()
        assert revert is not None and revert.isHidden()
        assert "read-only" in view.status_text
        assert not controller.can_write
        assert not controller.save(EDIT)
        with pytest.raises(
            DeviceAccessError, match="Writing iPod preferences is disabled"
        ):
            context.device_coordinator.save_preferences(
                active, controller.catalog, EDIT, Event()
            )
        assert context.device_controller.device_writes_allowed
    finally:
        view.close()
        context.shutdown()


@pytest.mark.parametrize("failure", ["none", "validation", "recovery"])
def test_saved_signal_only_follows_success_and_workers_release_reservations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    context, active = _context(tmp_path)
    controller = context.preferences_controller
    started, release = Event(), Event()
    thread_ids: list[int] = []
    saved: list[bool] = []
    original = controller.catalog

    def save(
        expected: ActiveIPod,
        catalog: IPodPreferencesCatalog,
        changes: tuple[IPodPreferenceEdit, ...],
        cancelled: Event,
    ) -> IPodPreferencesCatalog:
        assert expected is active and catalog is original and changes == EDIT
        assert not cancelled.is_set()
        thread_ids.append(get_ident())
        started.set()
        assert release.wait(5)
        if failure == "recovery":
            raise SyncRecoveryRequiredError("current-connection-journal")
        if failure == "validation":
            raise ValueError("Unsupported retained value")
        return original

    try:
        monkeypatch.setattr(context.device_coordinator, "save_preferences", save)
        controller.saved.connect(lambda: saved.append(True))
        assert controller.save(EDIT)
        assert started.wait(5)
        assert controller.busy
        assert not controller.can_write
        assert not context.device_controller.device_writes_allowed
        release.set()
        _wait(lambda: not controller.busy)
        assert thread_ids and thread_ids[0] != get_ident()
        assert saved == ([True] if failure == "none" else [])
        assert bool(controller.message) is (failure != "none")
        assert controller.catalog is original
        assert context.device_controller.device_writes_allowed is (
            failure != "recovery"
        )
    finally:
        release.set()
        context.shutdown()


@pytest.mark.parametrize("recovery", [False, True])
def test_stale_completion_cannot_publish_or_gate_another_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recovery: bool
) -> None:
    context, _active = _context(tmp_path)
    controller = context.preferences_controller
    original = controller.catalog
    started, release = Event(), Event()
    saved: list[bool] = []

    def save(
        expected: ActiveIPod,
        catalog: IPodPreferencesCatalog,
        changes: tuple[IPodPreferenceEdit, ...],
        cancelled: Event,
    ) -> IPodPreferencesCatalog:
        started.set()
        assert release.wait(5)
        assert cancelled.is_set()
        if recovery:
            raise SyncRecoveryRequiredError("old-connection-journal")
        return original

    gates: list[bool] = []
    try:
        monkeypatch.setattr(context.device_coordinator, "save_preferences", save)
        monkeypatch.setattr(
            context.device_controller, "set_recovery_required", gates.append
        )
        controller.saved.connect(lambda: saved.append(True))
        assert controller.save(EDIT)
        assert started.wait(5)
        context.device_controller.finish_sync_recovery(None)
        release.set()
        _wait(lambda: not controller.busy)
        assert not saved and not gates
        assert controller.catalog.document is None
        assert not controller.message
    finally:
        release.set()
        context.shutdown()


def test_shutdown_cancels_worker_and_releases_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, _active = _context(tmp_path)
    controller = context.preferences_controller
    original = controller.catalog
    started = Event()
    released: list[bool] = []
    real_finish = context.device_controller.finish_exclusive_operation

    def finish() -> None:
        released.append(True)
        real_finish()

    def save(
        expected: ActiveIPod,
        catalog: IPodPreferencesCatalog,
        changes: tuple[IPodPreferenceEdit, ...],
        cancelled: Event,
    ) -> IPodPreferencesCatalog:
        started.set()
        assert cancelled.wait(5)
        return original

    try:
        monkeypatch.setattr(context.device_coordinator, "save_preferences", save)
        monkeypatch.setattr(
            context.device_controller, "finish_exclusive_operation", finish
        )
        assert controller.save(EDIT)
        assert started.wait(5)
        controller.shutdown()
        APPLICATION.processEvents()
        assert released == [True]
        assert not controller.busy and not controller.can_write
    finally:
        context.shutdown()


def test_completed_failure_retains_template_for_later_language_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, _active = _context(tmp_path)
    controller = context.preferences_controller
    original = controller.catalog
    source = source_text("This preference is not available for editing.")
    translator = QTranslator()
    view = IPodPreferencesView(controller=controller)

    def save(
        expected: ActiveIPod,
        catalog: IPodPreferencesCatalog,
        changes: tuple[IPodPreferenceEdit, ...],
        cancelled: Event,
    ) -> IPodPreferencesCatalog:
        raise ValueError(source)

    try:
        monkeypatch.setattr(context.device_coordinator, "save_preferences", save)
        assert controller.save(EDIT)
        _wait(lambda: not controller.busy)
        assert controller.message is source
        assert controller.catalog is original
        assert controller.can_write
        assert view.status_text == source
        catalog = (
            Path(__file__).resolve().parents[3]
            / "src/iOpenPod/GUI/presentation/i18n/translations/iopenpod_de.qm"
        )
        assert translator.load(str(catalog))
        assert APPLICATION.installTranslator(translator)
        translated = translator.translate("Workflow", source.source)
        assert translated and translated != source
        assert view.status_text == translated
    finally:
        APPLICATION.removeTranslator(translator)
        view.close()
        context.shutdown()
