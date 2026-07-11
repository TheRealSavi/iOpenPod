"""
Dependency Manager - Auto-download FFmpeg and Chromaprint (fpcalc) binaries.

Downloads platform-appropriate static binaries to <settings_dir>/bin/ so users
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
import tarfile
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


# ── Binary directory ────────────────────────────────────────────────────────


def get_bin_dir() -> Path:
    """Get the directory where downloaded binaries are stored.

    Always co-located with the active settings directory as ``<settings_dir>/bin/``.
    """
    try:
        from iopenpod.infrastructure.settings_paths import get_settings_dir
        return Path(get_settings_dir()) / "bin"
    except Exception:
        pass

    # Fallback if settings module isn't available
    try:
        from iopenpod.infrastructure.settings_paths import default_data_dir
        return Path(default_data_dir()) / "bin"
    except Exception:
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

_FFPROBE_URLS = {
    "windows-x86_64": _FFMPEG_URLS["windows-x86_64"],
    "linux-x86_64": _FFMPEG_URLS["linux-x86_64"],
    "darwin-x86_64": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
    "darwin-arm64": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
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
        req = Request(url, headers={"User-Agent": "iOpenPod"})
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


def _binary_filename(binary_name: str) -> str:
    """Return the platform-specific executable filename for a tool."""
    if _platform_key().startswith("windows-") and not binary_name.endswith(".exe"):
        return f"{binary_name}.exe"
    return binary_name


def _extract_binaries(archive: Path, binary_names: Iterable[str], dest_dir: Path) -> dict[str, Path]:
    """
    Extract one or more binaries from a zip or tar archive.
    Returns a mapping of requested binary name to extracted path.
    """
    wanted = {name: {name.lower(), _binary_filename(name).lower()} for name in binary_names}
    extracted: dict[str, Path] = {}

    def _install_file(src, filename: str, requested_name: str) -> None:
        dest = dest_dir / Path(filename).name
        with open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        if sys.platform != "win32":
            dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        extracted[requested_name] = dest

    try:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                for info in zf.infolist():
                    basename = Path(info.filename).name.lower()
                    for requested_name, possible_names in wanted.items():
                        if requested_name in extracted or basename not in possible_names:
                            continue
                        with zf.open(info) as src:
                            _install_file(src, info.filename, requested_name)
                        break
                    if len(extracted) == len(wanted):
                        break

        elif archive.name.endswith((".tar.gz", ".tar.xz", ".tgz")):
            with tarfile.open(archive) as tf:
                for member in tf.getmembers():
                    basename = Path(member.name).name.lower()
                    for requested_name, possible_names in wanted.items():
                        if requested_name in extracted or basename not in possible_names:
                            continue
                        src = tf.extractfile(member)
                        if src is None:
                            continue
                        with src:
                            _install_file(src, member.name, requested_name)
                        break
                    if len(extracted) == len(wanted):
                        break

    except (zipfile.BadZipFile, tarfile.TarError, OSError) as e:
        logger.error(f"Extraction failed: {e}")
        return {}

    return extracted


def _extract_binary(archive: Path, binary_name: str, dest_dir: Path) -> Path | None:
    """
    Extract a specific binary from a zip or tar archive.
    Returns the path to the extracted binary, or None.
    """
    return _extract_binaries(archive, [binary_name], dest_dir).get(binary_name)


# ── Public API ──────────────────────────────────────────────────────────────

def get_bundled_ffmpeg() -> str | None:
    """Return path to bundled ffmpeg binary if it exists."""
    bin_dir = get_bin_dir()
    path = bin_dir / _binary_filename("ffmpeg")
    return str(path) if path.exists() else None


def get_bundled_ffprobe() -> str | None:
    """Return path to bundled ffprobe binary if it exists."""
    bin_dir = get_bin_dir()
    path = bin_dir / _binary_filename("ffprobe")
    return str(path) if path.exists() else None


def get_bundled_fpcalc() -> str | None:
    """Return path to bundled fpcalc binary if it exists."""
    bin_dir = get_bin_dir()
    path = bin_dir / _binary_filename("fpcalc")
    return str(path) if path.exists() else None


def download_ffmpeg(progress_callback=None) -> str | None:
    """
    Download static FFmpeg/ffprobe builds for the current platform.

    Args:
        progress_callback: Optional callable(downloaded_bytes, total_bytes)

    Returns:
        Path to the ffmpeg binary, or None on failure.
    """
    pkey = _platform_key()
    url = _FFMPEG_URLS.get(pkey)
    ffprobe_url = _FFPROBE_URLS.get(pkey)
    if not url or not ffprobe_url:
        logger.error(f"No FFmpeg download available for platform: {pkey}")
        return None

    bin_dir = _ensure_bin_dir()
    ffmpeg_name = _binary_filename("ffmpeg")
    ffprobe_name = _binary_filename("ffprobe")

    # Check if already downloaded
    existing_ffmpeg = bin_dir / ffmpeg_name
    existing_ffprobe = bin_dir / ffprobe_name
    if existing_ffmpeg.exists() and existing_ffprobe.exists():
        logger.info(f"FFmpeg already present: {existing_ffmpeg}")
        return str(existing_ffmpeg)

    # Download to temp file
    suffix = ".zip" if (url.endswith(".zip") or url.endswith("/zip")) else ".tar.xz" if url.endswith(".tar.xz") else ".tar.gz"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        if not _download(url, tmp_path, progress_callback):
            return None

        needed = ["ffmpeg"]
        if ffprobe_url == url and not existing_ffprobe.exists():
            needed.append("ffprobe")
        extracted = _extract_binaries(tmp_path, needed, bin_dir)
        if "ffmpeg" not in extracted and not existing_ffmpeg.exists():
            logger.error("Could not find ffmpeg binary in downloaded archive")
            return None
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    if not existing_ffprobe.exists() and ffprobe_url != url:
        suffix = ".zip" if (ffprobe_url.endswith(".zip") or ffprobe_url.endswith("/zip")) else ".tar.xz" if ffprobe_url.endswith(".tar.xz") else ".tar.gz"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            probe_tmp_path = Path(tmp.name)

        try:
            if not _download(ffprobe_url, probe_tmp_path, progress_callback):
                return None

            extracted = _extract_binaries(probe_tmp_path, ["ffprobe"], bin_dir)
            if "ffprobe" not in extracted:
                logger.error("Could not find ffprobe binary in downloaded archive")
                return None
        finally:
            if probe_tmp_path.exists():
                probe_tmp_path.unlink()

    if existing_ffmpeg.exists() and existing_ffprobe.exists():
        logger.info(f"FFmpeg installed to: {existing_ffmpeg}")
        logger.info(f"ffprobe installed to: {existing_ffprobe}")
        return str(existing_ffmpeg)

    logger.error("FFmpeg install incomplete: ffmpeg=%s ffprobe=%s", existing_ffmpeg.exists(), existing_ffprobe.exists())
    return None


def download_fpcalc(progress_callback=None) -> str | None:
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
    return pkey in _FFMPEG_URLS and pkey in _FFPROBE_URLS and pkey in _FPCALC_URLS
