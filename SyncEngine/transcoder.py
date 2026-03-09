"""
Transcoder - Convert audio files to iPod-compatible formats using FFmpeg.

Supported conversions:
- FLAC → ALAC (lossless to lossless)
- WAV/AIFF → ALAC (uncompressed to lossless)
- OGG/Opus → AAC (lossy to lossy)
- WMA → AAC (lossy to lossy)
- Video (MOV/MKV/AVI/x265/10bit/4K) → M4V H.264 Baseline + stereo AAC

iPod-native formats (no transcoding needed):
- MP3, M4A (AAC), M4P (protected AAC), M4B (audiobook)
- M4V, MP4 with H.264 Baseline ≤640x480, 8-bit, stereo AAC

Video files in MP4/M4V containers are probed with ffprobe to check if
the codec is iPod-compatible. HEVC/x265, 10-bit, >640x480, non-H.264,
or surround audio all trigger re-encoding.
"""

import subprocess
import sys
import logging
import shutil
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass
from enum import Enum

# Prevents console windows from flashing on Windows during subprocess calls
_SP_KWARGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)

logger = logging.getLogger(__name__)


class TranscodeTarget(Enum):
    """Target format for transcoding."""

    ALAC = "alac"  # Apple Lossless - for lossless sources
    AAC = "aac"  # AAC - for lossy sources
    VIDEO_H264 = "video_h264"  # H.264 + AAC in M4V container - for video
    COPY = "copy"  # No transcoding needed


# Mapping of source formats to transcoding targets (audio only — extension based)
# Video containers (.mp4, .m4v, .mov, .mkv, .avi) use probe_video_needs_transcode()
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
    # Already iPod-compatible (audio)
    ".mp3": TranscodeTarget.COPY,
    ".m4a": TranscodeTarget.COPY,
    ".m4p": TranscodeTarget.COPY,
    ".m4b": TranscodeTarget.COPY,
    ".aac": TranscodeTarget.COPY,
}

# Video containers — always need ffprobe to determine if transcoding is needed
# .mkv and .avi are never iPod-native containers, always transcode
VIDEO_CONTAINERS = {".mp4", ".m4v", ".mov", ".mkv", ".avi"}
VIDEO_ALWAYS_TRANSCODE = {".mov", ".mkv", ".avi"}  # non-iPod containers

# iPod-native formats that don't need transcoding (audio only; video needs probe)
IPOD_NATIVE_FORMATS = {".mp3", ".m4a", ".m4p", ".m4b", ".aac"}

# iPod video limits
_IPOD_MAX_WIDTH = 640
_IPOD_MAX_HEIGHT = 480

