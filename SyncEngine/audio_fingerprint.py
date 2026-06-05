"""
Audio Fingerprinting - Compute and store acoustic fingerprints using Chromaprint.

Acoustic fingerprints identify audio content regardless of encoding format.
Same song encoded as MP3 or FLAC → same fingerprint.

Requires: fpcalc binary (Chromaprint) - https://acoustid.org/chromaprint

Storage: Fingerprints are stored in file metadata as ACOUSTID_FINGERPRINT tag.
A filesystem-level cache (fingerprint_cache.json) avoids re-reading tags or
re-running fpcalc when a file's path/mtime/size haven't changed.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Optional

# Prevents console windows from flashing on Windows during subprocess calls
_SP_KWARGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)

try:
    import mutagen
    import mutagen.id3
    from mutagen.flac import FLAC
    from mutagen.id3 import ID3
    from mutagen.id3._frames import TXXX
    from mutagen.mp4 import MP4
    from mutagen.oggopus import OggOpus
    from mutagen.oggvorbis import OggVorbis

    MUTAGEN_AVAILABLE = True
except ImportError:
    mutagen = None  # type: ignore[assignment]
    ID3: Any = None
    TXXX: Any = None
    MP4: Any = None
    FLAC: Any = None
    OggVorbis: Any = None
    OggOpus: Any = None
    MUTAGEN_AVAILABLE = False
    logging.warning("mutagen not installed - fingerprint storage disabled")

logger = logging.getLogger(__name__)

# Tag names for storing fingerprint in different formats
FINGERPRINT_TAG = "ACOUSTID_FINGERPRINT"
FINGERPRINT_TAG_MP4 = "----:com.apple.iTunes:ACOUSTID_FINGERPRINT"


class FingerprintCache:
    """Disk-backed cache mapping (path, mtime, size) → fingerprint.

    Avoids re-reading file metadata or re-running fpcalc when a file
    hasn't changed since the last sync.  The cache is stored as a JSON
    file in the settings/cache directory and is loaded lazily on first
    access.
    """

    _instance: Optional["FingerprintCache"] = None
    _lock = threading.Lock()

    def __init__(self, cache_path: str | Path):
        self._path = Path(cache_path)
        self._dirty = False
        self._data: dict[str, dict] = {}  # path → {"mtime": float, "size": int, "fp": str}
        self._io_lock = threading.Lock()
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    self._data = raw
                    logger.debug("Loaded fingerprint cache with %d entries", len(self._data))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Could not load fingerprint cache: %s", e)
                self._data = {}

    def lookup(self, filepath: Path) -> str | None:
        key = str(filepath)
        entry = self._data.get(key)
        if entry is None:
            return None
        try:
            st = filepath.stat()
        except OSError:
            return None
        if st.st_size == entry.get("size") and abs(st.st_mtime - entry.get("mtime", 0)) < 0.01:
            return entry.get("fp")
        return None

    def store(self, filepath: Path, fingerprint: str):
        try:
            st = filepath.stat()
        except OSError:
            return
        with self._io_lock:
            self._data[str(filepath)] = {
                "mtime": st.st_mtime,
                "size": st.st_size,
                "fp": fingerprint,
            }
            self._dirty = True

    def save(self):
        with self._io_lock:
            if not self._dirty:
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, separators=(",", ":"))
                tmp.replace(self._path)
                self._dirty = False
                logger.debug("Saved fingerprint cache (%d entries)", len(self._data))
            except OSError as e:
                logger.warning("Could not save fingerprint cache: %s", e)

    @classmethod
    def get_instance(cls) -> "FingerprintCache":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    from infrastructure.settings_paths import default_cache_dir
                    cache_dir = default_cache_dir()
                    path = os.path.join(cache_dir, "fingerprint_cache.json")
                    cls._instance = cls(path)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Reset the singleton (useful for testing)."""
        with cls._lock:
            cls._instance = None


def find_fpcalc(fpcalc_path: str | None = None) -> str | None:
    """Find the fpcalc binary.

    Search order:
    1. Explicit path provided by the caller
    2. Bundled binary (auto-downloaded to <settings_dir>/bin/)
    3. System PATH
    4. Common installation directories
    """
    if fpcalc_path and Path(fpcalc_path).is_file():
        return fpcalc_path

    # 2. Bundled binary
    try:
        from SyncEngine.dependency_manager import get_bundled_fpcalc
        bundled = get_bundled_fpcalc()
        if bundled:
            return bundled
    except Exception:
        pass

    # 3. System PATH
    fpcalc = shutil.which("fpcalc")
    if fpcalc:
        return fpcalc

    # 4. Common installation locations
    common_paths = [
        # Windows
        r"C:\Program Files\fpcalc\fpcalc.exe",
        r"C:\Program Files (x86)\fpcalc\fpcalc.exe",
        # macOS (Homebrew)
        "/usr/local/bin/fpcalc",
        "/opt/homebrew/bin/fpcalc",
        # Linux
        "/usr/bin/fpcalc",
    ]

    for path in common_paths:
        if Path(path).exists():
            return path

    return None


