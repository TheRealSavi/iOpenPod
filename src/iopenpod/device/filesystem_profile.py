"""Inspect mounted-volume behavior before writing to an iPod.

This module reports host-observed filesystem facts separately from the
``reported_volume_format`` hint stored in SysInfoExtended.  Callers can retain
the returned identity and revalidate it before a later write boundary.
"""

from __future__ import annotations

import ctypes
import os
import plistlib
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol, cast

from .filesystem import detect_filesystem_type

_LINUX_MOUNTINFO = Path("/proc/self/mountinfo")

_MAX_FILE_SIZE_BYTES = {
    "fat": 2 * 1024**3 - 1,
    "fat16": 2 * 1024**3 - 1,
    "fat32": 4 * 1024**3 - 1,
    "msdos": 4 * 1024**3 - 1,
    "msdosfs": 4 * 1024**3 - 1,
    "vfat": 4 * 1024**3 - 1,
}


class _StatVFSResult(Protocol):
    f_frsize: int
    f_bsize: int


@dataclass(frozen=True, slots=True)
class VolumeIdentity:
    """Stable evidence identifying one mounted volume instance."""

    operating_system: str
    device_id: str
    volume_id: str
    mount_instance: str

    @property
    def is_complete(self) -> bool:
        """Return whether the identity is strong enough for revalidation."""
        return bool(
            self.operating_system
            and self.device_id
            and self.volume_id
            and self.mount_instance
        )


@dataclass(frozen=True, slots=True)
class FilesystemProfile:
    """Host-observed filesystem behavior and write-safety constraints."""

    mount_path: str
    filesystem_type: str
    reported_volume_format: str
    mount_source: str
    mount_options: tuple[str, ...]
    read_only: bool
    unsafe_write_reasons: tuple[str, ...]
    case_sensitive: bool | None
    max_file_size_bytes: int | None
    max_component_length: int | None
    allocation_unit_size: int | None
    identity: VolumeIdentity
    detection_errors: tuple[str, ...]
    inspection_path: str = ""

    @property
    def safe_for_writes(self) -> bool:
        """Return whether inspection found no reason to refuse writes."""
        return (
            not self.read_only
            and not self.unsafe_write_reasons
            and bool(self.filesystem_type)
            and self.identity.is_complete
        )


@dataclass(frozen=True, slots=True)
class FilesystemRevalidation:
    """Result of checking that a retained profile still describes the volume."""

    safe_to_continue: bool
    failure_code: str
    reason: str
    current_profile: FilesystemProfile

    @property
    def current_identity(self) -> VolumeIdentity:
        """Return the identity observed during this revalidation."""
        return self.current_profile.identity


@dataclass(frozen=True, slots=True)
class _MountedFilesystemFacts:
    mount_path: str
    filesystem_type: str
    mount_source: str
    mount_options: tuple[str, ...]
    read_only: bool
    identity: VolumeIdentity
    allocation_unit_size: int | None = None
    max_component_length: int | None = None
    errors: tuple[str, ...] = ()


def inspect_filesystem_profile(
    mount_path: str | Path,
    *,
    reported_volume_format: str = "",
    probe_case_sensitivity: bool = False,
) -> FilesystemProfile:
    """Return filesystem facts for the mounted volume containing *mount_path*."""
    requested_path = os.path.realpath(mount_path)
    if sys.platform.startswith("linux"):
        facts = _inspect_linux(requested_path)
    elif sys.platform == "darwin":
        facts = _inspect_macos(requested_path)
    elif sys.platform == "win32":
        facts = _inspect_windows(requested_path)
    else:
        facts = _unavailable_facts(requested_path)

    filesystem_type = facts.filesystem_type or detect_filesystem_type(requested_path)
    max_component_length = facts.max_component_length
    allocation_unit_size = facts.allocation_unit_size
    errors = list(facts.errors)
    if max_component_length is None:
        try:
            pathconf = vars(os).get("pathconf")
            if not callable(pathconf):
                raise AttributeError("os.pathconf is unavailable")
            pathconf_call = cast(Callable[[str, str], int], pathconf)
            max_component_length = int(pathconf_call(requested_path, "PC_NAME_MAX"))
        except (AttributeError, OSError, ValueError) as exc:
            errors.append(f"Could not determine maximum filename length: {exc}")
    if allocation_unit_size is None:
        try:
            statvfs = vars(os).get("statvfs")
            if not callable(statvfs):
                raise AttributeError("os.statvfs is unavailable")
            statvfs_call = cast(Callable[[str], _StatVFSResult], statvfs)
            stats = statvfs_call(requested_path)
            allocation_unit_size = int(stats.f_frsize or stats.f_bsize)
        except (AttributeError, OSError, ValueError) as exc:
            errors.append(f"Could not determine allocation unit size: {exc}")

    unsafe_reasons = _unsafe_write_reasons(
        operating_system=facts.identity.operating_system,
        filesystem_type=filesystem_type,
        mount_options=facts.mount_options,
    )
    case_sensitive: bool | None = None
    can_probe_safely = (
        not facts.read_only
        and not unsafe_reasons
        and bool(filesystem_type)
        and facts.identity.is_complete
    )
    if probe_case_sensitivity and can_probe_safely:
        case_sensitive, case_error = _probe_case_sensitivity(
            _case_probe_directory(requested_path)
        )
        if case_error:
            errors.append(case_error)
            unsafe_reasons += ("Filesystem case sensitivity could not be verified",)
    return FilesystemProfile(
        mount_path=facts.mount_path,
        filesystem_type=filesystem_type,
        reported_volume_format=str(reported_volume_format or "").strip(),
        mount_source=facts.mount_source,
        mount_options=facts.mount_options,
        read_only=facts.read_only,
        unsafe_write_reasons=unsafe_reasons,
        case_sensitive=case_sensitive,
        max_file_size_bytes=_MAX_FILE_SIZE_BYTES.get(filesystem_type),
        max_component_length=max_component_length,
        allocation_unit_size=allocation_unit_size,
        identity=facts.identity,
        detection_errors=tuple(errors),
        inspection_path=requested_path,
    )


