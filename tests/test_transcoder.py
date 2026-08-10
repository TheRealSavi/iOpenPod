import json
import logging
from pathlib import Path
from types import SimpleNamespace

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
    assert command[command.index("-f"):command.index("-f") + 2] == ["-f", "ipod"]


def test_video_transcode_uses_aac_at_specific_options() -> None:
    command = transcoder_module._cmd_video(
        "ffmpeg",
        "video.mp4",
        "output.m4v",
        crf=23,
        preset="medium",
        max_w=320,
        max_h=240,
        max_fps=30,
        max_bitrate=0,
        h264_level="1.3",
        audio_encoder="aac_at",
        audio_bitrate_kbps=480,
    )

    assert ["-c:a", "aac_at"] == command[command.index("-c:a"):command.index("-c:a") + 2]
    assert ["-aac_at_mode", "cbr"] == command[
        command.index("-aac_at_mode"):command.index("-aac_at_mode") + 2
    ]
    assert "-profile:a" not in command
    assert ["-b:a", "320k"] == command[command.index("-b:a"):command.index("-b:a") + 2]


def test_video_transcode_keeps_lower_source_audio_bitrate(monkeypatch) -> None:
    monkeypatch.setattr(
        transcoder_module,
        "get_transcode_target",
        lambda *_args, **_kwargs: TranscodeTarget.VIDEO_H264,
    )
    monkeypatch.setattr(
        transcoder_module,
        "probe_audio",
        lambda _path: AudioProperties(bitrate_kbps=128, probe_ok=True),
    )
    monkeypatch.setattr(transcoder_module, "_subtitle_streams", lambda _path: [])

    plan = transcoder_module.resolve_transcode_plan("video.mp4")
    command = transcoder_module._build_ffmpeg_command(
        "ffmpeg",
        plan.source_path,
        plan.source_path.with_suffix(plan.output_extension),
        plan,
        TranscodeOptions(),
    )

    assert plan.video_audio_bitrate_kbps == 128
    assert ["-b:a", "128k"] == command[command.index("-b:a"):command.index("-b:a") + 2]


def test_video_transcode_honors_the_resolved_lossy_encoder(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "available_aac_encoders", lambda _path=None: {"aac", "aac_at"})
    monkeypatch.setattr(transcoder_module, "_best_aac_encoder", lambda _path=None: "aac_at")
    monkeypatch.setattr(
        transcoder_module,
        "get_transcode_target",
        lambda *_args, **_kwargs: TranscodeTarget.VIDEO_H264,
    )
    monkeypatch.setattr(transcoder_module, "_subtitle_streams", lambda _path: [])
    monkeypatch.setattr(transcoder_module, "_get_video_caps", lambda: (320, 240, 30, 0, "1.3"))

    options = TranscodeOptions(lossy_encoder="aac")
    plan = transcoder_module.resolve_transcode_plan("video.mp4", options=options)
    command = transcoder_module._build_ffmpeg_command(
        "ffmpeg",
        plan.source_path,
        plan.source_path.with_suffix(plan.output_extension),
        plan,
        options,
    )

    assert plan.lossy_encoder == "aac"
    assert ["-c:a", "aac"] == command[command.index("-c:a"):command.index("-c:a") + 2]


def test_video_transcode_command_copies_compatible_video_when_only_audio_is_incompatible() -> None:
    command = transcoder_module._cmd_video(
        "ffmpeg",
        "video.mp4",
        "output.m4v",
        crf=23,
        preset="medium",
        max_w=640,
        max_h=480,
        max_fps=30,
        max_bitrate=2500,
        h264_level="3.0",
        audio_encoder="aac",
        copy_video=True,
    )

    assert ["-c:v", "copy"] == command[command.index("-c:v"):command.index("-c:v") + 2]
    assert "-vf" not in command
    assert ["-c:a", "aac"] == command[command.index("-c:a"):command.index("-c:a") + 2]


def test_video_transcode_command_copies_compatible_audio_when_only_video_is_incompatible() -> None:
    command = transcoder_module._cmd_video(
        "ffmpeg",
        "video.mp4",
        "output.m4v",
        crf=23,
        preset="medium",
        max_w=640,
        max_h=480,
        max_fps=30,
        max_bitrate=2500,
        h264_level="3.0",
        audio_encoder="aac",
        copy_audio=True,
    )

    assert ["-c:v", "libx264"] == command[command.index("-c:v"):command.index("-c:v") + 2]
    assert ["-c:a", "copy"] == command[command.index("-c:a"):command.index("-c:a") + 2]
    assert "-ar" not in command


