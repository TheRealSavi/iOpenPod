"""
Auto-updater for iOpenPod.

Checks GitHub Releases for newer versions and downloads platform-specific
binaries.  Designed to work both from PyInstaller bundles and ``uv run``.

Usage from the GUI (non-blocking):

    from iopenpod.gui.auto_updater import UpdateChecker
    checker = UpdateChecker()
    checker.result_ready.connect(on_result)
    checker.start()               # runs in a background thread
    # on_result receives an UpdateResult

Manual check (blocking):

    from iopenpod.gui.auto_updater import check_for_update
    result = check_for_update()   # blocks until HTTP completes
"""

import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

GITHUB_REPO = "TheRealSavi/iOpenPod"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

_DOWNLOAD_TEMP_PREFIX = "iopenpod-update-"
_STAGING_TEMP_PREFIX = "iopenpod-staging-"
_WINDOWS_PAYLOAD_ENTRIES = frozenset({"iOpenPod.exe", "_internal"})
_LINUX_PAYLOAD_ENTRIES = frozenset({"iOpenPod", "_internal"})


# ── Data types ──────────────────────────────────────────────────────────────


@dataclass
class UpdateResult:
    """Result of an update check."""
    update_available: bool = False
    current_version: str = ""
    latest_version: str = ""
    download_url: str = ""
    release_notes: str = ""
    release_page: str = ""
    error: str = ""


@dataclass(frozen=True)
class InstallMethod:
    """How the running copy of iOpenPod appears to be installed."""

    kind: str
    label: str
    detail: str


@dataclass(frozen=True)
class UpdateGuidance:
    """User-facing update guidance for a specific install method."""

    install_label: str
    summary: str
    steps: tuple[str, ...]
    commands: tuple[str, ...] = ()
    can_auto_install: bool = False
    auto_install_label: str = "Download and Install"
    release_asset_hint: str = ""


# ── HTTP helpers ────────────────────────────────────────────────────────────


def _get_json(url: str) -> dict:
    """Fetch a URL and parse the response as JSON."""
    req = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "iOpenPod-Updater",
    })
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


# ── Platform matching ───────────────────────────────────────────────────────


def _platform_asset_pattern() -> re.Pattern:
    """Return a regex that matches the release asset for this platform."""
    system = sys.platform

    if system == "win32":
        return re.compile(r"iOpenPod-Windows\.zip$", re.I)
    elif system == "darwin":
        return re.compile(r"iOpenPod-macOS\.zip$", re.I)
    else:
        return re.compile(r"iOpenPod-Linux\.tar\.gz$", re.I)


# ── Core logic ──────────────────────────────────────────────────────────────


def _current_version() -> str:
    """Get the running version string."""
    from iopenpod.infrastructure.version import get_version
    return get_version()


def _normalised_path_text(*paths: Path | str) -> str:
    return " ".join(str(path).replace("\\", "/").lower() for path in paths)


def _looks_like_source_checkout(cwd: Path) -> bool:
    pyproject = cwd / "pyproject.toml"
    try:
        pyproject_text = pyproject.read_text(encoding="utf-8").lower()
    except OSError:
        pyproject_text = ""

    return (
        (cwd / "src" / "iopenpod" / "__main__.py").exists()
        and pyproject.exists()
        and 'name = "iopenpod"' in pyproject_text
    )


