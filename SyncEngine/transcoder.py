"""
Transcoder - Convert audio files to iPod-compatible formats using FFmpeg.

Supported conversions:
- FLAC → ALAC (lossless to lossless)
- WAV/AIFF → ALAC (uncompressed to lossless)
- OGG/Opus → AAC (lossy to lossy)
- WMA → AAC (lossy to lossy)

iPod-native formats (no transcoding needed):
- MP3, M4A (AAC), M4P (protected AAC)
"""

import subprocess
import logging
import shutil
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TranscodeTarget(Enum):
    """Target format for transcoding."""

    ALAC = "alac"  # Apple Lossless - for lossless sources
    AAC = "aac"  # AAC - for lossy sources
    COPY = "copy"  # No transcoding needed


# Mapping of source formats to transcoding targets
FORMAT_TARGETS = {
    # Lossless → ALAC
    ".flac": TranscodeTarget.ALAC,
    ".wav": TranscodeTarget.ALAC,
    ".aif": TranscodeTarget.ALAC,
    ".aiff": TranscodeTarget.ALAC,
    # Lossy → AAC
    ".ogg": TranscodeTarget.AAC,
    ".opus": TranscodeTarget.AAC,
    ".wma": TranscodeTarget.AAC,
    # Already iPod-compatible
    ".mp3": TranscodeTarget.COPY,
    ".m4a": TranscodeTarget.COPY,
    ".m4p": TranscodeTarget.COPY,
    ".aac": TranscodeTarget.COPY,
}

# iPod-native formats that don't need transcoding
IPOD_NATIVE_FORMATS = {".mp3", ".m4a", ".m4p", ".aac"}

# Output extensions
TARGET_EXTENSIONS = {
    TranscodeTarget.ALAC: ".m4a",
    TranscodeTarget.AAC: ".m4a",
    TranscodeTarget.COPY: None,  # Keep original extension
}


@dataclass
class TranscodeResult:
    """Result of a transcode operation."""

    success: bool
    source_path: Path
    output_path: Optional[Path]
    target_format: TranscodeTarget
    was_transcoded: bool  # False if file was copied directly
    error_message: Optional[str] = None

    @property
    def ipod_format(self) -> str:
        """Format string for mapping file."""
        if self.output_path:
            return self.output_path.suffix.lstrip(".")
        return self.source_path.suffix.lstrip(".")


def find_ffmpeg() -> Optional[str]:
    """Find ffmpeg binary. Returns path or None."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    # Common installation locations
    common_paths = [
        # Windows
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        # macOS (Homebrew)
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        # Linux
        "/usr/bin/ffmpeg",
    ]

    for path in common_paths:
        if Path(path).exists():
            return path

    return None


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg is available."""
    return find_ffmpeg() is not None


def needs_transcoding(filepath: str | Path) -> bool:
    """Check if a file needs transcoding for iPod compatibility."""
    suffix = Path(filepath).suffix.lower()
    target = FORMAT_TARGETS.get(suffix, TranscodeTarget.AAC)
    return target != TranscodeTarget.COPY


def get_transcode_target(filepath: str | Path) -> TranscodeTarget:
    """Get the target format for a file."""
    suffix = Path(filepath).suffix.lower()
    return FORMAT_TARGETS.get(suffix, TranscodeTarget.AAC)


