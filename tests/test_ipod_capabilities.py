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