def detect_install_method(
    *,
    platform: str = sys.platform,
    frozen: bool | None = None,
    executable: Path | None = None,
    prefix: Path | None = None,
    base_prefix: Path | None = None,
    cwd: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> InstallMethod:
    """Infer the install method so update instructions can be specific."""

    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    executable = Path(sys.executable) if executable is None else executable
    prefix = Path(sys.prefix) if prefix is None else prefix
    base_prefix = (
        Path(getattr(sys, "base_prefix", sys.prefix))
        if base_prefix is None
        else base_prefix
    )
    cwd = Path.cwd() if cwd is None else cwd
    env = os.environ if environ is None else environ

    if frozen:
        if platform == "linux" and env.get("APPIMAGE"):
            return InstallMethod(
                "native_appimage",
                "Linux AppImage",
                "Replace the AppImage file with the new release asset.",
            )
        if platform == "darwin":
            return InstallMethod(
                "native_macos_app",
                "macOS app",
                "Use the built-in updater or download the latest macOS zip.",
            )
        if platform == "win32":
            return InstallMethod(
                "native_windows",
                "Windows native build",
                "Use the built-in updater or download the latest Windows zip.",
            )
        if platform == "linux":
            return InstallMethod(
                "native_linux_archive",
                "Linux native archive",
                "Use the built-in updater for extracted release folders.",
            )
        return InstallMethod(
            "native_binary",
            "Native build",
            "Use the matching release asset for your platform.",
        )

    path_text = _normalised_path_text(executable, prefix)
    if "/uv/tools/iopenpod/" in path_text or "/uv/tools/iopenpod" in path_text:
        return InstallMethod(
            "uv_tool",
            "uv tool install",
            "Update iOpenPod with uv from a terminal.",
        )
    if "/pipx/venvs/iopenpod/" in path_text or "/pipx/venvs/iopenpod" in path_text:
        return InstallMethod(
            "pipx",
            "pipx",
            "Update iOpenPod with pipx from a terminal.",
        )
    if _looks_like_source_checkout(cwd):
        return InstallMethod(
            "source_checkout",
            "Source checkout",
            "Pull the latest source and sync the development environment.",
        )
    if prefix != base_prefix:
        return InstallMethod(
            "pip_virtualenv",
            "Python virtual environment",
            "Upgrade iOpenPod inside the same virtual environment.",
        )

    return InstallMethod(
        "pip",
        "Python package",
        "Upgrade iOpenPod with the Python that launched the app.",
    )


def _release_asset_hint(platform: str, method: InstallMethod) -> str:
    if method.kind == "native_appimage":
        return "iOpenPod-Linux-x86_64.AppImage"
    if platform == "win32":
        return "iOpenPod-Windows.zip"
    if platform == "darwin":
        return "iOpenPod-macOS.zip"
    if platform == "linux":
        return "iOpenPod-Linux.tar.gz"
    return "the matching iOpenPod release asset"


def build_update_guidance(
    result: UpdateResult,
    *,
    method: InstallMethod | None = None,
    platform: str = sys.platform,
) -> UpdateGuidance:
    """Build clear update instructions for the detected install method."""

    method = detect_install_method(platform=platform) if method is None else method
    asset_hint = _release_asset_hint(platform, method)

    if method.kind == "uv_tool":
        return UpdateGuidance(
            method.label,
            "This copy is managed by uv. Use uv to upgrade it so the tool "
            "environment stays consistent.",
            (
                "Close iOpenPod.",
                "Open a terminal.",
                "Run the command below, then start iOpenPod again.",
            ),
            commands=("uv tool upgrade iopenpod", "iopenpod"),
            release_asset_hint=asset_hint,
        )

    if method.kind == "pipx":
        return UpdateGuidance(
            method.label,
            "This copy is managed by pipx. Use pipx to upgrade the isolated "
            "app environment.",
            (
                "Close iOpenPod.",
                "Open a terminal.",
                "Run the command below, then start iOpenPod again.",
            ),
            commands=("pipx upgrade iopenpod", "iopenpod"),
            release_asset_hint=asset_hint,
        )

    if method.kind == "source_checkout":
        return UpdateGuidance(
            method.label,
            "This copy is running from a local checkout. Pull the repo and "
            "resync dependencies.",
            (
                "Close iOpenPod.",
                "Open a terminal in the iOpenPod repo.",
                "Run the commands below.",
            ),
            commands=("git pull", "uv sync", "uv run iopenpod"),
            release_asset_hint=asset_hint,
        )

    if method.kind == "pip_virtualenv":
        return UpdateGuidance(
            method.label,
            "This copy is running inside a Python virtual environment. "
            "Upgrade it in that same environment.",
            (
                "Close iOpenPod.",
                "Activate the virtual environment you used to install iOpenPod.",
                "Run the command below, then start iOpenPod again.",
            ),
            commands=("python -m pip install --upgrade iopenpod", "iopenpod"),
            release_asset_hint=asset_hint,
        )

    if method.kind == "pip":
        return UpdateGuidance(
            method.label,
            "This copy was launched as a Python package. Upgrade it with the "
            "same Python install.",
            (
                "Close iOpenPod.",
                "Open a terminal.",
                "Run the command below, then start iOpenPod again.",
            ),
            commands=("python -m pip install --upgrade iopenpod", "iopenpod"),
            release_asset_hint=asset_hint,
        )

    if method.kind == "native_appimage":
        return UpdateGuidance(
            method.label,
            "This copy is running from an AppImage. Replace the AppImage file "
            "with the latest one from GitHub.",
            (
                f"Download {asset_hint} from the release page.",
                "Move it to the folder where you keep iOpenPod.",
                "Make it executable, then launch the new AppImage.",
            ),
            commands=(
                "chmod +x iOpenPod-Linux-x86_64.AppImage",
                "./iOpenPod-Linux-x86_64.AppImage",
            ),
            can_auto_install=False,
            release_asset_hint=asset_hint,
        )

    can_auto_install = bool(result.download_url)
    steps = (
        "Use Download and Install to fetch the matching release asset.",
        "iOpenPod will close, apply the update, and relaunch.",
        "If that fails, open the release page and download the asset manually.",
    )
    if not can_auto_install:
        steps = (
            f"Open the release page and download {asset_hint}.",
            "Close iOpenPod.",
            "Replace the old app files with the new release.",
        )

    return UpdateGuidance(
        method.label,
        method.detail,
        steps,
        can_auto_install=can_auto_install,
        release_asset_hint=asset_hint,
    )


def check_for_update() -> UpdateResult:
    """Check GitHub for a newer release. Blocks until HTTP completes."""
    result = UpdateResult(current_version=_current_version())

    try:
        data = _get_json(GITHUB_API)
    except (URLError, OSError, json.JSONDecodeError) as exc:
        result.error = f"Could not reach GitHub: {exc}"
        logger.warning("Update check failed: %s", exc)
        return result

    tag = data.get("tag_name", "")
    result.release_page = data.get("html_url", RELEASES_URL)
    result.release_notes = data.get("body", "")[:2000]

    # Normalise version: strip leading 'v'
    remote_ver = tag.lstrip("vV")
    result.latest_version = remote_ver

    try:
        if Version(remote_ver) <= Version(result.current_version):
            return result  # up-to-date
    except InvalidVersion:
        result.error = f"Could not parse remote version: {tag}"
        return result

    # Newer version exists — find the matching asset
    pattern = _platform_asset_pattern()
    for asset in data.get("assets", []):
        name = asset.get("name", "")
        if pattern.search(name):
            result.download_url = asset.get("browser_download_url", "")
            break

    result.update_available = True
    return result


def download_update(
    url: str,
    dest_dir: Path | None = None,
    progress_callback=None,
) -> Path | None:
    """Download the release archive to *dest_dir* (default: temp dir).

    *progress_callback(bytes_downloaded, total_bytes)* is called periodically.

    Returns the path to the downloaded file, or ``None`` on failure.
    """
    if dest_dir is None:
        dest_dir = Path(tempfile.mkdtemp(prefix=_DOWNLOAD_TEMP_PREFIX))
    dest_dir.mkdir(parents=True, exist_ok=True)

    filename = Path(urlparse(url).path).name
    if not filename or filename in {".", ".."}:
        logger.error("Update URL has no usable archive filename: %s", url)
        return None
    dest = dest_dir / filename
    logger.info("Downloading update: %s → %s", url, dest)

    created_dest = False
    try:
        req = Request(url, headers={"User-Agent": "iOpenPod-Updater"})
        with urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            # Do not overwrite an existing file supplied by the caller.  The
            # normal destination is a new private temporary directory, but an
            # update failure must never remove or replace an unrelated file.
            with open(dest, "xb") as f:
                created_dest = True
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total:
                        progress_callback(downloaded, total)
        logger.info("Download complete: %s (%d bytes)", dest, downloaded)
        return dest
    except (URLError, OSError) as exc:
        logger.error("Download failed: %s", exc)
        if created_dest:
            dest.unlink()
        return None


def verify_checksum(archive_path: Path, checksum_url: str) -> bool:
    """Download the .sha256 file and verify *archive_path* against it."""
    try:
        req = Request(checksum_url, headers={"User-Agent": "iOpenPod-Updater"})
        with urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8").strip()
        expected_hash = text.split()[0].lower()
    except (URLError, OSError) as exc:
        logger.warning("Could not fetch checksum: %s", exc)
        return False

    # Stream the file through hashlib to avoid loading entire archive into memory
    hasher = hashlib.sha256()
    try:
        with open(archive_path, "rb") as f:
            while True:
                chunk = f.read(256 * 1024)  # 256 KB chunks
                if not chunk:
                    break
                hasher.update(chunk)
        actual_hash = hasher.hexdigest().lower()
    except OSError as exc:
        logger.error("Failed to read archive for checksum: %s", exc)
        return False
    ok = actual_hash == expected_hash
    if not ok:
        logger.error(
            "Checksum mismatch: expected %s, got %s", expected_hash, actual_hash
        )
    return ok


# ── Update staging (extract to a staging directory) ─────────────────────────


def _validate_archive_member_path(name: str) -> None:
    """Reject archive members that could escape the updater staging directory."""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"unsafe archive member path: {name!r}")