def revalidate_filesystem_profile(
    retained_profile: FilesystemProfile,
    *,
    probe_case_sensitivity: bool | None = None,
) -> FilesystemRevalidation:
    """Fail closed unless *retained_profile* still matches a writable volume."""
    should_probe_case = probe_case_sensitivity is True
    current = inspect_filesystem_profile(
        retained_profile.inspection_path or retained_profile.mount_path,
        reported_volume_format=retained_profile.reported_volume_format,
        probe_case_sensitivity=should_probe_case,
    )
    if not should_probe_case and retained_profile.case_sensitive is not None:
        current = replace(
            current,
            case_sensitive=retained_profile.case_sensitive,
        )
    retained_identity = retained_profile.identity
    current_identity = current.identity

    if not retained_identity.is_complete:
        return FilesystemRevalidation(
            False,
            "identity_unavailable",
            "The original volume identity was incomplete and cannot be revalidated.",
            current,
        )
    if not current_identity.is_complete:
        return FilesystemRevalidation(
            False,
            "identity_unavailable",
            "The mounted volume identity could not be read.",
            current,
        )
    if retained_identity.mount_instance != current_identity.mount_instance:
        return FilesystemRevalidation(
            False,
            "mount_changed",
            "The volume mount instance changed after inspection.",
            current,
        )
    if retained_identity != current_identity:
        return FilesystemRevalidation(
            False,
            "volume_changed",
            "A different volume is mounted at the inspected path.",
            current,
        )
    if retained_profile.filesystem_type != current.filesystem_type:
        return FilesystemRevalidation(
            False,
            "filesystem_changed",
            "The mounted filesystem type changed after inspection.",
            current,
        )
    if current.read_only:
        return FilesystemRevalidation(
            False,
            "read_only",
            "The mounted volume is now read-only.",
            current,
        )
    if current.unsafe_write_reasons:
        return FilesystemRevalidation(
            False,
            "unsafe_mount",
            current.unsafe_write_reasons[0],
            current,
        )
    return FilesystemRevalidation(True, "", "", current)


def _inspect_linux(requested_path: str) -> _MountedFilesystemFacts:
    try:
        lines = _LINUX_MOUNTINFO.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        facts = _unavailable_facts(requested_path, operating_system="linux")
        return _MountedFilesystemFacts(
            mount_path=facts.mount_path,
            filesystem_type=facts.filesystem_type,
            mount_source=facts.mount_source,
            mount_options=facts.mount_options,
            read_only=facts.read_only,
            identity=facts.identity,
            errors=(f"Could not read Linux mount table: {exc}",),
        )

    best: tuple[int, _MountedFilesystemFacts] | None = None
    for line in lines:
        parsed = _parse_linux_mountinfo_line(line)
        if parsed is None:
            continue
        mount_point = parsed.mount_path.rstrip(os.sep) or os.sep
        if requested_path != mount_point and not requested_path.startswith(
            mount_point.rstrip(os.sep) + os.sep
        ):
            continue
        score = len(mount_point)
        if best is None or score > best[0]:
            best = (score, parsed)
    if best is not None:
        return best[1]
    facts = _unavailable_facts(requested_path, operating_system="linux")
    return _MountedFilesystemFacts(
        mount_path=facts.mount_path,
        filesystem_type=facts.filesystem_type,
        mount_source=facts.mount_source,
        mount_options=facts.mount_options,
        read_only=facts.read_only,
        identity=facts.identity,
        errors=(f"No Linux mount contains {requested_path}",),
    )


