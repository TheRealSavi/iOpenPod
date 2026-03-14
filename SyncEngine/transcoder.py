"""
Transcoder — Convert audio/video files to iPod-compatible formats via FFmpeg.

Supported conversions:
  FLAC/WAV/AIFF  → ALAC (lossless) or AAC (if prefer_lossy setting is on)
  OGG/Opus/WMA   → AAC
  Video           → M4V (H.264 Baseline + stereo AAC)
  Native formats  → re-encoded only when they exceed iPod hardware limits

iPod hardware limits enforced on every output:
  Sample rate  ≤ 48 000 Hz
  Channels     ≤ 2 (stereo)
  Bit depth    ≤ 16-bit   (ALAC only — AAC/MP3 are inherently ≤16-bit)
"""

import json as _json
import logging
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Suppress console flash on Windows
_SP_KWARGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)

# ── iPod hardware limits ────────────────────────────────────────────────────

IPOD_MAX_SAMPLE_RATE = 48_000   # Hz
IPOD_MAX_CHANNELS = 2           # Stereo
IPOD_MAX_BIT_DEPTH = 16         # ALAC/WAV ceiling

# Fallback video limits when no device is connected.
_DEFAULT_VIDEO_W = 640
_DEFAULT_VIDEO_H = 480

# ── Format classification ───────────────────────────────────────────────────


class TranscodeTarget(Enum):
    """What codec to produce."""
    ALAC = "alac"
    AAC = "aac"
    VIDEO_H264 = "video_h264"
    COPY = "copy"


# Extension sets — used by the target-resolution logic
_NON_NATIVE_LOSSLESS_EXTS = frozenset({".flac", ".wav", ".aif", ".aiff"})
_NON_NATIVE_LOSSY_EXTS = frozenset({".ogg", ".opus", ".wma"})
_NON_NATIVE_VIDEO_EXTS = frozenset({".mov", ".mkv", ".avi"})
IPOD_NATIVE_FORMATS = frozenset({".mp3", ".mp4", ".aac", ".m4a", ".m4b", ".m4p", ".m4v"})


_OUTPUT_EXT: dict[TranscodeTarget, str] = {
    TranscodeTarget.ALAC: ".m4a",
    TranscodeTarget.AAC: ".m4a",
    TranscodeTarget.VIDEO_H264: ".m4v",
}


# ── Result ──────────────────────────────────────────────────────────────────

@dataclass
class TranscodeResult:
    """Outcome of a single transcode / copy operation."""
    success: bool
    source_path: Path
    output_path: Optional[Path]
    target_format: TranscodeTarget
    was_transcoded: bool
    error_message: Optional[str] = None

    @property
    def ipod_format(self) -> str:
        if self.output_path:
            return self.output_path.suffix.lstrip(".")
        return self.source_path.suffix.lstrip(".")


# ═══════════════════════════════════════════════════════════════════════════
# Binary discovery
# ═══════════════════════════════════════════════════════════════════════════

