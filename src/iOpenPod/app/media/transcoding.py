"""Pure device encoding policy and Storage-owned Host media preparation."""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from iOpenPod.app.export_tagging import ExportMediaTagger
from iOpenPod.app.media.content_type import classify_content_type
from iOpenPod.app.media.inspection import MediaInspectionError, MediaInspector
from iOpenPod.app.media.models import StreamKind
from iPodDB.library import AudioEncoding, MediaKind, MediaType, TrackChapter
from storage.media_processing import (
    MediaToolError,
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

    from device_registry import DeviceProfile
    from iOpenPod.app.media.models import MediaInspection
    from iPodDB.library import Track
    from storage import FileFingerprint, HostPath


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
    bitrate = (
        settings.spoken_word_bitrate_kbps
        if spoken
        else {
            TranscodeQuality.COMPACT: 128,
            TranscodeQuality.BALANCED: 192,
            TranscodeQuality.HIGH: 256,
        }[settings.quality]
        if automatic
        else settings.bitrate_kbps
    )
    mode = BitrateMode.CBR if spoken or automatic else settings.bitrate_mode
    args = ["-c:a", encoder.value]
    if encoder is not LossyEncoder.MP3:
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


def resolve_transcode(
    observed: MediaInspection,
    profile: DeviceProfile,
    settings: TranscodeSettings,
    available_encoders: frozenset[str],
    *,
    spoken_word: bool = False,
) -> TranscodePlan:
    """Choose compatible copy or conversion without touching any filesystem."""
    if observed.video_streams:
        return _resolve_video(
            observed, profile, settings, available_encoders, spoken_word
        )
    if len(observed.audio_streams) != 1 or any(
        s.kind is StreamKind.VIDEO and s.attached_picture is not True
        for s in observed.streams
    ):
        raise MediaInspectionError(
            "media.unsupported_streams",
            "This item requires one audio stream and no motion video. Select an audio edition or exclude it from Review; the other selected items can still Sync.",
        )
    audio = observed.audio_streams[0]
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
        return TranscodePlan(compatible, _SUFFIXES[compatible], (), rate, channels)
    warnings: list[str] = []
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
        if not lossless:
            warnings.append("Re-encoding a lossy source can reduce audio quality.")
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
        or len(observed.audio_streams) > 1
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
        or video.bitrate_bps is None
        or not 0 < video.bitrate_bps <= caps.max_bitrate_kbps * 1000
    ):
        return False
    if observed.audio_streams:
        audio = observed.audio_streams[0]
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
        or (
            caps.supports_tx3g_subtitles
            and s.codec == "mov_text"
            and s.codec_tag == "tx3g"
            and bool(s.width)
            and bool(s.height)
        )
        for s in observed.streams
    )