# Output extensions
TARGET_EXTENSIONS = {
    TranscodeTarget.ALAC: ".m4a",
    TranscodeTarget.AAC: ".m4a",
    TranscodeTarget.VIDEO_H264: ".m4v",
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
    """Find ffmpeg binary.

    Search order:
    1. User-configured path in settings
    2. Bundled binary (auto-downloaded to ~/iOpenPod/bin/)
    3. System PATH
    4. Common installation directories
    """
    try:
        from GUI.settings import get_settings
        custom = get_settings().ffmpeg_path
        if custom and Path(custom).is_file():
            return custom
    except Exception:
        pass

    # 2. Bundled binary
    try:
        from .dependency_manager import get_bundled_ffmpeg
        bundled = get_bundled_ffmpeg()
        if bundled:
            return bundled
    except Exception:
        pass

    # 3. System PATH
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    # 4. Common installation locations
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


def probe_video_needs_transcode(
    filepath: str | Path,
    ffprobe_path: Optional[str] = None,
) -> bool:
    """Probe a video file to check if its codec is iPod-compatible.

    iPod requires: H.264 Baseline/Main profile, 8-bit, ≤640x480,
    and stereo (or mono) AAC audio.  Anything else needs re-encoding.

    Returns True if transcoding is needed, False if file can be copied as-is.
    On probe failure, returns True (safe default: transcode).

    Results are cached per resolved path so ffprobe only runs once per file.
    """
    return _probe_video_needs_transcode_cached(
        str(Path(filepath).resolve()), ffprobe_path
    )


@lru_cache(maxsize=256)
def _probe_video_needs_transcode_cached(
    resolved_path: str,
    ffprobe_path: Optional[str] = None,
) -> bool:
    """Cached inner implementation of probe_video_needs_transcode."""
    import json as _json

    filepath = resolved_path

    probe = ffprobe_path
    if not probe:
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            # ffprobe is alongside ffmpeg in the same directory
            probe_candidate = Path(ffmpeg).parent / (
                "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
            )
            if probe_candidate.exists():
                probe = str(probe_candidate)
            else:
                probe = shutil.which("ffprobe")
    if not probe:
        logger.warning("ffprobe not found, assuming video needs transcoding")
        return True

    try:
        result = subprocess.run(
            [
                probe,
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            **_SP_KWARGS,
        )
        if result.returncode != 0:
            logger.warning("ffprobe failed on %s, assuming transcode needed", filepath)
            return True

        info = _json.loads(result.stdout)
        streams = info.get("streams", [])

        video_ok = False
        audio_ok = False

        for s in streams:
            codec_type = s.get("codec_type")

            if codec_type == "video":
                codec = s.get("codec_name", "").lower()
                width = int(s.get("width", 9999))
                height = int(s.get("height", 9999))
                pix_fmt = s.get("pix_fmt", "")

                # Must be H.264
                if codec != "h264":
                    logger.info(
                        "Video codec '%s' is not H.264, needs transcode", codec
                    )
                    return True

                # Must be 8-bit (yuv420p, not yuv420p10le etc.)
                if pix_fmt and "10" in pix_fmt:
                    logger.info(
                        "Video pixel format '%s' is 10-bit, needs transcode",
                        pix_fmt,
                    )
                    return True

                # Must fit within 640x480
                if width > _IPOD_MAX_WIDTH or height > _IPOD_MAX_HEIGHT:
                    logger.info(
                        "Video resolution %dx%d exceeds iPod max %dx%d, needs transcode",
                        width, height, _IPOD_MAX_WIDTH, _IPOD_MAX_HEIGHT,
                    )
                    return True

                video_ok = True

            elif codec_type == "audio":
                codec = s.get("codec_name", "").lower()
                channels = int(s.get("channels", 0))

                # Must be AAC with ≤2 channels
                if codec != "aac":
                    logger.info(
                        "Audio codec '%s' is not AAC, needs transcode", codec
                    )
                    return True
                if channels > 2:
                    logger.info(
                        "Audio has %d channels (surround), needs transcode",
                        channels,
                    )
                    return True

                audio_ok = True

        if not video_ok:
            logger.info("No compatible video stream found, needs transcode")
            return True

        if not audio_ok:
            logger.info("No compatible audio stream found, needs transcode")
            return True

        return False  # All checks passed — file is iPod-compatible

    except Exception as e:
        logger.warning("ffprobe error on %s: %s, assuming transcode needed", filepath, e)
        return True


def needs_transcoding(filepath: str | Path) -> bool:
    """Check if a file needs transcoding for iPod compatibility.

    For audio files, this is a simple extension check.
    For video files, this probes the actual codec with ffprobe.
    """
    suffix = Path(filepath).suffix.lower()

    # Video containers need probing
    if suffix in VIDEO_CONTAINERS:
        # Non-iPod containers (.mkv, .avi, .mov) always need transcoding
        if suffix in VIDEO_ALWAYS_TRANSCODE:
            return True
        # iPod containers (.mp4, .m4v) — probe the codec
        return probe_video_needs_transcode(filepath)

    # Audio: extension-based check
    target = FORMAT_TARGETS.get(suffix, TranscodeTarget.AAC)
    return target != TranscodeTarget.COPY


def get_transcode_target(filepath: str | Path) -> TranscodeTarget:
    """Get the target format for a file.

    For video containers, returns VIDEO_H264 if transcoding is needed,
    COPY otherwise.
    """
    suffix = Path(filepath).suffix.lower()

    if suffix in VIDEO_CONTAINERS:
        if suffix in VIDEO_ALWAYS_TRANSCODE:
            return TranscodeTarget.VIDEO_H264
        # Probe iPod containers to decide
        if probe_video_needs_transcode(filepath):
            return TranscodeTarget.VIDEO_H264
        return TranscodeTarget.COPY

    return FORMAT_TARGETS.get(suffix, TranscodeTarget.AAC)


def _probe_duration_us(filepath: str | Path) -> int:
    """Probe a media file's duration in microseconds using ffprobe.

    Returns 0 on failure (caller should treat as unknown duration).
    """
    import json as _json

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return 0
    probe_bin = Path(ffmpeg).parent / (
        "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    )
    if not probe_bin.exists():
        probe_bin = Path(shutil.which("ffprobe") or "")
    if not probe_bin.exists():
        return 0

    try:
        result = subprocess.run(
            [
                str(probe_bin),
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(filepath),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            **_SP_KWARGS,
        )
        if result.returncode == 0:
            info = _json.loads(result.stdout)
            duration = float(info.get("format", {}).get("duration", 0))
            return int(duration * 1_000_000)
    except Exception:
        pass
    return 0


def _run_ffmpeg_with_progress(
    cmd: list[str],
    duration_us: int,
    progress_callback: Callable[[float], None],
    timeout: int,
) -> tuple[int, str]:
    """Run ffmpeg with ``-progress pipe:1`` and report progress.

    Parses ``out_time_us`` lines from ffmpeg's progress output to compute
    a 0.0–1.0 fraction, calling *progress_callback* periodically.

    Returns ``(returncode, stderr_text)``.
    """
    import threading

    # Insert -progress pipe:1 right after the ffmpeg binary
    full_cmd = [cmd[0], "-progress", "pipe:1", "-nostats"] + cmd[1:]

    proc = subprocess.Popen(
        full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_SP_KWARGS,
    )

    # Drain stderr in a background thread to prevent deadlock.
    # ffmpeg writes its banner + stats to stderr — if the pipe buffer
    # fills up while we're blocking on stdout, both processes deadlock.
    stderr_chunks: list[str] = []

    def _drain_stderr():
        assert proc.stderr is not None
        for chunk in proc.stderr:
            stderr_chunks.append(chunk)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    last_report = 0.0
    try:
        deadline = time.monotonic() + timeout
        assert proc.stdout is not None  # for type checker
        for line in proc.stdout:
            if time.monotonic() > deadline:
                proc.kill()
                return (-1, "Transcoding timed out")

            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    current_us = int(line.split("=", 1)[1])
                except (ValueError, IndexError):
                    continue
                if duration_us > 0:
                    frac = min(current_us / duration_us, 1.0)
                else:
                    frac = 0.0
                # Throttle callbacks to ~4/s
                now = time.monotonic()
                if now - last_report >= 0.25 or frac >= 1.0:
                    progress_callback(frac)
                    last_report = now

        stderr_thread.join(timeout=10)
        proc.wait(timeout=30)
    except Exception as e:
        proc.kill()
        stderr_thread.join(timeout=5)
        return (-1, str(e))

    return (proc.returncode, "".join(stderr_chunks))


def transcode(
    source_path: str | Path,
    output_dir: str | Path,
    output_filename: Optional[str] = None,
    ffmpeg_path: Optional[str] = None,
    aac_bitrate: int = 256,  # kbps for AAC encoding
    progress_callback: Optional[Callable[[float], None]] = None,
) -> TranscodeResult:
    """
    Transcode an audio/video file to iPod-compatible format.

    Args:
        source_path: Path to source audio/video file
        output_dir: Directory to write output file
        output_filename: Optional custom output filename (without extension)
        ffmpeg_path: Optional path to ffmpeg binary
        aac_bitrate: Bitrate for AAC encoding (kbps)
        progress_callback: Optional callback receiving a 0.0-1.0 float
            indicating transcode progress. Called periodically (~4/s)
            for video transcodes.

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

    # Read video CRF / preset from user settings (compatibility settings
    # like resolution, codec, and pixel format are always forced).
    crf = 23
    preset = "fast"
    try:
        from GUI.settings import get_settings
        _s = get_settings()
        crf = _s.video_crf
        preset = _s.video_preset
    except Exception:
        pass

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
    elif target == TranscodeTarget.VIDEO_H264:
        # Video transcoding to H.264 Baseline + stereo AAC in M4V container
        # iPod Classic: max 640x480, H.264 Baseline Profile Level 3.0, 8-bit
        # iPod Nano 3G+: max 320x240 (we target Classic specs; Nano will still play)
        #
        # Key flags:
        #   -pix_fmt yuv420p   → force 8-bit (10-bit sources like x265 need this)
        #   -ac 2              → downmix surround to stereo
        #   -crf 23            → quality-based encoding (good balance)
        #   scale filter       → fit within 640x480, force even dimensions
        #   -map 0:v:0 -map 0:a:0  → take first video + first audio stream only
        cmd = [
            ffmpeg,
            "-i", str(source_path),
            "-map", "0:v:0",           # First video stream only
            "-map", "0:a:0",           # First audio stream only
            "-vcodec", "libx264",
            "-profile:v", "baseline",
            "-level", "3.0",
            "-pix_fmt", "yuv420p",      # 8-bit output (critical for 10-bit sources)
            "-vf", (
                "scale='min(640,iw)':'-2'"
                ":force_original_aspect_ratio=decrease,"
                "scale='trunc(iw/2)*2':'trunc(ih/2)*2'"
            ),                          # Fit within 640 wide, even dimensions
            "-crf", str(crf),               # Quality-based encoding
            "-preset", preset,          # Speed/quality tradeoff
            "-acodec", "aac",
            "-ac", "2",                 # Stereo downmix
            "-b:a", f"{aac_bitrate}k",
            "-movflags", "+faststart",  # Streaming-friendly atom layout
            "-y",
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

        # Video transcoding may take significantly longer than audio
        timeout = 7200 if target == TranscodeTarget.VIDEO_H264 else 600

        # Use streaming progress for video when a callback is provided
        if progress_callback and target == TranscodeTarget.VIDEO_H264:
            duration_us = _probe_duration_us(source_path)
            returncode, stderr_text = _run_ffmpeg_with_progress(
                cmd, duration_us, progress_callback, timeout,
            )
            # Signal completion
            progress_callback(1.0)
        else:
            proc_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                **_SP_KWARGS,
            )
            returncode = proc_result.returncode
            stderr_text = proc_result.stderr

        if returncode != 0:
            return TranscodeResult(
                success=False,
                source_path=source_path,
                output_path=None,
                target_format=target,
                was_transcoded=True,
                error_message=f"ffmpeg failed: {stderr_text[:500]}",
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
    so this can be used to ensure tags are copied.  Uses both the
    easy-tag interface (for common tags) and the raw-tag interface
    (for podcast, TV show, sort, and other format-specific atoms
    that the easy interface cannot see).

    Args:
        source_path: Original file with metadata
        dest_path: Transcoded file to receive metadata

    Returns:
        True if successful
    """
    try:
        from mutagen import File as MutagenFile  # type: ignore[import-not-found]

        # --- Phase 1: easy-tag common fields ---
        source = MutagenFile(source_path, easy=True)
        dest = MutagenFile(dest_path, easy=True)

        if source is None or dest is None:
            return False

        # Copy common tags (skip keys the destination format doesn't support)
        for tag in ["title", "artist", "album", "albumartist", "genre",
                    "date", "tracknumber", "discnumber", "composer"]:
            if tag in source:
                try:
                    dest[tag] = source[tag]
                except (KeyError, ValueError):
                    pass

        dest.save()

        # --- Phase 2: raw-tag format-specific atoms ---
        # Re-open WITHOUT easy=True so we can access MP4 freeform atoms
        # and ID3 private frames.
        src_raw = MutagenFile(source_path)
        dst_raw = MutagenFile(dest_path)
        if src_raw is None or dst_raw is None:
            return True  # Phase 1 succeeded, phase 2 not possible

        src_tags = src_raw.tags
        dst_tags = dst_raw.tags
        if src_tags is None or dst_tags is None:
            return True

        # --- MP4/M4A → MP4/M4A raw atoms ---
        from mutagen.mp4 import MP4Tags
        if isinstance(src_tags, MP4Tags) and isinstance(dst_tags, MP4Tags):
            # Podcast atoms
            _MP4_COPY_KEYS = [
                "\xa9wrt",     # Composer (not in EasyMP4Tags)
                "pcst",        # Podcast flag
                "catg",        # Category
                "purl",        # Podcast URL
                "egid",        # Episode global ID
                "stik",        # Media kind (podcast=21, audiobook=2, etc.)
                "cpil",        # Compilation
                "rtng",        # Explicit/clean flag
                "tmpo",        # BPM
                "desc",        # Short description
                "ldes",        # Long description
                # TV show atoms
                "tvsh",        # TV show name
                "tvsn",        # TV season number
                "tves",        # TV episode number
                "tven",        # TV episode ID (e.g. "S01E05")
                "tvnn",        # TV network
                # Sort atoms
                "soar",        # Sort artist
                "sonm",        # Sort name
                "soal",        # Sort album
                "soaa",        # Sort album artist
                "soco",        # Sort composer
                "sosn",        # Sort show
            ]
            for key in _MP4_COPY_KEYS:
                if key in src_tags:
                    dst_tags[key] = src_tags[key]
            dst_raw.save()

        # --- ID3 (MP3) → ID3 raw frames ---
        from mutagen.id3 import ID3
        if isinstance(src_tags, ID3) and isinstance(dst_tags, ID3):
            # Copy podcast frames
            for frame_id in ("PCST", "TCAT", "WFED"):
                if frame_id in src_tags:
                    dst_tags.add(src_tags[frame_id])
            # Copy TXXX frames for podcast/sort metadata
            for frame in src_tags.getall("TXXX"):
                desc = getattr(frame, "desc", "")
                if desc in ("PODCAST", "CATEGORY", "PODCAST_URL"):
                    dst_tags.add(frame)
            dst_raw.save()

        return True

    except Exception as e:
        logger.warning(f"Could not copy metadata: {e}")
        return False
