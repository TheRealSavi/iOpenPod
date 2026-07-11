"""Cross-platform safe-eject helper for iPods.

Provides a single entry point, :func:`eject_ipod`, that unmounts and
(where applicable) powers down the device behind a given mount path.

Strategies per platform:
  * **Windows** — Windows device eject request, Shell "Eject" fallback,
                  and drive-removal verification.
  * **macOS**   — ``diskutil eject`` first, then force unmount/eject fallbacks.
  * **Linux**   — ``udisksctl`` unmount/power-off first, then ``eject``,
                  then force/lazy ``umount`` fallbacks.
"""

from __future__ import annotations

import json
import logging
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_TIMEOUT_SECS = 30
_WINDOWS_VERIFY_SECS = 20
_WINDOWS_LOCK_RETRY_SECS = 10
_ALREADY_UNMOUNTED_HINTS = (
    "not mounted",
    "not currently mounted",
    "already unmounted",
)
_MISSING_TARGET_HINTS = (
    "no such file or directory",
    "not found",
    "no object",
    "error looking up object",
    "does not exist",
)


def eject_ipod(mount_path: str) -> tuple[bool, str]:
    """Safely eject / unmount an iPod at *mount_path*.

    Returns ``(success, message)``.  The *message* is suitable for
    display in a dialog or log entry.
    """
    if not mount_path:
        return False, "No device path supplied."

    path = Path(mount_path)
    try:
        if sys.platform == "win32":
            return _eject_windows(path)
        if sys.platform == "darwin":
            return _eject_macos(path)
        return _eject_linux(path)
    except Exception as exc:  # last-ditch safety net
        logger.exception("eject_ipod: unexpected failure")
        return False, f"Unexpected error: {exc}"


# ──────────────────────────────────────────────────────────────────────
# Windows
# ──────────────────────────────────────────────────────────────────────

def _eject_windows(path: Path) -> tuple[bool, str]:
    """Ask Windows to safely remove the drive and verify it disappeared.

    Explorer's COM ``Eject`` verb returns before Windows confirms the
    device was actually removed, and it can fail silently when another
    process has an open handle. Prefer the Configuration Manager eject
    API, fall back to the shell verb, and only report success once the
    drive letter is no longer mounted.
    """
    drive = _windows_drive_from_path(path)
    if not drive:
        return False, f"Cannot determine drive letter from {path}."

    if not _windows_drive_is_mounted(drive):
        return True, f"{drive} is already ejected."

    pnp_device_id, pnp_msg = _get_windows_disk_pnp_id(drive)
    prep_ok, prep_msg = _prepare_windows_volume_for_eject(drive)
    if prep_ok and _wait_for_windows_drive_removed(drive):
        return True, prep_msg or f"Ejected {drive}"

    cfg_ok, cfg_msg = _run_windows_cfgmgr_eject(drive, pnp_device_id)
    if cfg_ok and _wait_for_windows_drive_removed(drive):
        return True, cfg_msg or f"Ejected {drive}"

    shell_ok, shell_msg = _run_windows_shell_eject(drive)
    if shell_ok and _wait_for_windows_drive_removed(drive):
        return True, shell_msg or f"Ejected {drive}"

    return False, _windows_eject_failure_message(
        drive=drive,
        prep_msg=prep_msg,
        pnp_msg=pnp_msg if not pnp_device_id else "",
        cfg_msg=cfg_msg,
        shell_msg=shell_msg,
    )


def _windows_drive_from_path(path: Path) -> str:
    """Return a normalized Windows drive string (``E:``) for *path*."""
    raw = str(path)
    m = re.match(r"^([a-zA-Z]):", raw)
    if m:
        return f"{m.group(1).upper()}:"

    drive = path.drive
    m = re.match(r"^([a-zA-Z]):", drive)
    if m:
        return f"{m.group(1).upper()}:"
    return ""


