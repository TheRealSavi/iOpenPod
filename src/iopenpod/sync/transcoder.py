"""
Transcoder — Convert audio/video files to iPod-compatible formats via FFmpeg.

Supported conversions:
    FLAC/AIFF      → ALAC (lossless) or lossy (AAC/MP3 when prefer_lossy is on)
    WAV            → copy, ALAC, or lossy depending on user settings
    OGG/Opus/WMA   → lossy (AAC/MP3)
  Video           → iPod M4V (H.264 Baseline + stereo AAC), or MOV for CEA-608
  Native formats  → re-encoded only when they exceed iPod hardware limits

iPod hardware limits enforced on every output:
  Sample rate  ≤ 48 000 Hz
  Channels     ≤ 2 (stereo)
  Bit depth    ≤ 16-bit   (ALAC only — AAC/MP3 are inherently ≤16-bit)
"""

import json as _json
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, ClassVar, Literal

from ._formats import (
    IPOD_NATIVE_FORMATS,
)
from ._formats import (
    NON_NATIVE_LOSSLESS as _NON_NATIVE_LOSSLESS_EXTS,
)
from ._formats import (
    NON_NATIVE_LOSSY as _NON_NATIVE_LOSSY_EXTS,
)
from ._formats import (
    NON_NATIVE_VIDEO as _NON_NATIVE_VIDEO_EXTS,
)

logger = logging.getLogger(__name__)

# Suppress console flash on Windows
_SP_KWARGS: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
)

# ── iPod hardware limits ────────────────────────────────────────────────────

IPOD_MAX_SAMPLE_RATE = 48_000   # Hz
IPOD_MAX_CHANNELS = 2           # Stereo
IPOD_MAX_BIT_DEPTH = 16         # ALAC/WAV ceiling
# Preserve reasonable audio quality for video transcodes.
IPOD_MAX_VIDEO_AUDIO_BITRATE_KBPS = 320

# Fallback video limits when device detection fails.
_DEFAULT_VIDEO_W = 640
_DEFAULT_VIDEO_H = 480

# ── Format classification ───────────────────────────────────────────────────


class TranscodeTarget(Enum):
    """What codec to produce."""
    ALAC = "alac"
    AAC = "aac"
    MP3 = "mp3"
    VIDEO_H264 = "video_h264"
    VIDEO_TRANSCODE_AUDIO = "video_transcode_audio"
    VIDEO_TRANSCODE_VIDEO = "video_transcode_video"
    VIDEO_REMUX = "video_remux"
    COPY = "copy"


_OUTPUT_EXT: dict[TranscodeTarget, str] = {
    TranscodeTarget.ALAC: ".m4a",
    TranscodeTarget.AAC: ".m4a",
    TranscodeTarget.MP3: ".mp3",
    TranscodeTarget.VIDEO_H264: ".m4v",
    TranscodeTarget.VIDEO_TRANSCODE_AUDIO: ".m4v",
    TranscodeTarget.VIDEO_TRANSCODE_VIDEO: ".m4v",
    TranscodeTarget.VIDEO_REMUX: ".m4v",
}

_VIDEO_TRANSCODE_TARGETS: frozenset[TranscodeTarget] = frozenset({
    TranscodeTarget.VIDEO_H264,
    TranscodeTarget.VIDEO_TRANSCODE_AUDIO,
    TranscodeTarget.VIDEO_TRANSCODE_VIDEO,
    TranscodeTarget.VIDEO_REMUX,
})

_VALID_LOSSY_ENCODERS: frozenset[str] = frozenset(
    {"auto", "libfdk_aac", "aac_at", "aac", "libmp3lame", "libshine"}
)
_VALID_QUALITY_LEVELS: frozenset[str] = frozenset({"high", "balanced", "compact"})
_VALID_BITRATE_MODES: frozenset[str] = frozenset({"cbr", "abr", "vbr", "cvbr"})

# Approximate kbps for aac_at VBR quality q0–q14 (for size estimation)
_AAC_AT_VBR_Q_KBPS: dict[int, int] = {
    0: 256, 1: 240, 2: 224, 3: 192, 4: 176, 5: 160,
    6: 144, 7: 128, 8: 112, 9: 96, 10: 80, 11: 72,
    12: 64, 13: 56, 14: 48,
}

# Approximate kbps for libfdk_aac VBR levels 1-5 (for size estimation)
_FDK_VBR_KBPS: dict[int, int] = {1: 32, 2: 64, 3: 96, 4: 128, 5: 192}
# Approximate kbps for libmp3lame VBR q0-q9 (for size estimation)
_MP3_VBR_Q_KBPS: dict[int, int] = {0: 245, 1: 225, 2: 190, 3: 175, 4: 165, 5: 130, 6: 115, 7: 100, 8: 85, 9: 65}

# Music bitrate per quality preset — used for AAC/CBR and spoken-word estimates
_QUALITY_MUSIC_KBPS: dict[str, int] = {"high": 256, "balanced": 192, "compact": 128}

# libmp3lame VBR q-value per quality preset (-q:a N, lower = better)
_QUALITY_MP3_VBR_Q: dict[str, int] = {"high": 2, "balanced": 4, "compact": 6}


# Approximate kbps for those VBR levels — for size estimation
_QUALITY_MP3_KBPS: dict[str, int] = {"high": 190, "balanced": 130, "compact": 100}

_VALID_X264_PRESETS: frozenset[str] = frozenset({
    "ultrafast", "superfast", "veryfast", "faster", "fast", "medium",
    "slow", "slower", "veryslow",
})

_AUDIO_TRANSCODE_TIMEOUT_FLOOR_S = 10 * 60
_AUDIO_TRANSCODE_TIMEOUT_PADDING_S = 10 * 60
_AUDIO_TRANSCODE_TIMEOUT_CEILING_S = 12 * 60 * 60
_VIDEO_TRANSCODE_TIMEOUT_FLOOR_S = 2 * 60 * 60
_VIDEO_TRANSCODE_TIMEOUT_PADDING_S = 30 * 60
_VIDEO_TRANSCODE_TIMEOUT_CEILING_S = 24 * 60 * 60


