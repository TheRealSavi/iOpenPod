import os
import sys
from pathlib import Path


def default_log_path() -> Path:
    """Determines a sensible default log path for Mac/Win/Linux"""

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "iOpenPod" / "iopenpod.log"

    if sys.platform == "win32":
        base = Path(
            os.environ.get(
                "LOCALAPPDATA",
                Path.home() / "AppData" / "Local",
            )
        )
        return base / "iOpenPod" / "Logs" / "iopenpod.log"

    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return base / "iOpenPod" / "iopenpod.log"


def default_backup_path() -> Path:
    """Return the default Backup Archive v4 parent directory."""

    if sys.platform == "win32":
        fallback = Path.home() / "AppData" / "Local"
        configured = os.environ.get("LOCALAPPDATA")
        candidate = Path(configured) if configured else fallback
        base = candidate if candidate.is_absolute() else fallback
        return base / "iOpenPod" / "Backups"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "iOpenPod" / "Backups"
    data_home = os.environ.get("XDG_DATA_HOME")
    base = (
        Path(data_home)
        if data_home and Path(data_home).is_absolute()
        else Path.home() / ".local" / "share"
    )
    return base / "iopenpod" / "backups"
