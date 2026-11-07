"""Open Host desktop applications without exposing frozen runtime libraries."""

import logging
import os
import sys
from pathlib import Path
from typing import cast

from PySide6.QtCore import QIODevice, QProcess, QProcessEnvironment, QUrl
from PySide6.QtGui import QDesktopServices

from iOpenPod.app.core.logging import active_log_path
from storage.host_tools import find_host_executable, host_tool_environment

logger = logging.getLogger(__name__)


def open_desktop_url(url: QUrl) -> bool:
    """Request opening without changing the environment of concurrent app work.

    A successful detached launch cannot guarantee a visible window. Retain the
    helper's stderr in the active log so subsequent launch failures are diagnosable.
    """
    if (
        sys.platform != "linux"
        or not getattr(sys, "frozen", False)
        or os.environ.get("FLATPAK_ID")
        or os.environ.get("SNAP")
        or Path("/.flatpak-info").exists()
    ):
        # Confined packages retain Qt's permission-aware portal integration.
        return QDesktopServices.openUrl(url)
    executable = find_host_executable("xdg-open")
    if executable is None:
        logger.warning("Could not open a desktop application: xdg-open is unavailable")
        return False
    environment = QProcessEnvironment()
    for key, value in host_tool_environment().items():
        environment.insert(key, value)
    process = QProcess()
    process.setProgram(executable)
    process.setArguments([url.toString(QUrl.ComponentFormattingOption.FullyEncoded)])
    process.setProcessEnvironment(environment)
    process.setStandardOutputFile(QProcess.nullDevice())
    log_path = active_log_path()
    if log_path is not None:
        process.setStandardErrorFile(str(log_path), QIODevice.OpenModeFlag.Append)
    # PySide's instance overload returns bool in 6.9.3 despite its tuple stub;
    # also accept versions exposing the PID alongside the launch result.
    result = cast("bool | tuple[bool, int]", process.startDetached())
    started = result if isinstance(result, bool) else result[0]
    if not started:
        logger.warning(
            "Could not start the Host desktop helper: %s", process.errorString()
        )
    return started
