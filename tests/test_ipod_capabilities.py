from iopenpod.device import capabilities_for_family_gen

_MIB = 1024 * 1024


def test_database_limit_defaults_to_32_mib_for_legacy_ipods() -> None:
    caps = capabilities_for_family_gen("iPod Mini", "2nd Gen")

    assert caps is not None
    assert caps.max_database_bytes == 32 * _MIB


def test_video_ipod_database_limit_tracks_high_capacity_ram() -> None:
    small = capabilities_for_family_gen(
        "iPod",
        "5.5th Gen",
        capacity="30GB",
    )
    large = capabilities_for_family_gen(
        "iPod",
        "5.5th Gen",
        capacity="80GB",
    )

    assert small is not None
    assert large is not None
    assert small.max_database_bytes == 32 * _MIB
    assert large.max_database_bytes == 64 * _MIB


def test_late_nanos_and_classics_report_64_mib_database_limit() -> None:
    nano = capabilities_for_family_gen("iPod Nano", "6th Gen")
    classic = capabilities_for_family_gen("iPod Classic", "7th Gen")

    assert nano is not None
    assert classic is not None
    assert nano.max_database_bytes == 64 * _MIB
    assert classic.max_database_bytes == 64 * _MIB


def test_tx3g_subtitle_support_begins_with_the_2007_video_ipods() -> None:
    ipod_video = capabilities_for_family_gen("iPod", "5.5th Gen")
    classic = capabilities_for_family_gen("iPod Classic", "7th Gen")
    nano = capabilities_for_family_gen("iPod Nano", "3rd Gen")

    assert ipod_video is not None
    assert classic is not None
    assert nano is not None
    assert ipod_video.supports_tx3g_subtitles is False
    assert classic.supports_tx3g_subtitles is True
    assert nano.supports_tx3g_subtitles is True


def test_video_ipod_timed_text_and_closed_caption_capabilities() -> None:
    expected = {
        ("iPod", "5th Gen"): (False, False),
        ("iPod", "5.5th Gen"): (False, False),
        ("iPod Classic", "6th Gen"): (True, True),
        ("iPod Classic", "6.5th Gen"): (True, True),
        ("iPod Classic", "7th Gen"): (True, True),
        ("iPod Nano", "3rd Gen"): (True, True),
        ("iPod Nano", "4th Gen"): (True, True),
        ("iPod Nano", "5th Gen"): (True, True),
        ("iPod Nano", "6th Gen"): (False, False),
        ("iPod Nano", "7th Gen"): (True, True),
    }

    for (family, generation), (supports_tx3g, supports_cea608) in expected.items():
        caps = capabilities_for_family_gen(family, generation)

        assert caps is not None
        assert caps.supports_tx3g_subtitles is supports_tx3g
        assert caps.supports_cea608_captions is supports_cea608


def test_classic_h264_video_bitrate_is_capped_at_apple_specification() -> None:
    classic = capabilities_for_family_gen("iPod Classic", "7th Gen")

    assert classic is not None
    assert classic.max_video_bitrate == 2500
