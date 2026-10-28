"""Pure device encoding policy and Storage-owned Host media preparation."""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from fractions import Fraction
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

import mutagen

from iOpenPod.app.export_tagging import ExportMediaTagger
from iOpenPod.app.media.captions import verify_captions
from iOpenPod.app.media.chapters import imported_chapters
from iOpenPod.app.media.inspection import MediaInspectionError, MediaInspector
from iOpenPod.app.media.lyrics import embedded_lyrics
from iOpenPod.app.media.models import StreamKind
from iOpenPod.app.media.progress import MediaPreparationPhase, MediaPreparationProgress
from iOpenPod.app.media.stream_selection import (
    MediaStreamSelection,
    SubtitleHandling,
    is_caption,
    subtitle_handling,
)
from iOpenPod.app.media.subtitles.compatibility import (
    normalize_clocks,
    verify_compatibility,
    verify_geometry,
)
from iOpenPod.app.media.subtitles.layout import configure_layout, verify_layout
from iOpenPod.app.media.subtitles.preparation import (
    SubtitleConversion,
    prepare_subtitles,
    verify_subtitles,
)
from iOpenPod.app.media.tags import apply_tag_values, inspection_tag_values
from iPodDB.library import AudioEncoding, MediaKind
from storage.host_input import LocalHostFile
from storage.media_processing import (
    MediaToolError,
    MediaToolFinder,
    available_compute_threads,
    discover_media_tools,
    inspect_mp3_variable_bitrate,
    media_workspace,
    run_media_tool,
)
from storage.media_processing import (
    MediaTools as MediaTools,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from typing import BinaryIO

    from device_registry import DeviceProfile
    from iOpenPod.app.media.models import MediaInspection, MediaStream
    from iPodDB.library import ArtworkPixels, Track
    from storage import FileFingerprint, HostPath
    from storage.media_processing import MediaToolProgress


class _MutagenReader(Protocol):
    """The file-like read operation used from Mutagen's untyped API."""

    def File(self, filething: BinaryIO) -> Any: ...


class LossyEncoder(StrEnum):
    AUTO = "auto"
    FDK_AAC = "libfdk_aac"
    AAC_AT = "aac_at"
    AAC = "aac"
    MP3 = "libmp3lame"


class BitrateMode(StrEnum):
    CBR = "cbr"
    VBR = "vbr"
    ABR = "abr"
    CVBR = "cvbr"


class TranscodeQuality(StrEnum):
    COMPACT = "compact"
    BALANCED = "balanced"
    HIGH = "high"


class VideoEncoding(StrEnum):
    MP4 = "mp4"


SUPPORTED_BITRATE_MODES: dict[LossyEncoder, tuple[BitrateMode, ...]] = {
    LossyEncoder.FDK_AAC: (BitrateMode.CBR, BitrateMode.VBR),
    LossyEncoder.AAC_AT: tuple(BitrateMode),
    LossyEncoder.AAC: (BitrateMode.CBR, BitrateMode.VBR),
    LossyEncoder.MP3: (BitrateMode.CBR, BitrateMode.VBR, BitrateMode.ABR),
}
VBR_QUALITIES = {
    LossyEncoder.FDK_AAC: tuple(range(1, 6)),
    LossyEncoder.AAC_AT: tuple(range(15)),
    LossyEncoder.AAC: (1, 2),
    LossyEncoder.MP3: tuple(range(10)),
}


@dataclass(frozen=True, slots=True)
class TranscodeSettings:
    lossy_encoder: LossyEncoder = LossyEncoder.AUTO
    quality: TranscodeQuality = TranscodeQuality.BALANCED
    lossless_to_lossy: bool = False
    retranscode_lossy: bool = False
    wav_aiff_to_alac: bool = True
    normalize_44100: bool = False
    smart_spoken_word: bool = True
    spoken_word_mono: bool = True
    spoken_word_bitrate_kbps: int = 64
    bitrate_mode: BitrateMode = BitrateMode.VBR
    bitrate_kbps: int = 192
    vbr_quality: int = 3
    bandwidth_cutoff_hz: int = 0
    afterburner: bool = True
    tns: bool = True
    pns: bool = False
    mid_side_stereo: bool = True
    intensity_stereo: bool = True

    def __post_init__(self) -> None:
        if self.spoken_word_bitrate_kbps not in (32, 48, 64, 80, 96):
            raise ValueError("Spoken Word bitrate must be 32, 48, 64, 80 or 96 kbps")
        if not 8 <= self.bitrate_kbps <= 320:
            raise ValueError("Lossy bitrate must be between 8 and 320 kbps")
        if not 0 <= self.bandwidth_cutoff_hz <= 24000:
            raise ValueError("Bandwidth cutoff must be between 0 and 24000 Hz")
        if self.lossy_encoder is not LossyEncoder.AUTO:
            if self.bitrate_mode not in SUPPORTED_BITRATE_MODES[self.lossy_encoder]:
                raise ValueError(
                    f"{self.lossy_encoder} does not support {self.bitrate_mode}"
                )
            if (
                self.bitrate_mode is BitrateMode.VBR
                and self.vbr_quality not in VBR_QUALITIES[self.lossy_encoder]
            ):
                raise ValueError(f"Invalid VBR quality for {self.lossy_encoder}")


@dataclass(frozen=True, slots=True)
class TranscodePlan:
    encoding: AudioEncoding | VideoEncoding
    suffix: str
    output_arguments: tuple[str, ...]
    sample_rate_hz: int
    channels: int
    warnings: tuple[str, ...] = ()
    video_muxer: Literal["ipod", "mov"] = "ipod"
    subtitle_conversions: tuple[SubtitleConversion, ...] = ()

    @property
    def requires_transcode(self) -> bool:
        return bool(self.output_arguments)


@dataclass(frozen=True, slots=True)
class PreparedTranscode:
    source: HostPath
    inspection: MediaInspection
    encoding: AudioEncoding | VideoEncoding
    original_fingerprint: FileFingerprint
    was_transcoded: bool
    warnings: tuple[str, ...] = ()
    normalization_gain_db: float | None = None
    variable_bitrate: bool | None = None
    original_inspection: MediaInspection | None = None
    metadata: Track | None = None


_LOSSLESS = frozenset(
    (
        "flac",
        "alac",
        "ape",
        "wavpack",
        "tta",
        "tak",
        "mlp",
        "truehd",
        "als",
        "shorten",
        "wmalossless",
    )
)
_SUFFIXES = {
    AudioEncoding.MP3: ".mp3",
    AudioEncoding.AAC: ".m4a",
    AudioEncoding.ALAC: ".m4a",
    AudioEncoding.WAV: ".wav",
    AudioEncoding.AIFF: ".aiff",
}
_FORMATS = "mov,mp3,aac,flac,wav,aiff,ogg,matroska,webm,avi,asf,mpeg,mpegts,ac3,eac3,dts,amr,ape,au,caf,wv,tta,aa,dsf,dff,tak,mpc,mpc8,rm"


def compatible_audio(
    observed: MediaInspection, profile: DeviceProfile
) -> AudioEncoding | None:
    """Require observed stream facts, including this Device Profile's limits."""
    if len(observed.audio_streams) != 1 or any(
        s.kind is StreamKind.VIDEO and s.attached_picture is not True
        for s in observed.streams
    ):
        return None
    audio = observed.audio_streams[0]
    limits = profile.capabilities.audio
    if (
        audio.channels is None
        or not 1 <= audio.channels <= limits.max_channels
        or audio.sample_rate_hz is None
        or not 0 < audio.sample_rate_hz <= limits.max_sample_rate_hz
    ):
        return None
    duration = audio.duration_seconds or observed.duration_seconds
    if duration is None or duration <= 0:
        return None
    if (
        audio.codec == "mp3"
        and "mp3" in observed.containers
        and audio.bitrate_bps is not None
        and 0 < audio.bitrate_bps <= 320000
    ):
        return AudioEncoding.MP3
    if "mov" in observed.containers:
        if (
            audio.codec == "aac"
            and audio.codec_tag == "mp4a"
            and audio.profile == "LC"
            and audio.bitrate_bps is not None
            and 0 < audio.bitrate_bps <= limits.max_aac_bitrate_kbps * 1000
        ):
            return AudioEncoding.AAC
        if (
            audio.codec == "alac"
            and audio.codec_tag == "alac"
            and limits.supports_alac
            and (audio.bits_per_raw_sample or audio.bits_per_sample)
            == limits.max_lossless_bits
        ):
            return AudioEncoding.ALAC
    if audio.codec == "pcm_s16le" and "wav" in observed.containers:
        return AudioEncoding.WAV
    if audio.codec == "pcm_s16be" and "aiff" in observed.containers:
        return AudioEncoding.AIFF
    return None


def _lossy_arguments(
    settings: TranscodeSettings, available: frozenset[str], spoken: bool
) -> tuple[AudioEncoding, tuple[str, ...]]:
    encoder = settings.lossy_encoder
    automatic = encoder is LossyEncoder.AUTO
    if automatic:
        encoder = next(
            (
                e
                for e in (
                    LossyEncoder.FDK_AAC,
                    LossyEncoder.AAC_AT,
                    LossyEncoder.MP3,
                    LossyEncoder.AAC,
                )
                if e.value in available
            ),
            LossyEncoder.AUTO,
        )
    if encoder.value not in available:
        raise MediaToolError(
            "media.encoder_unavailable",
            "No supported lossy encoder is available in this FFmpeg build. "
            "Install a build containing FDK AAC, AudioToolbox AAC, native AAC, or LAME MP3, then retry this item."
            if automatic
            else f"The selected encoder ({settings.lossy_encoder}) is unavailable in this FFmpeg build. Choose Auto or install an FFmpeg build containing that encoder, then retry this item.",
        )
    bitrate = nominal_lossy_bitrate_kbps(settings, spoken=spoken)
    mode = BitrateMode.CBR if spoken or automatic else settings.bitrate_mode
    args = ["-c:a", encoder.value]
    if encoder in (LossyEncoder.FDK_AAC, LossyEncoder.AAC):
        args += ["-profile:a", "aac_low"]
    if encoder is LossyEncoder.AAC_AT:
        args += ["-aac_at_mode", mode.value]
    if mode is BitrateMode.VBR:
        args += [
            "-vbr" if encoder is LossyEncoder.FDK_AAC else "-q:a",
            str(settings.vbr_quality),
        ]
    elif automatic and not spoken and encoder is LossyEncoder.MP3:
        args += [
            "-q:a",
            str(
                {
                    TranscodeQuality.COMPACT: 5,
                    TranscodeQuality.BALANCED: 3,
                    TranscodeQuality.HIGH: 0,
                }[settings.quality]
            ),
        ]
    else:
        args += ["-b:a", f"{bitrate}k"]
        if mode is BitrateMode.ABR and encoder is LossyEncoder.MP3:
            args += ["-abr", "1"]
    if encoder is LossyEncoder.FDK_AAC:
        args += [
            "-afterburner",
            str(int(settings.afterburner if not automatic else True)),
        ]
    elif encoder is LossyEncoder.AAC:
        args += [
            "-aac_tns",
            str(int(settings.tns if not automatic else True)),
            "-aac_pns",
            str(int(settings.pns if not automatic else False)),
            "-aac_ms",
            "-1" if automatic or settings.mid_side_stereo else "0",
            "-aac_is",
            str(int(settings.intensity_stereo if not automatic else True)),
        ]
    elif encoder is LossyEncoder.MP3:
        args += ["-joint_stereo", str(int(automatic or settings.mid_side_stereo))]
    if not automatic and settings.bandwidth_cutoff_hz:
        args += ["-cutoff", str(settings.bandwidth_cutoff_hz)]
    return (
        AudioEncoding.MP3 if encoder is LossyEncoder.MP3 else AudioEncoding.AAC
    ), tuple(args)


def nominal_lossy_bitrate_kbps(settings: TranscodeSettings, *, spoken: bool) -> int:
    """Return the nominal output rate selected by the shared encoding policy.

    VBR encoders use quality controls, so this remains an estimate for those modes.
    """
    return (
        settings.spoken_word_bitrate_kbps
        if spoken
        else {
            TranscodeQuality.COMPACT: 128,
            TranscodeQuality.BALANCED: 192,
            TranscodeQuality.HIGH: 256,
        }[settings.quality]
        if settings.lossy_encoder is LossyEncoder.AUTO
        else settings.bitrate_kbps
    )


def resolve_transcode(
    observed: MediaInspection,
    profile: DeviceProfile,
    settings: TranscodeSettings,
    available_encoders: frozenset[str],
    *,
    spoken_word: bool = False,
    stream_selection: MediaStreamSelection | None = None,
) -> TranscodePlan:
    """Choose compatible copy or conversion without touching any filesystem."""
    if stream_selection is not None:
        stream_selection.validate(observed, profile)
    if observed.video_streams:
        return _resolve_video(
            observed,
            profile,
            settings,
            available_encoders,
            spoken_word,
            stream_selection,
        )
    if not observed.audio_streams or any(
        s.kind is StreamKind.VIDEO and s.attached_picture is not True
        for s in observed.streams
    ):
        raise MediaInspectionError(
            "media.unsupported_streams",
            "No playable audio stream was found. This item will be skipped; the other selected items can still Sync.",
        )
    audio = (
        stream_selection.audio
        if stream_selection is not None
        else _select_preferred_stream(observed.audio_streams)
    )
    assert audio is not None
    warnings: list[str] = []
    multiple_audio = len(observed.audio_streams) > 1
    if multiple_audio and stream_selection is None:
        choice = "default" if audio.default is True else "first"
        warnings.append(
            f"Source contains {len(observed.audio_streams)} audio streams; selected the {choice} audio stream."
        )
    if multiple_audio or stream_selection is not None:
        observed = replace(observed, streams=(audio,))
    duration = audio.duration_seconds or observed.duration_seconds
    if (
        duration is None
        or duration <= 0
        or not audio.channels
        or not audio.sample_rate_hz
    ):
        raise MediaInspectionError(
            "media.incomplete_stream",
            "The source has no trustworthy duration, channel count or sample rate. Repair or replace the source, then rescan it.",
        )
    limits = profile.capabilities.audio
    rate = min(
        audio.sample_rate_hz,
        limits.max_sample_rate_hz,
        44100 if settings.normalize_44100 else limits.max_sample_rate_hz,
    )
    spoken = spoken_word and settings.smart_spoken_word
    channels = (
        1
        if spoken and settings.spoken_word_mono
        else min(audio.channels, limits.max_channels)
    )
    lossless = audio.codec in _LOSSLESS or audio.codec.startswith(("pcm_", "dsd_"))
    compatible = compatible_audio(observed, profile)
    needs_lossy = (
        spoken
        or (lossless and settings.lossless_to_lossy)
        or (not lossless and settings.retranscode_lossy)
    )
    needs_alac = (
        lossless and settings.wav_aiff_to_alac and audio.codec.startswith("pcm_")
    )
    if (
        compatible is not None
        and not needs_lossy
        and not needs_alac
        and rate == audio.sample_rate_hz
        and channels == audio.channels
    ):
        return TranscodePlan(
            compatible,
            _SUFFIXES[compatible],
            (
                "-map",
                f"0:{audio.index}",
                "-c:a",
                "copy",
                "-vn",
                "-map_metadata:s:0",
                f"0:s:{audio.index}",
                "-disposition:a:0",
                "default",
            )
            if multiple_audio or stream_selection is not None
            else (),
            rate,
            channels,
            tuple(warnings),
        )
    arguments: tuple[str, ...]
    if (
        lossless
        and (audio.bits_per_raw_sample or audio.bits_per_sample or 16)
        > limits.max_lossless_bits
        and not needs_lossy
    ):
        warnings.append(
            "Reduced lossless sample precision to 16 bits, as required by this iPod."
        )
    if audio.channels > limits.max_channels:
        warnings.append(
            f"Downmixed {audio.channels} source channels to {channels} for this iPod."
        )
    if rate < audio.sample_rate_hz:
        warnings.append(
            f"Resampled {audio.sample_rate_hz} Hz audio to {rate} Hz for the selected device and settings."
        )
    if (
        lossless
        and not needs_lossy
        and not settings.wav_aiff_to_alac
        and any(container in observed.containers for container in ("wav", "aiff"))
    ):
        encoding = (
            AudioEncoding.WAV if "wav" in observed.containers else AudioEncoding.AIFF
        )
        arguments = (
            "-c:a",
            "pcm_s16le" if encoding is AudioEncoding.WAV else "pcm_s16be",
        )
    elif lossless and not needs_lossy and limits.supports_alac:
        if "alac" not in available_encoders:
            raise MediaToolError(
                "media.encoder_unavailable",
                "This FFmpeg build lacks ALAC. Install a build with ALAC or enable Transcode Lossless into Lossy, then retry this item.",
            )
        encoding, arguments = (
            AudioEncoding.ALAC,
            ("-c:a", "alac", "-sample_fmt", "s16p"),
        )
    elif lossless and not needs_lossy:
        encoding, arguments = AudioEncoding.WAV, ("-c:a", "pcm_s16le")
        warnings.append(
            "This iPod does not support ALAC. Preserved lossless audio as 16-bit WAV; enable Transcode Lossless into Lossy to reduce device space and USB transfer time."
        )
    else:
        encoding, arguments = _lossy_arguments(settings, available_encoders, spoken)
    args = (
        "-map",
        f"0:{audio.index}",
        "-vn",
        *arguments,
        "-ar",
        str(rate),
        "-ac",
        str(channels),
        "-map_metadata:s:0",
        f"0:s:{audio.index}",
        "-disposition:a:0",
        "default",
    )
    return TranscodePlan(
        encoding, _SUFFIXES[encoding], args, rate, channels, tuple(warnings)
    )


def compatible_video(observed: MediaInspection, profile: DeviceProfile) -> bool:
    """Validate every retained timed stream against this iPod's video limits."""
    caps = profile.capabilities.video
    if (
        not caps.supported
        or len(observed.video_streams) != 1
        or len(observed.audio_streams) > 2
        or "mov" not in observed.containers
    ):
        return False
    video = observed.video_streams[0]
    duration = video.duration_seconds or observed.duration_seconds
    if (
        duration is None
        or duration <= 0
        or video.codec != "h264"
        or video.codec_tag != "avc1"
        or video.profile not in caps.h264_profiles
        or video.pixel_format != "yuv420p"
        or video.level is None
        or video.level > round(float(caps.h264_level) * 10)
        or video.width is None
        or not 0 < video.width <= caps.max_width
        or video.height is None
        or not 0 < video.height <= caps.max_height
        or video.frame_rate is None
        or not 0 < video.frame_rate <= caps.max_fps
        or video.nominal_frame_rate != video.frame_rate
        or video.bitrate_bps is None
        or not 0 < video.bitrate_bps <= caps.max_bitrate_kbps * 1000
    ):
        return False
    for audio in observed.audio_streams:
        if (
            audio.codec != "aac"
            or audio.codec_tag != "mp4a"
            or audio.profile != "LC"
            or audio.channels not in (1, 2)
            or audio.sample_rate_hz is None
            or not 0
            < audio.sample_rate_hz
            <= profile.capabilities.audio.max_sample_rate_hz
            or audio.bitrate_bps is None
            or not 0 < audio.bitrate_bps <= caps.max_audio_bitrate_kbps * 1000
        ):
            return False
    return all(
        s.kind is not StreamKind.SUBTITLE
        or subtitle_handling(s, profile) is SubtitleHandling.COPY
        for s in observed.streams
    )


def _scoped_audio_arguments(arguments: tuple[str, ...], index: int) -> tuple[str, ...]:
    """Scope encoder option/value pairs so one audio track cannot alter another."""
    result: list[str] = []
    for option, value in zip(arguments[::2], arguments[1::2], strict=True):
        suffix = f":{index}" if option.endswith(":a") else f":a:{index}"
        result.extend((option + suffix, value))
    return tuple(result)


def _native_timed_indices(
    observed: MediaInspection,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    return (
        tuple(s.index for s in observed.streams if s.codec_tag == "tx3g"),
        tuple(s.index for s in observed.streams if s.codec_tag == "c608"),
    )


def _prepare_native_headers(
    stream: BinaryIO, subtitles: tuple[int, ...], captions: tuple[int, ...]
) -> None:
    for index in subtitles:
        try:
            verify_geometry(stream, (index,))
        except MediaInspectionError as error:
            if error.code != "media.subtitle_incompatible":
                raise
            configure_layout(stream, (index,))
    normalize_clocks(stream, subtitles, captions)
    verify_compatibility(stream, subtitles, captions)


def _select_preferred_stream(streams: tuple[MediaStream, ...]) -> MediaStream:
    """Select the marked default stream, falling back to probe order."""
    if not streams:
        raise ValueError("At least one media stream is required")
    return next((stream for stream in streams if stream.default is True), streams[0])


def _resolve_video(
    observed: MediaInspection,
    profile: DeviceProfile,
    settings: TranscodeSettings,
    available: frozenset[str],
    spoken: bool,
    stream_selection: MediaStreamSelection | None,
) -> TranscodePlan:
    caps = profile.capabilities.video
    if not caps.supported:
        raise MediaInspectionError(
            "media.video_unsupported",
            "This iPod cannot play video. Choose an audio edition or exclude this item; the other selected items can still Sync.",
        )
    video_streams = observed.video_streams
    audio_streams = observed.audio_streams
    video = (
        stream_selection.video
        if stream_selection is not None
        else _select_preferred_stream(video_streams)
    )
    assert video is not None
    audio = (
        stream_selection.audio
        if stream_selection is not None
        else _select_preferred_stream(audio_streams)
        if audio_streams
        else None
    )
    selected_audio = (
        stream_selection.audio_streams
        if stream_selection is not None
        else (audio,)
        if audio is not None
        else ()
    )
    selected_streams = (
        video,
        *selected_audio,
        *(
            (*stream_selection.subtitles, *stream_selection.captions)
            if stream_selection is not None
            else tuple(s for s in observed.streams if s.kind is StreamKind.SUBTITLE)
        ),
    )
    selected = replace(observed, streams=selected_streams)
    warnings: list[str] = []
    if len(video_streams) > 1 and stream_selection is None:
        choice = "default" if video.default is True else "first"
        warnings.append(
            f"Source contains {len(video_streams)} video streams; selected the {choice} video stream."
        )
    if len(audio_streams) > 1 and stream_selection is None:
        choice = "default" if audio is not None and audio.default is True else "first"
        warnings.append(
            f"Source contains {len(audio_streams)} audio streams; selected the {choice} audio stream."
        )
    if (
        not video.width
        or not video.height
        or not video.frame_rate
        or not (video.duration_seconds or observed.duration_seconds)
    ):
        raise MediaInspectionError(
            "media.video_incomplete",
            "The video's dimensions, duration or frame rate could not be verified. Repair or replace the source and rescan it.",
        )
    rate = (
        min(
            audio.sample_rate_hz or 44100,
            44100
            if settings.normalize_44100
            else profile.capabilities.audio.max_sample_rate_hz,
        )
        if audio is not None
        else 0
    )
    channels = (
        min(audio.channels or 2, profile.capabilities.audio.max_channels)
        if audio is not None
        else 0
    )
    spoken = spoken and settings.smart_spoken_word
    if spoken and settings.spoken_word_mono and audio is not None:
        channels = 1
    has_extra_streams = len(video_streams) > 1 or len(audio_streams) > 1
    if (
        stream_selection is None
        and not has_extra_streams
        and compatible_video(selected, profile)
        and not settings.retranscode_lossy
        and not spoken
        and (
            audio is None
            or (rate == audio.sample_rate_hz and channels == audio.channels)
        )
    ):
        return TranscodePlan(VideoEncoding.MP4, ".m4v", (), rate, channels)
    args = ["-map", f"0:{video.index}"]
    mapped_streams = [video]
    # Check the motion stream independently so an audio repair can copy video.
    video_only = replace(selected, streams=(video,))
    output_width, output_height = video.width, video.height
    if compatible_video(video_only, profile):
        args += ["-c:v", "copy"]
    else:
        if "libx264" not in available:
            raise MediaToolError(
                "media.video_encoder_missing",
                "This FFmpeg build lacks libx264, required for this iPod's H.264 Baseline video. Install a build with libx264, then retry this item.",
            )
        # An average rate cannot rule out bursts above the device limit. Produce
        # a bounded constant rate whenever the motion stream needs conversion.
        frame_rate = (
            video.nominal_frame_rate
            if video.nominal_frame_rate is not None and video.nominal_frame_rate > 0
            else video.frame_rate
        )
        scale = min(
            Fraction(1),
            Fraction(caps.max_width, video.width),
            Fraction(caps.max_height, video.height),
        )
        output_width = max(2, int(video.width * scale) // 2 * 2)
        output_height = max(2, int(video.height * scale) // 2 * 2)
        filters = [
            f"scale=w={output_width}:h={output_height}:flags=lanczos",
            f"fps={min(frame_rate, caps.max_fps)}",
        ]
        args += [
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-level:v",
            caps.h264_level,
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "medium",
            "-crf",
            "23",
            "-maxrate",
            f"{caps.max_bitrate_kbps}k",
            "-bufsize",
            f"{caps.max_bitrate_kbps * 2}k",
            "-vf",
            ",".join(filters),
        ]
    for audio_index, selected_audio_stream in enumerate(selected_audio):
        audio = selected_audio_stream
        audio_rate = min(
            audio.sample_rate_hz or 44100,
            44100
            if settings.normalize_44100
            else profile.capabilities.audio.max_sample_rate_hz,
        )
        audio_channels = min(
            audio.channels or 2, profile.capabilities.audio.max_channels
        )
        if spoken and settings.spoken_word_mono:
            audio_channels = 1
        scoped_audio = len(selected_audio) > 1
        codec_option = f"-c:a:{audio_index}" if scoped_audio else "-c:a"
        args += ["-map", f"0:{audio.index}"]
        mapped_streams.append(audio)
        if (
            audio.codec == "aac"
            and audio.profile == "LC"
            and audio.channels == audio_channels
            and audio.sample_rate_hz == audio_rate
            and audio.bitrate_bps is not None
            and 0 < audio.bitrate_bps <= caps.max_audio_bitrate_kbps * 1000
            and not settings.retranscode_lossy
            and not spoken
        ):
            args += [codec_option, "copy"]
        else:
            encoder = settings.lossy_encoder
            if encoder in (LossyEncoder.AUTO, LossyEncoder.MP3):
                encoder = next(
                    (
                        e
                        for e in (
                            LossyEncoder.FDK_AAC,
                            LossyEncoder.AAC_AT,
                            LossyEncoder.AAC,
                        )
                        if e.value in available
                    ),
                    LossyEncoder.AUTO,
                )
                if settings.lossy_encoder is LossyEncoder.MP3:
                    warnings.append(
                        "Video requires AAC audio on this iPod; used an available AAC encoder for the video's audio."
                    )
            adjusted = replace(
                settings,
                lossy_encoder=encoder,
                bitrate_mode=BitrateMode.CBR,
                bitrate_kbps=min(
                    settings.bitrate_kbps, caps.max_audio_bitrate_kbps * 4 // 5
                ),
            )
            _, audio_args = _lossy_arguments(adjusted, available, spoken)
            stream_args = (
                *audio_args,
                "-ar",
                str(audio_rate),
                "-ac",
                str(audio_channels),
            )
            args.extend(
                _scoped_audio_arguments(stream_args, audio_index)
                if scoped_audio
                else stream_args
            )
    subtitle_index = 0
    subtitle_conversions: list[SubtitleConversion] = []
    original_video = _select_preferred_stream(observed.video_streams)
    for stream in selected.streams:
        if stream.kind is StreamKind.SUBTITLE:
            handling = subtitle_handling(stream, profile)
            if (
                handling is SubtitleHandling.COPY
                and not is_caption(stream)
                and (original_video.width, original_video.height)
                != (output_width, output_height)
            ):
                handling = SubtitleHandling.CONVERT
            if handling is not SubtitleHandling.UNSUPPORTED:
                args += [
                    "-map",
                    f"0:{stream.index}",
                    f"-c:s:{subtitle_index}",
                    "copy" if handling is SubtitleHandling.COPY else "mov_text",
                ]
                if not is_caption(stream):
                    # MOV is required for c608, but otherwise defaults text to
                    # the older QuickTime sample entry instead of iPod tx3g.
                    args += [f"-tag:s:{subtitle_index}", "tx3g"]
                if handling is SubtitleHandling.CONVERT:
                    subtitle_conversions.append(
                        SubtitleConversion(stream, len(mapped_streams))
                    )
                    if "mov_text" not in available:
                        raise MediaToolError(
                            "media.subtitle_encoder_missing",
                            "This FFmpeg build lacks the mov_text subtitle encoder. Install a build with mov_text or choose another subtitle stream.",
                        )
                    args += [
                        f"-s:s:{subtitle_index}",
                        f"{output_width}x{output_height}",
                    ]
                subtitle_index += 1
                mapped_streams.append(stream)
            else:
                warnings.append(
                    f"Subtitle stream {stream.index} ({stream.codec}) is unsupported in this iPod's M4V output and was excluded from the device copy."
                )
    # Preserve language and descriptive stream tags independently of the policy
    # for global music tags, using the selected streams' actual output order.
    for output_index, stream in enumerate(mapped_streams):
        args += [f"-map_metadata:s:{output_index}", f"0:s:{stream.index}"]
        if stream_selection is not None:
            disposition = (
                "default"
                if stream.kind is StreamKind.VIDEO
                or (selected_audio and stream == selected_audio[0])
                else "0"
                if stream.kind is StreamKind.AUDIO
                else "+".join(stream.dispositions) or "0"
            )
            args += [f"-disposition:{output_index}", disposition]
    return TranscodePlan(
        VideoEncoding.MP4,
        ".m4v",
        tuple(args),
        rate,
        channels,
        tuple(warnings),
        # FFmpeg's ipod muxer cannot store c608 tracks; the MOV muxer can.
        video_muxer="mov"
        if any(s.codec_tag == "c608" for s in mapped_streams)
        else "ipod",
        subtitle_conversions=tuple(subtitle_conversions),
    )


class MediaTranscoder:
    """Prepare verified Host files; keep them alive through the caller's commit."""

    def __init__(
        self, *, threads_per_job: int = 1, find_tool: MediaToolFinder | None = None
    ) -> None:
        if threads_per_job < 1:
            raise ValueError("Encoder thread count must be positive")
        self.threads_per_job = min(threads_per_job, available_compute_threads())
        self._find_tool = find_tool

    def embed_artwork(
        self,
        prepared: PreparedTranscode,
        track: Track,
        artwork: ArtworkPixels,
        *,
        checkpoint: Callable[[], None],
    ) -> PreparedTranscode:
        """Add verified Rockbox artwork to an already prepared private file."""

        checkpoint()
        suffix = (
            ".m4v"
            if prepared.encoding is VideoEncoding.MP4
            else _SUFFIXES[prepared.encoding]
        )
        ExportMediaTagger().prepare(
            prepared.source, track, artwork, file_name=f"media{suffix}"
        )
        inspection = MediaInspector(find_tool=self._find_tool).inspect(
            prepared.source, checkpoint=checkpoint
        )
        native_indices = _native_timed_indices(inspection)
        if prepared.encoding is VideoEncoding.MP4 and any(native_indices):
            with LocalHostFile.observe(prepared.source).open_read(
                checkpoint=checkpoint
            ) as stream:
                verify_compatibility(stream, *native_indices)
        return replace(prepared, inspection=inspection)

    def preflight(self, *, checkpoint: Callable[[], None]) -> MediaTools:
        return discover_media_tools(checkpoint=checkpoint, find_tool=self._find_tool)

    @contextmanager
    def prepare(
        self,
        source: HostPath,
        profile: DeviceProfile,
        settings: TranscodeSettings,
        *,
        checkpoint: Callable[[], None],
        spoken_word: bool = False,
        expected_source: FileFingerprint | None = None,
        tools: MediaTools | None = None,
        metadata: Track | None = None,
        rockbox_metadata: bool = False,
        normalize_tags: bool = False,
        compute_sound_check: bool = False,
        progress: Callable[[MediaPreparationProgress], None] | None = None,
        stream_selection: MediaStreamSelection | None = None,
    ) -> Generator[PreparedTranscode]:
        def report(
            phase: MediaPreparationPhase,
            message: str,
            sample: MediaToolProgress | None = None,
            duration: float | None = None,
        ) -> None:
            checkpoint()
            if progress is not None:
                progress(
                    MediaPreparationProgress(
                        phase,
                        message,
                        sample.processed_seconds if sample is not None else None,
                        duration,
                        sample.speed if sample is not None else None,
                    )
                )

        tools = tools or self.preflight(checkpoint=checkpoint)
        inspector = MediaInspector(tools.ffprobe)
        with media_workspace(checkpoint=checkpoint) as workspace:
            report(
                MediaPreparationPhase.READING,
                "Reading the Host file into private staging",
            )
            captured = workspace.capture(source, expected=expected_source)
            report(
                MediaPreparationPhase.INSPECTING, "Inspecting data streams and metadata"
            )
            observed = inspector.inspect_captured(captured, checkpoint=checkpoint)
            if metadata is not None:
                metadata = enrich_source_metadata(metadata, observed)
                # The captured file is the authority when it contains lyrics.
                # Host Scan and the reviewed Track may have older text.
                try:
                    with LocalHostFile.observe(captured.snapshot).open_read(
                        checkpoint=checkpoint
                    ) as stream:
                        file_lyrics = embedded_lyrics(
                            cast("_MutagenReader", mutagen).File(stream)
                        )
                except mutagen.MutagenError:
                    # Other containers can still use reviewed/FFprobe text.
                    file_lyrics = ""
                if file_lyrics:
                    metadata = replace(
                        metadata,
                        metadata=replace(metadata.metadata, lyrics=file_lyrics),
                    )
                spoken_word = spoken_word or metadata.media_kind in (
                    MediaKind.PODCAST,
                    MediaKind.AUDIOBOOK,
                )
            plan = resolve_transcode(
                observed,
                profile,
                settings,
                tools.encoders,
                spoken_word=spoken_word,
                stream_selection=stream_selection,
            )
            selected = (
                replace(observed, streams=stream_selection.streams)
                if stream_selection is not None
                else observed
            )
            result = replace(
                observed,
                source=captured.snapshot,
                fingerprint=workspace.snapshot_fingerprint(captured),
            )
            native_indices = _native_timed_indices(
                replace(
                    selected,
                    streams=tuple(
                        s
                        for s in selected.streams
                        if subtitle_handling(s, profile)
                        is not SubtitleHandling.UNSUPPORTED
                    ),
                )
            )
            if plan.encoding is VideoEncoding.MP4 and any(native_indices):
                try:
                    with LocalHostFile.observe(captured.snapshot).open_read(
                        checkpoint=checkpoint
                    ) as stream:
                        verify_compatibility(stream, *native_indices)
                except MediaInspectionError as error:
                    if error.code != "media.subtitle_incompatible":
                        raise
                    # Normalize the private input before any muxer sees it:
                    # FFmpeg can clamp a long subtitle delta at a high clock.
                    # Source geometry can be repaired separately by remuxing.
                    output = workspace.transform_stream(
                        captured.snapshot,
                        lambda stream: normalize_clocks(
                            stream, *native_indices, require_geometry=False
                        ),
                    )
                    result = inspector.inspect_captured(output, checkpoint=checkpoint)
                    if not plan.requires_transcode:
                        try:
                            output = workspace.transform_stream(
                                captured.snapshot,
                                lambda stream: _prepare_native_headers(
                                    stream, *native_indices
                                ),
                            )
                        except MediaInspectionError as geometry_error:
                            if geometry_error.code != "media.subtitle_incompatible":
                                raise
                            repair_selection = MediaStreamSelection(
                                _select_preferred_stream(observed.video_streams),
                                _select_preferred_stream(observed.audio_streams)
                                if observed.audio_streams
                                else None,
                                tuple(
                                    s for s in observed.streams if s.codec_tag == "tx3g"
                                ),
                                tuple(
                                    s for s in observed.streams if s.codec_tag == "c608"
                                ),
                            )
                            plan = _resolve_video(
                                observed,
                                profile,
                                settings,
                                tools.encoders,
                                spoken_word,
                                repair_selection,
                            )
                        else:
                            result = inspector.inspect_captured(
                                output, checkpoint=checkpoint
                            )
            output_path = captured.snapshot
            subtitle_warnings: tuple[str, ...] = ()
            source_captions = tuple(
                s
                for s in selected.streams
                if s.codec_tag == "c608"
                and subtitle_handling(s, profile) is SubtitleHandling.COPY
            )
            caption_evidence = verify_captions(
                source_captions,
                observed,
                captured.snapshot,
                tools,
                remux=plan.requires_transcode,
                duration_seconds=_duration(selected) or 0,
                checkpoint=checkpoint,
            )
            caption_warnings = tuple(
                dict.fromkeys(
                    warning for item in caption_evidence for warning in item.warnings
                )
            )
            if plan.requires_transcode:
                conversion_message = "Converting media for this iPod"
                report(MediaPreparationPhase.CONVERTING, conversion_message)
                output_path = workspace.output_path(plan.suffix)
                args = plan.output_arguments
                subtitles = prepare_subtitles(
                    tuple(item.stream for item in plan.subtitle_conversions),
                    observed,
                    captured.snapshot,
                    workspace,
                    tools,
                    duration_seconds=_duration(selected) or 0,
                    checkpoint=checkpoint,
                )
                subtitle_warnings = tuple(
                    warning for item in subtitles for warning in item.warnings
                )
                subtitle_inputs = tuple(
                    part
                    for item in subtitles
                    for part in (
                        "-f",
                        "webvtt",
                        "-sub_charenc",
                        "UTF-8",
                        "-c:s",
                        "text",
                        "-keep_ass_markup",
                        "1",
                        "-protocol_whitelist",
                        "file",
                        "-i",
                        str(item.source),
                    )
                )
                subtitle_maps = {
                    f"0:{item.source_index}": f"{index}:0"
                    for index, item in enumerate(subtitles, 1)
                }
                args = tuple(
                    subtitle_maps.get(value, value)
                    if index > 0 and args[index - 1] == "-map"
                    else value
                    for index, value in enumerate(args)
                )
                tags = (
                    _metadata_arguments(metadata, rockbox_metadata)
                    if metadata is not None
                    else ()
                )
                run_media_tool(
                    tools.ffmpeg,
                    (
                        *_input_arguments(captured.snapshot, self.threads_per_job),
                        *subtitle_inputs,
                        "-progress",
                        "pipe:1",
                        "-stats_period",
                        "0.5",
                        *args,
                        "-map_metadata",
                        "0" if rockbox_metadata else "-1",
                        "-map_chapters",
                        "0",
                        *tags,
                        "-threads",
                        str(self.threads_per_job),
                        *_container_arguments(plan.encoding, plan.video_muxer),
                        str(output_path),
                    ),
                    checkpoint=checkpoint,
                    timeout_seconds=max(120, float(observed.duration_seconds or 0) * 4),
                    progress=lambda sample: report(
                        MediaPreparationPhase.CONVERTING,
                        conversion_message,
                        sample,
                        _duration(selected),
                    ),
                )
                report(
                    MediaPreparationPhase.INSPECTING, "Inspecting the converted media"
                )
                if plan.subtitle_conversions:
                    output = workspace.transform_stream(
                        output_path,
                        lambda stream: configure_layout(
                            stream,
                            tuple(
                                item.output_index for item in plan.subtitle_conversions
                            ),
                        ),
                    )
                else:
                    output = workspace.inspect_output(output_path)
                result = inspector.inspect_captured(output, checkpoint=checkpoint)
                source_subtitles = (
                    (*stream_selection.subtitles, *stream_selection.captions)
                    if stream_selection is not None
                    else tuple(
                        stream
                        for stream in observed.streams
                        if stream.kind is StreamKind.SUBTITLE
                        and subtitle_handling(stream, profile)
                        is not SubtitleHandling.UNSUPPORTED
                    )
                )
                output_subtitles = tuple(
                    stream
                    for stream in result.streams
                    if stream.kind is StreamKind.SUBTITLE
                )
                if any(
                    "forced" in original.dispositions
                    and "forced" not in converted.dispositions
                    for original, converted in zip(
                        source_subtitles, output_subtitles, strict=False
                    )
                ):
                    subtitle_warnings += (
                        "Forced subtitle playback could not be retained; the text "
                        "remains available as a selectable subtitle track.",
                    )
                if subtitles:
                    by_index = {stream.index: stream for stream in result.streams}
                    if any(
                        item.output_index not in by_index
                        or by_index[item.output_index].codec != "mov_text"
                        for item in plan.subtitle_conversions
                    ):
                        raise MediaInspectionError(
                            "media.output_streams_mismatch",
                            "The prepared output did not retain the selected subtitles.",
                        )
                    verify_subtitles(
                        subtitles,
                        tuple(
                            by_index[item.output_index]
                            for item in plan.subtitle_conversions
                        ),
                        result,
                        tools,
                        duration_seconds=_duration(selected) or 0,
                        checkpoint=checkpoint,
                    )
                if stream_selection is not None and (
                    len(result.video_streams) != int(stream_selection.video is not None)
                    or len(result.audio_streams) != len(stream_selection.audio_streams)
                    or sum(s.kind is StreamKind.SUBTITLE for s in result.streams)
                    != len(stream_selection.subtitles) + len(stream_selection.captions)
                ):
                    raise MediaInspectionError(
                        "media.output_streams_mismatch",
                        "The prepared output did not retain the selected streams. This item was not written to the iPod.",
                    )
                if not (
                    compatible_video(result, profile)
                    if plan.encoding is VideoEncoding.MP4
                    else compatible_audio(result, profile) is plan.encoding
                ):
                    raise MediaInspectionError(
                        "media.output_incompatible",
                        "The prepared output does not meet this iPod's codec, bitrate, sample-rate or channel limits. Try Auto with Balanced quality; this item was not written to the iPod.",
                    )
                if result.audio_streams and (
                    result.audio_streams[0].sample_rate_hz != plan.sample_rate_hz
                    or result.audio_streams[0].channels != plan.channels
                ):
                    raise MediaInspectionError(
                        "media.output_settings_mismatch",
                        "The encoder did not honor the selected sample rate or channel settings. Choose another encoder and retry this item.",
                    )
                original_duration = _duration(selected)
                output_duration = _duration(result)
                if (
                    original_duration is None
                    or output_duration is None
                    or abs(float(original_duration - output_duration))
                    > max(0.25, float(original_duration) * 0.001)
                ):
                    raise MediaInspectionError(
                        "media.output_truncated",
                        "The prepared audio duration differs from its source. Check or replace the source file; this item was not written to the iPod.",
                    )
            native_indices = _native_timed_indices(result)
            if plan.encoding is VideoEncoding.MP4 and any(native_indices):
                output = workspace.transform_stream(
                    output_path,
                    lambda stream: _prepare_native_headers(stream, *native_indices),
                )
                output_path = output.snapshot
                result = inspector.inspect_captured(output, checkpoint=checkpoint)
            if rockbox_metadata:
                report(
                    MediaPreparationPhase.METADATA,
                    "Writing metadata to the prepared copy",
                )
                if metadata is None:
                    raise ValueError("Rockbox metadata requires the reviewed Track")
                reviewed_track = metadata
                tagger = ExportMediaTagger()
                output = workspace.transform_stream(
                    output_path,
                    lambda stream: tagger.prepare_stream(
                        stream, f"media{plan.suffix}", reviewed_track
                    ),
                )
                output_path = output.snapshot
                result = inspector.inspect_captured(output, checkpoint=checkpoint)
            if plan.subtitle_conversions:
                with LocalHostFile.observe(output_path).open_read(
                    checkpoint=checkpoint
                ) as stream:
                    verify_layout(
                        stream,
                        tuple(item.output_index for item in plan.subtitle_conversions),
                    )
            if plan.encoding is VideoEncoding.MP4 and any(native_indices):
                with LocalHostFile.observe(output_path).open_read(
                    checkpoint=checkpoint
                ) as stream:
                    verify_compatibility(stream, *_native_timed_indices(result))
            final_captions = verify_captions(
                tuple(s for s in result.streams if s.codec_tag == "c608"),
                result,
                output_path,
                tools,
                remux=False,
                duration_seconds=_duration(result) or 0,
                checkpoint=checkpoint,
            )
            if tuple(
                (item.packet_count, item.payload_sha256) for item in final_captions
            ) != tuple(
                (item.packet_count, item.payload_sha256) for item in caption_evidence
            ):
                raise MediaInspectionError(
                    "media.caption_payload_changed",
                    "The prepared video did not preserve its selected caption data. This item was not written to the iPod.",
                )
            measure_sound_check = compute_sound_check and bool(result.audio_streams)
            verification_message = (
                "Verifying prepared media and measuring Sound Check"
                if measure_sound_check
                else "Verifying prepared media"
            )
            report(MediaPreparationPhase.VERIFYING, verification_message)
            # Attached cover images are not playable video. A broken optional
            # picture must not invalidate otherwise decodable audio.
            verification = (
                *(
                    part
                    for stream in (*result.audio_streams, *result.video_streams)
                    for part in ("-map", f"0:{stream.index}")
                ),
                "-sn",
            )
            if measure_sound_check:
                # One Track has one gain value. Measure primary audio only,
                # while still decoding every retained audio stream below.
                verification += (
                    "-filter:a:0" if len(result.audio_streams) > 1 else "-af",
                    "ebur128=framelog=verbose",
                )
            verification_output = run_media_tool(
                tools.ffmpeg,
                (
                    *_input_arguments(
                        output_path, self.threads_per_job, info=measure_sound_check
                    ),
                    "-progress",
                    "pipe:1",
                    "-stats_period",
                    "0.5",
                    *verification,
                    "-xerror",
                    "-f",
                    "null",
                    "-",
                ),
                checkpoint=checkpoint,
                timeout_seconds=max(120, float(result.duration_seconds or 0) * 2),
                progress=lambda sample: report(
                    MediaPreparationPhase.VERIFYING,
                    verification_message,
                    sample,
                    _duration(result),
                ),
            )
            gain: float | None = None
            warnings = (*plan.warnings, *subtitle_warnings, *caption_warnings)
            if measure_sound_check:
                measurements = re.findall(
                    rb"I:\s*(-?\d+(?:\.\d+)?)\s+LUFS", verification_output.stderr
                )
                if measurements and float(measurements[-1]) > -70:
                    gain = -16.5 - float(measurements[-1])
                else:
                    warnings += (
                        "Sound Check could not measure this silent or very short track; its existing gain was retained.",
                    )
            checkpoint()
            if result.fingerprint.size > 0xFFFFFFFF:
                raise MediaInspectionError(
                    "media.output_too_large",
                    "The prepared file exceeds the iPod Library's 4 GiB size limit. Choose a smaller quality preset or split the source into shorter files, then rescan and retry this item.",
                )
            if output_path != captured.snapshot:
                workspace.discard_capture(captured)
            yield PreparedTranscode(
                output_path,
                result,
                plan.encoding,
                captured.fingerprint,
                plan.requires_transcode,
                warnings,
                gain,
                inspect_mp3_variable_bitrate(output_path)
                if plan.encoding is AudioEncoding.MP3
                else False,
                observed,
                metadata,
            )


def _input_arguments(
    source: HostPath, threads: int, *, info: bool = False
) -> tuple[str, ...]:
    return (
        "-hide_banner",
        "-nostdin",
        "-nostats",
        "-xerror",
        "-v",
        "info" if info else "error",
        "-n",
        "-protocol_whitelist",
        "file,pipe",
        "-format_whitelist",
        _FORMATS,
        "-threads",
        str(threads),
        "-filter_threads",
        str(threads),
        "-i",
        str(source),
    )


def _container_arguments(
    encoding: AudioEncoding | VideoEncoding,
    video_muxer: Literal["ipod", "mov"] = "ipod",
) -> tuple[str, ...]:
    if encoding is VideoEncoding.MP4:
        # Automatic stream-clock LCMs can prevent Classic subtitle playback.
        return (
            "-movie_timescale",
            "1000",
            "-movflags",
            "+faststart",
            "-f",
            video_muxer,
        )
    if encoding in (AudioEncoding.AAC, AudioEncoding.ALAC):
        return ("-movflags", "+faststart", "-f", "ipod")
    if encoding is AudioEncoding.MP3:
        return ("-id3v2_version", "3", "-write_id3v1", "0", "-f", "mp3")
    return ("-f", "wav" if encoding is AudioEncoding.WAV else "aiff")


def _duration(observed: MediaInspection) -> float | None:
    streams = observed.video_streams or observed.audio_streams
    stream = _select_preferred_stream(streams) if streams else None
    duration = stream.duration_seconds if stream is not None else None
    if not duration:
        duration = observed.duration_seconds
        # Matroska's Segment Duration includes a positive timestamp origin.
        # FFmpeg rebases that origin when remuxing; it is not playable duration.
        # Other containers (notably MPEG-TS) already report an elapsed duration.
        if (
            duration is not None
            and {"matroska", "webm"}.intersection(observed.containers)
            and observed.start_seconds is not None
            and 0 < observed.start_seconds < duration
        ):
            duration -= observed.start_seconds
    return float(duration) if duration is not None else None


def _metadata_arguments(track: Track, full: bool) -> tuple[str, ...]:
    metadata = track.metadata
    fields = {"lyrics": metadata.lyrics}
    if full:
        fields.update(
            title=track.title,
            artist=track.artist,
            album=track.album,
            album_artist=track.album_artist,
            genre=track.genre,
            date=str(track.year) if track.year else "",
            track=str(track.track_number) if track.track_number else "",
            disc=str(metadata.disc_number) if metadata.disc_number else "",
            composer=metadata.composer,
            comment=metadata.comment,
        )
    return tuple(
        part
        for key, value in fields.items()
        for part in ("-metadata", f"{key}={value}")
    )


def enrich_source_metadata(track: Track, observed: MediaInspection) -> Track:
    """Fill source-only metadata while preserving reviewed/normalized core tags."""
    enriched = apply_tag_values(
        track,
        inspection_tag_values(observed),
        suffix=observed.source.path.suffix,
        video=bool(observed.video_streams),
        fill_only=True,
    )
    metadata = enriched.metadata
    return replace(
        enriched,
        metadata=replace(
            metadata,
            chapters=metadata.chapters or imported_chapters(observed.chapters),
        ),
    )