def _resolve_video(
    observed: MediaInspection,
    profile: DeviceProfile,
    settings: TranscodeSettings,
    available: frozenset[str],
    spoken: bool,
) -> TranscodePlan:
    caps = profile.capabilities.video
    if not caps.supported:
        raise MediaInspectionError(
            "media.video_unsupported",
            "This iPod cannot play video. Choose an audio edition or exclude this item; the other selected items can still Sync.",
        )
    if len(observed.video_streams) != 1 or len(observed.audio_streams) > 1:
        raise MediaInspectionError(
            "media.video_stream_selection",
            "This video has multiple video or audio streams. Select an edition with one video and at most one audio stream, then rescan; no language or camera angle was silently removed.",
        )
    video = observed.video_streams[0]
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
    audio = next(iter(observed.audio_streams), None)
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
    if (
        compatible_video(observed, profile)
        and not settings.retranscode_lossy
        and not spoken
        and (
            audio is None
            or (rate == audio.sample_rate_hz and channels == audio.channels)
        )
    ):
        return TranscodePlan(VideoEncoding.MP4, ".m4v", (), rate, channels)
    warnings: list[str] = []
    args = ["-map", f"0:{video.index}"]
    # Check the motion stream independently so an audio repair can copy video.
    video_only = replace(observed, streams=(video,))
    if compatible_video(video_only, profile):
        args += ["-c:v", "copy"]
    else:
        if "libx264" not in available:
            raise MediaToolError(
                "media.video_encoder_missing",
                "This FFmpeg build lacks libx264, required for this iPod's H.264 Baseline video. Install a build with libx264, then retry this item.",
            )
        filters = [
            f"scale=w='min({caps.max_width},iw)':h='min({caps.max_height},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos"
        ]
        if video.frame_rate > caps.max_fps:
            filters.append(f"fps={caps.max_fps}")
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
        warnings.append(
            f"Prepared H.264 Baseline video within this iPod's {caps.max_width}x{caps.max_height}, {caps.max_fps} fps and bitrate limits."
        )
    if audio is not None:
        args += ["-map", f"0:{audio.index}"]
        if (
            audio.codec == "aac"
            and audio.profile == "LC"
            and audio.channels == channels
            and audio.sample_rate_hz == rate
            and audio.bitrate_bps is not None
            and 0 < audio.bitrate_bps <= caps.max_audio_bitrate_kbps * 1000
            and not settings.retranscode_lossy
            and not spoken
        ):
            args += ["-c:a", "copy"]
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
            args += [*audio_args, "-ar", str(rate), "-ac", str(channels)]
    for stream in observed.streams:
        if stream.kind is StreamKind.SUBTITLE:
            if (
                caps.supports_tx3g_subtitles
                and stream.codec == "mov_text"
                and stream.codec_tag == "tx3g"
                and stream.width
                and stream.height
            ):
                args += ["-map", f"0:{stream.index}", "-c:s", "copy"]
            else:
                warnings.append(
                    f"Subtitle stream {stream.index} ({stream.codec}) is unsupported in this iPod's M4V output and was excluded from the device copy."
                )
    return TranscodePlan(
        VideoEncoding.MP4, ".m4v", tuple(args), rate, channels, tuple(warnings)
    )


class MediaTranscoder:
    """Prepare verified Host files; keep them alive through the caller's commit."""

    def __init__(self, *, threads_per_job: int = 1) -> None:
        if threads_per_job < 1:
            raise ValueError("Encoder thread count must be positive")
        self.threads_per_job = min(threads_per_job, available_compute_threads())

    def preflight(self, *, checkpoint: Callable[[], None]) -> MediaTools:
        return discover_media_tools(checkpoint=checkpoint)

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
    ) -> Generator[PreparedTranscode]:
        tools = tools or self.preflight(checkpoint=checkpoint)
        inspector = MediaInspector(tools.ffprobe)
        with media_workspace(checkpoint=checkpoint) as workspace:
            captured = workspace.capture(source, expected=expected_source)
            observed = inspector.inspect_captured(captured, checkpoint=checkpoint)
            if metadata is not None:
                metadata = enrich_source_metadata(metadata, observed)
                spoken_word = spoken_word or metadata.media_kind in (
                    MediaKind.PODCAST,
                    MediaKind.AUDIOBOOK,
                )
            plan = resolve_transcode(
                observed, profile, settings, tools.encoders, spoken_word=spoken_word
            )
            result = replace(
                observed,
                source=captured.snapshot,
                fingerprint=workspace.snapshot_fingerprint(captured),
            )
            output_path = captured.snapshot
            if plan.requires_transcode:
                output_path = workspace.output_path(plan.suffix)
                args = plan.output_arguments
                tags = (
                    _metadata_arguments(metadata, rockbox_metadata)
                    if metadata is not None
                    else ()
                )
                run_media_tool(
                    tools.ffmpeg,
                    (
                        *_input_arguments(captured.snapshot, self.threads_per_job),
                        *args,
                        "-map_metadata",
                        "0" if rockbox_metadata else "-1",
                        "-map_chapters",
                        "0",
                        *tags,
                        "-threads",
                        str(self.threads_per_job),
                        *_container_arguments(plan.encoding),
                        str(output_path),
                    ),
                    checkpoint=checkpoint,
                    timeout_seconds=max(120, float(observed.duration_seconds or 0) * 4),
                )
                output = workspace.inspect_output(output_path)
                result = inspector.inspect_captured(output, checkpoint=checkpoint)
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
                original_duration = _duration(observed)
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
            if rockbox_metadata:
                if metadata is None:
                    raise ValueError("Rockbox metadata requires the reviewed Track")
                reviewed_track = metadata
                tagger = ExportMediaTagger()
                output = workspace.transform_bytes(
                    output_path,
                    plan.suffix,
                    lambda data: tagger.prepare_bytes(
                        data, f"media{plan.suffix}", reviewed_track
                    ),
                )
                output_path = output.snapshot
                result = inspector.inspect_captured(output, checkpoint=checkpoint)
            measure_sound_check = compute_sound_check and bool(result.audio_streams)
            verification: tuple[str, ...] = ("-map", "0:a?", "-map", "0:v?", "-sn")
            if measure_sound_check:
                verification += ("-af", "ebur128=framelog=verbose")
            verification_output = run_media_tool(
                tools.ffmpeg,
                (
                    *_input_arguments(
                        output_path, self.threads_per_job, info=measure_sound_check
                    ),
                    *verification,
                    "-xerror",
                    "-f",
                    "null",
                    "-",
                ),
                checkpoint=checkpoint,
                timeout_seconds=max(120, float(result.duration_seconds or 0) * 2),
            )
            gain: float | None = None
            warnings = plan.warnings
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


