"""
Extract embedded album art from music files using mutagen.

Supports: MP3, M4A/AAC, FLAC, OGG Vorbis, OPUS, WMA, AIFF/WAV
Returns raw image bytes (typically JPEG or PNG).
"""

import io
import hashlib
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import mutagen
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    from mutagen.flac import FLAC
    from mutagen.oggvorbis import OggVorbis
    from mutagen.oggopus import OggOpus
    from mutagen.aiff import AIFF
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    logger.warning("mutagen not installed - art extraction disabled")


def extract_art(file_path: str) -> Optional[bytes]:
    """
    Extract the first embedded album art image from a music file.

    Args:
        file_path: Path to the music file

    Returns:
        Raw image bytes (JPEG/PNG) or None if no art found
    """
    if not MUTAGEN_AVAILABLE:
        return None

    path = Path(file_path)
    ext = path.suffix.lower()

    try:
        if ext == '.mp3':
            return _extract_mp3(file_path)
        elif ext in ('.m4a', '.m4p', '.aac', '.alac'):
            return _extract_mp4(file_path)
        elif ext == '.flac':
            return _extract_flac(file_path)
        elif ext == '.ogg':
            return _extract_ogg(file_path)
        elif ext == '.opus':
            return _extract_opus(file_path)
        elif ext in ('.aif', '.aiff'):
            return _extract_aiff(file_path)
        else:
            # Try generic mutagen
            return _extract_generic(file_path)
    except Exception as e:
        logger.warning(f"ART: Failed to extract art from {file_path}: {e}")
        return None


def _extract_mp3(path: str) -> Optional[bytes]:
    """Extract art from MP3 (ID3v2 APIC frames)."""
    audio = MP3(path)
    if audio.tags is None:
        return None

    # Look for APIC frames (cover art)
    for key in audio.tags:
        if key.startswith('APIC'):
            frame = audio.tags[key]
            if frame.data:
                return frame.data
    return None


def _extract_mp4(path: str) -> Optional[bytes]:
    """Extract art from M4A/AAC (covr atom)."""
    audio = MP4(path)
    if audio.tags is None:
        return None

    covers = audio.tags.get('covr', [])
    if covers:
        return bytes(covers[0])
    return None


def _extract_flac(path: str) -> Optional[bytes]:
    """Extract art from FLAC (picture blocks)."""
    audio = FLAC(path)
    if audio.pictures:
        return audio.pictures[0].data
    return None


def _extract_ogg(path: str) -> Optional[bytes]:
    """Extract art from Ogg Vorbis (METADATA_BLOCK_PICTURE)."""
    audio = OggVorbis(path)
    return _extract_vorbis_picture(audio)


def _extract_opus(path: str) -> Optional[bytes]:
    """Extract art from Opus (METADATA_BLOCK_PICTURE)."""
    audio = OggOpus(path)
    return _extract_vorbis_picture(audio)


def _extract_vorbis_picture(audio) -> Optional[bytes]:
    """Extract art from Vorbis comment METADATA_BLOCK_PICTURE."""
    import base64

    pictures = audio.get('metadata_block_picture', [])
    if pictures:
        try:
            from mutagen.flac import Picture
            pic = Picture(base64.b64decode(pictures[0]))
            return pic.data
        except Exception:
            pass
    return None


def _extract_aiff(path: str) -> Optional[bytes]:
    """Extract art from AIFF (ID3v2 APIC frames)."""
    audio = AIFF(path)
    if audio.tags is None:
        return None
    for key in audio.tags:
        if key.startswith('APIC'):
            return audio.tags[key].data
    return None


def _extract_generic(path: str) -> Optional[bytes]:
    """Try generic mutagen extraction."""
    audio = mutagen.File(path)
    if audio is None or audio.tags is None:
        return None

    # Try ID3 APIC
    for key in audio.tags:
        if hasattr(key, 'startswith') and key.startswith('APIC'):
            frame = audio.tags[key]
            if hasattr(frame, 'data'):
                return frame.data

    # Try MP4 covr
    covers = audio.tags.get('covr', [])
    if covers:
        return bytes(covers[0])

    return None


def art_hash(art_bytes: bytes) -> str:
    """
    Compute a hash of album art bytes for deduplication.

    Tracks with identical art will share the same ArtworkDB entry.
    """
    return hashlib.md5(art_bytes).hexdigest()