def _stream_compatibility(
    *,
    video_compatible: bool = True,
    audio_compatible: bool = True,
    has_audio: bool = True,
) -> object:
    return transcoder_module.VideoStreamCompatibility(
        probe_ok=True,
        video_compatible=video_compatible,
        audio_compatible=audio_compatible,
        has_audio=has_audio,
    )


def test_video_probe_checks_only_the_mapped_primary_audio_and_video_streams(monkeypatch) -> None:
    stream_payload = {
        "streams": [
            {
                "codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p",
                "width": 640, "height": 480, "r_frame_rate": "30/1",
                "profile": "Baseline", "level": 30, "bit_rate": "2400000",
            },
            {
                "codec_type": "audio", "codec_name": "aac", "profile": "LC",
                "sample_rate": "48000", "channels": 2, "bit_rate": "320000",
            },
            {"codec_type": "video", "codec_name": "hevc"},
            {"codec_type": "audio", "codec_name": "ac3"},
        ],
    }
    monkeypatch.setattr(transcoder_module, "_find_ffprobe", lambda: "ffprobe")
    monkeypatch.setattr(transcoder_module, "_get_video_caps", lambda: (640, 480, 30, 2500, "3.0"))
    monkeypatch.setattr(
        transcoder_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(stream_payload)),
    )

    compatibility = transcoder_module.probe_video_stream_compatibility("video.mp4")

    assert compatibility.video_compatible is True
    assert compatibility.audio_compatible is True
    assert compatibility.has_audio is True


def test_video_probe_rejects_an_incompatible_primary_aac_stream(monkeypatch) -> None:
    stream_payload = {
        "streams": [
            {
                "codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p",
                "width": 640, "height": 480, "r_frame_rate": "30/1",
                "profile": "Baseline", "level": 30, "bit_rate": "2400000",
            },
            {
                "codec_type": "audio", "codec_name": "aac", "profile": "HE-AAC",
                "sample_rate": "96000", "channels": 2, "bit_rate": "192000",
            },
        ],
    }
    monkeypatch.setattr(transcoder_module, "_find_ffprobe", lambda: "ffprobe")
    monkeypatch.setattr(transcoder_module, "_get_video_caps", lambda: (640, 480, 30, 2500, "3.0"))
    monkeypatch.setattr(
        transcoder_module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(stream_payload)),
    )

    compatibility = transcoder_module.probe_video_stream_compatibility("video.mp4")

    assert compatibility.video_compatible is True
    assert compatibility.audio_compatible is False


def test_compatible_video_with_only_incompatible_audio_transcodes_audio_only(monkeypatch) -> None:
    monkeypatch.setattr(
        transcoder_module,
        "probe_video_stream_compatibility",
        lambda _path: _stream_compatibility(audio_compatible=False),
    )
    monkeypatch.setattr(transcoder_module, "_subtitle_streams", lambda _path: [])

    assert get_transcode_target("video.mp4") == TranscodeTarget.VIDEO_TRANSCODE_AUDIO


def test_compatible_audio_with_only_incompatible_video_transcodes_video_only(monkeypatch) -> None:
    monkeypatch.setattr(
        transcoder_module,
        "probe_video_stream_compatibility",
        lambda _path: _stream_compatibility(video_compatible=False),
    )
    monkeypatch.setattr(transcoder_module, "_subtitle_streams", lambda _path: [])

    assert get_transcode_target("video.mp4") == TranscodeTarget.VIDEO_TRANSCODE_VIDEO


def test_silent_compatible_video_copies_without_an_audio_reencode(monkeypatch) -> None:
    monkeypatch.setattr(
        transcoder_module,
        "probe_video_stream_compatibility",
        lambda _path: _stream_compatibility(has_audio=False),
    )
    monkeypatch.setattr(transcoder_module, "_subtitle_streams", lambda _path: [])

    assert get_transcode_target("silent.mp4") == TranscodeTarget.COPY


def test_video_transcode_command_preserves_native_tx3g_subtitles_and_metadata() -> None:
    command = transcoder_module._cmd_video(
        "ffmpeg",
        "subtitled.mp4",
        "output.m4v",
        crf=23,
        preset="medium",
        max_w=640,
        max_h=480,
        max_fps=30,
        max_bitrate=0,
        h264_level="3.0",
        audio_encoder="aac",
        subtitle_stream_indexes=[2],
    )

    assert any(command[index:index + 2] == ["-map", "0:2?"] for index in range(len(command)))
    assert command[command.index("-c:s"):command.index("-c:s") + 2] == ["-c:s", "copy"]
    assert command[command.index("-map_metadata"):command.index("-map_metadata") + 2] == ["-map_metadata", "0"]