def _prepare_windows_volume_for_eject(drive: str) -> tuple[bool, str]:
    """Flush, lock, and dismount the drive volume before PnP eject.

    This is the part Explorer hides behind "Safely Remove Hardware".  If
    Windows cannot lock the volume, some process still has an open handle
    to the iPod and the later device eject request will usually be vetoed.
    """
    import ctypes
    from ctypes import wintypes

    # Prefer WinDLL when available (gives use_last_error semantics),
    # otherwise fall back to windll.kernel32. Use getattr to avoid
    # static-analysis attribute complaints in type checkers.
    WinDLL = getattr(ctypes, "WinDLL", None)
    if WinDLL:
        kernel32 = WinDLL("kernel32", use_last_error=True)
    else:
        windll = getattr(ctypes, "windll", None)
        kernel32 = getattr(windll, "kernel32", None)

    if kernel32 is None:
        # This function should only be called on Windows where kernel32 is
        # available; fail fast to satisfy static analysis and avoid None
        # attribute access below.
        raise RuntimeError("Windows kernel32 API not available on this platform")
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.DeviceIoControl.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.DeviceIoControl.restype = wintypes.BOOL
    kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel32.FlushFileBuffers.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    generic_read = 0x80000000
    generic_write = 0x40000000
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    open_existing = 3
    invalid_handle_value = wintypes.HANDLE(-1).value

    fsctl_lock_volume = 0x00090018
    fsctl_dismount_volume = 0x00090020
    ioctl_storage_media_removal = 0x002D4804
    ioctl_storage_eject_media = 0x002D4808

    volume_name = f"\\\\.\\{drive}"
    handle = kernel32.CreateFileW(
        volume_name,
        generic_read | generic_write,
        file_share_read | file_share_write,
        None,
        open_existing,
        0,
        None,
    )
    if handle == invalid_handle_value:
        err = _windows_last_error_message()
        return False, f"Could not open {drive} for eject ({err})."

    try:
        kernel32.FlushFileBuffers(handle)

        deadline = time.monotonic() + _WINDOWS_LOCK_RETRY_SECS
        last_error = ""
        while True:
            ok, msg = _windows_device_io_control(
                kernel32,
                handle,
                fsctl_lock_volume,
            )
            if ok:
                break
            last_error = msg
            if time.monotonic() >= deadline:
                return (
                    False,
                    f"Could not lock {drive} for eject ({last_error}). "
                    "Another process still has the iPod volume open.",
                )
            time.sleep(0.25)

        ok, msg = _windows_device_io_control(
            kernel32,
            handle,
            fsctl_dismount_volume,
        )
        if not ok:
            return False, f"Locked {drive}, but Windows refused to dismount it ({msg})."

        prevent_removal = ctypes.c_ubyte(0)
        _windows_device_io_control(
            kernel32,
            handle,
            ioctl_storage_media_removal,
            ctypes.byref(prevent_removal),
            ctypes.sizeof(prevent_removal),
        )
        _windows_device_io_control(kernel32, handle, ioctl_storage_eject_media)

        return True, f"Locked and dismounted {drive}."
    finally:
        kernel32.CloseHandle(handle)


def _windows_device_io_control(
    kernel32,
    handle,
    ioctl: int,
    in_buffer=None,
    in_size: int = 0,
) -> tuple[bool, str]:
    import ctypes
    from ctypes import wintypes

    bytes_returned = wintypes.DWORD(0)
    ok = kernel32.DeviceIoControl(
        handle,
        ioctl,
        in_buffer,
        in_size,
        None,
        0,
        ctypes.byref(bytes_returned),
        None,
    )
    if ok:
        return True, ""
    return False, _windows_last_error_message()


def _windows_last_error_message() -> str:
    import ctypes

    # Use getattr to guard against static-analysis missing attributes.
    code = getattr(ctypes, "get_last_error", lambda: 0)()
    try:
        text = getattr(ctypes, "FormatError", lambda c: "Unknown Windows error")(code).strip()
    except Exception:
        text = "Unknown Windows error"
    return f"{text} (Win32 error {code})"


