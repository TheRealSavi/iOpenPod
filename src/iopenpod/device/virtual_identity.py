"""Filesystem identities for explicitly-created virtual iPods."""

from __future__ import annotations

import os
import stat
from dataclasses import replace
from pathlib import Path

from .filesystem_profile import FilesystemProfile, VolumeIdentity

_VIRTUAL_IPOD_INFO_FILENAME = "iPodInfo.json"


def virtual_ipod_profile(
    host_profile: FilesystemProfile,
    ipod_path: str | Path,
) -> FilesystemProfile:
    """Return a profile with a stable identity when *ipod_path* is virtual.

    A virtual iPod is an explicitly marked directory rather than a mounted
    device. Its root and marker file identify the selected virtual device, but
    host read-only and unsafe-mount facts remain intact.
    """
    root = Path(os.path.realpath(ipod_path))
    marker = root / _VIRTUAL_IPOD_INFO_FILENAME
    try:
        root_stat = root.stat()
        marker_stat = marker.stat()
    except OSError:
        return host_profile
    if not stat.S_ISREG(marker_stat.st_mode):
        return host_profile

    return replace(
        host_profile,
        mount_path=str(root),
        filesystem_type=host_profile.filesystem_type or "virtual",
        mount_source=host_profile.mount_source or str(root),
        identity=VolumeIdentity(
            operating_system="virtual",
            device_id=str(root_stat.st_dev),
            volume_id=str(root_stat.st_ino),
            mount_instance=(
                f"{marker_stat.st_dev}:{marker_stat.st_ino}:"
                f"{marker_stat.st_ctime_ns}:{marker_stat.st_size}"
            ),
        ),
        inspection_path=str(root),
    )
