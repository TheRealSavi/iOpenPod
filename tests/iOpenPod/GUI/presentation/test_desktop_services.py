"""Native desktop helpers use Host libraries and retain startup diagnostics."""

import json
import os
import shlex
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from iOpenPod.GUI.presentation import desktop_services
from storage import host_tools


@pytest.mark.skipif(os.name == "nt", reason="Native Linux helper uses a POSIX launcher")
def test_frozen_desktop_launch_restores_host_environment_and_appends_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    marker = tmp_path / "inherited.json"
    log = tmp_path / "iopenpod.log"
    log.write_text("existing application log\n", encoding="utf-8")
    script = tmp_path / "helper.py"
    script.write_text(
        "import json, os, pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text(json.dumps(dict(environment=dict(os.environ), arguments=sys.argv[1:])))\n"
        "print('desktop helper failed after launch', file=sys.stderr, flush=True)\n"
        "sys.exit(3)\n",
        encoding="utf-8",
    )
    launcher = tmp_path / "xdg-open"
    launcher.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    frozen = SimpleNamespace(platform="linux", frozen=True, _MEIPASS=str(bundle))
    monkeypatch.setattr(desktop_services, "sys", frozen)
    monkeypatch.setattr(host_tools, "sys", frozen)

    def find_executable(_name: str) -> str:
        return str(launcher)

    monkeypatch.setattr(desktop_services, "find_host_executable", find_executable)
    monkeypatch.setattr(desktop_services, "active_log_path", lambda: log)
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.delenv("SNAP", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", str(bundle))
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/host/library")
    monkeypatch.setenv("QT_PLUGIN_PATH", str(bundle / "plugins"))
    monkeypatch.setenv(
        "QML2_IMPORT_PATH", str(bundle / "qml") + os.pathsep + "/host/qml"
    )
    parent = dict(os.environ)

    url = QUrl.fromLocalFile(str(tmp_path / "log files é #"))
    assert desktop_services.open_desktop_url(url)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if marker.exists() and "desktop helper failed" in log.read_text(
            encoding="utf-8"
        ):
            break
        time.sleep(0.01)
    observed = json.loads(marker.read_text(encoding="utf-8"))
    inherited = observed["environment"]
    assert observed["arguments"] == [
        url.toString(QUrl.ComponentFormattingOption.FullyEncoded)
    ]
    assert inherited["LD_LIBRARY_PATH"] == "/host/library"
    assert "QT_PLUGIN_PATH" not in inherited
    assert inherited["QML2_IMPORT_PATH"] == "/host/qml"
    assert inherited["PATH"] == parent["PATH"]
    assert log.read_text(encoding="utf-8") == (
        "existing application log\ndesktop helper failed after launch\n"
    )
    assert dict(os.environ) == parent


@pytest.mark.parametrize("available", [False, True])
def test_desktop_helper_failure_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    available: bool,
) -> None:
    monkeypatch.setattr(
        desktop_services, "sys", SimpleNamespace(platform="linux", frozen=True)
    )
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.delenv("SNAP", raising=False)
    monkeypatch.setattr(desktop_services, "active_log_path", lambda: None)

    def find_executable(_name: str) -> str | None:
        return str(tmp_path / "missing-executable") if available else None

    monkeypatch.setattr(desktop_services, "find_host_executable", find_executable)
    assert not desktop_services.open_desktop_url(QUrl("https://example.org"))
    assert "desktop" in caplog.text


@pytest.mark.parametrize("channel", ["source", "macos", "flatpak", "snap"])
def test_non_native_channels_keep_qt_desktop_integration(
    monkeypatch: pytest.MonkeyPatch, channel: str
) -> None:
    monkeypatch.setattr(
        desktop_services,
        "sys",
        SimpleNamespace(
            platform="darwin" if channel == "macos" else "linux",
            frozen=channel != "source",
        ),
    )
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.delenv("SNAP", raising=False)
    if channel in {"flatpak", "snap"}:
        monkeypatch.setenv(
            "FLATPAK_ID" if channel == "flatpak" else "SNAP", "test-package"
        )
    opened: list[QUrl] = []

    def open_url(url: QUrl) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    url = QUrl("https://example.org")
    assert desktop_services.open_desktop_url(url)
    assert opened == [url]