def _get_windows_disk_pnp_id(drive: str) -> tuple[str | None, str]:
    """Return the Win32_DiskDrive PNPDeviceID backing *drive*."""
    ps_cmd = (
        "$ErrorActionPreference = 'Stop'\n"
        f"$drive = {_ps_single_quote(drive)}\n"
        r"""
function Write-IopResult {
    param([string]$Status, [string]$Message)
    [Console]::Out.WriteLine($Status + "`t" + $Message)
}

$logical = Get-CimInstance -ClassName Win32_LogicalDisk -Filter ("DeviceID='" + $drive + "'") -ErrorAction Stop
if ($null -eq $logical) {
    Write-IopResult "ERROR" ($drive + " is not mounted.")
    exit 2
}

$partition = Get-CimAssociatedInstance -InputObject $logical -ResultClassName Win32_DiskPartition -ErrorAction Stop | Select-Object -First 1
if ($null -eq $partition) {
    Write-IopResult "ERROR" ("Could not find the disk partition for " + $drive + ".")
    exit 2
}

$disk = Get-CimAssociatedInstance -InputObject $partition -ResultClassName Win32_DiskDrive -ErrorAction Stop | Select-Object -First 1
if ($null -eq $disk -or [string]::IsNullOrWhiteSpace([string]$disk.PNPDeviceID)) {
    Write-IopResult "ERROR" ("Could not find the physical disk for " + $drive + ".")
    exit 2
}

Write-IopResult "OK" ([string]$disk.PNPDeviceID)
exit 0
"""
    )
    ok, message = _run_windows_powershell_eject(
        ps_cmd,
        "Could not resolve the Windows disk device.",
    )
    return (message if ok else None), ("" if ok else message)


def _run_windows_cfgmgr_eject(
    drive: str,
    pnp_device_id: str | None = None,
) -> tuple[bool, str]:
    """Request safe device removal via ``CM_Request_Device_EjectW``."""
    ps_cmd = (
        "$ErrorActionPreference = 'Stop'\n"
        f"$drive = {_ps_single_quote(drive)}\n"
        f"$pnpDeviceId = {_ps_single_quote(pnp_device_id or '')}\n"
        r"""
function Write-IopResult {
    param([string]$Status, [string]$Message)
    [Console]::Out.WriteLine($Status + "`t" + $Message)
}

if ([string]::IsNullOrWhiteSpace($pnpDeviceId)) {
    $logical = Get-CimInstance -ClassName Win32_LogicalDisk -Filter ("DeviceID='" + $drive + "'") -ErrorAction Stop
    if ($null -eq $logical) {
        Write-IopResult "MISSING" ($drive + " is not mounted.")
        exit 0
    }

    $partition = Get-CimAssociatedInstance -InputObject $logical -ResultClassName Win32_DiskPartition -ErrorAction Stop | Select-Object -First 1
    if ($null -eq $partition) {
        Write-IopResult "ERROR" ("Could not find the disk partition for " + $drive + ".")
        exit 2
    }

    $disk = Get-CimAssociatedInstance -InputObject $partition -ResultClassName Win32_DiskDrive -ErrorAction Stop | Select-Object -First 1
    if ($null -eq $disk -or [string]::IsNullOrWhiteSpace([string]$disk.PNPDeviceID)) {
        Write-IopResult "ERROR" ("Could not find the physical disk for " + $drive + ".")
        exit 2
    }
    $pnpDeviceId = [string]$disk.PNPDeviceID
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class IopCfgMgr
{
    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    public static extern int CM_Locate_DevNodeW(out UInt32 pdnDevInst, string pDeviceID, UInt32 ulFlags);

    [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
    public static extern int CM_Request_Device_EjectW(UInt32 dnDevInst, out UInt32 pVetoType, StringBuilder pszVetoName, Int32 ulNameLength, UInt32 ulFlags);
}
"@

[UInt32]$devInst = 0
$locate = [IopCfgMgr]::CM_Locate_DevNodeW([ref]$devInst, [string]$pnpDeviceId, 0)
if ($locate -ne 0) {
    Write-IopResult "ERROR" ("Windows could not locate the device node for " + $drive + " (CM error " + $locate + ").")
    exit 3
}

[UInt32]$vetoType = 0
$vetoName = New-Object System.Text.StringBuilder 512
$result = [IopCfgMgr]::CM_Request_Device_EjectW($devInst, [ref]$vetoType, $vetoName, $vetoName.Capacity, 0)
if ($result -ne 0 -or $vetoType -ne 0) {
    $detail = "Windows vetoed eject for " + $drive + " (CM error " + $result + ", veto " + $vetoType
    $name = $vetoName.ToString()
    if (-not [string]::IsNullOrWhiteSpace($name)) {
        $detail += ", " + $name
    }
    $detail += ")."
    Write-IopResult "ERROR" $detail
    exit 4
}

Write-IopResult "OK" ("Windows accepted the eject request for " + $drive + ".")
exit 0
"""
    )
    return _run_windows_powershell_eject(ps_cmd, "Windows device eject request failed.")