def find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg (user setting → bundled → PATH → common dirs)."""
    try:
        from settings import get_settings
        custom = get_settings().ffmpeg_path
        if custom and Path(custom).is_file():
            return custom
    except Exception:
        pass
    try:
        from .dependency_manager import get_bundled_ffmpeg
        bundled = get_bundled_ffmpeg()
        if bundled:
            return bundled
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in (
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        "/usr/bin/ffmpeg",
    ):
        if Path(p).exists():
            return p
    return None


def is_ffmpeg_available() -> bool:
    return find_ffmpeg() is not None


def _find_ffprobe() -> Optional[str]:
    """Locate ffprobe (sibling of ffmpeg, then PATH)."""
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
        candidate = Path(ffmpeg).parent / name
        if candidate.exists():
            return str(candidate)
    return shutil.which("ffprobe")


@lru_cache(maxsize=1)
def _best_aac_encoder() -> str:
    """Return the best available AAC encoder.

    Preference: libfdk_aac (Fraunhofer) > aac_at (macOS AudioToolbox) > aac.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return "aac"
    try:
        r = subprocess.run(
            [ffmpeg, "-encoders"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=10, **_SP_KWARGS,
        )
        out = r.stdout
        for encoder in ("libfdk_aac", "aac_at", "aac"):
            if f" {encoder} " in out:
                logger.info("Using AAC encoder: %s", encoder)
                return encoder
    except Exception:
        pass
    return "aac"


# ═══════════════════════════════════════════════════════════════════════════
# Probing
# ═══════════════════════════════════════════════════════════════════════════

def _run_ffprobe(args: list[str], timeout: int = 30) -> Optional[dict]:
    """Run ffprobe with *args*, return parsed JSON or None."""
    probe = _find_ffprobe()
    if not probe:
        return None
    try:
        r = subprocess.run(
            [probe, "-v", "quiet", "-print_format", "json", *args],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout, **_SP_KWARGS,
        )
        if r.returncode == 0:
            return _json.loads(r.stdout)
    except Exception:
        pass
    return None


@dataclass(frozen=True)
class AudioProperties:
    """Probed audio-stream properties."""
    sample_rate: int = 0
    bits_per_sample: int = 0
    channels: int = 0

    def exceeds_ipod_limits(self) -> bool:
        return (
            self.sample_rate > IPOD_MAX_SAMPLE_RATE
            or self.bits_per_sample > IPOD_MAX_BIT_DEPTH
            or self.channels > IPOD_MAX_CHANNELS
        )


def probe_audio(filepath: str | Path) -> AudioProperties:
    """Probe the first audio stream for sample rate, bit depth, channels."""
    info = _run_ffprobe([
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,bits_per_raw_sample,channels",
        str(filepath),
    ])
    if not info:
        return AudioProperties()
    streams = info.get("streams", [])
    if not streams:
        return AudioProperties()
    s = streams[0]
    return AudioProperties(
        sample_rate=int(s.get("sample_rate", 0)),
        bits_per_sample=int(s.get("bits_per_raw_sample", 0) or 0),
        channels=int(s.get("channels", 0)),
    )


def probe_video_needs_transcode(
    filepath: str | Path,
    ffprobe_path: Optional[str] = None,
) -> bool:
    """True if a video file needs re-encoding for iPod compatibility."""
    probe = ffprobe_path or _find_ffprobe()
    if not probe:
        return True

    max_w, max_h = _get_video_limits()

    try:
        r = subprocess.run(
            [probe, "-v", "quiet", "-print_format", "json",
             "-show_streams", str(filepath)],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=120, **_SP_KWARGS,
        )
        if r.returncode != 0:
            return True
        streams = _json.loads(r.stdout).get("streams", [])
    except Exception:
        return True

    video_ok = audio_ok = False
    for s in streams:
        ct = s.get("codec_type")
        if ct == "video":
            if s.get("codec_name", "").lower() != "h264":
                return True
            if "10" in s.get("pix_fmt", ""):
                return True
            if int(s.get("width", 9999)) > max_w:
                return True
            if int(s.get("height", 9999)) > max_h:
                return True
            video_ok = True
        elif ct == "audio":
            if s.get("codec_name", "").lower() != "aac":
                return True
            if int(s.get("channels", 0)) > 2:
                return True
            audio_ok = True
    return not (video_ok and audio_ok)


def _probe_duration_us(filepath: str | Path) -> int:
    info = _run_ffprobe(["-show_format", str(filepath)], timeout=120)
    if not info:
        return 0
    try:
        return int(float(info.get("format", {}).get("duration", 0)) * 1_000_000)
    except (ValueError, TypeError):
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# Target resolution — "what should this file become?"
# ═══════════════════════════════════════════════════════════════════════════

def _read_prefer_lossy() -> bool:
    try:
        from settings import get_settings
        return bool(getattr(get_settings(), "prefer_lossy", False))
    except Exception:
        return False


def _get_video_limits() -> tuple[int, int]:
    """Return (max_width, max_height) for the currently connected iPod.

    Reads from ``DeviceCapabilities`` via ``device_info.get_current_device()``.
    Falls back to 640×480 when no device is connected or unrecognised.
    """
    try:
        from device_info import get_current_device
        from ipod_models import capabilities_for_family_gen
        dev = get_current_device()
        if dev and dev.model_family and dev.generation:
            caps = capabilities_for_family_gen(dev.model_family, dev.generation)
            if caps and caps.max_video_width > 0:
                return caps.max_video_width, caps.max_video_height
    except Exception:
        pass
    return _DEFAULT_VIDEO_W, _DEFAULT_VIDEO_H


def get_transcode_target(
    filepath: str | Path,
    *,
    prefer_lossy: Optional[bool] = None,
) -> TranscodeTarget:
    """Determine the target format for *filepath*.

    Decision tree:
      1. Video → probe → VIDEO_H264 or COPY
      2. Lossless source → ALAC (or AAC if prefer_lossy)
      3. Lossy non-native → AAC
      4. Native → COPY, unless iPod limits are exceeded
         (hi-res sample rate / 24-bit / surround)
         or prefer_lossy wants to shrink a native ALAC
    """
    suffix = Path(filepath).suffix.lower()

    # ── Non-native video — always transcode ─────────────────────────────
    if suffix in _NON_NATIVE_VIDEO_EXTS:
        return TranscodeTarget.VIDEO_H264

    if prefer_lossy is None:
        prefer_lossy = _read_prefer_lossy()

    # ── Non-native audio ────────────────────────────────────────────────
    if suffix in _NON_NATIVE_LOSSLESS_EXTS:
        return TranscodeTarget.AAC if prefer_lossy else TranscodeTarget.ALAC
    if suffix in _NON_NATIVE_LOSSY_EXTS:
        return TranscodeTarget.AAC

    # ── Native formats ──────────────────────────────────────────────────
    if suffix in IPOD_NATIVE_FORMATS:
        # Native video — probe codec compatibility
        if suffix in {".mp4", ".m4v"}:
            return (TranscodeTarget.VIDEO_H264
                    if probe_video_needs_transcode(filepath)
                    else TranscodeTarget.COPY)

        # Native audio — probe for iPod limits
        props = probe_audio(filepath)

        if props.exceeds_ipod_limits():
            if suffix in {".m4a", ".m4b"} and not prefer_lossy:
                return TranscodeTarget.ALAC
            return TranscodeTarget.AAC

        # User wants to shrink native ALAC → AAC
        # (bits_per_sample ≥ 16 distinguishes ALAC from AAC which reports 0)
        if prefer_lossy and suffix in {".m4a", ".m4b"} and props.bits_per_sample >= 16:
            return TranscodeTarget.AAC

        return TranscodeTarget.COPY

    # Unknown extension — AAC is the safest bet
    return TranscodeTarget.AAC


def needs_transcoding(
    filepath: str | Path,
    *,
    prefer_lossy: Optional[bool] = None,
) -> bool:
    """True if the file needs any conversion before it can go on iPod."""
    return get_transcode_target(filepath, prefer_lossy=prefer_lossy) != TranscodeTarget.COPY


# ═══════════════════════════════════════════════════════════════════════════
# AAC quality presets
# ═══════════════════════════════════════════════════════════════════════════

# Nominal bitrate for each quality tier (used for cache keys and track
# metadata — the actual encode may be VBR so the real bitrate varies).
_QUALITY_BITRATE: dict[str, int] = {
    "high": 320,
    "normal": 256,
    "compact": 128,
    "spoken": 64,
}

# Per-encoder flags for each quality tier.
_AAC_QUALITY_MAP: dict[str, dict[str, list[str]]] = {
    "libfdk_aac": {
        "high": ["-vbr", "5"],
        "normal": ["-vbr", "4"],
        "compact": ["-vbr", "3"],
        "spoken": ["-vbr", "2"],
    },
    "aac_at": {
        "high": ["-aac_at_mode", "cvbr", "-b:a", "320k"],
        "normal": ["-aac_at_mode", "cvbr", "-b:a", "256k"],
        "compact": ["-aac_at_mode", "cvbr", "-b:a", "128k"],
        "spoken": ["-b:a", "64k"],
    },
    "aac": {
        "high": ["-b:a", "320k"],
        "normal": ["-b:a", "256k"],
        "compact": ["-b:a", "128k"],
        "spoken": ["-b:a", "64k"],
    },
}


def quality_to_nominal_bitrate(quality: str) -> int:
    """Return the nominal bitrate (kbps) for a quality preset string."""
    return _QUALITY_BITRATE.get(quality, 256)


def _aac_quality_args(quality: str) -> list[str]:
    """Return encoder-specific ffmpeg flags for the given quality preset."""
    encoder = _best_aac_encoder()
    presets = _AAC_QUALITY_MAP.get(encoder, _AAC_QUALITY_MAP["aac"])
    return list(presets.get(quality, presets["normal"]))


# ═══════════════════════════════════════════════════════════════════════════
# FFmpeg command builders
# ═══════════════════════════════════════════════════════════════════════════

def _cmd_alac(ffmpeg: str, src: str, dst: str) -> list[str]:
    # Only downsample when the source exceeds the iPod hardware limit.
    # Unconditionally forcing -ar 48000 on a 44.1 kHz source upsamples the
    # audio while leaving sample_count in iTunesDB at the 44.1 kHz value,
    # causing the iPod to miscalculate the track end and skip ~20 s early.
    props = probe_audio(src)
    ar_args = (
        ["-ar", str(IPOD_MAX_SAMPLE_RATE)]
        if props.sample_rate == 0 or props.sample_rate > IPOD_MAX_SAMPLE_RATE
        else []
    )
    return [
        ffmpeg, "-i", src,
        "-vn",
        "-acodec", "alac",
        *ar_args,
        "-sample_fmt", "s16p",
        "-ac", str(IPOD_MAX_CHANNELS),
        "-y", dst,
    ]


def _cmd_aac(ffmpeg: str, src: str, dst: str, quality: str) -> list[str]:
    # Same rationale as _cmd_alac: preserve source rate unless it exceeds limits.
    props = probe_audio(src)
    ar_args = (
        ["-ar", str(IPOD_MAX_SAMPLE_RATE)]
        if props.sample_rate == 0 or props.sample_rate > IPOD_MAX_SAMPLE_RATE
        else []
    )
    return [
        ffmpeg, "-i", src,
        "-vn",
        "-acodec", _best_aac_encoder(),
        *ar_args,
        "-ac", str(IPOD_MAX_CHANNELS),
        *_aac_quality_args(quality),
        "-y", dst,
    ]


def _cmd_video(
    ffmpeg: str, src: str, dst: str,
    quality: str, crf: int, preset: str,
) -> list[str]:
    max_w, max_h = _get_video_limits()

    # Rotate portrait videos 90° CW when the target is landscape —
    # a tiny centred strip wastes most of the iPod's fixed-landscape screen.
    # passthrough=landscape means "leave landscape videos alone, only rotate
    # portrait ones".  Applied before scaling so dimensions are correct.
    vf_parts: list[str] = []
    if max_w > max_h:
        vf_parts.append("transpose=1:passthrough=landscape")
    vf_parts.append(
        f"scale={max_w}:{max_h}"
        ":force_original_aspect_ratio=decrease,"
        "scale='trunc(iw/2)*2':'trunc(ih/2)*2'"
    )

    return [
        ffmpeg, "-i", src,
        "-map", "0:v:0", "-map", "0:a:0",
        "-vcodec", "libx264",
        "-profile:v", "baseline", "-level", "3.0",
        "-pix_fmt", "yuv420p",
        "-vf", ",".join(vf_parts),
        "-crf", str(crf), "-preset", preset,
        "-acodec", _best_aac_encoder(),
        "-ac", str(IPOD_MAX_CHANNELS),
        "-ar", str(IPOD_MAX_SAMPLE_RATE),
        *_aac_quality_args(quality),
        "-movflags", "+faststart",
        "-y", dst,
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Transcode execution
# ═══════════════════════════════════════════════════════════════════════════

def transcode(
    source_path: str | Path,
    output_dir: str | Path,
    output_filename: Optional[str] = None,
    ffmpeg_path: Optional[str] = None,
    aac_quality: str = "normal",
    progress_callback: Optional[Callable[[float], None]] = None,
    *,
    prefer_lossy: Optional[bool] = None,
) -> TranscodeResult:
    """Transcode (or copy) *source_path* into *output_dir*.

    All iPod hardware limits are enforced automatically.
    Set *prefer_lossy* to force lossless sources to AAC.
    """
    source_path = Path(source_path)
    output_dir = Path(output_dir)

    if not source_path.exists():
        return TranscodeResult(
            success=False, source_path=source_path, output_path=None,
            target_format=TranscodeTarget.COPY, was_transcoded=False,
            error_message=f"Source file not found: {source_path}",
        )

    target = get_transcode_target(source_path, prefer_lossy=prefer_lossy)
    base_name = output_filename or source_path.stem

    # ── COPY ────────────────────────────────────────────────────────────
    if target == TranscodeTarget.COPY:
        out = output_dir / (base_name + source_path.suffix)
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, out)
            return TranscodeResult(
                success=True, source_path=source_path, output_path=out,
                target_format=target, was_transcoded=False,
            )
        except Exception as e:
            return TranscodeResult(
                success=False, source_path=source_path, output_path=None,
                target_format=target, was_transcoded=False,
                error_message=str(e),
            )

    # ── Transcode ───────────────────────────────────────────────────────
    ffmpeg = ffmpeg_path or find_ffmpeg()
    if not ffmpeg:
        return TranscodeResult(
            success=False, source_path=source_path, output_path=None,
            target_format=target, was_transcoded=False,
            error_message="ffmpeg not found",
        )

    ext = _OUTPUT_EXT[target]
    out = output_dir / (base_name + ext)
    src, dst = str(source_path), str(out)

    crf, preset = 23, "fast"
    try:
        from settings import get_settings
        _s = get_settings()
        crf = _s.video_crf
        preset = _s.video_preset
    except Exception:
        pass

    if target == TranscodeTarget.ALAC:
        cmd = _cmd_alac(ffmpeg, src, dst)
    elif target == TranscodeTarget.AAC:
        cmd = _cmd_aac(ffmpeg, src, dst, aac_quality)
    else:
        cmd = _cmd_video(ffmpeg, src, dst, aac_quality, crf, preset)

    return _run_transcode(cmd, source_path, out, target, progress_callback)


def _run_transcode(
    cmd: list[str],
    source_path: Path,
    output_path: Path,
    target: TranscodeTarget,
    progress_callback: Optional[Callable[[float], None]],
) -> TranscodeResult:
    """Run an ffmpeg command and return a TranscodeResult."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        timeout = 7200 if target == TranscodeTarget.VIDEO_H264 else 600

        if progress_callback and target == TranscodeTarget.VIDEO_H264:
            dur = _probe_duration_us(source_path)
            returncode, stderr = _run_ffmpeg_with_progress(
                cmd, dur, progress_callback, timeout,
            )
            progress_callback(1.0)
        else:
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                timeout=timeout, **_SP_KWARGS,
            )
            returncode, stderr = r.returncode, r.stderr

        if returncode != 0:
            return TranscodeResult(
                success=False, source_path=source_path, output_path=None,
                target_format=target, was_transcoded=True,
                error_message=f"ffmpeg failed: {stderr[:500]}",
            )
        if not output_path.exists():
            return TranscodeResult(
                success=False, source_path=source_path, output_path=None,
                target_format=target, was_transcoded=True,
                error_message="Output file not created",
            )
        logger.info("Transcoded %s → %s", source_path.name, output_path.name)
        return TranscodeResult(
            success=True, source_path=source_path, output_path=output_path,
            target_format=target, was_transcoded=True,
        )
    except subprocess.TimeoutExpired:
        return TranscodeResult(
            success=False, source_path=source_path, output_path=None,
            target_format=target, was_transcoded=True,
            error_message="Transcoding timed out",
        )
    except Exception as e:
        return TranscodeResult(
            success=False, source_path=source_path, output_path=None,
            target_format=target, was_transcoded=True,
            error_message=str(e),
        )


def _run_ffmpeg_with_progress(
    cmd: list[str],
    duration_us: int,
    progress_callback: Callable[[float], None],
    timeout: int,
) -> tuple[int, str]:
    """Run ffmpeg with ``-progress pipe:1`` and stream progress."""
    import threading

    full_cmd = [cmd[0], "-progress", "pipe:1", "-nostats"] + cmd[1:]
    proc = subprocess.Popen(
        full_cmd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
        **_SP_KWARGS,
    )

    stderr_chunks: list[str] = []

    def _drain():
        assert proc.stderr is not None
        for chunk in proc.stderr:
            stderr_chunks.append(chunk)

    t = threading.Thread(target=_drain, daemon=True)
    t.start()

    last_report = 0.0
    try:
        deadline = time.monotonic() + timeout
        assert proc.stdout is not None
        for line in proc.stdout:
            if time.monotonic() > deadline:
                proc.kill()
                return -1, "Transcoding timed out"
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    current = int(line.split("=", 1)[1])
                except (ValueError, IndexError):
                    continue
                frac = min(current / duration_us, 1.0) if duration_us > 0 else 0.0
                now = time.monotonic()
                if now - last_report >= 0.25 or frac >= 1.0:
                    progress_callback(frac)
                    last_report = now
        t.join(timeout=10)
        proc.wait(timeout=30)
    except Exception as e:
        proc.kill()
        t.join(timeout=5)
        return -1, str(e)

    return proc.returncode, "".join(stderr_chunks)


# ═══════════════════════════════════════════════════════════════════════════
# Metadata copy
# ═══════════════════════════════════════════════════════════════════════════

_MP4_COPY_KEYS = [
    "\xa9wrt",                                      # Composer
    "pcst", "catg", "purl", "egid", "stik",         # Podcast
    "cpil", "rtng", "tmpo", "desc", "ldes",         # Misc
    "tvsh", "tvsn", "tves", "tven", "tvnn",         # TV show
    "soar", "sonm", "soal", "soaa", "soco", "sosn",  # Sort
]


def copy_metadata(source_path: str | Path, dest_path: str | Path) -> bool:
    """Copy metadata tags from *source_path* to *dest_path*.

    Phase 1: common tags via mutagen's easy interface.
    Phase 2: format-specific atoms (podcast/TV/sort) via raw tags.
    """
    try:
        from mutagen._file import File as MutagenFile

        # Phase 1 — common tags
        src = MutagenFile(source_path, easy=True)
        dst = MutagenFile(dest_path, easy=True)
        if src is None or dst is None:
            return False
        for tag in (
            "title", "artist", "album", "albumartist", "genre",
            "date", "tracknumber", "discnumber", "composer",
        ):
            if tag in src:
                try:
                    dst[tag] = src[tag]
                except (KeyError, ValueError):
                    pass
        dst.save()

        # Phase 2 — raw atoms / frames
        src_raw = MutagenFile(source_path)
        dst_raw = MutagenFile(dest_path)
        if src_raw is None or dst_raw is None:
            return True
        src_tags, dst_tags = src_raw.tags, dst_raw.tags
        if src_tags is None or dst_tags is None:
            return True

        from mutagen.mp4 import MP4Tags
        if isinstance(src_tags, MP4Tags) and isinstance(dst_tags, MP4Tags):
            for key in _MP4_COPY_KEYS:
                if key in src_tags:
                    dst_tags[key] = src_tags[key]
            dst_raw.save()

        from mutagen.id3 import ID3
        if isinstance(src_tags, ID3) and isinstance(dst_tags, ID3):
            for frame_id in ("PCST", "TCAT", "WFED"):
                if frame_id in src_tags:
                    dst_tags.add(src_tags[frame_id])
            for frame in src_tags.getall("TXXX"):
                if getattr(frame, "desc", "") in ("PODCAST", "CATEGORY", "PODCAST_URL"):
                    dst_tags.add(frame)
            dst_raw.save()

        return True
    except Exception as e:
        logger.warning("Could not copy metadata: %s", e)
        return False
