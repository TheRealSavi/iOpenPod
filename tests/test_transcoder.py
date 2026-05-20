from SyncEngine.transcoder import TranscodeTarget, _transcode_timeout_seconds


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