def _is_symlink_or_junction(path: Path) -> bool:
    """Return whether *path* is a link/reparse point rather than real content."""
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _validate_staged_payload(staged_dir: Path, platform: str) -> None:
    """Ensure the extracted payload has the expected, narrowly scoped layout.

    The bootstrapper treats the archive as executable code.  Checking its layout
    before it is launched prevents a malformed archive from being overlaid onto
    an installation directory with arbitrary top-level files.
    """
    if not staged_dir.is_dir() or _is_symlink_or_junction(staged_dir):
        raise ValueError("staged update directory is missing or is a link")

    entries = {entry.name: entry for entry in staged_dir.iterdir()}
    if platform == "win32":
        if set(entries) != _WINDOWS_PAYLOAD_ENTRIES:
            raise ValueError("Windows update must contain only iOpenPod.exe and _internal")
        executable = entries["iOpenPod.exe"]
        internal = entries["_internal"]
    elif platform == "darwin":
        if staged_dir.name != "iOpenPod.app":
            raise ValueError("macOS update must contain an iOpenPod.app bundle")
        executable = staged_dir / "Contents" / "MacOS" / "iOpenPod"
        if not executable.is_file() or _is_symlink_or_junction(executable):
            raise ValueError("macOS update is missing its iOpenPod executable")
        return
    else:
        if set(entries) != _LINUX_PAYLOAD_ENTRIES:
            raise ValueError("Linux update must contain only iOpenPod and _internal")
        executable = entries["iOpenPod"]
        internal = entries["_internal"]

    if not executable.is_file() or _is_symlink_or_junction(executable):
        raise ValueError("staged update is missing a regular iOpenPod executable")
    if not internal.is_dir() or _is_symlink_or_junction(internal):
        raise ValueError("staged update is missing a regular _internal directory")


