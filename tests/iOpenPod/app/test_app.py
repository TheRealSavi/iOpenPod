"""Tests for the Qt application bootstrap."""

import signal

import pytest
from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication

from iOpenPod.app.app import (
    _install_interrupt_handler,  # pyright: ignore[reportPrivateUsage]
)


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


def test_sigint_requests_qt_application_quit(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = _application()
    quit_requests: list[None] = []
    monkeypatch.setattr(application, "quit", lambda: quit_requests.append(None))
    previous_handler = signal.getsignal(signal.SIGINT)

    restore = _install_interrupt_handler(application)
    try:
        with caplog.at_level("INFO"):
            QTimer.singleShot(0, lambda: signal.raise_signal(signal.SIGINT))
            QTimer.singleShot(50, QCoreApplication.quit)
            application.exec()
    finally:
        restore()

    assert quit_requests == [None]
    assert "Interrupt received" in caplog.text
    assert signal.getsignal(signal.SIGINT) is previous_handler
