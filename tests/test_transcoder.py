import logging

import iopenpod.sync.transcoder as transcoder_module
from iopenpod.infrastructure.settings_schema import AppSettings
from iopenpod.sync.transcoder import (
    AudioProperties,
    TranscodeOptions,
    TranscodeResult,
    TranscodeTarget,
    _transcode_timeout_seconds,
    find_ffprobe,
    get_transcode_target,
    needs_transcoding,
    transcode,
)


def test_audio_transcode_timeout_keeps_existing_floor_for_short_files() -> None:
    assert _transcode_timeout_seconds(TranscodeTarget.AAC, 0) == 600
    assert _transcode_timeout_seconds(TranscodeTarget.ALAC, 5 * 60 * 1_000_000) == 900


def test_audio_transcode_timeout_scales_for_long_audiobook_sized_files() -> None:
    twelve_hour_book_us = 12 * 60 * 60 * 1_000_000
    assert _transcode_timeout_seconds(TranscodeTarget.AAC, twelve_hour_book_us) == 43200


def test_audio_transcode_timeout_is_capped_for_extreme_durations() -> None:
    thirty_hour_book_us = 30 * 60 * 60 * 1_000_000
    assert _transcode_timeout_seconds(TranscodeTarget.MP3, thirty_hour_book_us) == 43200


def test_video_transcode_timeout_uses_longer_floor_and_padding() -> None:
    one_hour_video_us = 60 * 60 * 1_000_000
    assert _transcode_timeout_seconds(TranscodeTarget.VIDEO_H264, one_hour_video_us) == 9000


def test_video_transcode_command_allows_silent_sources() -> None:
    command = transcoder_module._cmd_video(
        "ffmpeg",
        "silent.mp4",
        "output.m4v",
        crf=23,
        preset="medium",
        max_w=320,
        max_h=240,
        max_fps=30,
        max_bitrate=0,
        h264_level="3.0",
        audio_encoder="aac",
    )

    assert "0:a:0?" in command


def test_unprobeable_native_audio_reencodes_instead_of_copying_blind(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        transcoder_module,
        "_resolve_lossy_target",
        lambda options: TranscodeTarget.AAC,
    )
    monkeypatch.setattr(
        transcoder_module,
        "probe_audio",
        lambda filepath: AudioProperties(probe_ok=False),
    )

    with caplog.at_level(logging.WARNING, logger="iopenpod.sync.transcoder"):
        target = get_transcode_target("Café.m4a")

    assert target == TranscodeTarget.AAC
    assert "re-encoding instead of copying blind" in caplog.text


def test_native_mp3_copies_by_default_and_reencodes_when_forced(monkeypatch) -> None:
    monkeypatch.setattr(
        transcoder_module,
        "_resolve_lossy_target",
        lambda options: TranscodeTarget.MP3,
    )
    monkeypatch.setattr(
        transcoder_module,
        "probe_audio",
        lambda filepath: AudioProperties(
            sample_rate=44100,
            channels=2,
            codec_name="mp3",
            probe_ok=True,
        ),
    )

    assert get_transcode_target("song.mp3") == TranscodeTarget.COPY

    options = TranscodeOptions(always_encode_lossy=True)

    assert get_transcode_target("song.mp3", options=options) == TranscodeTarget.MP3
    assert needs_transcoding("song.mp3", options=options) is True


def test_lossy_native_aac_copies_by_default_and_reencodes_when_forced(monkeypatch) -> None:
    monkeypatch.setattr(
        transcoder_module,
        "_resolve_lossy_target",
        lambda options: TranscodeTarget.AAC,
    )
    monkeypatch.setattr(
        transcoder_module,
        "probe_audio",
        lambda filepath: AudioProperties(
            sample_rate=44100,
            bits_per_sample=0,
            channels=2,
            codec_name="aac",
            profile="LC",
            probe_ok=True,
        ),
    )

    assert get_transcode_target("song.m4a") == TranscodeTarget.COPY

    options = TranscodeOptions(always_encode_lossy=True)

    assert get_transcode_target("song.m4a", options=options) == TranscodeTarget.AAC


