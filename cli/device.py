"""Device detection helpers for the CLI."""

from __future__ import annotations

import logging
from pathlib import Path

from ipod_device.scanner import scan_for_ipods
from ipod_device.info import DeviceInfo

logger = logging.getLogger(__name__)


def find_ipod(mount_hint: str | None = None) -> tuple[DeviceInfo, str] | None:
    """Return (DeviceInfo, itunesdb_path) for the first found iPod.

    If *mount_hint* is given, only that mount path is considered.
    Returns None when no iPod is found.
    """
    if mount_hint:
        # Synthesise a minimal scan from the user-supplied path
        db_path = _itunesdb_path(mount_hint)
        if not Path(db_path).exists():
            logger.error("No iTunesDB found at %s", db_path)
            return None
        devices = scan_for_ipods()
        for d in devices:
            if str(d.mount_path) == str(mount_hint):
                return d, db_path
        # Fallback: return path without full DeviceInfo (checksum detection still works)
        logger.warning("Device info not found for %s — using filesystem-only mode", mount_hint)
        return None

    devices = scan_for_ipods()
    if not devices:
        return None

    device = devices[0]
    if len(devices) > 1:
        logger.info("Multiple iPods found — using first: %s", device.display_name)

    db_path = _itunesdb_path(str(device.mount_path))
    return device, db_path


def _itunesdb_path(mount: str) -> str:
    return str(Path(mount) / "iPod_Control" / "iTunes" / "iTunesDB")
