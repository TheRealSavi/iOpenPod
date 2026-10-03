"""Store outcomes and controller policy without a live Store installation."""

import ctypes
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Thread
from time import monotonic
from types import SimpleNamespace

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from iOpenPod.app.core.status import ApplicationStatus
from iOpenPod.app.updates import windows
from iOpenPod.app.updates.backend import (
    InstallChannel,
    UpdateOutcome,
    UpdateProgress,
    UpdateProvider,
    UpdateResult,
)
from iOpenPod.app.updates.controller import UPDATE_STATUS_SOURCE, UpdateController
from iOpenPod.app.updates.windows import (
    NativeProgress,
    StoreBackend,
    install_result,
)

APPLICATION = QApplication.instance() or QApplication([])


def test_portable_download_keeps_work_usable_until_explicit_guarded_restart() -> None:
    backend = FakeBackend()
    status = ApplicationStatus()
    calls: list[str] = []
    blocked = True

    def prepare() -> str:
        calls.append("prepare")
        return "Save the Library Draft first" if blocked else ""

    updater = UpdateController(
        status,
        lambda: UpdateProvider(
            InstallChannel.FROZEN, backend, "GitHub", staged_download=True
        ),
        prepare,
        lambda: calls.append("finish"),
    )

    def restarted(native: bool) -> None:
        calls.append("restart-native" if native else "restart")

    updater.restartRequested.connect(restarted)
    try:
        updater.start()
        backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
        status.request_action(UPDATE_STATUS_SOURCE, "install")
        backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
        assert backend.downloads == 1 and not updater.installing and not calls
        backend.deliver(UpdateResult(UpdateOutcome.READY))
        assert backend.installs == 0
        status.request_action(UPDATE_STATUS_SOURCE, "restart")
        assert backend.installs == 0 and not updater.installing
        blocked = False
        status.request_action(UPDATE_STATUS_SOURCE, "restart")
        assert backend.installs == 1 and updater.installing
        backend.deliver(UpdateResult(UpdateOutcome.HANDOFF))
        assert updater.handing_off and updater.installing and backend.handoffs == 1
        assert calls == ["prepare", "prepare", "restart"]
    finally:
        updater.close()


