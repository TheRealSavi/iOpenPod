"""User-facing safe-eject status and outcome messages."""

import pytest
from PySide6.QtWidgets import QMessageBox
from tests.iOpenPod.GUI.application_shell_test_support import build_context

from iOpenPod.app.device_controller import (
    DeviceEjectCompletion,
    DeviceOperation,
    DeviceOperationFailure,
)
from iOpenPod.GUI.main_window import MainWindow


def test_eject_failure_dialog_preserves_actionable_native_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    dialogs: list[tuple[str, str]] = []

    def warning(_parent: object, title: str, message: str) -> None:
        dialogs.append((title, message))

    monkeypatch.setattr(QMessageBox, "warning", warning)
    try:
        window._device_operation_failed(  # pyright: ignore[reportPrivateUsage]
            DeviceOperationFailure(
                DeviceOperation.EJECT,
                "MusicApp.exe is using the iPod. Close it and try again.",
                "DeviceEjectError",
            )
        )

        assert dialogs == [
            (
                "Could Not Safely Eject iPod",
                "MusicApp.exe is using the iPod. Close it and try again.",
            )
        ]
    finally:
        window.close()
        context.shutdown()


def test_eject_success_is_the_only_safe_to_disconnect_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = build_context()
    window = MainWindow(context, auto_discover=False)
    dialogs: list[tuple[str, str]] = []

    def information(_parent: object, title: str, message: str) -> None:
        dialogs.append((title, message))

    monkeypatch.setattr(QMessageBox, "information", information)
    try:
        window._eject_started()  # pyright: ignore[reportPrivateUsage]
        assert window.statusBar().currentMessage() == (
            "Safely ejecting the Active iPod…"
        )

        window._eject_completed(  # pyright: ignore[reportPrivateUsage]
            DeviceEjectCompletion(
                "Test iPod",
                "The operating system confirmed safe removal.",
            )
        )

        assert dialogs == [
            (
                "iPod Ejected",
                "Test iPod is safe to disconnect.\n\n"
                "The operating system confirmed safe removal.",
            )
        ]
    finally:
        window.close()
        context.shutdown()
