"""Latest Classic profiles retain identical clock fields with distinct framing."""

import struct
from dataclasses import replace

import pytest

from iPodDB.preferences import (
    CityTimezone,
    ClassicClockPreferences,
    ClassicPreferences,
    PreferencesProfile,
    parse_preferences,
    write_preferences,
)
from iPodDB.shared.errors import iPodDBParseError, iPodDBWriteError

CLASSIC_TARGETS = (
    (24, "1.1.2", "MB029", 2952, 0x3C, PreferencesProfile.CLASSIC_6_1_1_2),
    (33, "2.0.1", "MB565", 2956, 0x3D, PreferencesProfile.CLASSIC_120GB_2_0_1),
    (35, "2.0.4", "MC293", 2956, 0x3E, PreferencesProfile.CLASSIC_UPDATER_35_2_0_4),
    (38, "2.0.5", "MC297", 2960, 0x3F, PreferencesProfile.CLASSIC_UPDATER_38_2_0_5),
)


def classic_preferences(
    size: int, version: int, city: int = 41, dst: int = 60
) -> bytes:
    data = bytearray((17 * index + 9) % 256 for index in range(size))
    struct.pack_into("<I", data, 0, version)
    # Ordinary saved clock evidence must not accidentally request a reset.
    struct.pack_into("<I", data, 4, 0)
    data[2808] = 0
    data[0xB6C] = dst
    struct.pack_into("<I", data, 0xB70, city)
    struct.pack_into("<iI", data, 0xB78, -1, 0xFFFFFFFF)
    return bytes(data)


@pytest.mark.parametrize("family,release,model,size,version,profile", CLASSIC_TARGETS)
@pytest.mark.parametrize("city", (41, 0x10029, 0xFFFFFFFF))
@pytest.mark.parametrize("dst", (0, 1, 60, 255))
def test_latest_profiles_preserve_full_city_and_raw_clock_state(
    family: int,
    release: str,
    model: str,
    size: int,
    version: int,
    profile: PreferencesProfile,
    city: int,
    dst: int,
) -> None:
    source = classic_preferences(size, version, city, dst)
    document = parse_preferences(source, profile=profile)
    assert isinstance(document.settings, ClassicPreferences)
    assert document.settings.city_id == city
    # Latest Classic firmware loads the entire language u32. Keep the nonzero
    # upper bytes in this fixture to detect accidental truncation on a no-op.
    assert document.settings.language_code == struct.unpack_from("<I", source, 0xAF8)[0]
    assert document.extended_settings == ClassicClockPreferences(
        version, dst, -1, 0xFFFFFFFF
    )
    assert document.timezone == CityTimezone(
        city, "America/New_York" if city == 41 else None
    )
    assert write_preferences(document) == source
    edited = replace(document, settings=replace(document.settings, language_code=7))
    expected = bytearray(source)
    struct.pack_into("<I", expected, 0xAF8, 7)
    assert write_preferences(edited) == expected


@pytest.mark.parametrize("family,release,model,size,version,profile", CLASSIC_TARGETS)
def test_clock_fields_are_observations_for_every_latest_profile(
    family: int,
    release: str,
    model: str,
    size: int,
    version: int,
    profile: PreferencesProfile,
) -> None:
    document = parse_preferences(classic_preferences(size, version), profile=profile)
    assert isinstance(document.settings, ClassicPreferences)
    clock = document.extended_settings
    assert isinstance(clock, ClassicClockPreferences)
    for field, value in (
        ("format_version", 0),
        ("retained_dst_state", 255),
        ("clock_bias_days", 0),
        ("clock_bias_seconds", 0),
    ):
        with pytest.raises(iPodDBWriteError) as error:
            write_preferences(
                replace(document, extended_settings=replace(clock, **{field: value}))
            )
        assert error.value.code == "preferences.read_only_clock"
    with pytest.raises(iPodDBWriteError) as error:
        write_preferences(
            replace(document, settings=replace(document.settings, city_id=0x69))
        )
    assert error.value.code == "preferences.read_only_clock"


@pytest.mark.parametrize("family,release,model,size,version,profile", CLASSIC_TARGETS)
def test_latest_profiles_cannot_be_selected_by_extent_or_shared_offsets(
    family: int,
    release: str,
    model: str,
    size: int,
    version: int,
    profile: PreferencesProfile,
) -> None:
    for other in CLASSIC_TARGETS:
        if other[-1] is profile:
            continue
        with pytest.raises(iPodDBParseError):
            parse_preferences(classic_preferences(other[3], other[4]), profile=profile)
    for wrong_size in (size - 1, size + 1):
        with pytest.raises(iPodDBParseError):
            parse_preferences(classic_preferences(wrong_size, version), profile=profile)


@pytest.mark.parametrize("family,release,model,size,version,profile", CLASSIC_TARGETS)
def test_unresolved_city_identity_is_not_guessed_on_any_latest_classic(
    family: int,
    release: str,
    model: str,
    size: int,
    version: int,
    profile: PreferencesProfile,
) -> None:
    source = classic_preferences(size, version, 0x26)
    document = parse_preferences(source, profile=profile)
    zone = document.timezone
    assert isinstance(zone, CityTimezone)
    assert zone.city_id == 0x26 and zone.timezone_name is None
    assert "legacy London" in zone.detail
    assert write_preferences(document) == source
