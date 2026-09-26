"""The recovery escape path is reachable and requires the user's explicit choice."""

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QMessageBox, QPushButton
from tests.iOpenPod.app.test_library_write_controller import wait_for
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinator,
    SyncRecoveryDeclinedError,
)
from iOpenPod.app.sync_controller import SyncController
from iOpenPod.GUI.main_window import MainWindow


@pytest.mark.parametrize("accept", [False, True])
def test_keep_contents_confirmation_controls_the_actual_worker(
    monkeypatch: pytest.MonkeyPatch,
    accept: bool,
) -> None:
    calls: list[str] = []
    prompts: list[str] = []
    path = ".iopenpod-recovery/" + "a" * 32 + "/transaction.json"

    def keep(_coordinator: DeviceCoordinator, journal: str) -> None:
        calls.append(journal)
        raise SyncRecoveryDeclinedError("Current contents kept. Reload the Library.")

    def question(
        _parent: object, _title: str, text: str, _buttons: object, default: object
    ) -> QMessageBox.StandardButton:
        prompts.append(text)
        assert default == QMessageBox.StandardButton.Cancel
        return (
            QMessageBox.StandardButton.Yes
            if accept
            else QMessageBox.StandardButton.Cancel
        )

    monkeypatch.setattr(DeviceCoordinator, "keep_sync_contents", keep)
    monkeypatch.setattr(QMessageBox, "question", question)
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    try:
        context.device_controller.recoveryRequired.emit(path)
        button = window.findChild(QPushButton, "keepSyncContents")
        controller = window.findChild(SyncController)
        assert button is not None and controller is not None
        assert not button.isHidden()
        button.click()
        wait_for(lambda: not controller.busy)
        assert len(prompts) == 1 and "incomplete" in prompts[0]
        assert calls == ([path] if accept else [])
        assert controller.needs_recovery is not accept
        assert context.library_workspace.locked is not accept
    finally:
        window.close()
        context.shutdown()
        window.deleteLater()
        APPLICATION.sendPostedEvents(window, QEvent.Type.DeferredDelete)
