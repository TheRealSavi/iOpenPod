import logging

import SyncEngine.transcoder as transcoder_module
from SyncEngine.transcoder import (
    AudioProperties,
    TranscodeTarget,
    _transcode_timeout_seconds,
    find_ffprobe,
    get_transcode_target,
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


def test_unprobeable_native_audio_copies_instead_of_lossy_fallback(monkeypatch, caplog) -> None:
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

    with caplog.at_level(logging.WARNING, logger="SyncEngine.transcoder"):
        target = get_transcode_target("Café.m4a")

    assert target == TranscodeTarget.COPY
    assert "skipping transcode fallback; copying as-is" in caplog.text
    assert "re-encoding to lossy codec as safe fallback" not in caplog.text


def test_find_ffprobe_uses_configured_ffmpeg_sibling(tmp_path, monkeypatch) -> None:
    bin_dir = tmp_path / "tools"
    bin_dir.mkdir()
    ffmpeg = bin_dir / "ffmpeg"
    ffprobe = bin_dir / "ffprobe"
    ffmpeg.write_text("", encoding="utf-8")
    ffprobe.write_text("", encoding="utf-8")

    find_ffprobe.cache_clear()
    monkeypatch.setattr(transcoder_module.shutil, "which", lambda _name: None)

    assert find_ffprobe(str(ffmpeg)) == str(ffprobe)


def test_ffmpeg_availability_requires_ffprobe(monkeypatch) -> None:
    monkeypatch.setattr(transcoder_module, "find_ffmpeg", lambda _path=None: "/tmp/ffmpeg")
    monkeypatch.setattr(transcoder_module, "find_ffprobe", lambda _path=None: None)

    assert transcoder_module.is_ffmpeg_available() is False