def stage_update(archive_path: Path, *, platform: str = sys.platform) -> Path | None:
    """Extract the archive into a staging directory.

    Returns the path to the staging directory containing the extracted
    update, or ``None`` on failure.  The caller is responsible for
    launching the bootstrap installer and exiting.
    """
    import tarfile
    import zipfile

    staging = Path(tempfile.mkdtemp(prefix=_STAGING_TEMP_PREFIX))

    try:
        if archive_path.suffix == ".zip":
            with zipfile.ZipFile(archive_path) as zf:
                for info in zf.infolist():
                    _validate_archive_member_path(info.filename)
                zf.extractall(staging)
        elif archive_path.name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive_path) as tf:
                for member in tf.getmembers():
                    _validate_archive_member_path(member.name)
                tf.extractall(staging, filter='data')
        else:
            raise ValueError(f"unknown archive format: {archive_path.name}")

        # Determine the actual root of the extracted update.
        # Some archives wrap everything in a single top-level folder
        # (e.g. macOS: iOpenPod.app/, Linux: iOpenPod/), while others
        # have files directly at the root (e.g. Windows zip created
        # with Compress-Archive -Path dist\iOpenPod\*).
        # ditto-created macOS archives can include an __MACOSX metadata
        # directory.  It is never part of the payload and is not copied.
        entries = [entry for entry in staging.iterdir() if entry.name != "__MACOSX"]
        if len(entries) == 1 and entries[0].is_dir():
            # Single top-level folder — use it as the source
            source_dir = entries[0]
        else:
            # Multiple entries at root — staging IS the source
            source_dir = staging

        _validate_staged_payload(source_dir, platform)
        logger.info("Update staged at %s", source_dir)
        return source_dir

    except Exception as exc:
        logger.error("Failed to stage update: %s", exc)
        shutil.rmtree(staging, ignore_errors=True)
        return None


# ── Bootstrap installer (runs after the app exits) ─────────────────────────
#
# On Windows, a running .exe and its DLLs are locked by the OS — you can't
# overwrite or rename them from inside the same process.  A small bootstrap
# script waits for the app to exit, replaces only the known runtime payload,
# and relaunches it.  On macOS/Linux the same approach is used for a
# consistent restart, but the staged files are overlaid without ever removing
# the installed app directory or bundle.


def _new_bootstrap_path(suffix: str) -> Path:
    """Create an owner-only, uniquely named temporary bootstrap file."""
    fd, raw_path = tempfile.mkstemp(prefix="iopenpod-bootstrap-", suffix=suffix)
    os.close(fd)
    return Path(raw_path)


