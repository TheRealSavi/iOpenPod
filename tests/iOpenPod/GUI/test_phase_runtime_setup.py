"""Optional setup is explicit, asynchronous, cancellable, and reachable in Settings."""

import time
from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app import phase_runtime_controller
from iOpenPod.app.phase_runtime import ManagedPhaseSources
from iOpenPod.app.phase_runtime_controller import PhaseRuntimeController
from iOpenPod.app.phase_runtime_install import runtime_target
from iOpenPod.GUI.dialogs.phase_runtime_setup import PhaseRuntimeSetupDialog
from iOpenPod.GUI.main_window import MainWindow
from storage import StorageOperationError


@pytest.fixture(autouse=True)
def isolate_runtime_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ManagedPhaseSources, "installed", lambda: None)
    monkeypatch.setattr(
        phase_runtime_controller,
        "host_runtime_target",
        lambda: runtime_target("win32", "AMD64"),
    )


def wait_until(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


def test_opening_setup_does_not_download_and_install_runs_off_gui_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = Event()
    release = Event()

    def install(
        *, checkpoint: Callable[[], None], progress: Callable[[str], None]
    ) -> None:
        entered.set()
        progress("Testing optional runtime")
        while not release.wait(0.01):
            checkpoint()

    monkeypatch.setattr(phase_runtime_controller, "install_phase_runtime", install)
    controller = PhaseRuntimeController()
    dialog = PhaseRuntimeSetupDialog(controller)
    dialog.open()
    APPLICATION.processEvents()
    assert not entered.is_set()
    button = dialog.findChild(QPushButton, "installPhaseRuntime")
    assert button is not None
    button.click()
    wait_until(entered.is_set)
    assert controller.busy
    assert not button.isEnabled()
    # Escape/Close requests cancellation; it cannot destroy a live installer.
    dialog.reject()
    assert controller.cancelling
    cancel = dialog.findChild(QPushButton, "cancelPhaseRuntime")
    assert cancel is not None and not cancel.isEnabled()
    wait_until(lambda: not controller.busy)
    assert "cancelled" in controller.message
    release.set()
    dialog.reject()
    controller.shutdown()


def test_queued_progress_cannot_replace_the_cancellation_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = Event()
    cancelled = Event()
    release = Event()

    def install(
        *, checkpoint: Callable[[], None], progress: Callable[[str], None]
    ) -> None:
        entered.set()
        try:
            while not release.wait(0.01):
                checkpoint()
        except Exception:
            progress("Late installation progress")
            cancelled.set()
            release.wait(5)
            raise

    monkeypatch.setattr(phase_runtime_controller, "install_phase_runtime", install)
    controller = PhaseRuntimeController()
    try:
        controller.install()
        wait_until(entered.is_set)
        controller.cancel()
        wait_until(cancelled.is_set)
        APPLICATION.processEvents()
        assert controller.busy and controller.cancelling
        assert controller.message == "Cancelling setup…"
    finally:
        release.set()
        wait_until(lambda: not controller.busy)
        controller.shutdown()


def test_settings_button_opens_setup_without_starting_installation() -> None:
    context = build_context()
    window = MainWindow(context)
    try:
        button = window.findChild(QPushButton, "setupPhaseAnalysis")
        assert button is not None
        button.click()
        APPLICATION.processEvents()
        dialog = window.findChild(PhaseRuntimeSetupDialog, "phaseRuntimeSetup")
        assert dialog is not None and dialog.isVisible()
        install = dialog.findChild(QPushButton, "installPhaseRuntime")
        assert install is not None and install.isEnabled()
        dialog.reject()
    finally:
        window.close()
        context.shutdown()


def test_setup_recognizes_an_existing_install_without_loading_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = ManagedPhaseSources(tmp_path, "tested-cpu")
    monkeypatch.setattr(ManagedPhaseSources, "installed", lambda: installed)
    controller = PhaseRuntimeController()
    dialog = PhaseRuntimeSetupDialog(controller)
    dialog.open()
    try:
        assert controller.installed
        button = dialog.findChild(QPushButton, "installPhaseRuntime")
        assert button is not None and button.text() == "Download and Reinstall"
        assert button.isEnabled()
        availability = dialog.findChild(QLabel, "phaseRuntimeAvailability")
        assert availability is not None and "is installed" in availability.text()
    finally:
        dialog.reject()
        controller.shutdown()


def test_unsupported_host_disables_download_before_starting_a_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> None:
        raise ValueError("Unsupported platform")

    def unexpected_install(**_kwargs: object) -> None:
        pytest.fail("Unsupported host started setup")

    monkeypatch.setattr(phase_runtime_controller, "host_runtime_target", unavailable)
    monkeypatch.setattr(
        phase_runtime_controller, "install_phase_runtime", unexpected_install
    )
    controller = PhaseRuntimeController()
    dialog = PhaseRuntimeSetupDialog(controller)
    dialog.open()
    try:
        button = dialog.findChild(QPushButton, "installPhaseRuntime")
        assert button is not None and not button.isEnabled()
        controller.install()
        assert not controller.busy
        assert "unavailable" in controller.availability
    finally:
        dialog.reject()
        controller.shutdown()


@pytest.mark.parametrize(
    "error", [ValueError("Invalid receipt"), StorageOperationError("Too large")]
)
def test_invalid_receipt_can_be_repaired_without_blocking_setup(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def invalid_receipt() -> None:
        raise error

    monkeypatch.setattr(ManagedPhaseSources, "installed", invalid_receipt)
    controller = PhaseRuntimeController()
    controller.refresh()
    assert controller.can_install and not controller.installed
    assert "needs attention" in controller.availability
    controller.shutdown()


def test_setup_failure_has_readable_status_and_scrollable_diagnostics(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    detail = "Download unavailable\n" * 200

    def fail(**_kwargs: object) -> None:
        raise RuntimeError(detail)

    monkeypatch.setattr(phase_runtime_controller, "install_phase_runtime", fail)
    controller = PhaseRuntimeController()
    dialog = PhaseRuntimeSetupDialog(controller)
    dialog.open()
    dialog.resize(440, 330)
    try:
        controller.install()
        wait_until(lambda: not controller.busy)
        assert controller.can_install
        assert (
            controller.message
            == "Setup could not finish. Acoustic analysis remains available."
        )
        details = dialog.findChild(QPlainTextEdit, "phaseRuntimeDetails")
        assert details is not None and details.isVisible() and details.isReadOnly()
        assert "Download unavailable" in details.toPlainText()
        assert details.blockCount() <= 100
        for label in dialog.findChildren(QLabel):
            if label.isVisible() and label.wordWrap():
                assert label.height() >= label.heightForWidth(label.width())
        assert "Optional Phase analysis setup failed" in caplog.text
    finally:
        dialog.reject()
        controller.shutdown()
