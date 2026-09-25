"""Encoder preferences remain valid and independent across selections and restarts."""

from pathlib import Path

import pytest

from iOpenPod.app.core.settings.definitions import (
    COMPUTE_SOUND_CHECK,
    FIT_THUMBNAILS,
    LOSSY_ENCODER,
    LOSSY_QUALITY,
    NORMALIZE_SAMPLE_RATE,
    NORMALIZE_TAGS_AFTER_SYNC,
    RETRANSCODE_LOSSY,
    ROCKBOX_METADATA_SUPPORT,
    ROTATE_TALL_PHOTOS,
    SMART_QUALITY_BY_CONTENT_TYPE,
    SPOKEN_WORD_BITRATE,
    SPOKEN_WORD_MONO,
    TRANSCODE_LOSSLESS_TO_LOSSY,
    TRANSCODE_PCM_TO_ALAC,
)
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import (
    DeviceSettingsStore,
    GlobalSettingsStore,
    JsonSettingsStore,
)
from iOpenPod.app.core.settings.transcoding import (
    encoder_bitrate,
    encoder_bitrate_mode,
    encoder_cutoff,
    encoder_option,
    encoder_vbr_quality,
    read_transcoder_settings,
)
from iOpenPod.app.media.transcoding import BitrateMode, LossyEncoder, TranscodeQuality
from storage import AtomicHostFile


def test_invalid_encoder_values_fall_back_to_valid_per_encoder_defaults() -> None:
    store = GlobalSettingsStore()
    settings = SettingsService(store, DeviceSettingsStore())
    settings.set_global(LOSSY_ENCODER, LossyEncoder.FDK_AAC.value)
    store.set(encoder_bitrate_mode(LossyEncoder.FDK_AAC).key, "cvbr")
    store.set(encoder_vbr_quality(LossyEncoder.FDK_AAC).key, 9)
    store.set(SPOKEN_WORD_BITRATE.key, True)
    captured = read_transcoder_settings(settings)
    assert captured.bitrate_mode is BitrateMode.VBR
    assert captured.vbr_quality == 3
    assert captured.spoken_word_bitrate_kbps == 64
    with pytest.raises(ValueError):
        settings.set_global(encoder_bitrate_mode(LossyEncoder.MP3), "cvbr")
    with pytest.raises(ValueError):
        settings.set_global(encoder_vbr_quality(LossyEncoder.FDK_AAC), 0)
    with pytest.raises(ValueError):
        settings.set_global(SPOKEN_WORD_BITRATE, 128)
    with pytest.raises(ValueError):
        encoder_option(LossyEncoder.MP3, "afterburner")
    with pytest.raises(ValueError):
        encoder_bitrate_mode(LossyEncoder.AUTO)


def test_sync_preferences_persist_and_policy_is_an_immutable_snapshot(
    tmp_path: Path,
) -> None:
    target = AtomicHostFile(tmp_path / "settings-v2.json")
    settings = SettingsService(JsonSettingsStore(target), DeviceSettingsStore())
    settings.set_global(LOSSY_ENCODER, "libfdk_aac")
    settings.set_global(LOSSY_QUALITY, "high")
    settings.set_global(encoder_bitrate_mode(LossyEncoder.FDK_AAC), "cbr")
    settings.set_global(encoder_bitrate(LossyEncoder.FDK_AAC), 256)
    settings.set_global(encoder_vbr_quality(LossyEncoder.FDK_AAC), 5)
    settings.set_global(encoder_cutoff(LossyEncoder.FDK_AAC), 18000)
    settings.set_global(encoder_option(LossyEncoder.FDK_AAC, "afterburner"), False)
    booleans = (
        COMPUTE_SOUND_CHECK,
        FIT_THUMBNAILS,
        NORMALIZE_SAMPLE_RATE,
        NORMALIZE_TAGS_AFTER_SYNC,
        RETRANSCODE_LOSSY,
        ROCKBOX_METADATA_SUPPORT,
        ROTATE_TALL_PHOTOS,
        SMART_QUALITY_BY_CONTENT_TYPE,
        SPOKEN_WORD_MONO,
        TRANSCODE_LOSSLESS_TO_LOSSY,
        TRANSCODE_PCM_TO_ALAC,
    )
    for definition in booleans:
        settings.set_global(definition, not definition.default)
    settings.set_global(SPOKEN_WORD_BITRATE, 80)
    settings.set_global(encoder_option(LossyEncoder.AAC, "pns"), True)
    settings.set_global(encoder_option(LossyEncoder.AAC, "tns"), False)
    settings.set_global(encoder_option(LossyEncoder.AAC, "mid-side-stereo"), False)
    settings.set_global(encoder_option(LossyEncoder.AAC, "intensity-stereo"), False)
    snapshot = read_transcoder_settings(settings)
    settings.set_global(LOSSY_ENCODER, "libmp3lame")
    settings.set_global(encoder_bitrate_mode(LossyEncoder.MP3), "abr")
    settings.set_global(encoder_bitrate(LossyEncoder.MP3), 128)

    reopened = SettingsService(JsonSettingsStore(target), DeviceSettingsStore())
    assert read_transcoder_settings(reopened).bitrate_mode is BitrateMode.ABR
    assert read_transcoder_settings(reopened).bitrate_kbps == 128
    assert snapshot.lossy_encoder is LossyEncoder.FDK_AAC
    assert snapshot.quality is TranscodeQuality.HIGH
    assert snapshot.bitrate_kbps == 256
    assert snapshot.spoken_word_bitrate_kbps == 80
    for definition in booleans:
        assert reopened.get(definition) is not definition.default
    reopened.set_global(LOSSY_ENCODER, "libfdk_aac")
    assert read_transcoder_settings(reopened) == snapshot


def test_auto_settings_ignore_stored_manual_quality_controls() -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    settings.set_global(encoder_bitrate_mode(LossyEncoder.FDK_AAC), "cbr")
    settings.set_global(encoder_bitrate(LossyEncoder.FDK_AAC), 32)
    automatic = read_transcoder_settings(settings)
    assert automatic.lossy_encoder is LossyEncoder.AUTO
    assert automatic.quality is TranscodeQuality.BALANCED
    assert automatic.bitrate_kbps != 32
    assert automatic.normalize_44100 is False
    assert automatic.pns is False