def test_video_remux_stream_copies_only_native_tx3g_subtitles() -> None:
    command = transcoder_module._cmd_video_remux(
        "ffmpeg",
        "subtitled.mp4",
        "output.m4v",
        subtitle_stream_indexes=[2],
    )

    assert any(command[index:index + 2] == ["-map", "0:2?"] for index in range(len(command)))
    assert ["-c:v", "copy"] == command[command.index("-c:v"):command.index("-c:v") + 2]
    assert ["-c:a", "copy"] == command[command.index("-c:a"):command.index("-c:a") + 2]
    assert ["-c:s", "copy"] == command[command.index("-c:s"):command.index("-c:s") + 2]


def test_video_transcode_selects_only_device_supported_timed_text(monkeypatch) -> None:
    monkeypatch.setattr(
        transcoder_module,
        "_run_ffprobe",
        lambda *_args, **_kwargs: {
            "streams": [
                {
                    "index": 2,
                    "codec_type": "subtitle",
                    "codec_name": "mov_text",
                    "codec_tag_string": "tx3g",
                    "width": 640,
                    "height": 54,
                },
                {"index": 3, "codec_type": "subtitle", "codec_name": "eia_608", "codec_tag_string": "c608"},
                {"index": 4, "codec_type": "subtitle", "codec_name": "mov_text", "codec_tag_string": "text"},
                {"index": 5, "codec_type": "subtitle", "codec_name": "eia_608", "codec_tag_string": "c708"},
                {"index": 6, "codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle", "codec_tag_string": "pgss"},
                {"index": 7, "codec_type": "subtitle", "codec_name": "subrip", "codec_tag_string": "subp"},
            ],
        },
    )
    monkeypatch.setattr(
        transcoder_module,
        "_device_supported_timed_text_codecs",
        lambda: frozenset({"mov_text", "eia_608"}),
    )

    assert transcoder_module._ipod_subtitle_stream_indexes("subtitled.mp4") == [2, 3]


def test_c608_is_not_selected_for_an_ipod_m4v_output(monkeypatch) -> None:
    monkeypatch.setattr(
        transcoder_module,
        "_run_ffprobe",
        lambda *_args, **_kwargs: {
            "streams": [
                {"index": 3, "codec_type": "subtitle", "codec_name": "eia_608", "codec_tag_string": "c608"},
            ],
        },
    )
    monkeypatch.setattr(
        transcoder_module,
        "_device_supported_timed_text_codecs",
        lambda: frozenset({"eia_608"}),
    )

    assert transcoder_module._ipod_subtitle_stream_indexes("captioned.mov") == [3]
    assert transcoder_module._ipod_subtitle_stream_indexes(
        "captioned.mov",
        output_muxer="ipod",
    ) == []


def test_transcoded_video_with_supported_c608_uses_mov_output(monkeypatch) -> None:
    monkeypatch.setattr(
        transcoder_module,
        "get_transcode_target",
        lambda *_args, **_kwargs: TranscodeTarget.VIDEO_TRANSCODE_VIDEO,
    )
    monkeypatch.setattr(
        transcoder_module,
        "_device_supported_timed_text_codecs",
        lambda: frozenset({"eia_608"}),
    )
    monkeypatch.setattr(
        transcoder_module,
        "_subtitle_streams",
        lambda _path: [
            transcoder_module.TimedTextStream(3, "eia_608", "c608"),
        ],
    )

    plan = transcoder_module.resolve_transcode_plan("captioned.mp4")
    command = transcoder_module._build_ffmpeg_command(
        "ffmpeg",
        plan.source_path,
        plan.source_path.with_suffix(plan.output_extension),
        plan,
        TranscodeOptions(),
    )

    assert plan.output_extension == ".mov"
    assert plan.cache_target_format == "mov"
    assert any(command[index:index + 2] == ["-map", "0:3?"] for index in range(len(command)))
    assert command[command.index("-f"):command.index("-f") + 2] == ["-f", "mov"]


def test_compatible_video_with_a_valid_c608_track_copies_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "probe_video_stream_compatibility", lambda _path: _stream_compatibility())
    monkeypatch.setattr(
        transcoder_module,
        "_device_supported_timed_text_codecs",
        lambda: frozenset({"eia_608"}),
    )
    monkeypatch.setattr(
        transcoder_module,
        "_subtitle_streams",
        lambda _path: [
            transcoder_module.TimedTextStream(3, "eia_608", "c608"),
        ],
    )

    assert get_transcode_target("captioned.mov") == TranscodeTarget.COPY


def test_compatible_video_with_a_wrong_tx3g_sample_entry_is_remuxed(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "probe_video_stream_compatibility", lambda _path: _stream_compatibility())
    monkeypatch.setattr(
        transcoder_module,
        "_device_supported_timed_text_codecs",
        lambda: frozenset({"mov_text"}),
    )
    monkeypatch.setattr(
        transcoder_module,
        "_subtitle_streams",
        lambda _path: [
            transcoder_module.TimedTextStream(2, "mov_text", "text"),
        ],
    )

    assert get_transcode_target("mistagged.mov") == TranscodeTarget.VIDEO_REMUX


