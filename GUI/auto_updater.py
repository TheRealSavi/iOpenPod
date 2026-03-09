"""
Auto-updater for iOpenPod.

Checks GitHub Releases for newer versions and downloads platform-specific
binaries.  Designed to work both from PyInstaller bundles and ``uv run``.

Usage from the GUI (non-blocking):

    from GUI.auto_updater import UpdateChecker
    checker = UpdateChecker()
    checker.result_ready.connect(on_result)
    checker.start()               # runs in a background thread
    # on_result receives an UpdateResult

Manual check (blocking):

    from GUI.auto_updater import check_for_update
    result = check_for_update()   # blocks until HTTP completes
"""

import hashlib
import json
import logging
import os
import platform
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from packaging.version import Version, InvalidVersion

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


# ── SSL / HTTP helpers ──────────────────────────────────────────────────────


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _get_json(url: str) -> dict:
    """Fetch a URL and parse the response as JSON."""
    req = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "iOpenPod-Updater",
    })
    with urlopen(req, timeout=15, context=_ssl_context()) as resp:
        return json.loads(resp.read())


# ── Platform matching ───────────────────────────────────────────────────────


def _platform_asset_pattern() -> re.Pattern:
    """Return a regex that matches the release asset for this platform."""
    system = sys.platform
    machine = platform.machine().lower()

    if system == "win32":
        return re.compile(r"iOpenPod-Windows\.zip$", re.I)
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            return re.compile(r"iOpenPod-macOS-AppleSilicon\.zip$", re.I)
        return re.compile(r"iOpenPod-macOS-Intel\.zip$", re.I)
    else:
        return re.compile(r"iOpenPod-Linux\.tar\.gz$", re.I)


# ── Core logic ──────────────────────────────────────────────────────────────


def _current_version() -> str:
    """Get the running version string."""
    from GUI.settings import get_version
    return get_version()


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
    dest_dir: Optional[Path] = None,
    progress_callback=None,
) -> Optional[Path]:
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
        with urlopen(req, timeout=300, context=_ssl_context()) as resp:
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
        with urlopen(req, timeout=15, context=_ssl_context()) as resp:
            text = resp.read().decode("utf-8").strip()
        expected_hash = text.split()[0].lower()
    except (URLError, OSError) as exc:
        logger.warning("Could not fetch checksum: %s", exc)
        return False

    actual_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest().lower()
    ok = actual_hash == expected_hash
    if not ok:
        logger.error(
            "Checksum mismatch: expected %s, got %s", expected_hash, actual_hash
        )
    return ok


# ── Update staging (extract to a staging directory) ─────────────────────────


def stage_update(archive_path: Path) -> Optional[Path]:
    """Extract the archive into a staging directory.

    Returns the path to the staging directory containing the extracted
    update, or ``None`` on failure.  The caller is responsible for
    launching the bootstrap installer and exiting.
    """
    import zipfile
    import tarfile

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

        # The archive contains an iOpenPod/ folder at the top level
        extracted_dirs = [d for d in staging.iterdir() if d.is_dir()]
        source_dir = extracted_dirs[0] if extracted_dirs else staging

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
    script = app_dir.parent / "_iopenpod_update.cmd"
    # Use robocopy for a reliable mirror that handles long paths
    script.write_text(
        f'@echo off\r\n'
        f'echo Waiting for iOpenPod to exit...\r\n'
        f':wait\r\n'
        f'tasklist /FI "PID eq {pid}" 2>NUL | find /I "{pid}" >NUL\r\n'
        f'if not errorlevel 1 (\r\n'
        f'    timeout /t 1 /nobreak >NUL\r\n'
        f'    goto wait\r\n'
        f')\r\n'
        f'echo Applying update...\r\n'
        f'if exist "{app_dir}.bak" rmdir /s /q "{app_dir}.bak"\r\n'
        f'move "{app_dir}" "{app_dir}.bak"\r\n'
        f'if errorlevel 1 (\r\n'
        f'    echo ERROR: Could not move old version aside.\r\n'
        f'    pause\r\n'
        f'    exit /b 1\r\n'
        f')\r\n'
        f'xcopy "{staged_dir}\\*" "{app_dir}\\" /E /I /Q /Y >NUL\r\n'
        f'echo Restarting iOpenPod...\r\n'
        f'start "" "{app_dir}\\{exe_name}"\r\n'
        f'echo Cleaning up...\r\n'
        f'rmdir /s /q "{app_dir}.bak" 2>NUL\r\n'
        f'rmdir /s /q "{staged_dir.parent}" 2>NUL\r\n'
        f'del "%~f0"\r\n',
        encoding="utf-8",
    )
    return script


def _write_unix_bootstrap(
    pid: int,
    app_dir: Path,
    staged_dir: Path,
    exe_name: str,
) -> Path:
    """Write a shell script that swaps the update after we exit."""
    script = app_dir.parent / "_iopenpod_update.sh"
    script.write_text(
        f'#!/bin/sh\n'
        f'echo "Waiting for iOpenPod to exit..."\n'
        f'while kill -0 {pid} 2>/dev/null; do sleep 1; done\n'
        f'echo "Applying update..."\n'
        f'rm -rf "{app_dir}.bak"\n'
        f'mv "{app_dir}" "{app_dir}.bak"\n'
        f'cp -R "{staged_dir}" "{app_dir}"\n'
        f'chmod +x "{app_dir}/{exe_name}"\n'
        f'echo "Restarting iOpenPod..."\n'
        f'"{app_dir}/{exe_name}" &\n'
        f'rm -rf "{app_dir}.bak"\n'
        f'rm -rf "{staged_dir.parent}"\n'
        f'rm -f "$0"\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def launch_bootstrap_and_exit(staged_dir: Path) -> bool:
    """Spawn the bootstrap script and return True if the app should exit.

    The caller must exit the application after this returns ``True``.
    Returns ``False`` if this is not a frozen build or the bootstrap
    could not be launched.
    """
    if not getattr(sys, "frozen", False):
        logger.info("Not a frozen build; bootstrap not applicable.")
        return False

    pid = os.getpid()
    app_dir = Path(sys.executable).parent
    exe_name = Path(sys.executable).name

    # macOS .app bundle: replace the entire .app directory, not just
    # Contents/MacOS/.  The staged archive also contains an .app folder.
    if sys.platform == "darwin" and ".app/Contents/MacOS" in str(app_dir):
        app_dir = app_dir.parent.parent.parent   # .app root
        exe_name = f"Contents/MacOS/{Path(sys.executable).name}"

    try:
        if sys.platform == "win32":
            script = _write_windows_bootstrap(pid, app_dir, staged_dir, exe_name)
            # Start detached: CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS
            subprocess.Popen(
                ["cmd.exe", "/c", str(script)],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS,
                close_fds=True,
            )
        else:
            script = _write_unix_bootstrap(pid, app_dir, staged_dir, exe_name)
            subprocess.Popen(
                ["/bin/sh", str(script)],
                start_new_session=True,
                close_fds=True,
            )

        logger.info("Bootstrap launched: %s — app should exit now.", script)
        return True

    except Exception as exc:
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
