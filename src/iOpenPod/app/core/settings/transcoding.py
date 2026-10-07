"""Persist encoder-specific preferences and capture one immutable Sync policy."""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from iOpenPod.app.media.transcoding import (
    SUPPORTED_BITRATE_MODES,
    VBR_QUALITIES,
    BitrateMode,
    LossyEncoder,
    TranscodeQuality,
    TranscodeSettings,
)

from .definitions import (
    LOSSY_ENCODER,
    LOSSY_QUALITY,
    NORMALIZE_SAMPLE_RATE,
    RETRANSCODE_LOSSY,
    SMART_QUALITY_BY_CONTENT_TYPE,
    SPOKEN_WORD_BITRATE,
    SPOKEN_WORD_MONO,
    TRANSCODE_LOSSLESS_TO_LOSSY,
    TRANSCODE_PCM_TO_ALAC,
    SettingDefinition,
)

if TYPE_CHECKING:
    from .service import SettingsService

ENCODER_BITRATES = (32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
BANDWIDTH_CUTOFFS = (0, 12000, 15000, 16000, 17000, 18000, 19000, 20000)


def _key(encoder: LossyEncoder, suffix: str) -> str:
    if encoder is LossyEncoder.AUTO:
        raise ValueError(
            "Auto uses quality presets instead of encoder-specific settings"
        )
    return f"transcoding/encoders/{encoder.value}/{suffix}"


@cache
def encoder_bitrate_mode(encoder: LossyEncoder) -> SettingDefinition[str]:
    """Keep a supported bitrate mode separately for each encoder."""

    return SettingDefinition[str](
        key=_key(encoder, "bitrate-mode"),
        value_type=str,
        default=BitrateMode.VBR.value,
        device_overridable=True,
        validator=lambda value: value in SUPPORTED_BITRATE_MODES[encoder],
    )


@cache
def encoder_bitrate(encoder: LossyEncoder) -> SettingDefinition[int]:
    return SettingDefinition[int](
        key=_key(encoder, "bitrate-kbps"),
        value_type=int,
        default=192,
        device_overridable=True,
        validator=lambda value: type(value) is int and value in ENCODER_BITRATES,
    )


@cache
def encoder_vbr_quality(encoder: LossyEncoder) -> SettingDefinition[int]:
    return SettingDefinition[int](
        key=_key(encoder, "vbr-quality"),
        value_type=int,
        default=2 if encoder is LossyEncoder.AAC else 3,
        device_overridable=True,
        validator=lambda value: type(value) is int and value in VBR_QUALITIES[encoder],
    )


@cache
def encoder_cutoff(encoder: LossyEncoder) -> SettingDefinition[int]:
    return SettingDefinition[int](
        key=_key(encoder, "bandwidth-cutoff-hz"),
        value_type=int,
        default=0,
        device_overridable=True,
        validator=lambda value: type(value) is int and value in BANDWIDTH_CUTOFFS,
    )


@cache
def encoder_option(encoder: LossyEncoder, option: str) -> SettingDefinition[bool]:
    allowed: set[str] = (
        {"afterburner"}
        if encoder is LossyEncoder.FDK_AAC
        else {"tns", "pns", "mid-side-stereo", "intensity-stereo"}
        if encoder is LossyEncoder.AAC
        else {"mid-side-stereo"}
        if encoder is LossyEncoder.MP3
        else set()
    )
    if option not in allowed:
        raise ValueError(f"{encoder.value} does not support {option}")
    return SettingDefinition[bool](
        key=_key(encoder, option),
        value_type=bool,
        default=option != "pns",
        device_overridable=True,
    )


def read_transcoder_settings(settings: SettingsService) -> TranscodeSettings:
    """Capture validated values once so an active Sync is unaffected by UI changes."""

    encoder = LossyEncoder(settings.get(LOSSY_ENCODER))
    # Auto ignores manual controls. Use the model's defaults for those fields.
    manual = encoder is not LossyEncoder.AUTO
    defaults = TranscodeSettings()
    return TranscodeSettings(
        lossy_encoder=encoder,
        quality=TranscodeQuality(settings.get(LOSSY_QUALITY)),
        lossless_to_lossy=settings.get(TRANSCODE_LOSSLESS_TO_LOSSY),
        retranscode_lossy=settings.get(RETRANSCODE_LOSSY),
        wav_aiff_to_alac=settings.get(TRANSCODE_PCM_TO_ALAC),
        normalize_44100=settings.get(NORMALIZE_SAMPLE_RATE),
        smart_spoken_word=settings.get(SMART_QUALITY_BY_CONTENT_TYPE),
        spoken_word_mono=settings.get(SPOKEN_WORD_MONO),
        spoken_word_bitrate_kbps=settings.get(SPOKEN_WORD_BITRATE),
        bitrate_mode=(
            BitrateMode(settings.get(encoder_bitrate_mode(encoder)))
            if manual
            else defaults.bitrate_mode
        ),
        bitrate_kbps=(
            settings.get(encoder_bitrate(encoder)) if manual else defaults.bitrate_kbps
        ),
        vbr_quality=(
            settings.get(encoder_vbr_quality(encoder))
            if manual
            else defaults.vbr_quality
        ),
        bandwidth_cutoff_hz=(
            settings.get(encoder_cutoff(encoder))
            if manual
            else defaults.bandwidth_cutoff_hz
        ),
        afterburner=settings.get(encoder_option(LossyEncoder.FDK_AAC, "afterburner")),
        tns=settings.get(encoder_option(LossyEncoder.AAC, "tns")),
        pns=settings.get(encoder_option(LossyEncoder.AAC, "pns")),
        mid_side_stereo=settings.get(
            encoder_option(
                LossyEncoder.MP3 if encoder is LossyEncoder.MP3 else LossyEncoder.AAC,
                "mid-side-stereo",
            )
        ),
        intensity_stereo=settings.get(
            encoder_option(LossyEncoder.AAC, "intensity-stereo")
        ),
    )
