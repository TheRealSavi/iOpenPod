"""
Dependency Manager - Auto-download FFmpeg and Chromaprint (fpcalc) binaries.

Downloads platform-appropriate static binaries to ~/iOpenPod/bin/ so users
don't need to install them system-wide or add them to PATH.

Supports:
  - Windows x86_64
  - macOS x86_64 / arm64
  - Linux x86_64
"""

import logging
import platform
import shutil
import stat
import sys
import tempfile
import zipfile
import tarfile
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger(__name__)


# ── Binary directory ────────────────────────────────────────────────────────


def get_bin_dir() -> Path:
    """Get the directory where downloaded binaries are stored.

    Always co-located with the active settings directory as ``<settings_dir>/bin/``.
    """
    try:
        from settings import _get_settings_dir
        return Path(_get_settings_dir()) / "bin"
    except Exception:
        pass

    # Fallback if settings module isn't available
    return Path.home() / "iOpenPod" / "bin"


def _ensure_bin_dir() -> Path:
    d = get_bin_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Platform detection ──────────────────────────────────────────────────────

def _platform_key() -> str:
    """Return a key like 'windows-x86_64', 'darwin-arm64', 'linux-x86_64'."""
    system = sys.platform  # win32, darwin, linux
    machine = platform.machine().lower()

    if system == "win32":
        os_name = "windows"
    elif system == "darwin":
        os_name = "darwin"
    else:
        os_name = "linux"

    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine

    return f"{os_name}-{arch}"


# ── FFmpeg download URLs ───────────────────────────────────────────────────
# BtbN/FFmpeg-Builds: static GPL builds, updated regularly.

_FFMPEG_URLS = {
    "windows-x86_64": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    "linux-x86_64": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
    "darwin-x86_64": "https://evermeet.cx/ffmpeg/getrelease/zip",
    "darwin-arm64": "https://evermeet.cx/ffmpeg/getrelease/zip",
}

# ── Chromaprint (fpcalc) download URLs ─────────────────────────────────────
# acoustid/chromaprint GitHub releases.

_FPCALC_VERSION = "1.5.1"
_FPCALC_URLS = {
    "windows-x86_64": f"https://github.com/acoustid/chromaprint/releases/download/v{_FPCALC_VERSION}/chromaprint-fpcalc-{_FPCALC_VERSION}-windows-x86_64.zip",
    "linux-x86_64": f"https://github.com/acoustid/chromaprint/releases/download/v{_FPCALC_VERSION}/chromaprint-fpcalc-{_FPCALC_VERSION}-linux-x86_64.tar.gz",
    "darwin-x86_64": f"https://github.com/acoustid/chromaprint/releases/download/v{_FPCALC_VERSION}/chromaprint-fpcalc-{_FPCALC_VERSION}-macos-x86_64.tar.gz",
    "darwin-arm64": f"https://github.com/acoustid/chromaprint/releases/download/v{_FPCALC_VERSION}/chromaprint-fpcalc-{_FPCALC_VERSION}-macos-universal.tar.gz",
}


# ── Download helpers ────────────────────────────────────────────────────────


def _download(url: str, dest: Path, progress_callback=None) -> bool:
    """Download a URL to a file. Returns True on success."""
    logger.info(f"Downloading {url}")
    try:
        req = Request(url, headers={"User-Agent": "iOpenPod/1.0.0"})
        with urlopen(req, timeout=120) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total:
                        progress_callback(downloaded, total)
        return True
    except (URLError, OSError) as e:
        logger.error(f"Download failed: {e}")
        if dest.exists():
            dest.unlink()
        return False