def _read_setting_str(settings: object, key: str, default: str) -> str:
    value = getattr(settings, key, default)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _read_setting_int(settings: object, key: str, default: int) -> int:
    value = getattr(settings, key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_choice(value: str, *, allowed: frozenset[str], default: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in allowed:
        return normalized
    return default


def _clamp_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


@dataclass(frozen=True)
class TranscodeOptions:
    """User-configurable transcoding options for one operation."""

    ffmpeg_path: str = ""
    prefer_lossy: bool = False
    always_encode_lossy: bool = False
    convert_wav_to_alac: bool = True
    normalize_sample_rate: bool = False
    mono_for_spoken: bool = True
    smart_quality_by_type: bool = True
    video_crf: int = 23
    video_preset: str = "medium"
    lossy_encoder: str = "auto"
    lossy_quality: str = "balanced"
    bitrate_mode: str = "cbr"
    music_lossy_cbr_bitrate: int = 192
    vbr_level: int = 4
    spoken_lossy_cbr_bitrate: int = 64
    aac_cutoff: int = 0
    aac_tns: bool = True
    aac_pns: bool = False
    aac_ms_stereo: bool = True
    aac_intensity_stereo: bool = True
    fdk_afterburner: bool = True

    def normalized(self) -> "TranscodeOptions":
        """Return a validated copy with sane bounds and allowed enum values."""
        return replace(
            self,
            video_crf=_clamp_int(int(self.video_crf), minimum=0, maximum=51),
            video_preset=_normalize_choice(
                self.video_preset,
                allowed=_VALID_X264_PRESETS,
                default="medium",
            ),
            lossy_encoder=_normalize_choice(
                self.lossy_encoder,
                allowed=_VALID_LOSSY_ENCODERS,
                default="auto",
            ),
            lossy_quality=_normalize_choice(
                self.lossy_quality,
                allowed=_VALID_QUALITY_LEVELS,
                default="balanced",
            ),
            bitrate_mode=_normalize_choice(
                self.bitrate_mode,
                allowed=_VALID_BITRATE_MODES,
                default="cbr",
            ),
            music_lossy_cbr_bitrate=_clamp_int(
                int(self.music_lossy_cbr_bitrate), minimum=32, maximum=320
            ),
            vbr_level=_clamp_int(int(self.vbr_level), minimum=0, maximum=14),
            spoken_lossy_cbr_bitrate=_clamp_int(
                int(self.spoken_lossy_cbr_bitrate), minimum=24, maximum=192
            ),
            aac_cutoff=_clamp_int(int(self.aac_cutoff), minimum=0, maximum=22050),
        )

    @classmethod
    def from_settings(cls, settings: object) -> "TranscodeOptions":
        return cls(
            ffmpeg_path=_read_setting_str(settings, "ffmpeg_path", ""),
            prefer_lossy=bool(getattr(settings, "prefer_lossy", False)),
            always_encode_lossy=bool(getattr(settings, "always_encode_lossy", False)),
            convert_wav_to_alac=bool(getattr(settings, "convert_wav_to_alac", True)),
            normalize_sample_rate=bool(getattr(settings, "normalize_sample_rate", False)),
            mono_for_spoken=bool(getattr(settings, "mono_for_spoken", True)),
            smart_quality_by_type=bool(getattr(settings, "smart_quality_by_type", True)),
            video_crf=_read_setting_int(settings, "video_crf", 23),
            video_preset=_read_setting_str(settings, "video_preset", "medium"),
            lossy_encoder=_read_setting_str(settings, "lossy_encoder", "auto"),
            lossy_quality=_read_setting_str(settings, "lossy_quality", "balanced"),
            bitrate_mode=_read_setting_str(settings, "bitrate_mode", "cbr"),
            music_lossy_cbr_bitrate=_read_setting_int(settings, "music_lossy_cbr_bitrate", 192),
            vbr_level=_read_setting_int(settings, "vbr_level", 4),
            spoken_lossy_cbr_bitrate=_read_setting_int(settings, "spoken_lossy_cbr_bitrate", 64),
            aac_cutoff=_read_setting_int(settings, "aac_cutoff", 0),
            aac_tns=bool(getattr(settings, "aac_tns", True)),
            aac_pns=bool(getattr(settings, "aac_pns", False)),
            aac_ms_stereo=bool(getattr(settings, "aac_ms_stereo", True)),
            aac_intensity_stereo=bool(getattr(settings, "aac_intensity_stereo", True)),
            fdk_afterburner=bool(getattr(settings, "fdk_afterburner", True)),
        ).normalized()


@dataclass(frozen=True)
class _ResolvedLossyPolicy:
    """Lossy codec policy resolved from user preferences and ffmpeg availability."""

    target: TranscodeTarget
    encoder: str


@dataclass(frozen=True)
class TranscodePlan:
    """Resolved transcode policy for a source file.

    This is the shared decision object used by the transcoder, sync executor,
    and storage estimator so target selection and bitrate assumptions do not
    drift apart.
    """

    source_path: Path
    target: TranscodeTarget
    aac_quality: str
    effective_quality: str
    prefer_lossy: bool
    normalize_sample_rate: bool
    mono_for_spoken: bool
    smart_quality_by_type: bool
    video_crf: int
    video_preset: str
    video_max_width: int
    video_max_height: int
    video_max_fps: int
    video_max_bitrate_kbps: int
    video_h264_level: str
    video_audio_bitrate_kbps: int | None = None
    video_output_muxer: Literal["ipod", "mov"] = "ipod"
    lossy_encoder: str = "aac"       # resolved encoder (e.g. "libfdk_aac")
    user_lossy_encoder: str = "auto"  # original user preference (e.g. "auto")
    lossy_quality: str = "balanced"
    bitrate_mode: str = "cbr"
    music_lossy_cbr_bitrate: int = 192
    vbr_level: int = 4
    spoken_lossy_cbr_bitrate: int = 64

    @property
    def is_spoken(self) -> bool:
        return self.effective_quality == "spoken"

    @property
    def output_extension(self) -> str:
        if self.target in _VIDEO_TRANSCODE_TARGETS and self.video_output_muxer == "mov":
            return ".mov"
        return _OUTPUT_EXT.get(self.target, self.source_path.suffix)

    @property
    def cache_target_format(self) -> str:
        if self.target == TranscodeTarget.ALAC:
            return "alac"
        if self.target == TranscodeTarget.AAC:
            return "aac"
        if self.target == TranscodeTarget.MP3:
            return "mp3"
        if self.target in _VIDEO_TRANSCODE_TARGETS:
            return "mov" if self.video_output_muxer == "mov" else "m4v"
        return self.source_path.suffix.lstrip(".")

    @property
    def cache_bitrate_kbps(self) -> int | None:
        if self.target == TranscodeTarget.AAC:
            return self._nominal_lossy_bitrate(self.effective_quality)
        if self.target == TranscodeTarget.MP3:
            return self._estimated_mp3_kbps()
        return None

    def estimate_output_size(self, *, source_size: int, duration_ms: int) -> int:
        """Estimate the post-transcode size in bytes.

        All estimates are a flat duration × nominal-CBR formula — no probing
        or sampling. Accuracy is "good enough for a storage bar"; the sync
        pipeline relies on exact disk sizes once files are written.
        """
        if self.target == TranscodeTarget.COPY:
            return source_size

        duration_seconds = duration_ms / 1000.0

        if self.target == TranscodeTarget.AAC:
            bitrate_kbps = self._estimated_aac_kbps()
            return int((duration_seconds * bitrate_kbps * 1000) / 8)

        if self.target == TranscodeTarget.MP3:
            bitrate_kbps = self._estimated_mp3_kbps()
            return int((duration_seconds * bitrate_kbps * 1000) / 8)

        if self.target == TranscodeTarget.ALAC:
            # WAV/AIFF → assume CD-quality PCM (1411 kbps) at ~55% ALAC ratio.
            # Other lossless inputs (FLAC etc.) are already compressed, so the
            # source size is the best no-probe estimate.
            suffix = self.source_path.suffix.lower()
            if suffix in {".wav", ".aif", ".aiff"} and duration_seconds > 0:
                return int((duration_seconds * 1411 * 1000 * 0.55) / 8)

            if source_size > 0:
                return source_size

            return int((duration_seconds * 900 * 1000) / 8)

        if self.target == TranscodeTarget.VIDEO_H264:
            return int((duration_seconds * self._estimated_video_kbps() * 1000) / 8)

        if self.target in {
            TranscodeTarget.VIDEO_REMUX,
            TranscodeTarget.VIDEO_TRANSCODE_AUDIO,
            TranscodeTarget.VIDEO_TRANSCODE_VIDEO,
        }:
            return source_size

        return source_size

    def _estimated_aac_kbps(self) -> int:
        if self.is_spoken:
            return self.spoken_lossy_cbr_bitrate
        is_manual = self.user_lossy_encoder not in {"auto", ""}
        if is_manual and self.bitrate_mode == "vbr":
            if self.lossy_encoder == "libfdk_aac":
                return _FDK_VBR_KBPS.get(_clamp_int(self.vbr_level, minimum=1, maximum=5), 128)
            if self.lossy_encoder == "aac_at":
                return _AAC_AT_VBR_Q_KBPS.get(_clamp_int(self.vbr_level, minimum=0, maximum=14), 128)
        if is_manual:
            return self.music_lossy_cbr_bitrate
        return _QUALITY_MUSIC_KBPS.get(self.lossy_quality, 192)

    def _estimated_mp3_kbps(self) -> int:
        if self.is_spoken:
            return self.spoken_lossy_cbr_bitrate
        is_manual = self.user_lossy_encoder not in {"auto", ""}
        if is_manual and self.bitrate_mode == "vbr" and self.lossy_encoder == "libmp3lame":
            return _MP3_VBR_Q_KBPS.get(_clamp_int(self.vbr_level, minimum=0, maximum=9), 165)
        if is_manual:
            return self.music_lossy_cbr_bitrate
        if self.lossy_encoder == "libmp3lame":
            return _QUALITY_MP3_KBPS.get(self.lossy_quality, 130)
        return _QUALITY_MUSIC_KBPS.get(self.lossy_quality, 192)

    def _nominal_lossy_bitrate(self, quality: str) -> int:
        if quality == "spoken":
            return self.spoken_lossy_cbr_bitrate
        return self._estimated_aac_kbps()

    def _estimated_video_kbps(self) -> int:
        """Rough CBR bitrate (kbps) for H.264 output at the plan's CRF.

        Model: ``kbps ≈ W × H × fps × bpp``, with ``bpp ≈ 0.10`` at CRF 23,
        scaled by ``2^((23 − crf) / 6)`` (each 6-point CRF step halves or
        doubles bitrate). Clamped to the device bitrate cap.
        """
        width = self.video_max_width or _DEFAULT_VIDEO_W
        height = self.video_max_height or _DEFAULT_VIDEO_H
        fps = self.video_max_fps or _DEFAULT_VIDEO_FPS
        base_kbps = (width * height * fps * 0.10) / 1000.0
        crf_scale = 2 ** ((23 - self.video_crf) / 6)
        est = int(base_kbps * crf_scale)
        cap = self.video_max_bitrate_kbps or 2500
        return max(64, min(est, cap))


def resolve_transcode_plan(
    filepath: str | Path,
    *,
    aac_quality: str | None = None,
    prefer_lossy: bool | None = None,
    is_spoken_content: bool = False,
    options: TranscodeOptions | None = None,
) -> TranscodePlan:
    """Resolve the full transcode policy for *filepath*.

    This calls the same target-selection logic used by :func:`transcode` and
    captures the user settings that influence the output command.

    ``aac_quality`` is a legacy override hint.  Only ``"spoken"`` is treated
    specially; all other values are normalized to music quality.
    ``is_spoken_content`` carries audiobook or podcast classification from the
    library scanner when the source file does not have usable MP4 tags.
    """
    source_path = Path(filepath)
    options = (options or TranscodeOptions()).normalized()
    if prefer_lossy is None:
        prefer_lossy = options.prefer_lossy

    lossy_policy = _resolve_lossy_policy(options)
    target = get_transcode_target(
        source_path,
        prefer_lossy=prefer_lossy,
        options=options,
    )
    video_output_muxer = _video_output_muxer(source_path, target)
    normalize_sample_rate = options.normalize_sample_rate
    mono_for_spoken = options.mono_for_spoken
    smart_quality_by_type = options.smart_quality_by_type

    effective_quality = _resolve_effective_quality(
        source_path,
        target,
        aac_quality=aac_quality,
        is_spoken_content=is_spoken_content,
        smart_quality_by_type=smart_quality_by_type,
    )

    max_width, max_height, max_fps, max_bitrate_kbps, h264_level = _get_video_caps()
    video_audio_bitrate_kbps = None
    if target in {TranscodeTarget.VIDEO_H264, TranscodeTarget.VIDEO_TRANSCODE_AUDIO}:
        video_audio_bitrate_kbps = probe_audio(source_path).bitrate_kbps

    return TranscodePlan(
        source_path=source_path,
        target=target,
        aac_quality=aac_quality or "normal",
        effective_quality=effective_quality,
        prefer_lossy=prefer_lossy,
        normalize_sample_rate=normalize_sample_rate,
        mono_for_spoken=mono_for_spoken,
        smart_quality_by_type=smart_quality_by_type,
        video_crf=options.video_crf,
        video_preset=options.video_preset,
        video_max_width=max_width,
        video_max_height=max_height,
        video_max_fps=max_fps,
        video_max_bitrate_kbps=max_bitrate_kbps,
        video_h264_level=h264_level,
        video_audio_bitrate_kbps=video_audio_bitrate_kbps,
        video_output_muxer=video_output_muxer,
        lossy_encoder=lossy_policy.encoder,
        user_lossy_encoder=options.lossy_encoder,
        lossy_quality=options.lossy_quality,
        bitrate_mode=options.bitrate_mode,
        music_lossy_cbr_bitrate=options.music_lossy_cbr_bitrate,
        vbr_level=options.vbr_level,
        spoken_lossy_cbr_bitrate=options.spoken_lossy_cbr_bitrate,
    )


def _resolve_effective_quality(
    source_path: Path,
    target: TranscodeTarget,
    *,
    aac_quality: str | None,
    is_spoken_content: bool,
    smart_quality_by_type: bool,
) -> str:
    """Resolve legacy quality hint plus spoken-word auto-detection."""
    if not smart_quality_by_type:
        return "normal"

    if _is_spoken_quality(aac_quality or ""):
        return "spoken"

    if target in {TranscodeTarget.AAC, TranscodeTarget.MP3}:
        if is_spoken_content:
            return "spoken"
        media_type = _probe_media_type(source_path)
        if media_type in _SPOKEN_STIK_VALUES:
            return "spoken"

    return "normal"


# ── Result ──────────────────────────────────────────────────────────────────

@dataclass
class TranscodeResult:
    """Outcome of a single transcode / copy operation."""
    success: bool
    source_path: Path
    output_path: Path | None
    target_format: TranscodeTarget
    was_transcoded: bool
    error_message: str | None = None

    @property
    def ipod_format(self) -> str:
        if self.output_path:
            return self.output_path.suffix.lstrip(".")
        return self.source_path.suffix.lstrip(".")


def clear_caches() -> None:
    """Clear cached settings/binary lookups. Call at the start of each sync."""
    find_ffprobe.cache_clear()
    _best_aac_encoder.cache_clear()
    _best_mp3_encoder.cache_clear()


# ═══════════════════════════════════════════════════════════════════════════
# Binary discovery
# ═══════════════════════════════════════════════════════════════════════════

def find_ffmpeg(ffmpeg_path: str | None = None) -> str | None:
    """Locate ffmpeg (user setting → bundled → PATH → common dirs)."""
    if ffmpeg_path and Path(ffmpeg_path).is_file():
        return ffmpeg_path
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


def is_ffmpeg_available(ffmpeg_path: str | None = None) -> bool:
    return find_ffmpeg(ffmpeg_path) is not None and find_ffprobe(ffmpeg_path) is not None


@lru_cache(maxsize=8)
def find_ffprobe(ffmpeg_path: str | None = None) -> str | None:
    """Locate ffprobe (sibling of ffmpeg, bundled, PATH, then common dirs)."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if ffmpeg:
        name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
        candidate = Path(ffmpeg).parent / name
        if candidate.exists():
            return str(candidate)
    try:
        from .dependency_manager import get_bundled_ffprobe
        bundled = get_bundled_ffprobe()
        if bundled:
            return bundled
    except Exception:
        pass
    found = shutil.which("ffprobe")
    if found:
        return found
    for p in (
        r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
        r"C:\ffmpeg\bin\ffprobe.exe",
        "/usr/local/bin/ffprobe",
        "/opt/homebrew/bin/ffprobe",
        "/usr/bin/ffprobe",
    ):
        if Path(p).exists():
            return p
    return None


def _find_ffprobe() -> str | None:
    """Locate ffprobe using the default discovery cascade."""
    return find_ffprobe()


@lru_cache(maxsize=8)
def available_aac_encoders(ffmpeg_path: str | None = None) -> set[str]:
    """Return the set of AAC encoders exposed by the current ffmpeg build."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        return set()
    try:
        r = subprocess.run(
            [ffmpeg, "-encoders"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=10, **_SP_KWARGS,
        )
        out = r.stdout
        available: set[str] = set()
        for encoder in ("libfdk_aac", "aac_at", "aac"):
            if f" {encoder} " in out:
                available.add(encoder)
        return available
    except Exception:
        return set()


@lru_cache(maxsize=8)
def _best_aac_encoder(ffmpeg_path: str | None = None) -> str:
    """Return the best available AAC encoder.

    Preference: libfdk_aac (Fraunhofer) > aac_at (macOS AudioToolbox) > aac.
    """
    available = available_aac_encoders(ffmpeg_path)
    for encoder in ("libfdk_aac", "aac_at", "aac"):
        if encoder in available:
            logger.info("Using AAC encoder: %s", encoder)
            return encoder
    return "aac"


@lru_cache(maxsize=8)
def available_mp3_encoders(ffmpeg_path: str | None = None) -> set[str]:
    """Return the set of MP3 encoders exposed by the current ffmpeg build."""
    ffmpeg = find_ffmpeg(ffmpeg_path)
    if not ffmpeg:
        return set()
    try:
        r = subprocess.run(
            [ffmpeg, "-encoders"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=10, **_SP_KWARGS,
        )
        out = r.stdout
        available: set[str] = set()
        for encoder in ("libmp3lame", "libshine"):
            if f" {encoder} " in out:
                available.add(encoder)
        return available
    except Exception:
        return set()


@lru_cache(maxsize=8)
def _best_mp3_encoder(ffmpeg_path: str | None = None) -> str:
    """Return the best available MP3 encoder.

    Preference: libmp3lame > libshine.
    """
    available = available_mp3_encoders(ffmpeg_path)
    for encoder in ("libmp3lame", "libshine"):
        if encoder in available:
            logger.info("Using MP3 encoder: %s", encoder)
            return encoder
    return "libmp3lame"


# ═══════════════════════════════════════════════════════════════════════════
# Probing
# ═══════════════════════════════════════════════════════════════════════════

def _run_ffprobe(args: list[str], timeout: int = 30) -> dict | None:
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
    bitrate_kbps: int | None = None
    codec_name: str = ""   # e.g. "aac", "mp3", "flac"
    profile: str = ""      # e.g. "LC", "HE-AAC", "HE-AACv2"
    probe_ok: bool = False  # False when ffprobe couldn't parse the file

    # AAC profiles the iPod can play — anything else is re-encoded
    _COMPATIBLE_AAC_PROFILES: ClassVar[frozenset[str]] = frozenset({
        "lc", "aac_low", "aac lc",
    })

    def exceeds_ipod_limits(self) -> bool:
        # ``bits_per_raw_sample`` from ffprobe is not meaningful for compressed
        # codecs like AAC/MP3 and can report large internal decode precision
        # (e.g. 24/32), which should not trigger an ALAC safety transcode.
        # Enforce bit-depth only for codecs where source bit depth is real.
        bit_depth_relevant = self.codec_name.lower() in {
            "alac", "flac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "wavpack"
        }
        return (
            self.sample_rate > IPOD_MAX_SAMPLE_RATE
            or (bit_depth_relevant and self.bits_per_sample > IPOD_MAX_BIT_DEPTH)
            or self.channels > IPOD_MAX_CHANNELS
        )

    def is_incompatible_aac_profile(self) -> bool:
        """True if the stream is AAC but not a profile the iPod supports."""
        if self.codec_name.lower() != "aac":
            return False
        # Empty profile string means ffprobe couldn't determine it — treat as incompatible
        if not self.profile:
            return True
        return self.profile.lower() not in self._COMPATIBLE_AAC_PROFILES


def probe_audio(filepath: str | Path) -> AudioProperties:
    """Probe the first audio stream for its properties and bitrate."""
    info = _run_ffprobe([
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,bits_per_raw_sample,channels,bit_rate,codec_name,profile",
        str(filepath),
    ])
    if not info:
        return AudioProperties(probe_ok=False)
    streams = info.get("streams", [])
    if not streams:
        return AudioProperties(probe_ok=False)
    s = streams[0]
    return AudioProperties(
        sample_rate=int(s.get("sample_rate", 0)),
        bits_per_sample=int(s.get("bits_per_raw_sample", 0) or 0),
        channels=int(s.get("channels", 0)),
        bitrate_kbps=_stream_bitrate_kbps(s),
        codec_name=s.get("codec_name", ""),
        profile=s.get("profile", ""),
        probe_ok=True,
    )


@dataclass(frozen=True)
class VideoStreamCompatibility:
    """Compatibility of the first video and audio streams we map to output."""

    probe_ok: bool = False
    video_compatible: bool = False
    audio_compatible: bool = False
    has_audio: bool = False

    @property
    def is_fully_compatible(self) -> bool:
        return self.probe_ok and self.video_compatible and self.audio_compatible


def _parse_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _h264_level_value(value: object) -> int | None:
    """Normalize FFmpeg's numeric or dotted H.264 level to tenths."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if "." in text:
            return int(round(float(text) * 10))
        return int(text)
    except ValueError:
        return None


def _stream_bitrate_kbps(stream: dict) -> int | None:
    bits_per_second = _parse_int(stream.get("bit_rate"))
    if bits_per_second is None or bits_per_second <= 0:
        return None
    return math.ceil(bits_per_second / 1000)


def _video_stream_is_compatible(
    stream: dict,
    *,
    max_width: int,
    max_height: int,
    max_fps: int,
    max_bitrate_kbps: int,
    h264_level: str,
) -> bool:
    if str(stream.get("codec_name") or "").lower() != "h264":
        return False
    if str(stream.get("pix_fmt") or "").lower() != "yuv420p":
        return False

    width = _parse_int(stream.get("width"))
    height = _parse_int(stream.get("height"))
    if width is None or height is None or width <= 0 or height <= 0:
        return False
    if width > max_width or height > max_height:
        return False

    try:
        numerator, denominator = (int(part) for part in str(stream.get("r_frame_rate") or "").split("/"))
        fps = numerator / denominator
    except (TypeError, ValueError, ZeroDivisionError):
        return False
    if fps > max_fps + 0.5:
        return False

    profile = str(stream.get("profile") or "").casefold()
    if profile not in {"baseline", "constrained baseline"}:
        return False
    source_level = _h264_level_value(stream.get("level"))
    target_level = _h264_level_value(h264_level)
    if source_level is None or target_level is None or source_level > target_level:
        return False

    if max_bitrate_kbps > 0:
        bitrate_kbps = _stream_bitrate_kbps(stream)
        if bitrate_kbps is None or bitrate_kbps > max_bitrate_kbps:
            return False
    return True


def _audio_stream_is_compatible(stream: dict) -> bool:
    if str(stream.get("codec_name") or "").lower() != "aac":
        return False
    profile = str(stream.get("profile") or "").casefold()
    if profile not in AudioProperties._COMPATIBLE_AAC_PROFILES:
        return False

    sample_rate = _parse_int(stream.get("sample_rate"))
    channels = _parse_int(stream.get("channels"))
    bitrate_kbps = _stream_bitrate_kbps(stream)
    return (
        sample_rate is not None
        and 0 < sample_rate <= IPOD_MAX_SAMPLE_RATE
        and channels is not None
        and 0 < channels <= IPOD_MAX_CHANNELS
        and bitrate_kbps is not None
        and bitrate_kbps <= IPOD_MAX_VIDEO_AUDIO_BITRATE_KBPS
    )


def probe_video_stream_compatibility(
    filepath: str | Path,
    ffprobe_path: str | None = None,
) -> VideoStreamCompatibility:
    """Probe the first mapped video/audio streams against iPod limits.

    Additional streams do not affect the result because the output commands
    explicitly map only ``0:v:0`` and ``0:a:0?``.
    """
    probe = ffprobe_path or _find_ffprobe()
    if not probe:
        return VideoStreamCompatibility()

    max_w, max_h, max_fps, max_bitrate, h264_level = _get_video_caps()
    try:
        result = subprocess.run(
            [probe, "-v", "quiet", "-print_format", "json", "-show_streams", str(filepath)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            **_SP_KWARGS,
        )
        if result.returncode != 0:
            return VideoStreamCompatibility()
        streams = _json.loads(result.stdout).get("streams", [])
    except (OSError, subprocess.SubprocessError, _json.JSONDecodeError):
        return VideoStreamCompatibility()

    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    video_compatible = video_stream is not None and _video_stream_is_compatible(
        video_stream,
        max_width=max_w,
        max_height=max_h,
        max_fps=max_fps,
        max_bitrate_kbps=max_bitrate,
        h264_level=h264_level,
    )
    has_audio = audio_stream is not None
    audio_compatible = not has_audio or _audio_stream_is_compatible(audio_stream)
    return VideoStreamCompatibility(
        probe_ok=True,
        video_compatible=video_compatible,
        audio_compatible=audio_compatible,
        has_audio=has_audio,
    )


def probe_video_needs_transcode(
    filepath: str | Path,
    ffprobe_path: str | None = None,
) -> bool:
    """True if either output-mapped A/V stream needs conversion."""
    return not probe_video_stream_compatibility(filepath, ffprobe_path).is_fully_compatible


_IPOD_TX3G_SUBTITLE_CODEC = "mov_text"
_IPOD_CEA608_CAPTION_CODEC = "eia_608"
_IPOD_TIMED_TEXT_CODEC_TAGS: dict[str, str] = {
    _IPOD_TX3G_SUBTITLE_CODEC: "tx3g",
    _IPOD_CEA608_CAPTION_CODEC: "c608",
}


@dataclass(frozen=True)
class TimedTextStream:
    """The FFprobe fields needed to validate an iPod timed-text stream."""

    index: int
    codec_name: str
    codec_tag_string: str
    display_width: int = 0
    display_height: int = 0


def _subtitle_streams(filepath: str | Path) -> list[TimedTextStream] | None:
    """Return subtitle streams and their container codec tags, or ``None``.

    The codec name alone is insufficient: ``mov_text`` is iPod-compatible only
    with the MP4 ``tx3g`` sample entry and a non-empty display rectangle;
    ``eia_608`` requires the QuickTime ``c608`` sample entry.  An FFmpeg
    ``mov_text`` output without ``-s:s`` has a zero-sized track rectangle.  A
    Classic selects that track but renders only a small gray corner artifact.
    """
    info = _run_ffprobe(
        [
            "-show_entries",
            "stream=index,codec_type,codec_name,codec_tag_string,width,height",
            str(filepath),
        ],
        timeout=120,
    )
    if not info:
        return None

    streams: list[TimedTextStream] = []
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "subtitle":
            try:
                streams.append(
                    TimedTextStream(
                        index=int(stream["index"]),
                        codec_name=str(stream.get("codec_name") or "").casefold(),
                        codec_tag_string=str(stream.get("codec_tag_string") or "").casefold(),
                        display_width=_parse_int(stream.get("width")) or 0,
                        display_height=_parse_int(stream.get("height")) or 0,
                    ),
                )
            except (KeyError, TypeError, ValueError):
                continue
    return streams


def _stream_is_natively_supported_by_ipod(
    stream: TimedTextStream,
    supported_codecs: frozenset[str],
) -> bool:
    """Whether *stream* has a target-supported iPod codec and sample entry."""
    has_ipod_sample_entry = (
        stream.codec_name in supported_codecs
        and _IPOD_TIMED_TEXT_CODEC_TAGS.get(stream.codec_name)
        == stream.codec_tag_string
    )
    if not has_ipod_sample_entry:
        return False
    if stream.codec_name == _IPOD_TX3G_SUBTITLE_CODEC:
        return stream.display_width > 0 and stream.display_height > 0
    return True


def _video_output_muxer(
    filepath: str | Path,
    target: TranscodeTarget,
) -> Literal["ipod", "mov"]:
    """Choose the container required by compatible timed-text streams.

    CEA-608 closed-caption tracks use QuickTime's ``c608`` sample entry.
    FFmpeg can copy that entry only with the MOV muxer, while 3GPP timed text
    (``tx3g``) works with FFmpeg's iPod M4V muxer.  This is evaluated only for
    transformed video; direct copies keep their existing container and suffix.
    """
    if target not in _VIDEO_TRANSCODE_TARGETS:
        return "ipod"

    streams = _subtitle_streams(filepath)
    if streams is None:
        return "ipod"

    supported_codecs = _device_supported_timed_text_codecs()
    if any(
        stream.codec_name == _IPOD_CEA608_CAPTION_CODEC
        and _stream_is_natively_supported_by_ipod(stream, supported_codecs)
        for stream in streams
    ):
        return "mov"
    return "ipod"


def _ipod_subtitle_stream_indexes(
    filepath: str | Path,
    *,
    output_muxer: Literal["ipod", "mov"] | None = None,
) -> list[int]:
    """Return only timed-text streams natively supported by the target iPod.

    MP4 timed text (``tx3g``) appears as ``mov_text`` in ffprobe.  QuickTime
    CEA-608 closed-caption tracks (``c608``) appear as ``eia_608``.  Other
    text and image subtitle formats are deliberately excluded until a dedicated
    subtitle converter is available.

    FFmpeg's iPod muxer cannot write an ``eia_608`` track.  Retain it only when
    the output uses the QuickTime MOV muxer; direct copies keep their existing
    container and suffix.
    """
    streams = _subtitle_streams(filepath)
    if streams is None:
        return []
    supported_codecs = _device_supported_timed_text_codecs()
    return [
        stream.index
        for stream in streams
        if _stream_is_natively_supported_by_ipod(stream, supported_codecs)
        and not (
            output_muxer is not None
            and output_muxer != "mov"
            and stream.codec_name == _IPOD_CEA608_CAPTION_CODEC
        )
    ]


def _video_subtitles_need_remux(filepath: str | Path) -> bool:
    """Whether a stream-compatible video needs a remux to filter subtitles."""
    streams = _subtitle_streams(filepath)
    # If we cannot inspect subtitles, do not copy unknown tracks to a device.
    if streams is None:
        return True
    if not streams:
        return False
    supported_codecs = _device_supported_timed_text_codecs()
    return any(
        not _stream_is_natively_supported_by_ipod(stream, supported_codecs)
        for stream in streams
    )


def _probe_duration_us(filepath: str | Path) -> int:
    info = _run_ffprobe(["-show_format", str(filepath)], timeout=120)
    if not info:
        return 0
    try:
        return int(float(info.get("format", {}).get("duration", 0)) * 1_000_000)
    except (ValueError, TypeError):
        return 0


def _transcode_timeout_seconds(
    target: TranscodeTarget,
    duration_us: int,
) -> int:
    """Return a duration-aware transcode timeout in seconds.

    Audio jobs used to share a hard 10-minute timeout, which is too small for
    long spoken-word files such as audiobooks. Scale the timeout with source
    duration while keeping lower/upper bounds so wedged ffmpeg processes still
    get reaped eventually.
    """
    if target in _VIDEO_TRANSCODE_TARGETS:
        floor_s = _VIDEO_TRANSCODE_TIMEOUT_FLOOR_S
        padding_s = _VIDEO_TRANSCODE_TIMEOUT_PADDING_S
        ceiling_s = _VIDEO_TRANSCODE_TIMEOUT_CEILING_S
    else:
        floor_s = _AUDIO_TRANSCODE_TIMEOUT_FLOOR_S
        padding_s = _AUDIO_TRANSCODE_TIMEOUT_PADDING_S
        ceiling_s = _AUDIO_TRANSCODE_TIMEOUT_CEILING_S

    if duration_us <= 0:
        return floor_s

    duration_s = math.ceil(duration_us / 1_000_000)
    if target in _VIDEO_TRANSCODE_TARGETS:
        return min(ceiling_s, max(floor_s, duration_s) + padding_s)
    return max(floor_s, min(ceiling_s, duration_s + padding_s))


# ═══════════════════════════════════════════════════════════════════════════
# Target resolution — "what should this file become?"
# ═══════════════════════════════════════════════════════════════════════════

# stik atom values that indicate spoken-word content.
# Apple stik table: 0=Movie, 1=Normal(Music), 2=Audiobook, 5=Whacked Bookmark,
# 6=Music Video, 9=Short Film, 10=TV Show, 11=Booklet, 14=Ringtone, 21=iTunes U,
# 23=Voice Memo, 24=iTunes Extras
_SPOKEN_STIK_VALUES: frozenset[int] = frozenset({2, 21})  # Audiobook, iTunes U


def _probe_media_type(filepath: str | Path) -> int:
    """Return the ``stik`` atom value from an MP4/M4A file, or -1 if absent/unreadable.

    stik values relevant here:
      2  = Audiobook
      21 = iTunes U / Podcast (many podcast encoders write 21)
    Additionally, the presence of a ``pcst`` (podcast) atom is checked as a fallback.
    """
    try:
        from mutagen.mp4 import MP4
        tags = MP4(str(filepath)).tags
        if tags is None:
            return -1
        stik = tags.get("stik")
        if stik:
            return int(stik[0])
        # Podcast fallback: pcst atom = True
        pcst = tags.get("pcst")
        if pcst and pcst[0]:
            return 21
    except Exception:
        pass
    return -1


_DEFAULT_VIDEO_FPS = 30
_DEFAULT_VIDEO_BITRATE = 0      # 0 = CRF-only, no hard bitrate cap
_DEFAULT_VIDEO_LEVEL = "3.0"


def _get_video_caps() -> tuple[int, int, int, int, str]:
    """Return ``(max_width, max_height, max_fps, max_bitrate_kbps, h264_level)``
    for the currently connected iPod.

    Falls back to ``640×480 / 30 fps / no bitrate cap / Level 3.0`` when no
    device is connected or the model is unrecognised.
    """
    try:
        from iopenpod.device import capabilities_for_family_gen, get_current_device
        dev = get_current_device()
        if dev and dev.model_family:
            caps = capabilities_for_family_gen(
                dev.model_family, dev.generation or "",
            )
            if caps and caps.max_video_width > 0:
                return (
                    caps.max_video_width,
                    caps.max_video_height,
                    caps.max_video_fps,
                    caps.max_video_bitrate,
                    caps.h264_level,
                )
    except Exception:
        pass
    return _DEFAULT_VIDEO_W, _DEFAULT_VIDEO_H, _DEFAULT_VIDEO_FPS, _DEFAULT_VIDEO_BITRATE, _DEFAULT_VIDEO_LEVEL


def _get_video_limits() -> tuple[int, int]:
    """Return ``(max_width, max_height)`` — kept for callers that only need
    the resolution.  Prefer ``_get_video_caps()`` for full device info."""
    w, h, *_ = _get_video_caps()
    return w, h


def _device_supports_alac() -> bool:
    """Return True if the connected iPod supports ALAC audio.

    Falls back to True (safe default) when no device is connected or
    the model is unrecognised — avoids unnecessary re-encodes.
    """
    try:
        from iopenpod.device import capabilities_for_family_gen, get_current_device
        dev = get_current_device()
        if dev and dev.model_family:
            caps = capabilities_for_family_gen(
                dev.model_family, dev.generation or "",
            )
            if caps is not None:
                return caps.supports_alac
    except Exception:
        pass
    return True


def _device_supported_timed_text_codecs() -> frozenset[str]:
    """Return the caption/subtitle codecs verified for the connected iPod.

    Unknown devices return an empty set so that a sync never copies an
    unverified soft-subtitle or closed-caption track.
    """
    try:
        from iopenpod.device import capabilities_for_family_gen, get_current_device
        dev = get_current_device()
        if dev and dev.model_family:
            caps = capabilities_for_family_gen(
                dev.model_family, dev.generation or "",
            )
            if caps is not None:
                supported: set[str] = set()
                if caps.supports_tx3g_subtitles:
                    supported.add(_IPOD_TX3G_SUBTITLE_CODEC)
                if caps.supports_cea608_captions:
                    supported.add(_IPOD_CEA608_CAPTION_CODEC)
                return frozenset(supported)
    except (ImportError, AttributeError, TypeError):
        return frozenset()
    return frozenset()


def _device_supports_tx3g_subtitles() -> bool:
    """Return whether the connected iPod can display MP4 timed text."""
    return _IPOD_TX3G_SUBTITLE_CODEC in _device_supported_timed_text_codecs()


def _device_supports_cea608_captions() -> bool:
    """Return whether the connected iPod can display CEA-608 captions."""
    return _IPOD_CEA608_CAPTION_CODEC in _device_supported_timed_text_codecs()


def _is_native_lossy_audio(suffix: str, props: AudioProperties) -> bool:
    """Return True for native audio that is already lossy."""
    codec_name = props.codec_name.lower()
    if suffix == ".mp3" or codec_name == "mp3":
        return True
    if suffix == ".aac" or codec_name == "aac":
        return True
    if suffix in {".m4a", ".m4b", ".m4p"}:
        return codec_name != "alac" and props.bits_per_sample < 16
    return False


def get_transcode_target(
    filepath: str | Path,
    *,
    prefer_lossy: bool | None = None,
    options: TranscodeOptions | None = None,
) -> TranscodeTarget:
    """Determine the target format for *filepath*.

    Decision tree:
      1. Video → probe → VIDEO_H264, VIDEO_REMUX, or COPY
      2. Lossless source → ALAC (or AAC if prefer_lossy)
         WAV may copy instead when convert_wav_to_alac is disabled
      3. Lossy non-native → AAC
      4. Native → COPY, unless iPod limits are exceeded
         (hi-res sample rate / 24-bit / surround)
         or always_encode_lossy wants to re-encode native lossy audio
         or prefer_lossy wants to shrink a native ALAC
    """
    suffix = Path(filepath).suffix.lower()
    options = (options or TranscodeOptions()).normalized()
    lossy_target = _resolve_lossy_target(options)

    # ── Non-native video — always transcode ─────────────────────────────
    #
    # ``.mov`` is a container extension rather than a codec guarantee. A
    # number of iPod-targeted encoders use it for otherwise standard
    # H.264/AAC MP4 payloads, which the iPod can play without re-encoding.
    # Probe it just like MP4/M4V; the remaining non-native containers still
    # need a conversion regardless of their streams.
    if suffix in _NON_NATIVE_VIDEO_EXTS:
        if suffix == ".mov":
            return _video_transcode_target(filepath)
        return TranscodeTarget.VIDEO_H264

    if prefer_lossy is None:
        prefer_lossy = options.prefer_lossy

    # ── Non-native audio ────────────────────────────────────────────────
    if suffix in _NON_NATIVE_LOSSLESS_EXTS:
        if suffix == ".wav":
            if prefer_lossy:
                return lossy_target
            if options.convert_wav_to_alac:
                if not _device_supports_alac():
                    return lossy_target
                return TranscodeTarget.ALAC
            return TranscodeTarget.COPY
        if prefer_lossy or not _device_supports_alac():
            return lossy_target
        return TranscodeTarget.ALAC
    if suffix in _NON_NATIVE_LOSSY_EXTS:
        return lossy_target

    # ── Native formats ──────────────────────────────────────────────────
    if suffix in IPOD_NATIVE_FORMATS:
        # Native video — probe codec compatibility
        if suffix in {".mp4", ".m4v"}:
            return _video_transcode_target(filepath)

        # Native audio — probe for iPod limits and codec compatibility
        props = probe_audio(filepath)

        # Probe failed: do not copy blind. A native-looking extension is not
        # enough to prove the stream is compatible with the iPod.
        if not props.probe_ok:
            logger.warning(
                "TRANSCODE: could not probe %s — re-encoding instead of copying blind",
                Path(filepath).name,
            )
            return lossy_target

        if options.always_encode_lossy and _is_native_lossy_audio(suffix, props):
            return lossy_target

        if props.exceeds_ipod_limits():
            if suffix in {".m4a", ".m4b"} and not prefer_lossy and _device_supports_alac():
                return TranscodeTarget.ALAC
            return lossy_target

        # HE-AAC v1/v2 — iPod only supports AAC-LC; re-encode to LC
        if props.is_incompatible_aac_profile():
            logger.info("TRANSCODE: %s has incompatible AAC profile %r — re-encoding to AAC-LC",
                        Path(filepath).name, props.profile)
            return lossy_target

        # User wants to shrink native ALAC → AAC
        # (bits_per_sample ≥ 16 distinguishes ALAC from AAC which reports 0)
        if prefer_lossy and suffix in {".m4a", ".m4b"} and props.bits_per_sample >= 16:
            return lossy_target

        # Device doesn't support ALAC: transcode native ALAC → AAC
        if (suffix in {".m4a", ".m4b"} and props.bits_per_sample >= 16
                and not _device_supports_alac()):
            return lossy_target

        return TranscodeTarget.COPY

    # Unknown extension — AAC is the safest bet
    return lossy_target


def _video_transcode_target(filepath: str | Path) -> TranscodeTarget:
    """Choose the minimum safe A/V conversion for the mapped streams."""
    compatibility = probe_video_stream_compatibility(filepath)
    if not compatibility.probe_ok or not compatibility.video_compatible:
        if compatibility.probe_ok and compatibility.audio_compatible:
            return TranscodeTarget.VIDEO_TRANSCODE_VIDEO
        return TranscodeTarget.VIDEO_H264
    if not compatibility.audio_compatible:
        return TranscodeTarget.VIDEO_TRANSCODE_AUDIO
    if _video_subtitles_need_remux(filepath):
        return TranscodeTarget.VIDEO_REMUX
    return TranscodeTarget.COPY


def needs_transcoding(
    filepath: str | Path,
    *,
    prefer_lossy: bool | None = None,
    options: TranscodeOptions | None = None,
) -> bool:
    """True if the file needs any conversion before it can go on iPod."""
    return (
        get_transcode_target(filepath, prefer_lossy=prefer_lossy, options=options)
        != TranscodeTarget.COPY
    )


# ═══════════════════════════════════════════════════════════════════════════
# AAC quality presets
# ═══════════════════════════════════════════════════════════════════════════

def quality_to_nominal_bitrate(
    quality: str,
    options: TranscodeOptions | None = None,
) -> int:
    """Return the nominal bitrate (kbps) for display / cache-key purposes."""
    options = options or TranscodeOptions()
    if quality == "spoken":
        return options.spoken_lossy_cbr_bitrate
    return _QUALITY_MUSIC_KBPS.get(options.lossy_quality, 192)


def _is_spoken_quality(quality: str) -> bool:
    return quality == "spoken"


def _bitrate_for_quality(quality: str, options: TranscodeOptions) -> int:
    if _is_spoken_quality(quality):
        return options.spoken_lossy_cbr_bitrate
    return _QUALITY_MUSIC_KBPS.get(options.lossy_quality, 192)


def _resolve_lossy_policy(options: TranscodeOptions) -> _ResolvedLossyPolicy:
    """Resolve lossy target and the concrete encoder name from user settings."""
    pref = (options.lossy_encoder or "auto").lower()
    ffmpeg_path = options.ffmpeg_path

    if pref in {"libmp3lame", "libshine"}:
        avail = available_mp3_encoders(ffmpeg_path)
        encoder = pref if pref in avail else _best_mp3_encoder(ffmpeg_path)
        return _ResolvedLossyPolicy(target=TranscodeTarget.MP3, encoder=encoder)

    if pref in {"libfdk_aac", "aac_at", "aac"}:
        avail = available_aac_encoders(ffmpeg_path)
        encoder = pref if pref in avail else _best_aac_encoder(ffmpeg_path)
        return _ResolvedLossyPolicy(target=TranscodeTarget.AAC, encoder=encoder)

    # "auto" — use best available AAC encoder; only fall back to MP3 if no AAC at all
    aac_avail = available_aac_encoders(ffmpeg_path)
    if aac_avail:
        return _ResolvedLossyPolicy(target=TranscodeTarget.AAC, encoder=_best_aac_encoder(ffmpeg_path))
    if available_mp3_encoders(ffmpeg_path):
        return _ResolvedLossyPolicy(target=TranscodeTarget.MP3, encoder=_best_mp3_encoder(ffmpeg_path))
    return _ResolvedLossyPolicy(target=TranscodeTarget.AAC, encoder="aac")


def _resolve_lossy_target(options: TranscodeOptions) -> TranscodeTarget:
    """Resolve user lossy policy to AAC or MP3."""
    return _resolve_lossy_policy(options).target


def resolve_effective_encoder(options: TranscodeOptions) -> tuple[TranscodeTarget, str]:
    """Return the (target, encoder) that will actually be used for *options*.

    Checks ffmpeg availability and applies the same fallback logic as the
    transcoder so callers can derive VBR/encoder flags without re-running
    the full encode pipeline.
    """
    policy = _resolve_lossy_policy(options.normalized())
    return policy.target, policy.encoder


def _aac_quality_args(
    quality: str,
    options: TranscodeOptions | None = None,
    *,
    encoder: str | None = None,
) -> list[str]:
    """Build encoder-specific ffmpeg flags from user settings."""
    options = (options or TranscodeOptions()).normalized()
    encoder = encoder or _best_aac_encoder(options.ffmpeg_path)
    is_spoken = _is_spoken_quality(quality)
    is_manual = options.lossy_encoder not in {"auto", ""}

    # ── aac_at: has its own CBR / ABR / VBR mode system ──────────
    if encoder == "aac_at":
        args: list[str] = []
        if is_spoken:
            args += ["-aac_at_mode", "cbr", "-b:a", f"{options.spoken_lossy_cbr_bitrate}k"]
        elif is_manual and options.bitrate_mode == "vbr":
            q = _clamp_int(options.vbr_level, minimum=0, maximum=14)
            args += ["-aac_at_mode", "vbr", "-q:a", str(q)]
        elif is_manual and options.bitrate_mode in ("abr", "cvbr"):
            args += ["-aac_at_mode", options.bitrate_mode, "-b:a", f"{options.music_lossy_cbr_bitrate}k"]
        elif is_manual:
            args += ["-aac_at_mode", "cbr", "-b:a", f"{options.music_lossy_cbr_bitrate}k"]
        else:
            args += ["-aac_at_mode", "cbr", "-b:a", f"{_QUALITY_MUSIC_KBPS.get(options.lossy_quality, 192)}k"]
        if is_manual and options.aac_cutoff > 0:
            args += ["-cutoff", str(options.aac_cutoff)]
        return args

    args: list[str] = []

    # ── Bitrate / VBR level (libfdk_aac and native aac) ───────
    if is_spoken:
        args += ["-b:a", f"{options.spoken_lossy_cbr_bitrate}k"]
    elif is_manual and options.bitrate_mode == "vbr" and encoder == "libfdk_aac":
        args += ["-vbr", str(_clamp_int(options.vbr_level, minimum=1, maximum=5))]
    elif is_manual:
        args += ["-b:a", f"{options.music_lossy_cbr_bitrate}k"]
    else:
        args += ["-b:a", f"{_QUALITY_MUSIC_KBPS.get(options.lossy_quality, 192)}k"]

    # ── Encoder-specific flags ─────────────────────────────────
    if encoder == "libfdk_aac":
        args += ["-profile:a", "aac_low"]
        if is_manual:
            args += ["-afterburner", "1" if options.fdk_afterburner else "0"]
            if options.aac_cutoff > 0:
                args += ["-cutoff", str(options.aac_cutoff)]
        else:
            args += ["-afterburner", "1"]
    else:
        # Native aac
        if is_manual:
            args += ["-aac_pns", "1" if options.aac_pns else "0"]
            args += ["-aac_tns", "1" if options.aac_tns else "0"]
            args += ["-aac_ms", "1" if options.aac_ms_stereo else "0"]
            args += ["-aac_is", "1" if options.aac_intensity_stereo else "0"]
            if options.aac_cutoff > 0:
                args += ["-cutoff", str(options.aac_cutoff)]
        else:
            args += ["-aac_pns", "0"]

    return args


def _mp3_quality_args(
    quality: str,
    options: TranscodeOptions | None = None,
    *,
    encoder: str | None = None,
) -> list[str]:
    """Build encoder-specific ffmpeg flags for MP3 output."""
    options = (options or TranscodeOptions()).normalized()
    encoder = encoder or _best_mp3_encoder(options.ffmpeg_path)
    is_spoken = _is_spoken_quality(quality)
    is_manual = options.lossy_encoder not in {"auto", ""}

    if is_spoken:
        return ["-b:a", f"{options.spoken_lossy_cbr_bitrate}k"]

    if encoder == "libshine":
        bitrate = options.music_lossy_cbr_bitrate if is_manual else _QUALITY_MUSIC_KBPS.get(options.lossy_quality, 192)
        return ["-b:a", f"{bitrate}k"]

    # libmp3lame
    if is_manual and options.bitrate_mode == "vbr":
        q = _clamp_int(options.vbr_level, minimum=0, maximum=9)
        return ["-q:a", str(q)]
    if is_manual:
        return ["-b:a", f"{options.music_lossy_cbr_bitrate}k"]
    # auto mode — VBR by quality preset
    q = _QUALITY_MP3_VBR_Q.get(options.lossy_quality, 4)
    return ["-q:a", str(q)]


# ═══════════════════════════════════════════════════════════════════════════
# FFmpeg command builders
# ═══════════════════════════════════════════════════════════════════════════

def _target_sample_rate(source_rate: int, normalize: bool) -> int | None:
    """Return the ``-ar`` value to pass to ffmpeg, or ``None`` to omit the flag.

    Rules:
    - If source rate is unknown (0) → cap to IPOD_MAX_SAMPLE_RATE.
    - If source rate exceeds iPod limit → cap to IPOD_MAX_SAMPLE_RATE.
    - If ``normalize`` is True → always output 44 100 Hz (CD rate).
    - Otherwise → preserve source rate (no -ar flag).

    The iPod hardware accepts 44 100 Hz and 48 000 Hz equally well; we avoid
    upsampling 44.1 kHz sources to 48 000 Hz because that shifts the
    sample_count stored in iTunesDB and causes early track termination.
    """
    if source_rate == 0 or source_rate > IPOD_MAX_SAMPLE_RATE:
        return IPOD_MAX_SAMPLE_RATE
    if normalize:
        return 44_100
    return None   # preserve source rate


def _cmd_alac(ffmpeg: str, src: str, dst: str, normalize_sr: bool = False) -> list[str]:
    props = probe_audio(src)
    target_sr = _target_sample_rate(props.sample_rate, normalize_sr)
    ar_args = ["-ar", str(target_sr)] if target_sr is not None else []
    # Preserve source channel count when possible (mono stays mono, stereo stays stereo).
    # Cap at IPOD_MAX_CHANNELS (2) in case source has 5.1 or surround.
    channels = min(props.channels, IPOD_MAX_CHANNELS) if props.channels > 0 else IPOD_MAX_CHANNELS
    return [
        ffmpeg, "-i", src,
        "-vn",
        "-acodec", "alac",
        *ar_args,
        "-sample_fmt", "s16p",
        "-ac", str(channels),
        "-movflags", "+faststart",
        "-y", dst,
    ]


def _cmd_aac(
    ffmpeg: str, src: str, dst: str, quality: str,
    normalize_sr: bool = False,
    mono: bool = False,
    options: TranscodeOptions | None = None,
    *,
    encoder: str | None = None,
) -> list[str]:
    props = probe_audio(src)
    target_sr = _target_sample_rate(props.sample_rate, normalize_sr)
    ar_args = ["-ar", str(target_sr)] if target_sr is not None else []
    # Mono downmix: spoken-word at 64 kbps sounds better in mono (~50% smaller)
    channels = 1 if mono else IPOD_MAX_CHANNELS
    options = (options or TranscodeOptions()).normalized()
    encoder = encoder or _best_aac_encoder(options.ffmpeg_path)
    return [
        ffmpeg, "-i", src,
        "-vn",
        "-acodec", encoder,
        *ar_args,
        "-ac", str(channels),
        *_aac_quality_args(quality, options, encoder=encoder),
        "-movflags", "+faststart",
        "-y", dst,
    ]


def _cmd_mp3(
    ffmpeg: str, src: str, dst: str, quality: str,
    normalize_sr: bool = False,
    mono: bool = False,
    options: TranscodeOptions | None = None,
    *,
    encoder: str | None = None,
) -> list[str]:
    props = probe_audio(src)
    target_sr = _target_sample_rate(props.sample_rate, normalize_sr)
    ar_args = ["-ar", str(target_sr)] if target_sr is not None else []
    channels = 1 if mono else IPOD_MAX_CHANNELS
    options = (options or TranscodeOptions()).normalized()
    encoder = encoder or _best_mp3_encoder(options.ffmpeg_path)
    return [
        ffmpeg, "-i", src,
        "-vn",
        "-acodec", encoder,
        *ar_args,
        "-ac", str(channels),
        *_mp3_quality_args(quality, options, encoder=encoder),
        "-id3v2_version", "3",
        "-y", dst,
    ]


def _cmd_video(
    ffmpeg: str,
    src: str,
    dst: str,
    *,
    crf: int,
    preset: str,
    max_w: int,
    max_h: int,
    max_fps: int,
    max_bitrate: int,
    h264_level: str,
    audio_encoder: str,
    audio_bitrate_kbps: int | None = None,
    subtitle_stream_indexes: list[int] | None = None,
    copy_video: bool = False,
    copy_audio: bool = False,
    output_muxer: Literal["ipod", "mov"] = "ipod",
) -> list[str]:
    video_args: list[str]
    if copy_video:
        video_args = ["-c:v", "copy"]
    else:
        # Rotate portrait videos 90° CW when the target is landscape —
        # a tiny centred strip wastes most of the iPod's fixed-landscape screen.
        # passthrough=landscape means "leave landscape videos alone, only rotate
        # portrait ones". Applied before scaling so dimensions are correct.
        vf_parts: list[str] = []
        if max_w > max_h:
            vf_parts.append("transpose=1:passthrough=landscape")
        vf_parts.append(
            f"scale={max_w}:{max_h}"
            ":force_original_aspect_ratio=decrease,"
            "scale='trunc(iw/2)*2':'trunc(ih/2)*2'"
        )
        # Cap frame rate to device maximum (handles 60fps sources for Nano 3G/4G,
        # and prevents excessive bitrate on high-fps content)
        vf_parts.append(f"fps=fps={max_fps}")

        # Hard bitrate ceiling — enforced on devices with Level 1.3 decoders
        # (Nano 3G/4G: 768 kbps). Uses a 2× buffer for encoder headroom.
        bitrate_args: list[str] = []
        if max_bitrate > 0:
            bitrate_args = ["-maxrate", f"{max_bitrate}k", "-bufsize", f"{max_bitrate * 2}k"]
        video_args = [
            "-c:v", "libx264",
            "-profile:v", "baseline", "-level", h264_level,
            "-pix_fmt", "yuv420p",
            "-tag:v", "avc1",
            "-vf", ",".join(vf_parts),
            "-crf", str(crf), "-preset", preset,
            *bitrate_args,
        ]

    audio_args = ["-c:a", "copy"] if copy_audio else _video_aac_args(
        audio_encoder,
        bitrate_kbps=audio_bitrate_kbps,
    )

    subtitle_stream_indexes = subtitle_stream_indexes or []
    subtitle_map_args = [
        item
        for index in subtitle_stream_indexes
        for item in ("-map", f"0:{index}?")
    ]
    subtitle_codec_args = ["-c:s", "copy"] if subtitle_stream_indexes else []

    return [
        ffmpeg, "-i", src,
        "-map", "0:v:0", "-map", "0:a:0?",
        *subtitle_map_args,
        "-map_metadata", "0",
        *video_args,
        *audio_args,
        *subtitle_codec_args,
        "-movflags", "+faststart",
        "-f", output_muxer,
        "-y", dst,
    ]


def _video_aac_args(encoder: str, *, bitrate_kbps: int | None = None) -> list[str]:
    """Build AAC-LC audio options for an iPod video transcode.

    ``aac_at`` is AudioToolbox's AAC-LC encoder, but it does not accept
    FFmpeg's symbolic ``aac_low`` profile value.  Its CBR mode produces the
    same iPod-compatible AAC-LC output through its own encoder option.
    """
    encoder_args = (
        ["-aac_at_mode", "cbr"]
        if encoder == "aac_at"
        else ["-profile:a", "aac_low"]
    )
    target_bitrate_kbps = IPOD_MAX_VIDEO_AUDIO_BITRATE_KBPS
    if bitrate_kbps is not None and bitrate_kbps > 0:
        target_bitrate_kbps = min(bitrate_kbps, target_bitrate_kbps)

    return [
        "-c:a", encoder,
        *encoder_args,
        "-ac", str(IPOD_MAX_CHANNELS),
        "-ar", str(IPOD_MAX_SAMPLE_RATE),
        "-b:a", f"{target_bitrate_kbps}k",
    ]


def _cmd_video_remux(
    ffmpeg: str,
    src: str,
    dst: str,
    *,
    subtitle_stream_indexes: list[int] | None = None,
    output_muxer: Literal["ipod", "mov"] = "ipod",
) -> list[str]:
    """Copy compatible video/audio streams while retaining only native subtitles."""
    subtitle_stream_indexes = subtitle_stream_indexes or []
    subtitle_map_args = [
        item
        for index in subtitle_stream_indexes
        for item in ("-map", f"0:{index}?")
    ]
    subtitle_codec_args = ["-c:s", "copy"] if subtitle_stream_indexes else []
    return [
        ffmpeg, "-i", src,
        "-map", "0:v:0", "-map", "0:a:0?",
        *subtitle_map_args,
        "-map_metadata", "0",
        "-c:v", "copy", "-c:a", "copy",
        *subtitle_codec_args,
        "-movflags", "+faststart",
        "-f", output_muxer,
        "-y", dst,
    ]


def _resolve_lossy_runtime(plan: TranscodePlan) -> tuple[str, bool]:
    """Resolve per-file lossy quality and downmix policy from a plan."""
    if plan.smart_quality_by_type and plan.target in {TranscodeTarget.AAC, TranscodeTarget.MP3} and plan.is_spoken:
        logger.debug(
            "smart_quality_by_type: spoken-word content detected for %s",
            plan.source_path.name,
        )

    use_mono = (
        plan.mono_for_spoken
        and plan.is_spoken
        and plan.target in {TranscodeTarget.AAC, TranscodeTarget.MP3}
    )
    return plan.effective_quality, use_mono


def _build_ffmpeg_command(
    ffmpeg: str,
    source_path: Path,
    output_path: Path,
    plan: TranscodePlan,
    options: TranscodeOptions,
) -> list[str]:
    """Build the ffmpeg command for the resolved transcode plan."""
    src = str(source_path)
    dst = str(output_path)
    quality, use_mono = _resolve_lossy_runtime(plan)

    if plan.target == TranscodeTarget.ALAC:
        return _cmd_alac(ffmpeg, src, dst, normalize_sr=plan.normalize_sample_rate)

    if plan.target == TranscodeTarget.AAC:
        return _cmd_aac(
            ffmpeg,
            src,
            dst,
            quality,
            normalize_sr=plan.normalize_sample_rate,
            mono=use_mono,
            options=options,
            encoder=plan.lossy_encoder,
        )

    if plan.target == TranscodeTarget.MP3:
        return _cmd_mp3(
            ffmpeg,
            src,
            dst,
            quality,
            normalize_sr=plan.normalize_sample_rate,
            mono=use_mono,
            options=options,
            encoder=plan.lossy_encoder,
        )

    subtitle_stream_indexes = _ipod_subtitle_stream_indexes(
        source_path,
        output_muxer=plan.video_output_muxer,
    )
    if plan.target == TranscodeTarget.VIDEO_REMUX:
        return _cmd_video_remux(
            ffmpeg,
            src,
            dst,
            subtitle_stream_indexes=subtitle_stream_indexes,
            output_muxer=plan.video_output_muxer,
        )

    copy_video = plan.target == TranscodeTarget.VIDEO_TRANSCODE_AUDIO
    copy_audio = plan.target == TranscodeTarget.VIDEO_TRANSCODE_VIDEO
    video_aac_encoder = (
        plan.lossy_encoder
        if plan.lossy_encoder in {"libfdk_aac", "aac_at", "aac"}
        else _best_aac_encoder(options.ffmpeg_path)
    )
    return _cmd_video(
        ffmpeg,
        src,
        dst,
        crf=plan.video_crf,
        preset=plan.video_preset,
        max_w=plan.video_max_width,
        max_h=plan.video_max_height,
        max_fps=plan.video_max_fps,
        max_bitrate=plan.video_max_bitrate_kbps,
        h264_level=plan.video_h264_level,
        audio_encoder=video_aac_encoder,
        audio_bitrate_kbps=plan.video_audio_bitrate_kbps,
        subtitle_stream_indexes=subtitle_stream_indexes,
        copy_video=copy_video,
        copy_audio=copy_audio,
        output_muxer=plan.video_output_muxer,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Transcode execution
# ═══════════════════════════════════════════════════════════════════════════

def transcode(
    source_path: str | Path,
    output_dir: str | Path,
    output_filename: str | None = None,
    ffmpeg_path: str | None = None,
    aac_quality: str = "normal",
    progress_callback: Callable[[float], None] | None = None,
    *,
    prefer_lossy: bool | None = None,
    options: TranscodeOptions | None = None,
    plan: TranscodePlan | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> TranscodeResult:
    """Transcode (or copy) *source_path* into *output_dir*.

    All iPod hardware limits are enforced automatically.
    Set *prefer_lossy* to force lossless sources to AAC.
    """
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    options = (options or TranscodeOptions()).normalized()

    if not source_path.exists():
        return TranscodeResult(
            success=False, source_path=source_path, output_path=None,
            target_format=TranscodeTarget.COPY, was_transcoded=False,
            error_message=f"Source file not found: {source_path}",
        )

    if plan is None:
        plan = resolve_transcode_plan(
            source_path,
            aac_quality=aac_quality,
            prefer_lossy=prefer_lossy,
            options=options,
        )
    target = plan.target
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
    ffmpeg = ffmpeg_path or find_ffmpeg(options.ffmpeg_path)
    if not ffmpeg:
        return TranscodeResult(
            success=False, source_path=source_path, output_path=None,
            target_format=target, was_transcoded=False,
            error_message="ffmpeg not found",
        )
    if not find_ffprobe(ffmpeg_path or options.ffmpeg_path):
        return TranscodeResult(
            success=False, source_path=source_path, output_path=None,
            target_format=target, was_transcoded=False,
            error_message="ffprobe not found",
        )

    ext = plan.output_extension
    out = output_dir / (base_name + ext)
    cmd = _build_ffmpeg_command(ffmpeg, source_path, out, plan, options)

    return _run_transcode(cmd, source_path, out, target, progress_callback,
                          is_cancelled=is_cancelled)


def _run_transcode(
    cmd: list[str],
    source_path: Path,
    output_path: Path,
    target: TranscodeTarget,
    progress_callback: Callable[[float], None] | None,
    is_cancelled: Callable[[], bool] | None = None,
) -> TranscodeResult:
    """Run an ffmpeg command and return a TranscodeResult."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration_us = _probe_duration_us(source_path)
        timeout = _transcode_timeout_seconds(target, duration_us)

        if progress_callback and target in _VIDEO_TRANSCODE_TARGETS:
            returncode, stderr = _run_ffmpeg_with_progress(
                cmd, duration_us, progress_callback, timeout,
                is_cancelled=is_cancelled,
            )
            progress_callback(1.0)
        else:
            # Audio transcodes: run via Popen so we can kill on cancel.
            # stdout is unused; stderr must be drained in a thread to
            # prevent a deadlock on Windows where small pipe buffers
            # (4 KB) fill up and block ffmpeg when multiple workers run
            # in parallel.
            import threading as _threading

            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                **_SP_KWARGS,
            )
            stderr_chunks: list[bytes] = []

            def _drain_stderr() -> None:
                pipe = proc.stderr
                if pipe is None:
                    return
                while True:
                    chunk = pipe.read(4096)
                    if not chunk:
                        break
                    if isinstance(chunk, str):
                        stderr_chunks.append(chunk.encode("utf-8", errors="replace"))
                    else:
                        stderr_chunks.append(chunk)

            drain_t = _threading.Thread(target=_drain_stderr, daemon=True)
            drain_t.start()

            # Poll so we can check cancellation every 0.5s; enforce global timeout
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                if is_cancelled and is_cancelled():
                    proc.kill()
                    proc.wait(timeout=5)
                    drain_t.join(timeout=5)
                    return TranscodeResult(
                        success=False, source_path=source_path,
                        output_path=None, target_format=target,
                        was_transcoded=True, error_message="Cancelled",
                    )
                if time.monotonic() > deadline:
                    proc.kill()
                    proc.wait(timeout=5)
                    drain_t.join(timeout=5)
                    return TranscodeResult(
                        success=False, source_path=source_path,
                        output_path=None, target_format=target,
                        was_transcoded=True, error_message="Transcoding timed out",
                    )
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    pass

            drain_t.join(timeout=10)
            returncode = proc.returncode
            stderr = b"".join(stderr_chunks).decode("utf-8", errors="replace")

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
        # logger.info("Transcoded %s → %s", source_path.name, output_path.name)
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
    is_cancelled: Callable[[], bool] | None = None,
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
            if is_cancelled and is_cancelled():
                proc.kill()
                t.join(timeout=5)
                return -1, "Cancelled"
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
# Metadata helpers
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


def strip_metadata(file_path: str | Path) -> bool:
    """Remove user-facing tags/artwork from a media file in place."""
    path = Path(file_path)
    is_iso_media = path.suffix.casefold() in {".m4a", ".m4v", ".mov", ".mp4"}
    try:
        from mutagen._file import File as MutagenFile

        audio = MutagenFile(path)
        if audio is None:
            return _strip_iso_media_user_data(path) if is_iso_media else False
        if audio.tags is not None and hasattr(audio, "delete"):
            audio.delete()
        elif audio.tags is not None:
            audio.tags.clear()
            audio.save()
        # Mutagen does not expose QuickTime's legacy ``moov/udta`` fields on
        # every MOV variant (notably MOVs with a c608 track).  Scrub that
        # user-data atom too, so a successful no-tags result cannot leave
        # visible title/artist/album metadata on the device payload.
        return _strip_iso_media_user_data(path) if is_iso_media else True
    except Exception as e:
        if is_iso_media and _strip_iso_media_user_data(path):
            return True
        logger.warning("Could not strip metadata from %s: %s", path.name, e)
        return False


def _strip_iso_media_user_data(file_path: Path) -> bool:
    """Neutralize global ``moov/udta`` metadata without moving media bytes.

    Replacing the atom type with ``free`` retains its size, so ``stco``/``co64``
    chunk offsets remain valid.  This is the only reliable fallback for MOV
    variants whose legacy QuickTime metadata Mutagen does not surface.
    """
    try:
        with file_path.open("r+b") as media_file:
            media_file.seek(0, os.SEEK_END)
            file_size = media_file.tell()
            for atom_offset, atom_size, atom_type, header_size in _iso_media_atoms(
                media_file,
                start=0,
                end=file_size,
            ):
                if atom_type != b"moov":
                    continue
                for child_offset, _child_size, child_type, _child_header_size in _iso_media_atoms(
                    media_file,
                    start=atom_offset + header_size,
                    end=atom_offset + atom_size,
                ):
                    if child_type == b"udta":
                        media_file.seek(child_offset + 4)
                        media_file.write(b"free")
            return True
    except (OSError, ValueError) as exc:
        logger.warning("Could not strip QuickTime user data from %s: %s", file_path.name, exc)
        return False


def _iso_media_atoms(
    media_file: BinaryIO,
    *,
    start: int,
    end: int,
) -> Iterator[tuple[int, int, bytes, int]]:
    """Yield validated ISO-media atom headers in one container payload."""
    offset = start
    while offset < end:
        if end - offset < 8:
            raise ValueError("truncated atom header")
        media_file.seek(offset)
        header = media_file.read(8)
        atom_size = int.from_bytes(header[:4], "big")
        atom_type = header[4:]
        header_size = 8
        if atom_size == 1:
            extended_size = media_file.read(8)
            if len(extended_size) != 8:
                raise ValueError("truncated extended atom header")
            atom_size = int.from_bytes(extended_size, "big")
            header_size = 16
        elif atom_size == 0:
            atom_size = end - offset
        if atom_size < header_size or offset + atom_size > end:
            raise ValueError("invalid atom size")
        yield offset, atom_size, atom_type, header_size
        offset += atom_size