def _staging_root_for(staged_dir: Path) -> Path:
    """Return the updater-owned staging root containing *staged_dir*.

    Bootstrap scripts are intentionally allowed to remove their own staging
    directory.  This check makes that permission explicit: callers cannot
    point cleanup at an arbitrary directory merely by supplying a path.
    """
    source = staged_dir.resolve(strict=True)
    temp_dir = Path(tempfile.gettempdir()).resolve()

    for candidate in (source, *source.parents):
        if candidate.parent == temp_dir and candidate.name.startswith(_STAGING_TEMP_PREFIX):
            return candidate
    raise ValueError("staged update is not in an updater-owned temporary directory")


def _cmd_safe_path(path: Path) -> str:
    """Return a path safe for use in a generated cmd.exe script.

    Quoting alone does not make all cmd metacharacters safe (notably percent
    expansion and delayed expansion), so a native update declines to run from
    a path containing one.  The user can still update manually in that rare
    case; the updater must not turn a path into a command.
    """
    text = str(path)
    if any(character in text for character in '"&|<>()^%!\r\n'):
        raise ValueError("update path contains cmd.exe metacharacters")
    return text


def _write_windows_bootstrap(
    pid: int,
    app_dir: Path,
    staged_dir: Path,
    exe_name: str,
) -> Path:
    """Write a .cmd script that replaces only the Windows runtime payload."""
    # Write to temp dir — app_dir.parent may be read-only (Program Files, etc.)
    script = _new_bootstrap_path(".cmd")
    log_file = Path(tempfile.gettempdir()) / "_iopenpod_update.log"
    staging_root = _staging_root_for(staged_dir)
    app_executable = app_dir / exe_name
    app_internal = app_dir / "_internal"
    staged_executable = staged_dir / exe_name

    app_dir_text = _cmd_safe_path(app_dir)
    staged_dir_text = _cmd_safe_path(staged_dir)
    staging_root_text = _cmd_safe_path(staging_root)
    app_executable_text = _cmd_safe_path(app_executable)
    app_internal_text = _cmd_safe_path(app_internal)
    staged_executable_text = _cmd_safe_path(staged_executable)
    log_file_text = _cmd_safe_path(log_file)

    script.write_text(
        f'@echo off\r\n'
        f'setlocal EnableDelayedExpansion\r\n'
        f'title iOpenPod Updater\r\n'
        f'\r\n'
        f'set "LOG={log_file_text}"\r\n'
        f'set "APP_DIR={app_dir_text}"\r\n'
        f'set "STAGED_DIR={staged_dir_text}"\r\n'
        f'set "STAGING_ROOT={staging_root_text}"\r\n'
        f'set "APP_EXE={app_executable_text}"\r\n'
        f'set "APP_INTERNAL={app_internal_text}"\r\n'
        f'set "STAGED_EXE={staged_executable_text}"\r\n'
        f'echo [%date% %time%] iOpenPod updater starting >> "%LOG%"\r\n'
        f'echo App dir:    %APP_DIR% >> "%LOG%"\r\n'
        f'echo Staged dir: %STAGED_DIR% >> "%LOG%"\r\n'
        f'echo Exe name:   {exe_name} >> "%LOG%"\r\n'
        f'echo PID:        {pid} >> "%LOG%"\r\n'
        f'\r\n'
        f'echo Waiting for iOpenPod to exit...\r\n'
        f':wait\r\n'
        f'tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL\r\n'
        f'if not errorlevel 1 (\r\n'
        f'    ping -n 2 127.0.0.1 >NUL\r\n'
        f'    goto wait\r\n'
        f')\r\n'
        f'echo Process exited. >> "%LOG%"\r\n'
        f'\r\n'
        f'echo Applying update...\r\n'
        f'ping -n 5 127.0.0.1 >NUL\r\n'
        f'\r\n'
        f'if not exist "%STAGED_EXE%" (\r\n'
        f'    echo ERROR: staged executable is missing >> "%LOG%"\r\n'
        f'    exit /b 1\r\n'
        f')\r\n'
        f'\r\n'
        f'rem Remove only the old executable and its PyInstaller _internal\r\n'
        f'rem runtime directory.  Do not mirror the install directory: /MIR\r\n'
        f'rem would remove unrelated files a user keeps beside iOpenPod.\r\n'
        f'if exist "%APP_EXE%" del /f /q "%APP_EXE%"\r\n'
        f'if exist "%APP_EXE%" (\r\n'
        f'    echo ERROR: old executable is still locked >> "%LOG%"\r\n'
        f'    exit /b 1\r\n'
        f')\r\n'
        f'if exist "%APP_INTERNAL%" rmdir /s /q "%APP_INTERNAL%"\r\n'
        f'if exist "%APP_INTERNAL%" (\r\n'
        f'    echo ERROR: old _internal directory could not be removed >> "%LOG%"\r\n'
        f'    exit /b 1\r\n'
        f')\r\n'
        f'\r\n'
        f'rem Robocopy overlays the validated payload.  /E copies directories\r\n'
        f'rem but intentionally does not delete anything at the destination.\r\n'
        f'echo Copying new files over existing install... >> "%LOG%"\r\n'
        f'echo Copying new files...\r\n'
        f'robocopy "%STAGED_DIR%" "%APP_DIR%" /E /COPY:DAT /DCOPY:DAT /R:30 /W:2 /NP /NDL /NFL >> "%LOG%" 2>&1\r\n'
        f'set "RC=!errorlevel!"\r\n'
        f'echo robocopy exit code: !RC! >> "%LOG%"\r\n'
        f'rem Robocopy codes below 8 are successful.\r\n'
        f'if !RC! geq 8 (\r\n'
        f'    echo ERROR: robocopy failed with exit code !RC! >> "%LOG%"\r\n'
        f'    echo ERROR: File copy failed. The update files are at:\r\n'
        f'    echo %STAGED_DIR%\r\n'
        f'    pause\r\n'
        f'    exit /b 1\r\n'
        f')\r\n'
        f'\r\n'
        f'if not exist "%APP_EXE%" (\r\n'
        f'    echo ERROR: updated executable was not installed >> "%LOG%"\r\n'
        f'    exit /b 1\r\n'
        f')\r\n'
        f'\r\n'
        f'echo Starting updated iOpenPod...\r\n'
        f'echo Launching: "%APP_EXE%" >> "%LOG%"\r\n'
        f'start "" "%APP_EXE%"\r\n'
        f'\r\n'
        f'echo Cleaning up...\r\n'
        f'rem STAGING_ROOT was validated as an updater-owned temp directory.\r\n'
        f'rmdir /s /q "%STAGING_ROOT%" 2>NUL\r\n'
        f'echo [%date% %time%] Update complete. >> "%LOG%"\r\n'
        f'ping -n 2 127.0.0.1 >NUL\r\n'
        f'del "%~f0"\r\n',
        encoding="utf-8",
    )
    return script


