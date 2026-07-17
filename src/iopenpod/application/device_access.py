"""Device mount access checks used before iOpenPod starts working with an iPod."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from iopenpod.device.recovery import LinuxMountDetails, linux_mount_details
from iopenpod.device.write_guard import DeviceWriteGuard, DeviceWriteSafetyError
from iopenpod.device.write_readiness import (
    inspect_device_write_readiness,
    revalidate_device_write_readiness,
    volume_lock_key,
)


@dataclass(frozen=True)
class DeviceWriteAccessResult:
    writable: bool
    reason: str = ""
    mount_path: str = ""
    mount: LinuxMountDetails | None = None


def _access_failure(
    ipod_path: Path,
    reason: str,
    mount: LinuxMountDetails | None,
) -> DeviceWriteAccessResult:
    return DeviceWriteAccessResult(
        writable=False,
        reason=reason,
        mount_path=str(ipod_path),
        mount=mount,
    )


def check_ipod_write_access(ipod_path: str | Path) -> DeviceWriteAccessResult:
    """Verify write access only while the selected volume is identity-locked."""

    root = Path(ipod_path)
    probe_dir = root / "iPod_Control" / "iTunes"
    mount = linux_mount_details(root)
    if mount is not None and mount.is_read_only:
        return _access_failure(root, "mount is read-only", mount)

    if not probe_dir.is_dir():
        return _access_failure(root, f"{probe_dir} does not exist", mount)

    try:
        profile = inspect_device_write_readiness(root)
        with DeviceWriteGuard(
            root,
            volume_key=volume_lock_key(profile),
        ):
            revalidate_device_write_readiness(
                profile,
                probe_case_sensitivity=True,
            )
    except DeviceWriteSafetyError as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        return _access_failure(root, reason, mount)
    except OSError as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        return _access_failure(root, reason, mount)

    return DeviceWriteAccessResult(True)