def _container_arguments(encoding: AudioEncoding | VideoEncoding) -> tuple[str, ...]:
    if encoding in (AudioEncoding.AAC, AudioEncoding.ALAC, VideoEncoding.MP4):
        return ("-movflags", "+faststart", "-f", "ipod")
    if encoding is AudioEncoding.MP3:
        return ("-id3v2_version", "3", "-write_id3v1", "0", "-f", "mp3")
    return ("-f", "wav" if encoding is AudioEncoding.WAV else "aiff")


def _duration(observed: MediaInspection) -> float | None:
    stream = next(iter(observed.video_streams or observed.audio_streams), None)
    duration = (
        stream.duration_seconds if stream is not None else None
    ) or observed.duration_seconds
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
    tags = {
        tag.name.casefold(): tag.value
        for tag in (
            *observed.tags,
            *(tag for stream in observed.audio_streams for tag in stream.tags),
        )
    }
    metadata = track.metadata
    lyrics = tags.get("lyrics", "") or next(
        (value for key, value in tags.items() if key.startswith("lyrics-")), ""
    )
    media_types = track.media_types
    if media_types in ((MediaType.AUDIO,), (MediaType.VIDEO,)):
        media_types = (
            classify_content_type(
                observed.source.path.suffix, tags, video=bool(observed.video_streams)
            ),
        )
    return replace(
        track,
        media_types=media_types,
        metadata=replace(
            metadata,
            composer=metadata.composer or tags.get("composer", ""),
            comment=metadata.comment or tags.get("comment", ""),
            lyrics=metadata.lyrics or lyrics,
            copyright=metadata.copyright or tags.get("copyright", ""),
            grouping=metadata.grouping or tags.get("grouping", ""),
            description=metadata.description or tags.get("description", ""),
            chapters=metadata.chapters
            or tuple(
                TrackChapter(
                    next(
                        (
                            tag.value
                            for tag in chapter.tags
                            if tag.name.casefold() == "title"
                        ),
                        "",
                    ),
                    round(chapter.start_seconds * 1000),
                )
                for chapter in observed.chapters
            ),
        ),
    )
