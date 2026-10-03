"""Startup diagnostics retain the running version and evidenced source label."""

import logging
from pathlib import Path

import pytest

import iopenpod_launcher
from iOpenPod.app.core import certifi_ssl, version
from iOpenPod.app.core import logging as application_logging
from iOpenPod.app.core.settings import stores
from iOpenPod.app.updates import platform, windows
from iOpenPod.app.updates.backend import InstallChannel
from storage import Storage


@pytest.fixture
def startup_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise startup without reading user settings or changing logging/SSL setup."""

    def create_settings(_storage: Storage) -> stores.GlobalSettingsStore:
        return stores.GlobalSettingsStore()

    def setup_logger(_path: str | Path) -> logging.Logger:
        return logging.getLogger()

    monkeypatch.setattr(stores, "create_global_settings_store", create_settings)
    monkeypatch.setattr(application_logging, "setup_logger", setup_logger)
    monkeypatch.setattr(certifi_ssl, "install_certifi_ssl", lambda: None)


@pytest.mark.parametrize("channel", list(InstallChannel))
@pytest.mark.usefixtures("startup_environment")
def test_startup_version_includes_shared_source_label(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    channel: InstallChannel,
) -> None:
    monkeypatch.setattr(version, "get_version", lambda: "2.3.4")
    monkeypatch.setattr(platform, "detect_install_channel", lambda: channel)
    with caplog.at_level(logging.INFO, logger="iopenpod_launcher"):
        iopenpod_launcher.initialize_application()
    version_messages = [
        message for message in caplog.messages if message.startswith("Version:")
    ]
    assert version_messages == [f"Version: 2.3.4 · {channel.display_name}"]


@pytest.mark.usefixtures("startup_environment")
def test_source_detection_failure_does_not_interrupt_startup_logging(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail_detection() -> InstallChannel:
        raise OSError("package identity unavailable")

    monkeypatch.setattr(version, "get_version", lambda: "2.3.4")
    monkeypatch.setattr(platform, "detect_install_channel", fail_detection)
    with caplog.at_level(logging.INFO, logger="iopenpod_launcher"):
        iopenpod_launcher.initialize_application()
    assert "Version: 2.3.4 · Unknown source" in caplog.messages
    assert caplog.messages[-1].startswith("Log Path:")
    assert "package identity unavailable" in caplog.text


def test_windows_source_detection_needs_no_update_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    calls: list[str] = []

    def initialize_runtime() -> None:
        calls.append("runtime")

    def detect_channel() -> InstallChannel:
        calls.append("identity")
        return InstallChannel.MICROSOFT_STORE

    def unexpected_provider(_window: int) -> None:
        pytest.fail("Reading a source label must not create a Store updater")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(platform, "_runtime_error", "")
    monkeypatch.setattr(platform, "initialize_update_runtime", initialize_runtime)
    monkeypatch.setattr(windows, "detect_channel", detect_channel)
    monkeypatch.setattr(windows, "create_store_provider", unexpected_provider)
    assert platform.detect_install_channel() is InstallChannel.MICROSOFT_STORE
    assert calls == ["runtime", "identity"]
