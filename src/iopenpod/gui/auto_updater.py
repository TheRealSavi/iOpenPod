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
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

GITHUB_REPO = "TheRealSavi/iOpenPod"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"


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
        dest_dir = Path(tempfile.mkdtemp(prefix="iopenpod-update-"))
    dest_dir.mkdir(parents=True, exist_ok=True)

    filename = url.rsplit("/", 1)[-1]
    dest = dest_dir / filename
    logger.info("Downloading update: %s → %s", url, dest)

    try:
        req = Request(url, headers={"User-Agent": "iOpenPod-Updater"})
        with urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
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
        if dest.exists():
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


def stage_update(archive_path: Path) -> Path | None:
    """Extract the archive into a staging directory.

    Returns the path to the staging directory containing the extracted
    update, or ``None`` on failure.  The caller is responsible for
    launching the bootstrap installer and exiting.
    """
    import tarfile
    import zipfile

    staging = Path(tempfile.mkdtemp(prefix="iopenpod-staging-"))

    try:
        if archive_path.suffix == ".zip":
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(staging)
        elif archive_path.name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive_path) as tf:
                tf.extractall(staging, filter='data')
        else:
            logger.error("Unknown archive format: %s", archive_path.name)
            return None

        # Determine the actual root of the extracted update.
        # Some archives wrap everything in a single top-level folder
        # (e.g. macOS: iOpenPod.app/, Linux: iOpenPod/), while others
        # have files directly at the root (e.g. Windows zip created
        # with Compress-Archive -Path dist\iOpenPod\*).
        entries = list(staging.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            # Single top-level folder — use it as the source
            source_dir = entries[0]
        else:
            # Multiple entries at root — staging IS the source
            source_dir = staging

        logger.info("Update staged at %s", source_dir)
        return source_dir

    except Exception as exc:
        logger.error("Failed to stage update: %s", exc)
        shutil.rmtree(staging, ignore_errors=True)
        return None


# ── Bootstrap installer (runs after the app exits) ─────────────────────────
#
# On Windows, a running .exe and its DLLs are locked by the OS — you can't
# overwrite or rename them from inside the same process.  The solution is a
# small script that:
#   1. Waits for the current process to exit
#   2. Moves the old install to a .bak directory
#   3. Copies the staged update into the install location
#   4. Relaunches the new executable
#   5. Cleans up the .bak directory and the staging folder
#
# On macOS/Linux a shell script does the same thing (though renaming open
# files would technically work, the script approach is consistent and also
# restarts the app).


def _write_windows_bootstrap(
    pid: int,
    app_dir: Path,
    staged_dir: Path,
    exe_name: str,
) -> Path:
    """Write a .cmd batch script that swaps the update after we exit."""
    # Write to temp dir — app_dir.parent may be read-only (Program Files, etc.)
    script = Path(tempfile.gettempdir()) / "_iopenpod_update.cmd"
    log_file = Path(tempfile.gettempdir()) / "_iopenpod_update.log"

    # staged_dir may be the staging root itself (flat archive) or a
    # subfolder (archive with single top-level dir).  Clean up the
    # staging root in both cases.
    staging_root = staged_dir
    if staged_dir.parent.name.startswith("iopenpod-staging-"):
        staging_root = staged_dir.parent

    script.write_text(
        f'@echo off\r\n'
        f'setlocal EnableDelayedExpansion\r\n'
        f'title iOpenPod Updater\r\n'
        f'\r\n'
        f'set "LOG={log_file}"\r\n'
        f'echo [%date% %time%] iOpenPod updater starting >> "%LOG%"\r\n'
        f'echo App dir:    {app_dir} >> "%LOG%"\r\n'
        f'echo Staged dir: {staged_dir} >> "%LOG%"\r\n'
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
        f'rem Use robocopy to mirror staged files over the install dir.\r\n'
        f'rem Robocopy retries locked files individually (unlike move which\r\n'
        f'rem fails if ANY file is locked). /MIR = mirror, /R:30 = 30 retries,\r\n'
        f'rem /W:2 = 2 sec between retries, /NP = no progress percentage.\r\n'
        f'echo Copying new files over existing install... >> "%LOG%"\r\n'
        f'echo Copying new files...\r\n'
        f'robocopy "{staged_dir}" "{app_dir}" /MIR /R:30 /W:2 /NP /NDL /NFL >> "%LOG%" 2>&1\r\n'
        f'set "RC=!errorlevel!"\r\n'
        f'echo robocopy exit code: !RC! >> "%LOG%"\r\n'
        f'rem robocopy: 0=nothing copied, 1=files copied, 2=extra files removed,\r\n'
        f'rem 3=1+2, etc.  Codes < 8 are success. 8+ means error.\r\n'
        f'if !RC! geq 8 (\r\n'
        f'    echo ERROR: robocopy failed with exit code !RC! >> "%LOG%"\r\n'
        f'    echo ERROR: File copy failed. The update files are at:\r\n'
        f'    echo {staged_dir}\r\n'
        f'    pause\r\n'
        f'    exit /b 1\r\n'
        f')\r\n'
        f'\r\n'
        f'echo Starting updated iOpenPod...\r\n'
        f'echo Launching: "{app_dir}\\{exe_name}" >> "%LOG%"\r\n'
        f'start "" "{app_dir}\\{exe_name}"\r\n'
        f'\r\n'
        f'echo Cleaning up...\r\n'
        f'rmdir /s /q "{staging_root}" 2>NUL\r\n'
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


def _write_unix_bootstrap(
    pid: int,
    app_dir: Path,
    staged_dir: Path,
    exe_name: str,
) -> Path:
    """Write a shell script that swaps the update after we exit."""
    # Write to temp dir — app_dir.parent (e.g. /Applications/) may not be writable
    script = Path(tempfile.gettempdir()) / "_iopenpod_update.sh"
    log_file = Path(tempfile.gettempdir()) / "_iopenpod_update.log"

    is_macos = sys.platform == "darwin"

    if is_macos:
        # On macOS, put the actual file operations in a separate helper script.
        # The bootstrap then tries running it directly; if that fails (e.g. the
        # app is in /Applications/ which is root-owned), it retries via osascript
        # which shows macOS's standard admin password dialog.
        ops_script = Path(tempfile.gettempdir()) / "_iopenpod_update_ops.sh"
        ops_script.write_text(
            f'#!/bin/sh\n'
            f'LOG="{log_file}"\n'
            f'exec >> "$LOG" 2>&1\n'
            f'echo "Starting file operations..."\n'
            f'rm -rf "{app_dir}.bak"\n'
            f'if ! mv "{app_dir}" "{app_dir}.bak"; then\n'
            f'    echo "ERROR: mv failed — cannot move old app aside"\n'
            f'    exit 1\n'
            f'fi\n'
            f'echo "Old app moved to .bak"\n'
            f'if ! ditto "{staged_dir}" "{app_dir}"; then\n'
            f'    echo "ERROR: ditto failed — restoring backup"\n'
            f'    mv "{app_dir}.bak" "{app_dir}"\n'
            f'    exit 1\n'
            f'fi\n'
            f'echo "New app copied"\n'
            f'xattr -dr com.apple.quarantine "{app_dir}" 2>/dev/null\n'
            f'chmod -R +x "{app_dir}/Contents/MacOS" 2>/dev/null\n'
            f'rm -rf "{app_dir}.bak"\n'
            f'rm -rf "{staged_dir.parent}"\n'
            f'echo "File operations complete"\n',
            encoding="utf-8",
        )
        ops_script.chmod(ops_script.stat().st_mode | stat.S_IEXEC)

        # Build the osascript fallback.  The ops script path is embedded as a
        # double-quoted shell word inside the AppleScript string literal, so
        # inner double-quotes must be escaped with \".
        ops_escaped = str(ops_script).replace('"', '\\"')
        apply_block = (
            f'# Try without admin first (works when app is outside /Applications/)\n'
            f'if /bin/sh "{ops_script}"; then\n'
            f'    echo "Updated without elevated privileges"\n'
            f'else\n'
            f'    echo "Retrying with administrator privileges via osascript..."\n'
            f'    osascript -e \'do shell script "/bin/sh \\"{ops_escaped}\\"" with administrator privileges\' >> "$LOG" 2>&1\n'
            f'    if [ $? -ne 0 ]; then\n'
            f'        echo "ERROR: osascript elevated install failed"\n'
            f'        exit 1\n'
            f'    fi\n'
            f'fi\n'
        )
        relaunch = f'open -a "{app_dir}"\n'
        cleanup = f'rm -f "{ops_script}"\n'

    else:
        apply_block = (
            f'rm -rf "{app_dir}.bak"\n'
            f'if ! mv "{app_dir}" "{app_dir}.bak"; then\n'
            f'    echo "ERROR: mv failed — cannot move old app aside"\n'
            f'    exit 1\n'
            f'fi\n'
            f'echo "Old app moved to .bak"\n'
            f'if ! cp -a "{staged_dir}/." "{app_dir}/"; then\n'
            f'    echo "ERROR: copy failed — restoring backup"\n'
            f'    mv "{app_dir}.bak" "{app_dir}"\n'
            f'    exit 1\n'
            f'fi\n'
            f'echo "New files copied"\n'
            f'chmod +x "{app_dir}/{exe_name}"\n'
            f'rm -rf "{app_dir}.bak"\n'
            f'rm -rf "{staged_dir.parent}"\n'
        )
        relaunch = f'"{app_dir}/{exe_name}" &\n'
        cleanup = ''

    script.write_text(
        f'#!/bin/sh\n'
        f'LOG="{log_file}"\n'
        f'exec >> "$LOG" 2>&1\n'
        f'echo "=== iOpenPod updater started $(date) ==="\n'
        f'echo "App dir:    {app_dir}"\n'
        f'echo "Staged dir: {staged_dir}"\n'
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
        f'rm -f "$0"\n',
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

    pid = os.getpid()
    app_dir, exe_name = _resolve_install_target(Path(sys.executable), sys.platform)

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