def compute_fingerprint(filepath: str | Path, fpcalc_path: str | None = None) -> str | None:
    """
    Compute acoustic fingerprint using Chromaprint's fpcalc.

    Args:
        filepath: Path to audio file
        fpcalc_path: Optional path to fpcalc binary

    Returns:
        Fingerprint string, or None if computation failed
    """
    filepath = Path(filepath)
    if not filepath.exists():
        logger.error(f"File not found: {filepath}")
        return None

    fpcalc = fpcalc_path or find_fpcalc()
    if not fpcalc:
        logger.error("fpcalc not found. Install Chromaprint: https://acoustid.org/chromaprint")
        return None

    try:
        result = subprocess.run(
            [fpcalc, "-raw", str(filepath)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            **_SP_KWARGS,
        )

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if "Empty fingerprint" in stderr:
                logger.warning(
                    "Fingerprint unavailable for %s: fpcalc returned no audio fingerprint "
                    "(silent, empty, or unsupported media).",
                    filepath.name,
                )
            else:
                logger.error(f"fpcalc failed for {filepath}: {stderr}")
            return None

        # Parse output: DURATION=123\nFINGERPRINT=abc123...
        fingerprint = None
        for line in result.stdout.strip().split("\n"):
            if line.startswith("FINGERPRINT="):
                fingerprint = line.split("=", 1)[1]
                break

        if not fingerprint:
            logger.warning(
                "Fingerprint unavailable for %s: fpcalc produced no fingerprint output",
                filepath.name,
            )
            return None

        return fingerprint

    except subprocess.TimeoutExpired:
        logger.error(f"fpcalc timed out for {filepath}")
        return None
    except Exception as e:
        logger.error(f"Error computing fingerprint for {filepath}: {e}")
        return None


def read_fingerprint(filepath: str | Path) -> str | None:
    """
    Read stored fingerprint from file metadata.

    Args:
        filepath: Path to audio file

    Returns:
        Fingerprint string if stored, None otherwise
    """
    if not MUTAGEN_AVAILABLE:
        return None

    filepath = Path(filepath)
    suffix = filepath.suffix.lower()

    try:
        if suffix == ".mp3":
            audio = ID3(filepath)
            # Look for TXXX:ACOUSTID_FINGERPRINT
            for frame in audio.getall("TXXX"):
                if frame.desc == FINGERPRINT_TAG:
                    return frame.text[0] if frame.text else None

        elif suffix in (".m4a", ".m4p", ".aac", ".alac", ".m4v", ".mp4", ".mov"):
            audio = MP4(filepath)
            if FINGERPRINT_TAG_MP4 in audio:
                val = audio[FINGERPRINT_TAG_MP4]
                if val:
                    # MP4 stores as list of bytes
                    return val[0].decode("utf-8") if isinstance(val[0], bytes) else val[0]

        elif suffix == ".flac":
            audio = FLAC(filepath)
            if FINGERPRINT_TAG.lower() in audio:
                return audio[FINGERPRINT_TAG.lower()][0]
            if FINGERPRINT_TAG in audio:
                return audio[FINGERPRINT_TAG][0]

        elif suffix == ".ogg":
            audio = OggVorbis(filepath)
            if FINGERPRINT_TAG.lower() in audio:
                return audio[FINGERPRINT_TAG.lower()][0]

        elif suffix == ".opus":
            audio = OggOpus(filepath)
            if FINGERPRINT_TAG.lower() in audio:
                return audio[FINGERPRINT_TAG.lower()][0]

    except Exception as e:
        logger.debug(f"Could not read fingerprint from {filepath}: {e}")

    return None


def write_fingerprint(filepath: str | Path, fingerprint: str) -> bool:
    """
    Write fingerprint to file metadata.

    Args:
        filepath: Path to audio file
        fingerprint: Fingerprint string to store

    Returns:
        True if successful, False otherwise
    """
    if not MUTAGEN_AVAILABLE:
        logger.error("mutagen not available - cannot write fingerprint")
        return False

    filepath = Path(filepath)
    suffix = filepath.suffix.lower()

    try:
        if suffix == ".mp3":
            try:
                audio = ID3(filepath)
            except Exception:  # ID3NoHeaderError
                audio = ID3()

            # Remove existing fingerprint frame if present
            audio.delall("TXXX:ACOUSTID_FINGERPRINT")
            # Add new frame
            audio.add(TXXX(encoding=3, desc=FINGERPRINT_TAG, text=[fingerprint]))
            audio.save(filepath)
            return True

        elif suffix in (".m4a", ".m4p", ".aac", ".alac", ".m4v", ".mp4", ".mov"):
            audio = MP4(filepath)
            audio[FINGERPRINT_TAG_MP4] = [fingerprint.encode("utf-8")]
            audio.save()
            return True

        elif suffix == ".flac":
            audio = FLAC(filepath)
            audio[FINGERPRINT_TAG] = fingerprint
            audio.save()
            return True

        elif suffix == ".ogg":
            audio = OggVorbis(filepath)
            audio[FINGERPRINT_TAG] = fingerprint
            audio.save()
            return True

        elif suffix == ".opus":
            audio = OggOpus(filepath)
            audio[FINGERPRINT_TAG] = fingerprint
            audio.save()
            return True

        else:
            logger.warning(f"Unsupported format for fingerprint storage: {suffix}")
            return False

    except UnicodeError as e:
        logger.debug(f"Could not write fingerprint to {filepath}: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to write fingerprint to {filepath}: {e}")
        return False


def get_or_compute_fingerprint_with_status(
    filepath: str | Path,
    fpcalc_path: str | None = None,
    write_to_file: bool = True,
) -> tuple[str | None, str]:
    """
    Get fingerprint from file metadata, or compute and optionally store it.

    This is the main entry point for fingerprinting.

    Lookup order:
    1. Filesystem cache (fingerprint_cache.json) — instant if path/mtime/size match
    2. File metadata tag (ACOUSTID_FINGERPRINT) — requires parsing file headers
    3. Compute via fpcalc — slowest, subprocess call

    Args:
        filepath: Path to audio file
        fpcalc_path: Optional path to fpcalc binary
        write_to_file: If True, store computed fingerprint in file metadata

    Returns:
        Tuple of ``(fingerprint, status)``. Status is one of ``cache``,
        ``tag``, ``computed``, or ``failed``.
    """

    def _is_raw_fingerprint(value: str) -> bool:
        """Return True when fingerprint is fpcalc -raw integer CSV format.

        Historical iOpenPod builds may have cached/stored fingerprints in the
        compressed/default fpcalc format.  Those won't compare equal to current
        raw CSV fingerprints, so we treat them as legacy and recompute.
        """
        v = (value or "").strip()
        if not v:
            return False
        return bool(re.fullmatch(r"-?\d+(,-?\d+)*", v))

    filepath = Path(filepath)
    cache = FingerprintCache.get_instance()

    # 1. Check filesystem cache (no file I/O needed)
    cached = cache.lookup(filepath)
    if cached:
        if _is_raw_fingerprint(cached):
            return cached, "cache"
        logger.debug(
            "Legacy cached fingerprint format for %s; recomputing raw fingerprint",
            filepath.name,
        )

    # 2. Try to read existing fingerprint from file tags
    fingerprint = read_fingerprint(filepath)
    if fingerprint:
        if _is_raw_fingerprint(fingerprint):
            cache.store(filepath, fingerprint)
            return fingerprint, "tag"
        logger.debug(
            "Legacy tagged fingerprint format for %s; recomputing raw fingerprint",
            filepath.name,
        )

    # 3. Compute new fingerprint
    fingerprint = compute_fingerprint(filepath, fpcalc_path)
    if not fingerprint:
        return None, "failed"

    # Optionally store in file metadata
    if write_to_file:
        if write_fingerprint(filepath, fingerprint):
            pass
        else:
            logger.debug(f"Could not store fingerprint in {filepath.name}; using cache only")

    # Update cache with current file stats (post-write if applicable)
    cache.store(filepath, fingerprint)

    return fingerprint, "computed"


def get_or_compute_fingerprint(
    filepath: str | Path,
    fpcalc_path: str | None = None,
    write_to_file: bool = True,
) -> str | None:
    """
    Get fingerprint from file metadata, or compute and optionally store it.

    This compatibility wrapper returns only the fingerprint. Use
    :func:`get_or_compute_fingerprint_with_status` when batch callers need
    cache/tag/computed/failed counts for summary logging.
    """
    fingerprint, _status = get_or_compute_fingerprint_with_status(
        filepath,
        fpcalc_path=fpcalc_path,
        write_to_file=write_to_file,
    )
    return fingerprint


def is_fpcalc_available(fpcalc_path: str | None = None) -> bool:
    """Check if fpcalc is available on this system."""
    return find_fpcalc(fpcalc_path) is not None