def _inspect_macos(requested_path: str) -> _MountedFilesystemFacts:
    try:
        proc = subprocess.run(
            ["diskutil", "info", "-plist", requested_path],
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        facts = _unavailable_facts(requested_path, operating_system="macos")
        return _replace_facts_error(facts, f"Could not inspect macOS volume: {exc}")
    if proc.returncode != 0:
        facts = _unavailable_facts(requested_path, operating_system="macos")
        return _replace_facts_error(
            facts,
            f"diskutil info failed with exit code {proc.returncode}",
        )
    try:
        info = plistlib.loads(proc.stdout)
    except (plistlib.InvalidFileException, TypeError, ValueError) as exc:
        facts = _unavailable_facts(requested_path, operating_system="macos")
        return _replace_facts_error(facts, f"Could not parse diskutil output: {exc}")
    if not isinstance(info, dict):
        facts = _unavailable_facts(requested_path, operating_system="macos")
        return _replace_facts_error(facts, "diskutil returned an unexpected response")

    device_id = str(info.get("DeviceIdentifier") or "").strip()
    volume_id = str(
        info.get("VolumeUUID")
        or info.get("DiskUUID")
        or info.get("MediaUUID")
        or ""
    ).strip()
    filesystem_type = str(
        info.get("FilesystemType")
        or info.get("FilesystemName")
        or info.get("FilesystemPersonality")
        or ""
    ).strip().casefold()
    actual_mount = os.path.realpath(str(info.get("MountPoint") or requested_path))
    raw_options = info.get("MountOptions")
    if isinstance(raw_options, str):
        options = _unique_options(raw_options)
    elif isinstance(raw_options, (list, tuple)):
        options = tuple(
            str(option).strip()
            for option in raw_options
            if str(option).strip()
        )
    else:
        options = ()
    read_only = bool(
        info.get("Writable") is False
        or info.get("VolumeReadOnly") is True
        or info.get("ReadOnlyVolume") is True
    )
    allocation_size = _positive_int(info.get("AllocationBlockSize"))
    return _MountedFilesystemFacts(
        mount_path=actual_mount,
        filesystem_type=filesystem_type,
        mount_source=f"/dev/{device_id}" if device_id else "",
        mount_options=options,
        read_only=read_only,
        allocation_unit_size=allocation_size,
        identity=VolumeIdentity(
            operating_system="macos",
            device_id=device_id,
            volume_id=volume_id,
            mount_instance=device_id,
        ),
    )


def _inspect_windows(requested_path: str) -> _MountedFilesystemFacts:
    absolute = os.path.abspath(requested_path)
    drive, _tail = os.path.splitdrive(absolute)
    root = f"{drive}\\" if drive else str(Path(absolute).anchor or absolute)
    filesystem_name = ctypes.create_unicode_buffer(256)
    volume_name = ctypes.create_unicode_buffer(1024)
    serial = ctypes.c_ulong()
    max_component = ctypes.c_ulong()
    flags = ctypes.c_ulong()
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        succeeded = kernel32.GetVolumeInformationW(
            root,
            None,
            0,
            ctypes.byref(serial),
            ctypes.byref(max_component),
            ctypes.byref(flags),
            filesystem_name,
            len(filesystem_name),
        )
    except (AttributeError, OSError) as exc:
        facts = _unavailable_facts(root, operating_system="windows")
        return _replace_facts_error(facts, f"Could not inspect Windows volume: {exc}")
    if not succeeded:
        facts = _unavailable_facts(root, operating_system="windows")
        return _replace_facts_error(facts, "GetVolumeInformationW failed")

    try:
        has_volume_name = kernel32.GetVolumeNameForVolumeMountPointW(
            root,
            volume_name,
            len(volume_name),
        )
    except (AttributeError, OSError):
        has_volume_name = False
    volume_device = volume_name.value if has_volume_name else root

    allocation_unit_size: int | None = None
    sectors_per_cluster = ctypes.c_ulong()
    bytes_per_sector = ctypes.c_ulong()
    free_clusters = ctypes.c_ulong()
    total_clusters = ctypes.c_ulong()
    try:
        has_geometry = kernel32.GetDiskFreeSpaceW(
            root,
            ctypes.byref(sectors_per_cluster),
            ctypes.byref(bytes_per_sector),
            ctypes.byref(free_clusters),
            ctypes.byref(total_clusters),
        )
    except (AttributeError, OSError):
        has_geometry = False
    if has_geometry:
        allocation_unit_size = sectors_per_cluster.value * bytes_per_sector.value
        if allocation_unit_size <= 0:
            allocation_unit_size = None

    return _MountedFilesystemFacts(
        mount_path=root,
        filesystem_type=filesystem_name.value.strip().casefold(),
        mount_source=volume_device,
        mount_options=(),
        read_only=bool(flags.value & 0x00080000),
        allocation_unit_size=allocation_unit_size,
        max_component_length=_positive_int(max_component.value),
        identity=VolumeIdentity(
            operating_system="windows",
            device_id=volume_device,
            volume_id=f"{serial.value:08X}",
            mount_instance=volume_device,
        ),
    )


def _parse_linux_mountinfo_line(line: str) -> _MountedFilesystemFacts | None:
    fields = line.split()
    try:
        separator = fields.index("-")
    except ValueError:
        return None
    if separator < 6 or len(fields) <= separator + 3:
        return None
    mount_id = fields[0]
    device = fields[2]
    mount_point = os.path.realpath(_decode_mountinfo_field(fields[4]))
    filesystem_type = fields[separator + 1].strip().casefold()
    source = _decode_mountinfo_field(fields[separator + 2])
    mount_options = _unique_options(fields[5], fields[separator + 3])
    return _MountedFilesystemFacts(
        mount_path=mount_point,
        filesystem_type=filesystem_type,
        mount_source=source,
        mount_options=mount_options,
        read_only="ro" in mount_options,
        identity=VolumeIdentity(
            operating_system="linux",
            device_id=device,
            volume_id=source,
            mount_instance=mount_id,
        ),
    )


def _unique_options(*values: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        for option in value.split(","):
            if option and option not in result:
                result.append(option)
    return tuple(result)


def _positive_int(value: object) -> int | None:
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _decode_mountinfo_field(value: str) -> str:
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _unsafe_write_reasons(
    *,
    operating_system: str,
    filesystem_type: str,
    mount_options: tuple[str, ...],
) -> tuple[str, ...]:
    if (
        operating_system == "linux"
        and filesystem_type in {"hfs", "hfs+", "hfsplus", "hfsx"}
        and "force" in mount_options
    ):
        return ("Linux HFS volume is mounted with the unsafe 'force' option",)
    return ()


def _probe_case_sensitivity(mount_path: str) -> tuple[bool | None, str]:
    """Probe filename lookup behavior and remove the unique probe immediately."""
    fd: int | None = None
    probe_path: Path | None = None
    case_sensitive: bool | None = None
    error = ""
    try:
        fd, raw_path = tempfile.mkstemp(
            prefix=".iOpenPod_CaseProbe_Aa_",
            dir=mount_path,
        )
        probe_path = Path(raw_path)
        os.close(fd)
        fd = None
        alternate = probe_path.with_name(probe_path.name.swapcase())
        case_sensitive = not alternate.exists()
    except OSError as exc:
        error = f"Could not probe filesystem case sensitivity: {exc}"
    finally:
        if fd is not None:
            os.close(fd)
        if probe_path is not None:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError as exc:
                case_sensitive = None
                error = f"Could not remove filesystem case probe: {exc}"
    return case_sensitive, error


def _case_probe_directory(requested_path: str) -> str:
    """Prefer the database directory that iOpenPod will actually modify."""
    requested = Path(requested_path)
    database_directory = requested / "iPod_Control" / "iTunes"
    if database_directory.is_dir():
        return str(database_directory)
    return str(requested)


def _unavailable_facts(
    requested_path: str,
    *,
    operating_system: str = "unknown",
) -> _MountedFilesystemFacts:
    return _MountedFilesystemFacts(
        mount_path=requested_path,
        filesystem_type="",
        mount_source="",
        mount_options=(),
        read_only=False,
        identity=VolumeIdentity(
            operating_system=operating_system,
            device_id="",
            volume_id="",
            mount_instance="",
        ),
    )


def _replace_facts_error(
    facts: _MountedFilesystemFacts,
    error: str,
) -> _MountedFilesystemFacts:
    return _MountedFilesystemFacts(
        mount_path=facts.mount_path,
        filesystem_type=facts.filesystem_type,
        mount_source=facts.mount_source,
        mount_options=facts.mount_options,
        read_only=facts.read_only,
        identity=facts.identity,
        allocation_unit_size=facts.allocation_unit_size,
        max_component_length=facts.max_component_length,
        errors=(error,),
    )
