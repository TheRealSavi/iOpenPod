"""Drive media-tool dialogs with harmless asynchronous stand-in processes."""

import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app import media_tools_controller
from iOpenPod.app.media_tools_controller import MediaToolsController
from iOpenPod.app.services.media_tools import (
    TOOL_NAMES,
    InstallCommand,
    MediaToolInstallPlan,
    MediaToolSetup,
    MediaToolStatus,
)
from iOpenPod.GUI.dialogs.media_tools_setup import MediaToolsSetupDialog
from iOpenPod.GUI.main_window import MainWindow


def _setup(*commands: InstallCommand, ready: bool = False) -> MediaToolSetup:
    return MediaToolSetup(
        tuple(
            MediaToolStatus(name, f"C:/{name}" if ready else "") for name in TOOL_NAMES
        ),
        MediaToolInstallPlan("Test channel", "Test packages", commands),
    )


def _wait(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 8
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


def _command(label: str, code: str) -> InstallCommand:
    return InstallCommand(label, sys.executable, ("-c", code))


def _mock_inspection(monkeypatch: pytest.MonkeyPatch, setup: MediaToolSetup) -> None:
    def inspect(*, checkpoint: Callable[[], None]) -> MediaToolSetup:
        return setup

    monkeypatch.setattr(media_tools_controller, "inspect_media_tools", inspect)


def test_check_and_skip_do_not_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = tmp_path / "never-installed"
    setup = _setup(_command("test", f"open({str(marker)!r}, 'w').close()"))
    _mock_inspection(monkeypatch, setup)
    controller = MediaToolsController()
    dialog = MediaToolsSetupDialog(controller)
    dialog.open()
    controller.check()
    _wait(lambda: not controller.busy)
    try:
        button = dialog.findChild(QPushButton, "installMediaTools")
        assert button is not None and button.isEnabled()
        status = dialog.findChild(QLabel, "mediaToolStatus")
        assert status is not None and status.text().count("Missing") == 3
        dialog.reject()
        assert not dialog.isVisible()
        assert not marker.exists()
    finally:
        controller.shutdown()


def test_install_is_sequential_nonblocking_and_verified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = tmp_path / "installed"
    first = _command(
        "first",
        f"import time; time.sleep(0.1); open({str(marker)!r}, 'w').write('1'); print('first done')",
    )
    second = _command(
        "second",
        f"from pathlib import Path; p = Path({str(marker)!r}); assert p.read_text() == '1'; p.write_text('12')",
    )
    _mock_inspection(monkeypatch, _setup(ready=True))
    controller = MediaToolsController()
    controller.setup = _setup(first, second)
    messages: list[str] = []
    controller.output.connect(messages.append)
    try:
        controller.install()
        assert controller.installing
        controller.install()  # Repeated clicks cannot launch concurrent installers.
        APPLICATION.processEvents()
        _wait(lambda: not controller.busy)
        assert marker.read_text() == "12"
        assert controller.setup.ready
        assert "first done" in "".join(messages)
        assert "ready to use" in controller.message
    finally:
        controller.shutdown()


def test_failure_stops_remaining_packages_and_rechecks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = tmp_path / "not-run"
    _mock_inspection(monkeypatch, _setup())
    controller = MediaToolsController()
    controller.setup = _setup(
        _command("failure", "import sys; print('Network unavailable'); sys.exit(7)"),
        _command("next", f"open({str(marker)!r}, 'w').close()"),
    )
    messages: list[str] = []
    controller.output.connect(messages.append)
    try:
        controller.install()
        _wait(lambda: not controller.busy)
        assert "exit 7" in controller.message
        assert "Network unavailable" in "".join(messages)
        assert not marker.exists()
        assert not controller.setup.ready
    finally:
        controller.shutdown()


def test_failed_launch_recovers_without_waiting_for_finished(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_inspection(monkeypatch, _setup())
    controller = MediaToolsController()
    controller.setup = _setup(
        InstallCommand("missing manager", str(tmp_path / "absent-program"), ())
    )
    try:
        controller.install()
        _wait(lambda: not controller.busy)
        assert "Could not start" in controller.message
    finally:
        controller.shutdown()


def test_installer_output_is_bounded_even_without_newlines() -> None:
    controller = MediaToolsController()
    dialog = MediaToolsSetupDialog(controller)
    try:
        log = dialog.findChild(QPlainTextEdit, "mediaToolInstallLog")
        assert log is not None
        for _ in range(30):
            controller.output.emit("x" * 8192)
        assert len(log.toPlainText()) < 65536
    finally:
        controller.shutdown()


def test_application_close_does_not_kill_package_install(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mock_inspection(monkeypatch, _setup())
    marker = tmp_path / "package-finished"
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    window.show()
    controller = window.findChild(MediaToolsController)
    assert controller is not None
    controller.setup = _setup(
        _command(
            "test package",
            f"import time; time.sleep(0.2); open({str(marker)!r}, 'w').close()",
        )
    )
    try:
        controller.install()
        assert not window.close()
        assert window.isVisible() and controller.stopping
        _wait(lambda: not controller.busy)
        assert marker.exists()
    finally:
        window.close()
        context.shutdown()


def test_closing_during_install_waits_for_current_package(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _mock_inspection(monkeypatch, _setup())
    controller = MediaToolsController()
    controller.setup = _setup(
        _command(
            "first", f"import time; time.sleep(0.2); open({str(first)!r}, 'w').close()"
        ),
        _command("second", f"open({str(second)!r}, 'w').close()"),
    )
    dialog = MediaToolsSetupDialog(controller)
    dialog.open()
    try:
        controller.install()
        dialog.reject()
        assert dialog.isVisible() and controller.stopping
        _wait(lambda: not controller.busy)
        assert first.exists() and not second.exists()
        dialog.reject()
        assert not dialog.isVisible()
    finally:
        controller.shutdown()


@pytest.mark.parametrize("ready", [True, False])
def test_startup_prompts_only_for_unavailable_tools_and_settings_reopens(
    monkeypatch: pytest.MonkeyPatch, ready: bool
) -> None:
    _mock_inspection(monkeypatch, _setup(ready=ready))
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    window.show()
    try:
        window.check_media_tools()
        dialog = window.findChild(MediaToolsSetupDialog)
        controller = window.findChild(MediaToolsController)
        assert dialog is not None and controller is not None
        _wait(lambda: not controller.busy)
        assert dialog.isVisible() is (not ready)
        dialog.reject()
        button = window.findChild(QPushButton, "setupMediaTools")
        assert button is not None
        assert button.isHidden() is ready
        if not ready:
            button.click()
            assert dialog.isVisible()
            _wait(lambda: not controller.busy)
    finally:
        window.close()
        context.shutdown()