def test_compatible_video_with_subtitles_is_remuxed_for_a_device_without_tx3g(
    monkeypatch,
) -> None:
    monkeypatch.setattr(transcoder_module, "probe_video_stream_compatibility", lambda _path: _stream_compatibility())
    monkeypatch.setattr(transcoder_module, "_device_supported_timed_text_codecs", lambda: frozenset())
    monkeypatch.setattr(
        transcoder_module,
        "_subtitle_streams",
        lambda _path: [
            transcoder_module.TimedTextStream(2, "mov_text", "tx3g"),
        ],
    )

    assert get_transcode_target("subtitled.mp4") == TranscodeTarget.VIDEO_REMUX


def test_compatible_video_keeps_only_tx3g_when_the_device_supports_it(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "probe_video_stream_compatibility", lambda _path: _stream_compatibility())
    monkeypatch.setattr(
        transcoder_module,
        "_device_supported_timed_text_codecs",
        lambda: frozenset({"mov_text"}),
    )
    monkeypatch.setattr(
        transcoder_module,
        "_subtitle_streams",
        lambda _path: [
            transcoder_module.TimedTextStream(2, "mov_text", "tx3g", 640, 54),
            transcoder_module.TimedTextStream(3, "subrip", "subp"),
        ],
    )

    assert get_transcode_target("subtitled.mp4") == TranscodeTarget.VIDEO_REMUX


def test_compatible_video_with_only_tx3g_copies_for_a_supported_device(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "probe_video_stream_compatibility", lambda _path: _stream_compatibility())
    monkeypatch.setattr(
        transcoder_module,
        "_device_supported_timed_text_codecs",
        lambda: frozenset({"mov_text"}),
    )
    monkeypatch.setattr(
        transcoder_module,
        "_subtitle_streams",
        lambda _path: [
            transcoder_module.TimedTextStream(2, "mov_text", "tx3g", 640, 54),
        ],
    )

    assert get_transcode_target("subtitled.mp4") == TranscodeTarget.COPY


def test_compatible_video_with_zero_sized_tx3g_is_remuxed_without_subtitles(
    monkeypatch,
) -> None:
    monkeypatch.setattr(transcoder_module, "probe_video_stream_compatibility", lambda _path: _stream_compatibility())
    monkeypatch.setattr(
        transcoder_module,
        "_device_supported_timed_text_codecs",
        lambda: frozenset({"mov_text"}),
    )
    monkeypatch.setattr(
        transcoder_module,
        "_subtitle_streams",
        lambda _path: [
            transcoder_module.TimedTextStream(2, "mov_text", "tx3g", 0, 0),
        ],
    )

    assert get_transcode_target("broken-tx3g.mp4") == TranscodeTarget.VIDEO_REMUX
    assert transcoder_module._ipod_subtitle_stream_indexes("broken-tx3g.mp4") == []


def test_compatible_mov_video_copies_when_its_streams_are_ipod_safe(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "probe_video_stream_compatibility", lambda _path: _stream_compatibility())
    monkeypatch.setattr(transcoder_module, "_subtitle_streams", lambda _path: [])

    assert get_transcode_target("video.mov") == TranscodeTarget.COPY


def test_incompatible_mov_video_is_transcoded(monkeypatch) -> None:
    monkeypatch.setattr(
        transcoder_module,
        "probe_video_stream_compatibility",
        lambda _path: _stream_compatibility(video_compatible=False, audio_compatible=False),
    )

    assert get_transcode_target("video.mov") == TranscodeTarget.VIDEO_H264


def test_strip_iso_media_user_data_neutralizes_only_global_udta(tmp_path: Path) -> None:
    def atom(atom_type: bytes, payload: bytes) -> bytes:
        return (len(payload) + 8).to_bytes(4, "big") + atom_type + payload

    nested_udta = atom(b"trak", atom(b"udta", b"track-scoped"))
    global_udta = atom(b"udta", b"title-and-artist")
    media = tmp_path / "tagged.mov"
    media.write_bytes(atom(b"ftyp", b"qt  ") + atom(b"moov", nested_udta + global_udta) + atom(b"mdat", b"media"))

    assert transcoder_module._strip_iso_media_user_data(media) is True

    payload = media.read_bytes()
    assert b"trak" in payload
    assert b"track-scoped" in payload
    assert b"udtatitle-and-artist" not in payload
    assert b"freetitle-and-artist" in payload


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
