"""One fail-closed entry point for inspecting and revalidating iPod writes."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .filesystem import filesystem_itunesdb_platform
from .filesystem_profile import (
    FilesystemProfile,
    inspect_filesystem_profile,
    revalidate_filesystem_profile,
)
from .write_guard import DeviceWriteSafetyError

logger = logging.getLogger(__name__)

_SUPPORTED_PHYSICAL_FILESYSTEMS = frozenset({
    "fat",
    "fat16",
    "fat32",
    "hfs",
    "hfs+",
    "hfsplus",
    "hfsx",
    "msdos",
    "msdosfs",
    "vfat",
})


def inspect_device_write_readiness(
    mount_path: str | Path,
    *,
    reported_volume_format: str = "",
) -> FilesystemProfile:
    """Inspect a selected iPod volume and refuse uncertain or unsafe writes."""
    profile = inspect_filesystem_profile(
        mount_path,
        reported_volume_format=reported_volume_format,
        probe_case_sensitivity=False,
    )
    _log_profile("inspected", profile)
    _log_reported_format_mismatch(profile)
    requested = os.path.normcase(os.path.realpath(mount_path))
    observed_mount = os.path.normcase(os.path.realpath(profile.mount_path))
    is_virtual_ipod = (Path(requested) / "iPodInfo.json").is_file()
    if requested != observed_mount and not is_virtual_ipod:
        raise DeviceWriteSafetyError(
            "The selected iPod path is not mounted as its own volume. "
            f"Selected path: {requested}; containing mount: {observed_mount}. "
            "iOpenPod stopped to avoid writing into an empty host directory."
        )
    if not is_virtual_ipod and not (Path(requested) / "iPod_Control").is_dir():
        raise DeviceWriteSafetyError(
            "The selected volume does not contain an iPod_Control directory. "
            "iOpenPod stopped before writing to an unrecognized volume."
        )
    if (
        not is_virtual_ipod
        and profile.filesystem_type not in _SUPPORTED_PHYSICAL_FILESYSTEMS
    ):
        raise DeviceWriteSafetyError(
            "The selected physical iPod uses an unsupported filesystem "
            f"({profile.filesystem_type or 'unknown'}). Stock iPods require "
            "a FAT-formatted Windows volume or an HFS-formatted Mac volume."
        )
    if not profile.safe_for_writes:
        raise DeviceWriteSafetyError(_unsafe_profile_message(profile))
    return profile


def revalidate_device_write_readiness(
    retained_profile: FilesystemProfile,
    *,
    probe_case_sensitivity: bool | None = None,
) -> FilesystemProfile:
    """Return current facts only if the original writable volume is unchanged."""
    result = revalidate_filesystem_profile(
        retained_profile,
        probe_case_sensitivity=probe_case_sensitivity,
    )
    _log_profile("revalidated", result.current_profile)
    if not result.safe_to_continue:
        raise DeviceWriteSafetyError(
            "The iPod volume is no longer safe to write: "
            f"{result.reason} iOpenPod stopped before the next write."
        )
    return result.current_profile


def volume_lock_key(profile: FilesystemProfile) -> str:
    """Return a host-lock key tied to this exact mounted volume instance."""
    identity = profile.identity
    return "|".join((
        identity.operating_system,
        identity.device_id,
        identity.volume_id,
        identity.mount_instance,
    ))


def _unsafe_profile_message(profile: FilesystemProfile) -> str:
    reasons: list[str] = []
    if profile.read_only:
        reasons.append("the volume is mounted read-only")
    reasons.extend(profile.unsafe_write_reasons)
    if not profile.filesystem_type:
        reasons.append("the actual filesystem type could not be detected")
    if not profile.identity.is_complete:
        reasons.append("the mounted volume identity could not be verified")
    if not reasons and profile.detection_errors:
        reasons.extend(profile.detection_errors)
    detail = "; ".join(reasons) or "filesystem safety could not be verified"
    actual = profile.filesystem_type or "unknown"
    reported = profile.reported_volume_format or "unknown"
    return (
        f"The iPod filesystem is not safe for writing: {detail}. "
        f"Actual filesystem: {actual}; device-reported format: {reported}."
    )


def _log_profile(action: str, profile: FilesystemProfile) -> None:
    identity = profile.identity
    logger.info(
        "iPod filesystem profile %s: selected=%s mount=%s actual=%s reported=%s "
        "source=%s options=%s read_only=%s case_sensitive=%s "
        "max_file_bytes=%s max_name=%s allocation_unit=%s "
        "identity=%s/%s/%s/%s safe_for_writes=%s errors=%s",
        action,
        profile.inspection_path or profile.mount_path,
        profile.mount_path,
        profile.filesystem_type or "unknown",
        profile.reported_volume_format or "unknown",
        profile.mount_source or "unknown",
        ",".join(profile.mount_options) or "none",
        profile.read_only,
        profile.case_sensitive,
        profile.max_file_size_bytes,
        profile.max_component_length,
        profile.allocation_unit_size,
        identity.operating_system or "unknown",
        identity.device_id or "unknown",
        identity.volume_id or "unknown",
        identity.mount_instance or "unknown",
        profile.safe_for_writes,
        "; ".join(profile.detection_errors) or "none",
    )


def _log_reported_format_mismatch(profile: FilesystemProfile) -> None:
    actual_platform = filesystem_itunesdb_platform(profile.filesystem_type)
    reported_platform = filesystem_itunesdb_platform(
        profile.reported_volume_format
    )
    if (
        actual_platform is not None
        and reported_platform is not None
        and actual_platform != reported_platform
    ):
        logger.warning(
            "iPod filesystem/report mismatch: actual=%s reported=%s",
            profile.filesystem_type,
            profile.reported_volume_format,
        )
