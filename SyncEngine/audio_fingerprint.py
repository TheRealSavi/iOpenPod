"""
Audio Fingerprinting - Compute and store acoustic fingerprints using Chromaprint.

Acoustic fingerprints identify audio content regardless of encoding format.
Same song encoded as MP3 or FLAC → same fingerprint.

Requires: fpcalc binary (Chromaprint) - https://acoustid.org/chromaprint

Storage: Fingerprints are stored in file metadata as ACOUSTID_FINGERPRINT tag.
"""

import subprocess
import logging
from pathlib import Path
from typing import Optional, Any
import shutil

try:
    import mutagen
    import mutagen.id3
    from mutagen.id3 import ID3
    from mutagen.id3._frames import TXXX
    from mutagen.mp4 import MP4
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis
    from mutagen.oggopus import OggOpus

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


def find_fpcalc() -> Optional[str]:
    """Find the fpcalc binary. Returns path or None."""
    # Check if in PATH
    fpcalc = shutil.which("fpcalc")
    if fpcalc:
        return fpcalc

    # Common installation locations
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


def compute_fingerprint(filepath: str | Path, fpcalc_path: Optional[str] = None) -> Optional[str]:
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
            timeout=60,
        )

        if result.returncode != 0:
            logger.error(f"fpcalc failed for {filepath}: {result.stderr}")
            return None

        # Parse output: DURATION=123\nFINGERPRINT=abc123...
        fingerprint = None
        for line in result.stdout.strip().split("\n"):
            if line.startswith("FINGERPRINT="):
                fingerprint = line.split("=", 1)[1]
                break

        if not fingerprint:
            logger.error(f"No fingerprint in fpcalc output for {filepath}")
            return None

        return fingerprint

    except subprocess.TimeoutExpired:
        logger.error(f"fpcalc timed out for {filepath}")
        return None
    except Exception as e:
        logger.error(f"Error computing fingerprint for {filepath}: {e}")
        return None


def read_fingerprint(filepath: str | Path) -> Optional[str]:
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

        elif suffix in (".m4a", ".m4p", ".aac", ".alac"):
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

        elif suffix in (".m4a", ".m4p", ".aac", ".alac"):
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

    except Exception as e:
        logger.error(f"Failed to write fingerprint to {filepath}: {e}")
        return False


def get_or_compute_fingerprint(
    filepath: str | Path,
    fpcalc_path: Optional[str] = None,
    write_to_file: bool = True,
) -> Optional[str]:
    """
    Get fingerprint from file metadata, or compute and optionally store it.

    This is the main entry point for fingerprinting.

    Args:
        filepath: Path to audio file
        fpcalc_path: Optional path to fpcalc binary
        write_to_file: If True, store computed fingerprint in file metadata

    Returns:
        Fingerprint string, or None if unavailable
    """
    filepath = Path(filepath)

    # Try to read existing fingerprint
    fingerprint = read_fingerprint(filepath)
    if fingerprint:
        logger.debug(f"Read existing fingerprint for {filepath.name}")
        return fingerprint

    # Compute new fingerprint
    logger.debug(f"Computing fingerprint for {filepath.name}")
    fingerprint = compute_fingerprint(filepath, fpcalc_path)
    if not fingerprint:
        return None

    # Optionally store it
    if write_to_file:
        if write_fingerprint(filepath, fingerprint):
            logger.debug(f"Stored fingerprint in {filepath.name}")
        else:
            logger.warning(f"Could not store fingerprint in {filepath.name}")

    return fingerprint


def is_fpcalc_available() -> bool:
    """Check if fpcalc is available on this system."""
    return find_fpcalc() is not None