def _run_windows_shell_eject(drive: str) -> tuple[bool, str]:
    """Invoke Explorer's shell ``Eject`` verb as a compatibility fallback."""
    ps_cmd = (
        "$ErrorActionPreference = 'Stop'\n"
        f"$drive = {_ps_single_quote(drive)}\n"
        r"""
function Write-IopResult {
    param([string]$Status, [string]$Message)
    [Console]::Out.WriteLine($Status + "`t" + $Message)
}

$shell = New-Object -ComObject Shell.Application
$computer = $shell.Namespace(17)
if ($null -eq $computer) {
    Write-IopResult "ERROR" "Explorer did not expose the Computer namespace."
    exit 2
}

$item = $computer.ParseName($drive)
if ($null -eq $item) {
    Write-IopResult "MISSING" ($drive + " is not mounted.")
    exit 0
}

$item.InvokeVerb("Eject")
Write-IopResult "OK" ("Explorer accepted the eject request for " + $drive + ".")
exit 0
"""
    )
    return _run_windows_powershell_eject(ps_cmd, "Explorer eject request failed.")


def _run_windows_powershell_eject(ps_cmd: str, default_error: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECS,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return False, "PowerShell is not available on this system."
    except subprocess.TimeoutExpired:
        return False, "Eject timed out."

    status, message = _parse_windows_eject_result(proc.stdout)
    if status in {"OK", "MISSING"} and proc.returncode == 0:
        return True, message
    if status == "ERROR":
        return False, message

    err = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode != 0:
        return False, err or f"{default_error} PowerShell exited with code {proc.returncode}."
    return True, err or default_error


def _parse_windows_eject_result(output: str) -> tuple[str, str]:
    for line in output.splitlines():
        status, sep, message = line.partition("\t")
        if sep and status in {"OK", "MISSING", "ERROR"}:
            return status, message.strip()
    return "", output.strip()


def _wait_for_windows_drive_removed(drive: str) -> bool:
    deadline = time.monotonic() + _WINDOWS_VERIFY_SECS
    while time.monotonic() < deadline:
        if not _windows_drive_is_mounted(drive):
            return True
        time.sleep(0.25)
    return not _windows_drive_is_mounted(drive)


def _windows_drive_is_mounted(drive: str) -> bool:
    if sys.platform != "win32":
        return Path(_windows_drive_root(drive)).exists()

    import ctypes

    drive_type = ctypes.windll.kernel32.GetDriveTypeW(_windows_drive_root(drive))
    return drive_type != 1  # DRIVE_NO_ROOT_DIR


def _windows_drive_root(drive: str) -> str:
    return f"{drive[0].upper()}:\\"


def _ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _windows_eject_failure_message(
    drive: str,
    prep_msg: str,
    pnp_msg: str,
    cfg_msg: str,
    shell_msg: str,
) -> str:
    details = []
    for msg in (pnp_msg, prep_msg, cfg_msg, shell_msg):
        msg = msg.strip()
        if msg and msg not in details:
            details.append(msg)

    message = (
        f"Windows did not eject {drive}; the drive is still mounted. "
        "Close any File Explorer windows or apps using the iPod, then try again."
    )
    if details:
        message += "\n\nDetails: " + " | ".join(details)
    return message


# ──────────────────────────────────────────────────────────────────────
# macOS
# ──────────────────────────────────────────────────────────────────────

def _eject_macos(path: Path) -> tuple[bool, str]:
    """Eject via ``diskutil`` with forced unmount fallbacks."""
    if not shutil.which("diskutil"):
        return False, "diskutil is not available."

    mount_path = str(path)
    info, info_msg = _macos_disk_info(mount_path)
    device_id = str(info.get("DeviceIdentifier") or "")
    parent = str(info.get("ParentWholeDisk") or "")
    whole_disk = device_id if info.get("WholeDisk") else parent
    disk_target = whole_disk or device_id or mount_path
    volume_target = device_id or mount_path
    mount_point = str(info.get("MountPoint") or mount_path)

    if not info and not _macos_mount_is_present(mount_point, device_id):
        return True, "Device already unmounted."

    _run_sync()
    attempts: list[str] = []

    ok, msg = _run_command(["diskutil", "eject", disk_target])
    attempts.append(msg)
    if ok and _wait_for_macos_mount_gone(mount_point, device_id):
        return True, f"Ejected {disk_target}"

    ok, msg = _run_command(["diskutil", "unmount", volume_target])
    attempts.append(msg)
    if ok:
        ok_eject, eject_msg = _run_command(["diskutil", "eject", disk_target])
        attempts.append(eject_msg)
        if (ok_eject or _is_benign_absence(eject_msg)) and _wait_for_macos_mount_gone(
            mount_point,
            device_id,
        ):
            return True, f"Unmounted and ejected {disk_target}"

    ok, msg = _run_command(["diskutil", "unmount", "force", volume_target])
    attempts.append(msg)
    if ok:
        ok_eject, eject_msg = _run_command(["diskutil", "eject", disk_target])
        attempts.append(eject_msg)
        if (ok_eject or _is_benign_absence(eject_msg)) and _wait_for_macos_mount_gone(
            mount_point,
            device_id,
        ):
            return True, f"Force-unmounted and ejected {disk_target}"

    ok, msg = _run_command(["diskutil", "unmountDisk", "force", disk_target])
    attempts.append(msg)
    if ok:
        ok_eject, eject_msg = _run_command(["diskutil", "eject", disk_target])
        attempts.append(eject_msg)
        if _wait_for_macos_mount_gone(mount_point, device_id):
            if ok_eject or _is_benign_absence(eject_msg):
                return True, f"Force-unmounted and ejected {disk_target}"
            return True, f"Force-unmounted {disk_target}; eject reported: {eject_msg}"

    if _wait_for_macos_mount_gone(mount_point, device_id):
        return True, f"Device unmounted: {disk_target}"

    details = _join_unique_messages([info_msg, *attempts])
    return False, details or f"diskutil could not eject {disk_target}."


def _macos_disk_info(target: str) -> tuple[dict, str]:
    """Return ``diskutil info -plist`` data for *target*."""
    try:
        proc = subprocess.run(
            ["diskutil", "info", "-plist", target],
            capture_output=True,
            timeout=10,
        )
    except FileNotFoundError:
        return {}, "diskutil is not available."
    except subprocess.TimeoutExpired:
        return {}, "diskutil info timed out."

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
        return {}, err or "diskutil info failed."

    try:
        data = plistlib.loads(proc.stdout)
    except Exception as exc:
        return {}, f"Could not parse diskutil info: {exc}"
    if isinstance(data, dict):
        return data, ""
    return {}, "diskutil info returned an unexpected response."


def _wait_for_macos_mount_gone(mount_point: str, device_id: str = "") -> bool:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not _macos_mount_is_present(mount_point, device_id):
            return True
        time.sleep(0.25)
    return not _macos_mount_is_present(mount_point, device_id)


def _macos_mount_is_present(mount_point: str, device_id: str = "") -> bool:
    try:
        proc = subprocess.run(
            ["mount"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT_SECS,
        )
    except subprocess.TimeoutExpired:
        return True
    except FileNotFoundError:
        return Path(mount_point).exists()

    if proc.returncode != 0:
        return Path(mount_point).exists()

    wanted_mount = _normalize_posix_path(mount_point)
    wanted_device = f"/dev/{device_id}" if device_id else ""
    for line in proc.stdout.splitlines():
        m = re.match(r"^(.+) on (.+) \(.+\)$", line)
        if not m:
            continue
        dev, mounted_at = m.group(1), m.group(2)
        if _normalize_posix_path(mounted_at) == wanted_mount:
            return True
        if wanted_device and dev == wanted_device:
            return True
    return False


# ──────────────────────────────────────────────────────────────────────
# Linux
# ──────────────────────────────────────────────────────────────────────

def _eject_linux(path: Path) -> tuple[bool, str]:
    """Try udisksctl, eject, then force/lazy umount, verifying each step."""
    mount_path = str(path)
    device = _find_block_device(mount_path)
    detach_target = (_parent_block_device(device) or device) if device else None
    if not _linux_path_is_mounted(mount_path, device):
        return True, "Device already unmounted."

    _run_sync()
    errors: list[str] = []
    last_error: str | None = None

    if device and shutil.which("udisksctl"):
        ok, msg = _udisks_eject(device, mount_path)
        if ok and _wait_for_linux_mount_gone(mount_path, device):
            return True, msg
        last_error = msg
        errors.append(msg)
        logger.debug("udisksctl eject failed, falling back: %s", msg)

    if detach_target and shutil.which("eject"):
        ok, msg = _run_eject_command(detach_target)
        if ok and _wait_for_linux_mount_gone(mount_path, device):
            return True, msg
        if _is_benign_absence(msg):
            return True, f"Device already detached: {detach_target}"
        last_error = msg
        errors.append(msg)
        logger.debug("eject command failed for %s: %s", detach_target, msg)

    if shutil.which("umount"):
        umount_targets: list[str] = []
        if device:
            umount_targets.append(device)
        if path.exists():
            umount_targets.append(mount_path)
        umount_targets = list(dict.fromkeys(umount_targets))

        modes = ("normal", "force", "lazy", "force_lazy")
        for target in umount_targets:
            for mode in modes:
                ok, msg, already_unmounted = _run_umount_command(target, mode=mode)
                if ok or already_unmounted:
                    if _wait_for_linux_mount_gone(mount_path, device):
                        detach_msg = _detach_linux_after_unmount(detach_target)
                        if detach_msg:
                            return True, f"{msg}; {detach_msg}"
                        return True, msg
                last_error = msg
                errors.append(msg)

    if _wait_for_linux_mount_gone(mount_path, device):
        return True, "Device already unmounted."

    details = _join_unique_messages(errors)
    return False, details or last_error or (
        "No suitable unmount utility found "
        "(tried udisksctl, eject, force/lazy umount)."
    )


def _find_block_device(mount_path: str) -> str | None:
    """Return the block device backing *mount_path* (e.g. ``/dev/sdb1``)."""
    if shutil.which("findmnt"):
        try:
            proc = subprocess.run(
                ["findmnt", "-n", "-o", "TARGET,SOURCE", "--target", mount_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0:
                line = proc.stdout.strip().splitlines()[0].strip() if proc.stdout.strip() else ""
                parts = line.split(None, 1)
                target = _decode_mount_field(parts[0]) if parts else ""
                source = parts[1].strip() if len(parts) > 1 else ""
                if (
                    source.startswith("/dev/")
                    and target != "/"
                    and (
                        _normalize_posix_path(mount_path) == _normalize_posix_path(target)
                        or _normalize_posix_path(mount_path).startswith(
                            _normalize_posix_path(target).rstrip("/") + "/"
                        )
                    )
                ):
                    return source
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Fallback: scan /proc/mounts for the longest matching mountpoint.
    best: str | None = None
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            best_len = -1
            for line in f:
                parts = line.split()
                if len(parts) < 2:
                    continue
                dev, mp = parts[0], _decode_mount_field(parts[1])
                if mp == "/":
                    continue
                if mount_path == mp or mount_path.startswith(mp.rstrip("/") + "/"):
                    if dev.startswith("/dev/") and len(mp) > best_len:
                        best, best_len = dev, len(mp)
    except OSError:
        pass

    if shutil.which("lsblk"):
        try:
            proc = subprocess.run(
                ["lsblk", "-J", "-o", "NAME,MOUNTPOINT"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                for dev_entry in data.get("blockdevices", []):
                    for child in dev_entry.get("children", []):
                        mountpoint = child.get("mountpoint") or ""
                        if mountpoint == mount_path:
                            name = child.get("name", "")
                            if name:
                                return f"/dev/{name}"
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            pass

    return best


def _udisks_eject(device: str, mount_path: str) -> tuple[bool, str]:
    """Unmount then power off the parent disk via ``udisksctl``."""
    ok, msg = _run_udisks_unmount(device, force=False)
    if not ok and not _is_benign_absence(msg):
        ok, msg = _run_udisks_unmount(device, force=True)
    if not ok and not _is_benign_absence(msg):
        return False, msg

    if not _wait_for_linux_mount_gone(mount_path, device):
        return False, msg or f"udisksctl did not unmount {device}."

    parent = _parent_block_device(device)
    if not parent:
        return True, f"Unmounted {device}"

    return _run_udisks_poweroff(parent)


def _run_udisks_unmount(device: str, force: bool) -> tuple[bool, str]:
    args = [
        "udisksctl", "unmount",
        "--block-device", device,
        "--no-user-interaction",
    ]
    if force:
        args.append("--force")

    ok, msg = _run_command(args)
    if ok:
        label = "force-unmounted" if force else "unmounted"
        return True, f"udisksctl {label} {device}."
    if _is_benign_absence(msg):
        return True, "Device already unmounted."
    prefix = "udisksctl force unmount failed" if force else "udisksctl unmount failed"
    return False, msg or f"{prefix}."


def _run_udisks_poweroff(parent: str) -> tuple[bool, str]:
    ok, msg = _run_command(
        [
            "udisksctl", "power-off",
            "--block-device", parent,
            "--no-user-interaction",
        ]
    )
    if ok:
        return True, f"Ejected {parent}"
    if _is_benign_absence(msg):
        return True, f"Device already detached: {parent}"
    return False, msg or "udisksctl power-off failed."


def _run_eject_command(target: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["eject", target],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECS,
        )
    except subprocess.TimeoutExpired:
        return False, "eject timed out."

    if proc.returncode == 0:
        return True, f"Ejected {target}"
    err = (proc.stderr or proc.stdout).strip()
    return False, err or "eject failed."


def _run_umount_command(target: str, mode: str = "normal") -> tuple[bool, str, bool]:
    args = ["umount"]
    label = "umount"
    if mode == "force":
        args.append("-f")
        label = "force umount"
    elif mode == "lazy":
        args.append("-l")
        label = "lazy umount"
    elif mode == "force_lazy":
        args.append("-fl")
        label = "force/lazy umount"
    args.append(target)

    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECS,
        )
    except subprocess.TimeoutExpired:
        return False, f"{label} timed out.", False

    if proc.returncode == 0:
        return True, f"{label} succeeded for {target}", False

    err = (proc.stderr or proc.stdout).strip()
    if _is_benign_absence(err):
        return False, err or "Device already unmounted.", True
    return False, err or f"{label} failed.", False


def _detach_linux_after_unmount(detach_target: str | None) -> str:
    if not detach_target:
        return ""

    if shutil.which("udisksctl"):
        ok, msg = _run_udisks_poweroff(detach_target)
        if ok or _is_benign_absence(msg):
            return msg
        logger.debug("udisksctl power-off after umount failed: %s", msg)

    if shutil.which("eject"):
        ok, msg = _run_eject_command(detach_target)
        if ok or _is_benign_absence(msg):
            return msg
        logger.debug("eject after umount failed: %s", msg)

    return ""


def _wait_for_linux_mount_gone(mount_path: str, device: str | None = None) -> bool:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not _linux_path_is_mounted(mount_path, device):
            return True
        time.sleep(0.25)
    return not _linux_path_is_mounted(mount_path, device)


def _linux_path_is_mounted(mount_path: str, device: str | None = None) -> bool:
    wanted_mount = _normalize_posix_path(mount_path)
    wanted_device = device or ""

    for dev, mp in _linux_mount_entries():
        if wanted_device and dev == wanted_device:
            return True
        normalized_mp = _normalize_posix_path(mp)
        if wanted_mount == normalized_mp:
            return True
        if (
            normalized_mp != "/"
            and wanted_mount.startswith(normalized_mp.rstrip("/") + "/")
            and dev.startswith("/dev/")
        ):
            if not wanted_device or dev == wanted_device:
                return True
    return False


def _linux_mount_entries() -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    entries.append((parts[0], _decode_mount_field(parts[1])))
    except OSError:
        pass
    return entries


def _run_sync() -> None:
    if not shutil.which("sync"):
        return
    try:
        subprocess.run(
            ["sync"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _run_command(args: list[str], timeout: int = _TIMEOUT_SECS) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return False, f"{args[0]} is not available."
    except subprocess.TimeoutExpired:
        return False, f"{' '.join(args)} timed out."

    output = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode == 0:
        return True, output or f"{' '.join(args)} succeeded."
    return False, output or f"{' '.join(args)} failed with code {proc.returncode}."


def _join_unique_messages(messages: list[str]) -> str:
    unique: list[str] = []
    for msg in messages:
        msg = (msg or "").strip()
        if msg and msg not in unique:
            unique.append(msg)
    return " | ".join(unique)


def _normalize_posix_path(path: str) -> str:
    try:
        return str(Path(path).resolve(strict=False))
    except OSError:
        return path.rstrip("/") or "/"


def _decode_mount_field(field: str) -> str:
    """Decode octal escapes from ``/proc/mounts`` mountpoint fields."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def _is_benign_absence(message: str) -> bool:
    lower = message.lower()
    return any(hint in lower for hint in _ALREADY_UNMOUNTED_HINTS + _MISSING_TARGET_HINTS)


def _parent_block_device(device: str) -> str | None:
    """Given ``/dev/sdb1`` return ``/dev/sdb`` (``nvme0n1p1`` → ``nvme0n1``)."""
    name = device.rsplit("/", 1)[-1]
    m = re.match(r"^(nvme\d+n\d+)p\d+$", name)
    if m:
        return "/dev/" + m.group(1)
    m = re.match(r"^(mmcblk\d+)p\d+$", name)
    if m:
        return "/dev/" + m.group(1)
    m = re.match(r"^([a-z]+)\d+$", name)
    if m:
        return "/dev/" + m.group(1)
    return None