def wait_until(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 2
    while not predicate() and monotonic() < deadline:
        QTest.qWait(10)
    assert predicate(), "The expected update event was not delivered"


def test_cancel_download_closes_worker_without_acquiring_install_guard() -> None:
    backend = FakeBackend()
    status = ApplicationStatus()
    calls: list[str] = []

    def prepare() -> str:
        calls.append("prepare")
        return ""

    updater = UpdateController(
        status,
        lambda: UpdateProvider(
            InstallChannel.FROZEN, backend, "GitHub", staged_download=True
        ),
        prepare,
        lambda: calls.append("finish"),
    )
    try:
        updater.start()
        backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
        status.request_action(UPDATE_STATUS_SOURCE, "install")
        backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
        backend.deliver(UpdateProgress("archive.zip", 0.25, False))
        assert status.current_status is not None
        assert status.current_status.action is not None
        assert status.current_status.action.key == "cancel-download"
        status.request_action(UPDATE_STATUS_SOURCE, "cancel-download")
        assert backend.closed and not updater.busy and not updater.installing
        assert not calls and backend.installs == 0
        # A late worker event cannot turn cancellation into a restart.
        backend.event = UpdateResult(UpdateOutcome.READY)
        QTest.qWait(150)
        status.request_action(UPDATE_STATUS_SOURCE, "restart")
        assert backend.installs == 0 and "canceled" in updater.message
    finally:
        updater.close()


class FakeBackend:
    def __init__(self) -> None:
        self.checks = 0
        self.downloads = 0
        self.handoffs = 0
        self.installs = 0
        self.closed = False
        self.event: UpdateResult | UpdateProgress | None = None
        self.error: Exception | None = None

    def check(self) -> None:
        self.checks += 1
        if self.error:
            raise self.error

    def install(self) -> None:
        self.installs += 1

    def download(self) -> None:
        self.downloads += 1

    def complete_handoff(self) -> None:
        self.handoffs += 1

    def poll(self) -> UpdateResult | UpdateProgress | None:
        event, self.event = self.event, None
        return event

    def close(self) -> None:
        self.closed = True

    def deliver(self, event: UpdateResult | UpdateProgress) -> None:
        """Let the real Qt timer consume one native-backend event."""
        self.event = event
        wait_until(lambda: self.event is None)


def controller(
    backend: FakeBackend,
) -> tuple[UpdateController, ApplicationStatus, list[str]]:
    status = ApplicationStatus()
    calls: list[str] = []

    def prepare() -> str:
        calls.append("prepare")
        return ""

    updater = UpdateController(
        status,
        lambda: UpdateProvider(InstallChannel.MICROSOFT_STORE, backend),
        prepare,
        lambda: calls.append("finish"),
    )
    return updater, status, calls


def test_startup_check_is_nonblocking_and_status_action_rechecks_before_install() -> (
    None
):
    backend = FakeBackend()
    updater, status, calls = controller(backend)
    try:
        updater.start()
        updater.start()
        assert backend.checks == 1
        assert status.current_status is not None
        assert status.current_status.progress is not None
        assert status.current_status.action is None
        backend.event = UpdateResult(UpdateOutcome.AVAILABLE)
        QTest.qWait(150)  # Exercise actual Qt timer dispatch.
        status.request_action(UPDATE_STATUS_SOURCE, "install")
        status.request_action(UPDATE_STATUS_SOURCE, "install")
        assert backend.checks == 2
        assert backend.installs == 0
        assert calls == []
        backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
        assert backend.installs == 1
        assert updater.installing
        assert calls == ["prepare"]
        backend.deliver(UpdateProgress("optional-package", 0.8, False))
        progress = status.current_status.progress
        assert progress.current == 80
        assert progress.detail == "Package: optional-package"
        backend.deliver(UpdateResult(UpdateOutcome.CANCELED))
        assert calls == ["prepare", "finish"]
        assert not updater.installing
        assert "canceled" in status.current_message
        assert backend.installs == 1
    finally:
        updater.close()


@pytest.mark.parametrize(
    "outcome", [UpdateOutcome.COMPLETED, UpdateOutcome.FAILED, UpdateOutcome.CANCELED]
)
def test_terminal_install_results_release_guard(outcome: UpdateOutcome) -> None:
    backend = FakeBackend()
    updater, status, calls = controller(backend)
    updater.start()
    backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
    status.request_action(UPDATE_STATUS_SOURCE, "install")
    backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
    backend.deliver(UpdateResult(outcome, "Network error"))
    assert not updater.installing
    assert calls == ["prepare", "finish"]
    assert status.current_status is not None
    assert status.current_status.progress is None
    assert (
        status.current_status.action is None
        if outcome is UpdateOutcome.COMPLETED
        else status.current_status.action is not None
    )
    updater.close()


def test_recheck_can_report_no_updates_and_does_not_prepare_or_install() -> None:
    backend = FakeBackend()
    updater, status, calls = controller(backend)
    updater.start()
    backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
    status.request_action(UPDATE_STATUS_SOURCE, "install")
    backend.deliver(UpdateResult(UpdateOutcome.CURRENT))
    assert calls == [] and backend.installs == 0
    assert "reports no updates" in status.current_message
    updater.close()


def test_unsafe_work_is_checked_after_recheck_and_leaves_update_action() -> None:
    backend = FakeBackend()
    status = ApplicationStatus()
    updater = UpdateController(
        status,
        lambda: UpdateProvider(InstallChannel.MICROSOFT_STORE, backend),
        lambda: "Save the Library Draft first",
        lambda: None,
    )
    updater.start()
    backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
    status.request_action(UPDATE_STATUS_SOURCE, "install")
    backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
    assert not updater.installing and backend.installs == 0
    assert status.current_message == "Save the Library Draft first"
    assert (
        status.current_status is not None and status.current_status.action is not None
    )
    updater.close()


def test_failed_check_is_not_current_and_retry_has_backoff() -> None:
    backend = FakeBackend()
    backend.error = OSError("offline")
    updater, status, _calls = controller(backend)
    updater.start()
    assert "offline" in status.current_message
    assert "no updates" not in status.current_message
    status.request_action(UPDATE_STATUS_SOURCE, "retry")
    updater.check_now()
    assert backend.checks == 1
    updater.close()


def test_manual_check_before_startup_does_not_duplicate_or_install() -> None:
    backend = FakeBackend()
    updater, _status, calls = controller(backend)
    try:
        updater.check_now()
        updater.start()
        updater.check_now()
        assert backend.checks == 1
        backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
        updater.check_now()
        backend.deliver(UpdateResult(UpdateOutcome.CURRENT))
        assert backend.checks == 2 and backend.installs == 0
        assert calls == []
        updater.close()
        updater.check_now()
        assert backend.checks == 2
    finally:
        updater.close()


def test_unsupported_install_does_not_claim_current_or_contact_store() -> None:
    status = ApplicationStatus()
    status.show("other-work", "Saving…")
    updater = UpdateController(
        status,
        lambda: UpdateProvider(InstallChannel.UNPACKAGED),
        lambda: "",
        lambda: None,
    )
    updater.start()
    assert status.current_message == "Saving…"
    updater.close()


def test_close_discards_late_results_and_releases_guard_once() -> None:
    backend = FakeBackend()
    updater, status, calls = controller(backend)
    updater.start()
    backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
    status.request_action(UPDATE_STATUS_SOURCE, "install")
    backend.deliver(UpdateResult(UpdateOutcome.AVAILABLE))
    updater.close()
    updater.close()
    backend.event = UpdateResult(UpdateOutcome.COMPLETED)
    QTest.qWait(150)
    assert backend.event == UpdateResult(UpdateOutcome.COMPLETED)
    assert calls == ["prepare", "finish"]
    assert status.current_status is None
    assert backend.closed


@dataclass
class PackageProgress:
    package_family_name: str = "optional"
    package_download_progress: float = 0.8
    package_update_state: int = 1


@dataclass
class PackageResult:
    overall_state: int
    store_package_update_statuses: Iterable[NativeProgress]


@pytest.mark.parametrize(
    ("overall", "package", "expected"),
    [
        (3, 3, UpdateOutcome.COMPLETED),
        (3, 5, UpdateOutcome.FAILED),
        (4, 4, UpdateOutcome.CANCELED),
        (6, 6, UpdateOutcome.FAILED),
        (8, 8, UpdateOutcome.FAILED),
        (999, 3, UpdateOutcome.FAILED),
    ],
)
def test_native_result_checks_overall_and_per_package(
    overall: int, package: int, expected: UpdateOutcome
) -> None:
    assert (
        install_result(
            PackageResult(overall, [PackageProgress(package_update_state=package)])
        ).outcome
        is expected
    )


class Operation:
    def __init__(self, result: object) -> None:
        self.status = 0
        self.result = result
        self.closed = False
        self.cancelled = False
        self.progress: Callable[[object, NativeProgress], None] = (
            lambda _sender, _value: None
        )

    def get_results(self) -> object:
        assert self.status != 0, "Never wait for a native operation on the GUI thread"
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def cancel(self) -> None:
        self.cancelled = True
        self.status = 2

    def close(self) -> None:
        self.closed = True


class Context:
    def __init__(self) -> None:
        self.updates = (object(), object())
        self.check_operation = Operation(self.updates)
        self.install_operation = Operation(
            PackageResult(3, [PackageProgress(package_update_state=3)])
        )

    def get_app_and_optional_store_package_updates_async(self) -> Operation:
        return self.check_operation

    def request_download_and_install_store_package_updates_async(
        self, updates: Iterable[object]
    ) -> Operation:
        assert tuple(updates) == self.updates  # Includes optional packages.
        return self.install_operation


def test_native_operation_polling_progress_and_lifetime() -> None:
    native = Context()
    backend = StoreBackend(native)
    backend.check()
    assert backend.poll() is None
    with pytest.raises(RuntimeError, match="busy"):
        backend.check()
    native.check_operation.status = 1
    assert backend.poll() == UpdateResult(UpdateOutcome.AVAILABLE)
    assert native.check_operation.closed
    backend.install()
    thread = Thread(
        target=lambda: native.install_operation.progress(None, PackageProgress())
    )
    thread.start()
    thread.join()
    assert backend.poll() == UpdateProgress("optional", 0.8, False)
    native.install_operation.status = 1
    assert backend.poll() == UpdateResult(UpdateOutcome.COMPLETED)
    assert native.install_operation.closed
    backend.close()


def test_native_error_closes_operation_without_claiming_no_updates() -> None:
    native = Context()
    native.check_operation.result = OSError("Store unavailable")
    native.check_operation.status = 3
    backend = StoreBackend(native)
    backend.check()
    with pytest.raises(OSError, match="Store unavailable"):
        backend.poll()
    assert native.check_operation.closed
    backend.close()


def test_native_close_cancels_and_releases_owner_once() -> None:
    native = Context()
    released: list[bool] = []
    backend = StoreBackend(native, lambda: released.append(True))
    backend.check()
    backend.close()
    backend.close()
    assert native.check_operation.cancelled
    assert released == [True]
    assert backend.poll() is None


def mock_package_identity(monkeypatch: pytest.MonkeyPatch, result: int) -> None:
    def package_name(_size: object, _name: object) -> int:
        return result

    kernel = SimpleNamespace(GetCurrentPackageFullName=package_name)

    def load_kernel(_name: str, *, use_last_error: bool) -> SimpleNamespace:
        assert use_last_error
        return kernel

    monkeypatch.setattr(ctypes, "WinDLL", load_kernel, raising=False)


@pytest.mark.parametrize(
    ("identity_result", "signature", "expected"),
    [
        (15700, 0, InstallChannel.UNPACKAGED),
        (122, 3, InstallChannel.MICROSOFT_STORE),
        (122, 1, InstallChannel.WINDOWS_PACKAGE),
    ],
)
def test_channel_detection_requires_store_signature(
    monkeypatch: pytest.MonkeyPatch,
    identity_result: int,
    signature: int,
    expected: InstallChannel,
) -> None:
    mock_package_identity(monkeypatch, identity_result)
    model = SimpleNamespace(
        Package=SimpleNamespace(current=SimpleNamespace(signature_kind=signature)),
        PackageSignatureKind=SimpleNamespace(STORE=3),
    )
    imports: list[str] = []

    def load(name: str) -> SimpleNamespace:
        imports.append(name)
        return model

    monkeypatch.setattr(windows, "import_module", load)
    assert windows.detect_channel() is expected
    if expected is InstallChannel.UNPACKAGED:
        assert not imports


def test_identity_failure_is_not_treated_as_an_unpacked_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_package_identity(monkeypatch, 5)
    with pytest.raises(OSError, match="identity"):
        windows.detect_channel()


def test_sideloaded_package_never_initializes_store_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        windows, "detect_channel", lambda: InstallChannel.WINDOWS_PACKAGE
    )

    def forbidden(_name: str) -> None:
        pytest.fail("A non-Store package must not contact Microsoft Store")

    monkeypatch.setattr(windows, "import_module", forbidden)
    assert windows.create_store_provider(123).backend is None


def test_check_timeout_closes_backend_and_offers_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeBackend()
    updater, status, _calls = controller(backend)
    now = 100.0
    monkeypatch.setattr("iOpenPod.app.updates.controller.monotonic", lambda: now)
    updater.start()
    now += 61
    wait_until(lambda: backend.closed)
    assert backend.closed
    assert "timed out" in status.current_message
    updater.close()