def _resolve_install_target(executable: Path, platform: str) -> tuple[Path, str]:
    """Return the install directory and relaunch executable for a frozen app."""
    app_dir = executable.parent
    exe_name = executable.name

    if platform == "darwin":
        macos_dir = executable.parent
        contents_dir = macos_dir.parent
        bundle_dir = contents_dir.parent
        if (
            macos_dir.name == "MacOS"
            and contents_dir.name == "Contents"
            and bundle_dir.suffix.lower() == ".app"
        ):
            return bundle_dir, f"Contents/MacOS/{executable.name}"

    return app_dir, exe_name


def _validated_install_target(executable: Path, platform: str) -> tuple[Path, str]:
    """Return a safe native install target or reject an unexpected launcher.

    Auto-update is deliberately limited to the executable layout produced by
    this project's release builds.  In particular, it must not operate on a
    renamed launcher, a symbolic link, or a reparse-point runtime directory.
    Those configurations can still be updated manually.
    """
    expected_name = "iOpenPod.exe" if platform == "win32" else "iOpenPod"
    names_match = (
        executable.name.lower() == expected_name.lower()
        if platform == "win32"
        else executable.name == expected_name
    )
    if not names_match:
        raise ValueError("running executable is not a native iOpenPod release binary")
    if not executable.is_file() or _is_symlink_or_junction(executable):
        raise ValueError("running executable is missing or is a link")

    app_dir, exe_name = _resolve_install_target(executable, platform)
    target_executable = app_dir / exe_name
    if not app_dir.is_dir() or _is_symlink_or_junction(app_dir):
        raise ValueError("native install directory is missing or is a link")
    if not target_executable.is_file() or _is_symlink_or_junction(target_executable):
        raise ValueError("native install executable is missing or is a link")

    # Windows is the sole platform where the updater deliberately removes a
    # directory.  Refuse to delete a junction, which could otherwise point
    # outside the iOpenPod install directory.
    internal = app_dir / "_internal"
    if platform == "win32" and internal.exists() and _is_symlink_or_junction(internal):
        raise ValueError("Windows _internal directory is a link")

    return app_dir, exe_name