def transcode(
    source_path: str | Path,
    output_dir: str | Path,
    output_filename: Optional[str] = None,
    ffmpeg_path: Optional[str] = None,
    aac_bitrate: int = 256,  # kbps for AAC encoding
) -> TranscodeResult:
    """
    Transcode an audio file to iPod-compatible format.

    Args:
        source_path: Path to source audio file
        output_dir: Directory to write output file
        output_filename: Optional custom output filename (without extension)
        ffmpeg_path: Optional path to ffmpeg binary
        aac_bitrate: Bitrate for AAC encoding (kbps)

    Returns:
        TranscodeResult with output path and status
    """
    source_path = Path(source_path)
    output_dir = Path(output_dir)

    if not source_path.exists():
        return TranscodeResult(
            success=False,
            source_path=source_path,
            output_path=None,
            target_format=TranscodeTarget.COPY,
            was_transcoded=False,
            error_message=f"Source file not found: {source_path}",
        )

    target = get_transcode_target(source_path)

    # Determine output path
    if output_filename:
        base_name = output_filename
    else:
        base_name = source_path.stem

    if target == TranscodeTarget.COPY:
        # No transcoding needed - just copy
        output_path = output_dir / (base_name + source_path.suffix)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, output_path)
            return TranscodeResult(
                success=True,
                source_path=source_path,
                output_path=output_path,
                target_format=target,
                was_transcoded=False,
            )
        except Exception as e:
            return TranscodeResult(
                success=False,
                source_path=source_path,
                output_path=None,
                target_format=target,
                was_transcoded=False,
                error_message=str(e),
            )

    # Transcoding needed
    ffmpeg = ffmpeg_path or find_ffmpeg()
    if not ffmpeg:
        return TranscodeResult(
            success=False,
            source_path=source_path,
            output_path=None,
            target_format=target,
            was_transcoded=False,
            error_message="ffmpeg not found",
        )

    output_ext = TARGET_EXTENSIONS[target]
    output_path = output_dir / (base_name + output_ext)

    # Build ffmpeg command
    if target == TranscodeTarget.ALAC:
        # Lossless transcoding to ALAC
        cmd = [
            ffmpeg,
            "-i",
            str(source_path),
            "-vn",  # No video
            "-acodec",
            "alac",  # Apple Lossless
            "-y",  # Overwrite output
            str(output_path),
        ]
    else:
        # Lossy transcoding to AAC
        cmd = [
            ffmpeg,
            "-i",
            str(source_path),
            "-vn",  # No video
            "-acodec",
            "aac",
            "-b:a",
            f"{aac_bitrate}k",
            "-y",  # Overwrite output
            str(output_path),
        ]

    try:
        output_dir.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",  # Handle non-UTF8 bytes gracefully
            timeout=300,  # 5 minute timeout
        )

        if result.returncode != 0:
            return TranscodeResult(
                success=False,
                source_path=source_path,
                output_path=None,
                target_format=target,
                was_transcoded=True,
                error_message=f"ffmpeg failed: {result.stderr[:500]}",
            )

        if not output_path.exists():
            return TranscodeResult(
                success=False,
                source_path=source_path,
                output_path=None,
                target_format=target,
                was_transcoded=True,
                error_message="Output file not created",
            )

        logger.info(f"Transcoded {source_path.name} → {output_path.name}")
        return TranscodeResult(
            success=True,
            source_path=source_path,
            output_path=output_path,
            target_format=target,
            was_transcoded=True,
        )

    except subprocess.TimeoutExpired:
        return TranscodeResult(
            success=False,
            source_path=source_path,
            output_path=None,
            target_format=target,
            was_transcoded=True,
            error_message="Transcoding timed out",
        )
    except Exception as e:
        return TranscodeResult(
            success=False,
            source_path=source_path,
            output_path=None,
            target_format=target,
            was_transcoded=True,
            error_message=str(e),
        )


def copy_metadata(source_path: str | Path, dest_path: str | Path) -> bool:
    """
    Copy metadata tags from source to destination file.

    FFmpeg doesn't always preserve all metadata during transcoding,
    so this can be used to ensure tags are copied.

    Args:
        source_path: Original file with metadata
        dest_path: Transcoded file to receive metadata

    Returns:
        True if successful
    """
    try:
        from mutagen._file import File as MutagenFile  # type: ignore[import-not-found]

        source = MutagenFile(source_path, easy=True)
        dest = MutagenFile(dest_path, easy=True)

        if source is None or dest is None:
            return False

        # Copy common tags
        for tag in ["title", "artist", "album", "albumartist", "genre", "date", "tracknumber", "discnumber"]:
            if tag in source:
                dest[tag] = source[tag]

        dest.save()
        return True

    except Exception as e:
        logger.warning(f"Could not copy metadata: {e}")
        return False