def _extract_binary(archive: Path, binary_name: str, dest_dir: Path) -> Optional[Path]:
    """
    Extract a specific binary from a zip or tar archive.
    Returns the path to the extracted binary, or None.
    """
    name_lower = binary_name.lower()
    extracted = None

    try:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    basename = Path(info.filename).name.lower()
                    if basename == name_lower or basename == name_lower + ".exe":
                        # Extract to temp, then move
                        with zf.open(info) as src:
                            dest = dest_dir / Path(info.filename).name
                            with open(dest, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            extracted = dest
                            break

        elif archive.name.endswith((".tar.gz", ".tar.xz", ".tgz")):
            with tarfile.open(archive) as tf:
                for member in tf.getmembers():
                    basename = Path(member.name).name.lower()
                    if basename == name_lower or basename == name_lower + ".exe":
                        # Extract member
                        member.name = Path(member.name).name  # flatten path
                        tf.extract(member, dest_dir)
                        extracted = dest_dir / Path(member.name).name
                        break

    except (zipfile.BadZipFile, tarfile.TarError, OSError) as e:
        logger.error(f"Extraction failed: {e}")
        return None

    # Make executable on Unix
    if extracted and extracted.exists() and sys.platform != "win32":
        extracted.chmod(extracted.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    return extracted


# ── Public API ──────────────────────────────────────────────────────────────

def get_bundled_ffmpeg() -> Optional[str]:
    """Return path to bundled ffmpeg binary if it exists."""
    bin_dir = get_bin_dir()
    if sys.platform == "win32":
        path = bin_dir / "ffmpeg.exe"
    else:
        path = bin_dir / "ffmpeg"
    return str(path) if path.exists() else None


def get_bundled_fpcalc() -> Optional[str]:
    """Return path to bundled fpcalc binary if it exists."""
    bin_dir = get_bin_dir()
    if sys.platform == "win32":
        path = bin_dir / "fpcalc.exe"
    else:
        path = bin_dir / "fpcalc"
    return str(path) if path.exists() else None


def download_ffmpeg(progress_callback=None) -> Optional[str]:
    """
    Download a static FFmpeg build for the current platform.

    Args:
        progress_callback: Optional callable(downloaded_bytes, total_bytes)

    Returns:
        Path to the ffmpeg binary, or None on failure.
    """
    pkey = _platform_key()
    url = _FFMPEG_URLS.get(pkey)
    if not url:
        logger.error(f"No FFmpeg download available for platform: {pkey}")
        return None

    bin_dir = _ensure_bin_dir()
    binary_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"

    # Check if already downloaded
    existing = bin_dir / binary_name
    if existing.exists():
        logger.info(f"FFmpeg already present: {existing}")
        return str(existing)

    # Download to temp file
    suffix = ".zip" if url.endswith(".zip") else ".tar.xz" if url.endswith(".tar.xz") else ".tar.gz"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        if not _download(url, tmp_path, progress_callback):
            return None

        result = _extract_binary(tmp_path, "ffmpeg", bin_dir)
        if result:
            logger.info(f"FFmpeg installed to: {result}")
            return str(result)
        else:
            logger.error("Could not find ffmpeg binary in downloaded archive")
            return None
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def download_fpcalc(progress_callback=None) -> Optional[str]:
    """
    Download fpcalc (Chromaprint) for the current platform.

    Args:
        progress_callback: Optional callable(downloaded_bytes, total_bytes)

    Returns:
        Path to the fpcalc binary, or None on failure.
    """
    pkey = _platform_key()
    url = _FPCALC_URLS.get(pkey)
    if not url:
        logger.error(f"No fpcalc download available for platform: {pkey}")
        return None

    bin_dir = _ensure_bin_dir()
    binary_name = "fpcalc.exe" if sys.platform == "win32" else "fpcalc"

    # Check if already downloaded
    existing = bin_dir / binary_name
    if existing.exists():
        logger.info(f"fpcalc already present: {existing}")
        return str(existing)

    # Download to temp file
    suffix = ".zip" if url.endswith(".zip") else ".tar.gz"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        if not _download(url, tmp_path, progress_callback):
            return None

        result = _extract_binary(tmp_path, "fpcalc", bin_dir)
        if result:
            logger.info(f"fpcalc installed to: {result}")
            return str(result)
        else:
            logger.error("Could not find fpcalc binary in downloaded archive")
            return None
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def is_platform_supported() -> bool:
    """Check if auto-download is supported on this platform."""
    pkey = _platform_key()
    return pkey in _FFMPEG_URLS and pkey in _FPCALC_URLS