def _write_unix_bootstrap(
    pid: int,
    app_dir: Path,
    staged_dir: Path,
    exe_name: str,
    *,
    platform: str = sys.platform,
) -> Path:
    """Write a shell script that overlays the update after we exit."""
    # Write to temp dir — app_dir.parent (e.g. /Applications/) may not be writable.
    script = _new_bootstrap_path(".sh")
    log_file = Path(tempfile.gettempdir()) / "_iopenpod_update.log"
    staging_root = _staging_root_for(staged_dir)
    temp_dir = Path(tempfile.gettempdir()).resolve()

    script_path = shlex.quote(str(script))
    app_dir_path = shlex.quote(str(app_dir))
    staged_dir_path = shlex.quote(str(staged_dir))
    staging_root_path = shlex.quote(str(staging_root))
    temp_dir_path = shlex.quote(str(temp_dir))
    log_file_path = shlex.quote(str(log_file))
    executable_path = shlex.quote(str(app_dir / exe_name))
    cleanup_staging = (
        f'cleanup_staging() {{\n'
        f'    case "$STAGING_ROOT" in\n'
        f'        "$TEMP_DIR"/{_STAGING_TEMP_PREFIX}*) /bin/rm -rf -- "$STAGING_ROOT" ;;\n'
        f'        *) echo "ERROR: refusing to remove non-updater staging directory $STAGING_ROOT"; return 1 ;;\n'
        f'    esac\n'
        f'}}\n'
    )

    if platform == "darwin":
        # The app bundle is overlaid in place.  A separate helper permits the
        # same operation to be retried through macOS's standard admin prompt.
        ops_script = _new_bootstrap_path(".sh")
        ops_script_path = shlex.quote(str(ops_script))
        ops_script.write_text(
            f'#!/bin/sh\n'
            f'LOG={log_file_path}\n'
            f'APP_DIR={app_dir_path}\n'
            f'STAGED_DIR={staged_dir_path}\n'
            f'STAGING_ROOT={staging_root_path}\n'
            f'TEMP_DIR={temp_dir_path}\n'
            f'exec >> "$LOG" 2>&1\n'
            f'echo "Starting file operations..."\n'
            f'if ! /usr/bin/ditto "$STAGED_DIR" "$APP_DIR"; then\n'
            f'    echo "ERROR: ditto failed while overlaying the app bundle"\n'
            f'    exit 1\n'
            f'fi\n'
            f'echo "New app overlaid"\n'
            f'/usr/bin/xattr -dr com.apple.quarantine "$APP_DIR" 2>/dev/null || true\n'
            f'{cleanup_staging}'
            f'echo "File operations complete"\n',
            encoding="utf-8",
        )
        ops_script.chmod(ops_script.stat().st_mode | stat.S_IEXEC)

        apple_script = (
            f"do shell script {json.dumps('/bin/sh ' + shlex.quote(str(ops_script)))} "
            "with administrator privileges"
        )
        apply_block = (
            f'# Try without admin first (works when app is outside /Applications/)\n'
            f'if /bin/sh {ops_script_path}; then\n'
            f'    echo "Updated without elevated privileges"\n'
            f'else\n'
            f'    echo "Retrying with administrator privileges via osascript..."\n'
            f'    if ! /usr/bin/osascript -e {shlex.quote(apple_script)} >> "$LOG" 2>&1; then\n'
            f'        echo "ERROR: osascript elevated install failed"\n'
            f'        exit 1\n'
            f'    fi\n'
            f'fi\n'
        )
        relaunch = '/usr/bin/open "$APP_DIR"\n'
        cleanup = f'/bin/rm -f -- {ops_script_path}\n'
    else:
        apply_block = (
            f'if ! /bin/cp -a "$STAGED_DIR/." "$APP_DIR/"; then\n'
            f'    echo "ERROR: copy failed while overlaying the app files"\n'
            f'    exit 1\n'
            f'fi\n'
            f'echo "New files overlaid"\n'
            f'chmod +x {executable_path}\n'
            f'{cleanup_staging}'
        )
        relaunch = f'{executable_path} &\n'
        cleanup = ''

    script.write_text(
        f'#!/bin/sh\n'
        f'LOG={log_file_path}\n'
        f'APP_DIR={app_dir_path}\n'
        f'STAGED_DIR={staged_dir_path}\n'
        f'STAGING_ROOT={staging_root_path}\n'
        f'TEMP_DIR={temp_dir_path}\n'
        f'exec >> "$LOG" 2>&1\n'
        f'{cleanup_staging}'
        f'echo "=== iOpenPod updater started $(date) ==="\n'
        f'echo "App dir:    $APP_DIR"\n'
        f'echo "Staged dir: $STAGED_DIR"\n'
        f'echo "Exe name:   {exe_name}"\n'
        f'echo "PID:        {pid}"\n'
        f'\n'
        f'echo "Waiting for iOpenPod to exit..."\n'
        f'while kill -0 {pid} 2>/dev/null; do sleep 1; done\n'
        f'echo "Process exited."\n'
        f'sleep 1\n'
        f'\n'
        f'echo "Applying update..."\n'
        f'{apply_block}'
        f'\n'
        f'echo "Restarting iOpenPod..."\n'
        f'{relaunch}'
        f'{cleanup}'
        f'echo "=== Update complete $(date) ==="\n'
        f'/bin/rm -f -- {script_path}\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def update_log_path() -> Path:
    """Return the path to the persistent update log file."""
    return Path(tempfile.gettempdir()) / "_iopenpod_update.log"


def _log_update(msg: str) -> None:
    """Append *msg* (with timestamp) to the update log file."""
    import datetime
    line = f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}\n"
    try:
        with open(update_log_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    logger.info(msg)


def launch_bootstrap_and_exit(staged_dir: Path) -> bool:
    """Spawn the bootstrap script and return True if the app should exit.

    The caller must exit the application after this returns ``True``.
    Returns ``False`` if this is not a frozen build or the bootstrap
    could not be launched.
    """
    _log_update("=== launch_bootstrap_and_exit called ===")
    _log_update(f"sys.frozen={getattr(sys, 'frozen', False)}")
    _log_update(f"sys.executable={sys.executable}")
    _log_update(f"sys.platform={sys.platform}")
    _log_update(f"staged_dir={staged_dir}")

    if not getattr(sys, "frozen", False):
        _log_update("Not a frozen build — bootstrap not applicable.")
        return False

    try:
        _validate_staged_payload(staged_dir, sys.platform)
        app_dir, exe_name = _validated_install_target(Path(sys.executable), sys.platform)
        _staging_root_for(staged_dir)
    except (OSError, ValueError) as exc:
        _log_update(f"Refusing unsafe update target or payload: {exc}")
        logger.error("Refusing unsafe update target or payload: %s", exc)
        return False

    pid = os.getpid()

    try:
        staged_contents = [p.name for p in staged_dir.iterdir()]
        _log_update(f"staged_dir contents: {staged_contents}")
    except Exception as exc:
        _log_update(f"Could not list staged_dir: {exc}")

    _log_update(f"pid={pid}  app_dir={app_dir}  exe_name={exe_name}")

    try:
        if sys.platform == "win32":
            script = _write_windows_bootstrap(pid, app_dir, staged_dir, exe_name)
            _log_update(f"Windows bootstrap script written to: {script}")
            # os.startfile uses ShellExecute — the launched process is
            # completely detached from Python.  Unlike subprocess.Popen,
            # it cannot be killed when the parent process exits.
            # A console window will briefly appear (acceptable).
            os.startfile(str(script))
            _log_update("os.startfile succeeded — app should exit now.")
        else:
            script = _write_unix_bootstrap(pid, app_dir, staged_dir, exe_name)
            _log_update(f"Unix bootstrap script written to: {script}")
            subprocess.Popen(
                ["/bin/sh", str(script)],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _log_update("subprocess.Popen succeeded — app should exit now.")

        return True

    except Exception as exc:
        _log_update(f"ERROR launching bootstrap: {exc}")
        logger.error("Failed to launch bootstrap: %s", exc)
        return False


# ── Qt thread wrapper ───────────────────────────────────────────────────────


class UpdateChecker(QThread):
    """Background thread that checks for updates.

    Emits ``result_ready(UpdateResult)`` when done.
    """

    result_ready = pyqtSignal(object)  # UpdateResult

    def run(self):
        result = check_for_update()
        self.result_ready.emit(result)


class UpdateDownloader(QThread):
    """Background thread that downloads a release asset.

    Emits:
      - ``progress(int, int)`` — bytes downloaded, total bytes
      - ``finished_download(str)`` — path to downloaded file ("" on failure)
    """

    progress = pyqtSignal(int, int)
    finished_download = pyqtSignal(str)

    def __init__(self, download_url: str, checksum_url: str = "", parent=None):
        super().__init__(parent)
        self._url = download_url
        self._checksum_url = checksum_url

    def run(self):
        path = download_update(self._url, progress_callback=self._on_progress)
        if path and self._checksum_url:
            if not verify_checksum(path, self._checksum_url):
                logger.error("Checksum verification failed — discarding download")
                path.unlink(missing_ok=True)
                path = None
        self.finished_download.emit(str(path) if path else "")

    def _on_progress(self, downloaded: int, total: int):
        self.progress.emit(downloaded, total)