def test_alac_m4a_is_not_forced_by_always_encode_lossy(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "_device_supports_alac", lambda: True)
    monkeypatch.setattr(
        transcoder_module,
        "_resolve_lossy_target",
        lambda options: TranscodeTarget.AAC,
    )
    monkeypatch.setattr(
        transcoder_module,
        "probe_audio",
        lambda filepath: AudioProperties(
            sample_rate=44100,
            bits_per_sample=16,
            channels=2,
            codec_name="alac",
            probe_ok=True,
        ),
    )

    assert (
        get_transcode_target(
            "song.m4a",
            options=TranscodeOptions(always_encode_lossy=True),
        )
        == TranscodeTarget.COPY
    )
    assert (
        get_transcode_target(
            "song.m4a",
            options=TranscodeOptions(always_encode_lossy=True, prefer_lossy=True),
        )
        == TranscodeTarget.AAC
    )


def test_transcode_options_from_settings_preserves_always_encode_lossy() -> None:
    settings = AppSettings(always_encode_lossy=True)

    options = TranscodeOptions.from_settings(settings)

    assert options.always_encode_lossy is True


def test_wav_copies_when_alac_conversion_disabled(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "_device_supports_alac", lambda: True)

    options = TranscodeOptions(convert_wav_to_alac=False)

    assert get_transcode_target("song.wav", options=options) == TranscodeTarget.COPY
    assert needs_transcoding("song.wav", options=options) is False


def test_wav_converts_to_alac_when_alac_conversion_enabled(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "_device_supports_alac", lambda: True)

    assert get_transcode_target("song.wav") == TranscodeTarget.ALAC


def test_wav_prefer_lossy_overrides_alac_conversion_setting(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "_device_supports_alac", lambda: True)
    monkeypatch.setattr(
        transcoder_module,
        "_resolve_lossy_target",
        lambda options: TranscodeTarget.MP3,
    )

    options = TranscodeOptions(prefer_lossy=True, convert_wav_to_alac=True)

    assert get_transcode_target("song.wav", options=options) == TranscodeTarget.MP3


def test_wav_falls_back_to_lossy_when_alac_requested_but_unsupported(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "_device_supports_alac", lambda: False)
    monkeypatch.setattr(
        transcoder_module,
        "_resolve_lossy_target",
        lambda options: TranscodeTarget.AAC,
    )

    options = TranscodeOptions(convert_wav_to_alac=True)

    assert get_transcode_target("song.wav", options=options) == TranscodeTarget.AAC


def test_find_ffprobe_uses_configured_ffmpeg_sibling(tmp_path, monkeypatch) -> None:
    bin_dir = tmp_path / "tools"
    bin_dir.mkdir()
    ffmpeg = bin_dir / "ffmpeg"
    ffprobe_name = "ffprobe.exe" if transcoder_module.sys.platform == "win32" else "ffprobe"
    ffprobe = bin_dir / ffprobe_name
    ffmpeg.write_text("", encoding="utf-8")
    ffprobe.write_text("", encoding="utf-8")

    find_ffprobe.cache_clear()
    monkeypatch.setattr(transcoder_module.shutil, "which", lambda _name: None)

    assert find_ffprobe(str(ffmpeg)) == str(ffprobe)


def test_ffmpeg_availability_requires_ffprobe(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "find_ffmpeg", lambda _path=None: "/tmp/ffmpeg")
    monkeypatch.setattr(transcoder_module, "find_ffprobe", lambda _path=None: None)

    assert transcoder_module.is_ffmpeg_available() is False


def test_transcode_requires_ffprobe_for_transcodes(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.flac"
    source.write_bytes(b"audio")

    monkeypatch.setattr(transcoder_module, "find_ffmpeg", lambda _path=None: "/tmp/ffmpeg")
    monkeypatch.setattr(transcoder_module, "find_ffprobe", lambda _path=None: None)

    result = transcode(source, tmp_path / "out")

    assert isinstance(result, TranscodeResult)
    assert result.success is False
    assert result.error_message == "ffprobe not found"
