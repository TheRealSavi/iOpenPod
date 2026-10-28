"""Preferences contract tests with authored bytes, independent of device captures."""

import struct
from dataclasses import replace

import pytest

from iPodDB.preferences import (
    CityPreferences,
    CityTimezone,
    Classic201ClockPreferences,
    Classic201Preferences,
    FixedOffsetTimezone,
    FourthGenerationPreferences,
    Nano3Preferences,
    PreferencesLayout,
    PreferencesProfile,
    PreferencesSettings,
    PreferencesTimezone,
    VideoPreferences,
    VolumeLimitPreferences,
    parse_preferences,
    write_preferences,
)
from iPodDB.preferences.definitions import PREFERENCES_DEFINITIONS
from iPodDB.preferences.timezones import CITY_TIMEZONE_NAMES
from iPodDB.shared.binary_struct import validate_binary_struct_definition
from iPodDB.shared.errors import iPodDBParseError, iPodDBWriteError


def _source(size: int, offset: int, value: int) -> bytes:
    # Nonzero unknown bytes expose accidental normalization and wide writes.
    data = bytearray((index * 31 + 17) % 256 for index in range(size))
    struct.pack_into("<h", data, offset, value)
    data[2808] = 0
    return bytes(data)


@pytest.mark.parametrize(
    "size,offset,value,settings,zone,layout",
    (
        (
            2892,
            0xB10,
            25,
            FourthGenerationPreferences(25),
            FixedOffsetTimezone(0),
            PreferencesLayout.FOURTH_GENERATION,
        ),
        (
            2924,
            0xB22,
            150,
            VideoPreferences(150),
            FixedOffsetTimezone(-19800),
            PreferencesLayout.VIDEO,
        ),
        (
            2952,
            0xB70,
            0x69,
            CityPreferences(0x69),
            CityTimezone(0x69, "Europe/Rome"),
            PreferencesLayout.CITY,
        ),
        (
            2956,
            0xB70,
            0x29,
            CityPreferences(0x29),
            CityTimezone(0x29, "America/New_York"),
            PreferencesLayout.CITY,
        ),
        (
            2960,
            0xB70,
            0x1D,
            CityPreferences(0x1D),
            CityTimezone(0x1D, "America/New_York"),
            PreferencesLayout.CITY,
        ),
    ),
)
def test_known_layouts_have_typed_settings_and_exact_roundtrips(
    size: int,
    offset: int,
    value: int,
    settings: PreferencesSettings,
    zone: PreferencesTimezone,
    layout: PreferencesLayout,
) -> None:
    source = _source(size, offset, value)
    document = parse_preferences(source)
    assert document.layout is layout
    assert document.settings == settings
    assert document.timezone == zone
    assert write_preferences(document) == source


@pytest.mark.parametrize(
    "code,hours",
    ((0, -12), (1, -12), (14, -5), (15, -5), (24, 0), (25, 0), (26, 1), (48, 12)),
)
def test_fourth_generation_uses_adjusted_dst_parity(code: int, hours: int) -> None:
    document = parse_preferences(_source(2892, 0xB10, code))
    assert document.timezone == FixedOffsetTimezone(hours * 3600)


@pytest.mark.parametrize(
    "code,seconds", ((-240, -43200), (480, 0), (825, 20700), (1200, 43200))
)
def test_video_preserves_signed_minutes_and_fractional_hour_offsets(
    code: int, seconds: int
) -> None:
    document = parse_preferences(_source(2924, 0xB22, code))
    assert document.timezone == FixedOffsetTimezone(seconds)


@pytest.mark.parametrize(
    "size,offset,old,new",
    (
        (2892, 0xB10, 25, FourthGenerationPreferences(15)),
        (2924, 0xB22, 480, VideoPreferences(825)),
        (2952, 0xB70, 0x29, CityPreferences(0x69)),
        (2956, 0xB70, 0x29, CityPreferences(0x69)),
        (2960, 0xB70, 0x29, CityPreferences(0x69)),
    ),
)
def test_writer_changes_only_the_two_evidenced_bytes(
    size: int, offset: int, old: int, new: PreferencesSettings
) -> None:
    source = _source(size, offset, old)
    document = parse_preferences(source)
    edited = replace(document, settings=new)
    output = write_preferences(edited)
    assert len(output) == len(source)
    assert output[:offset] == source[:offset]
    assert output[offset + 2 :] == source[offset + 2 :]
    assert output != source
    assert parse_preferences(output).settings == new
    assert write_preferences(document) == source


@pytest.mark.parametrize(
    "size,offset,value",
    (
        (2892, 0xB10, -1),
        (2892, 0xB10, 49),
        (2924, 0xB22, -241),
        (2924, 0xB22, 1201),
        (2956, 0xB70, -1),
        (2960, 0xB70, 0),
        (2952, 0xB70, 0x7FFF),
    ),
)
def test_invalid_or_unknown_source_zone_roundtrips_without_fallback(
    size: int, offset: int, value: int
) -> None:
    source = _source(size, offset, value)
    document = parse_preferences(source)
    assert write_preferences(document) == source
    if isinstance(document.settings, CityPreferences):
        assert document.timezone == CityTimezone(value, None)
    else:
        assert document.timezone is None


@pytest.mark.parametrize("new", (-1, 49, 2**40))
def test_writer_rejects_new_invalid_fourth_generation_codes(new: int) -> None:
    document = parse_preferences(_source(2892, 0xB10, 25))
    with pytest.raises(iPodDBWriteError) as error:
        write_preferences(replace(document, settings=FourthGenerationPreferences(new)))
    assert error.value.code == "preferences.invalid_timezone"


@pytest.mark.parametrize("new", (-241, 1201, 2**40))
def test_writer_rejects_new_invalid_video_offsets(new: int) -> None:
    document = parse_preferences(_source(2924, 0xB22, 480))
    with pytest.raises(iPodDBWriteError, match="timezone"):
        write_preferences(replace(document, settings=VideoPreferences(new)))


@pytest.mark.parametrize("new", (-1, 0, 0xCE, 0x7FFF, 2**40))
def test_writer_rejects_new_unknown_city_ids(new: int) -> None:
    document = parse_preferences(_source(2960, 0xB70, 0x29))
    with pytest.raises(iPodDBWriteError, match="timezone"):
        write_preferences(replace(document, settings=CityPreferences(new)))


def test_unknown_city_can_be_explicitly_replaced_with_a_known_city() -> None:
    document = parse_preferences(_source(2960, 0xB70, 0))
    output = write_preferences(replace(document, settings=CityPreferences(0x69)))
    assert parse_preferences(output).timezone == CityTimezone(0x69, "Europe/Rome")


@pytest.mark.parametrize(
    "size", (1, 128, 2891, 2912, 2923, 2951, 2955, 2959, 2961, 4096)
)
def test_unrecognized_sizes_are_opaque_even_with_plausible_city_bytes(
    size: int,
) -> None:
    source = _source(size, 0xB70, 0x69) if size > 0xB72 else bytes([0xA5]) * size
    document = parse_preferences(source)
    assert document.layout is PreferencesLayout.UNKNOWN
    assert document.settings is None
    assert document.timezone is None
    assert write_preferences(document) == source
    with pytest.raises(iPodDBWriteError, match="no editable fields"):
        write_preferences(replace(document, settings=CityPreferences(0x29)))


def test_model_policy_can_explicitly_keep_a_known_size_opaque() -> None:
    source = _source(2960, 0xB70, 0x29)
    document = parse_preferences(source, layout=PreferencesLayout.UNKNOWN)
    assert document.settings is None
    assert document.timezone is None
    assert write_preferences(document) == source


def test_explicit_layout_assertion_rejects_truncation_and_wrong_family() -> None:
    source = _source(2956, 0xB70, 0x29)
    assert parse_preferences(
        source, layout=PreferencesLayout.CITY
    ).settings == CityPreferences(0x29)
    for bad in (source[:100], source[:-1], source + b"extension"):
        with pytest.raises(iPodDBParseError, match="does not match"):
            parse_preferences(bad, layout=PreferencesLayout.CITY)
    with pytest.raises(iPodDBParseError, match="does not match"):
        parse_preferences(source, layout=PreferencesLayout.VIDEO)


def test_writer_rejects_layout_changes_and_settings_of_the_wrong_type() -> None:
    document = parse_preferences(_source(2956, 0xB70, 0x29))
    for bad in (
        replace(document, settings=VideoPreferences(480)),
        replace(document, settings=None),
        replace(document, layout=PreferencesLayout.VIDEO),
        replace(document, source_bytes=document.source_bytes[:-1]),
    ):
        with pytest.raises(iPodDBWriteError, match="layout"):
            write_preferences(bad)


@pytest.mark.parametrize("value", (True, False, 25.0, "25", None))
def test_writer_rejects_noninteger_fields_even_if_equal_to_the_source(
    value: object,
) -> None:
    document = parse_preferences(_source(2892, 0xB10, 25))
    settings = FourthGenerationPreferences(25)
    object.__setattr__(settings, "timezone_code", value)
    with pytest.raises(iPodDBWriteError, match="integers"):
        write_preferences(replace(document, settings=settings))


def test_bytearray_input_is_captured_and_empty_file_is_not_valid() -> None:
    source = bytearray(_source(2960, 0xB70, 0x29))
    original = bytes(source)
    document = parse_preferences(source)
    source[0] ^= 0xFF
    assert write_preferences(document) == original
    with pytest.raises(iPodDBParseError, match="empty"):
        parse_preferences(b"")
    with pytest.raises(iPodDBWriteError, match="nonempty"):
        write_preferences(replace(document, source_bytes=b""))


def test_every_definition_fits_its_exact_supported_extents() -> None:
    for definition in PREFERENCES_DEFINITIONS:
        for size in definition.sizes:
            validate_binary_struct_definition(
                definition.settings_type, supported_sizes=(size,)
            )


@pytest.mark.parametrize("city_id", tuple(CITY_TIMEZONE_NAMES))
def test_catalog_city_ids_roundtrip_without_resolving_host_timezone_data(
    city_id: int,
) -> None:
    document = parse_preferences(_source(2960, 0xB70, 0x29))
    result = parse_preferences(
        write_preferences(replace(document, settings=CityPreferences(city_id)))
    )
    assert isinstance(result.timezone, CityTimezone)
    assert result.timezone.city_id == city_id
    assert result.timezone.timezone_name


@pytest.mark.parametrize("size,offset", ((2892, 0xB10), (2924, 0xB22), (2960, 0xB70)))
def test_language_is_independent_of_an_unknown_timezone(size: int, offset: int) -> None:
    source = bytearray(_source(size, offset, -1))
    source[2808] = 231  # A future/unknown language code must remain representable.
    document = parse_preferences(source)
    assert document.settings is not None
    assert document.settings.language_code == 231
    assert write_preferences(document) == source
    edited = replace(document, settings=replace(document.settings, language_code=7))
    expected = bytearray(source)
    expected[2808] = 7
    assert write_preferences(edited) == expected
    assert parse_preferences(expected).timezone == document.timezone
    for invalid in (-1, 256):
        with pytest.raises(iPodDBWriteError):
            write_preferences(
                replace(
                    document, settings=replace(document.settings, language_code=invalid)
                )
            )


@pytest.mark.parametrize(
    "size,offset,profile,settings",
    (
        (2952, 0x6BC, PreferencesProfile.NANO_3, Nano3Preferences(60)),
        (
            2924,
            0xB50,
            PreferencesProfile.VOLUME_LIMIT_1_1_1,
            VolumeLimitPreferences(64),
        ),
    ),
)
def test_model_specific_settings_require_explicit_profile(
    size: int,
    offset: int,
    profile: PreferencesProfile,
    settings: Nano3Preferences | VolumeLimitPreferences,
) -> None:
    source = bytes([0xA5]) * size
    assert parse_preferences(source).extended_settings is None
    document = parse_preferences(source, profile=profile)
    # Even an invalid existing field is retained, including during another edit.
    assert write_preferences(document) == source
    assert document.settings is not None
    language_edit = replace(
        document, settings=replace(document.settings, language_code=0)
    )
    assert write_preferences(language_edit)[offset] == 0xA5
    expected = bytearray(source)
    expected[offset] = 60 if profile is PreferencesProfile.NANO_3 else 64
    assert write_preferences(replace(document, extended_settings=settings)) == expected
    assert parse_preferences(expected, profile=profile).extended_settings == settings
    with pytest.raises(iPodDBWriteError, match="profile"):
        write_preferences(replace(document, extended_settings=None))


@pytest.mark.parametrize("invalid", (-1, 1, 59, 61, 256))
def test_nano3_dst_accepts_only_evidenced_minutes(invalid: int) -> None:
    document = parse_preferences(bytes(2952), profile=PreferencesProfile.NANO_3)
    with pytest.raises(iPodDBWriteError, match="Invalid"):
        write_preferences(
            replace(document, extended_settings=Nano3Preferences(invalid))
        )


@pytest.mark.parametrize("invalid", (-1, 65, 256))
def test_volume_limit_rejects_out_of_range_edits(invalid: int) -> None:
    document = parse_preferences(
        bytes(2924), profile=PreferencesProfile.VOLUME_LIMIT_1_1_1
    )
    with pytest.raises(iPodDBWriteError, match="Invalid"):
        write_preferences(
            replace(document, extended_settings=VolumeLimitPreferences(invalid))
        )


def test_profiles_cannot_decode_wrong_or_unknown_layouts() -> None:
    for size in (2892, 2924, 2956, 2960, 4000):
        with pytest.raises(iPodDBParseError):
            parse_preferences(bytes(size), profile=PreferencesProfile.NANO_3)
    with pytest.raises(iPodDBParseError):
        parse_preferences(bytes(2892), profile=PreferencesProfile.VOLUME_LIMIT_1_1_1)
    with pytest.raises(iPodDBParseError):
        parse_preferences(
            bytes(2952),
            layout=PreferencesLayout.UNKNOWN,
            profile=PreferencesProfile.NANO_3,
        )


def _classic201_source(
    city_id: int = 0x29, dst: int = 60, alternate_audio: int = 0
) -> bytes:
    data = bytearray((index * 31 + 17) % 256 for index in range(2956))
    struct.pack_into("<I", data, 0, 0x3D)
    struct.pack_into("<I", data, 0xB70, city_id)
    data[0xB6C] = dst
    data[0xB85] = alternate_audio
    struct.pack_into("<iI", data, 0xB78, -1, 81000)
    data[2808] = 0
    return bytes(data)


@pytest.mark.parametrize(
    "city_id,name",
    (
        (0x18, "America/Costa_Rica"),
        (0x36, "America/Puerto_Rico"),
        (0x41, "America/Sao_Paulo"),
        (0x95, "Indian/Mahe"),
    ),
)
@pytest.mark.parametrize(
    "profile", (PreferencesProfile.STANDARD, PreferencesProfile.CLASSIC_120GB_2_0_1)
)
def test_corrected_city_identity_preserves_preferences_bytes(
    city_id: int, name: str, profile: PreferencesProfile
) -> None:
    source = _classic201_source(city_id)
    document = parse_preferences(source, profile=profile)
    assert document.timezone == CityTimezone(city_id, name)
    assert write_preferences(document) == source
    assert document.settings is not None
    edited = replace(document, settings=replace(document.settings, language_code=7))
    expected = bytearray(source)
    expected[2808] = 7
    assert write_preferences(edited) == expected


def test_classic201_unresolved_manchester_identity_retains_raw_city_and_language() -> (
    None
):
    source = _classic201_source(0x26)
    document = parse_preferences(source, profile=PreferencesProfile.CLASSIC_120GB_2_0_1)
    assert document.settings == Classic201Preferences(0x26, 0)
    assert isinstance(document.timezone, CityTimezone)
    assert document.timezone.city_id == 0x26
    assert document.timezone.timezone_name is None
    assert "city 0x26" in document.timezone.detail
    assert "legacy London" in document.timezone.detail
    assert write_preferences(document) == source
    expected = bytearray(source)
    expected[2808] = 7
    edited = replace(document, settings=Classic201Preferences(0x26, 7))
    assert write_preferences(edited) == expected
    # Other models still use the existing policy, not a guessed US city.
    assert parse_preferences(source).timezone == CityTimezone(0x26, "Europe/London")


@pytest.mark.parametrize("city_id", (0x29, 0x10029, 0xFFFF0029))
@pytest.mark.parametrize("dst", (0, 1, 60, 255))
def test_classic201_profile_reads_full_city_and_retains_saved_clock_words(
    city_id: int, dst: int
) -> None:
    source = _classic201_source(city_id, dst)
    document = parse_preferences(source, profile=PreferencesProfile.CLASSIC_120GB_2_0_1)
    assert document.settings == Classic201Preferences(city_id, 0)
    assert document.extended_settings == Classic201ClockPreferences(
        0x3D, dst, -1, 81000
    )
    assert document.timezone == CityTimezone(
        city_id, "America/New_York" if city_id == 0x29 else None
    )
    assert write_preferences(document) == source
    edited = replace(document, settings=Classic201Preferences(city_id, 7))
    expected = bytearray(source)
    expected[2808] = 7
    assert write_preferences(edited) == expected
    # The older capture-scoped interpretation remains the default.
    generic = parse_preferences(source)
    assert generic.settings == CityPreferences(0x29, 0)
    assert generic.extended_settings is None
    assert write_preferences(generic) == source


@pytest.mark.parametrize("size", (2952, 2960, 2955, 2957))
def test_classic201_profile_rejects_unverified_extents(size: int) -> None:
    data = bytearray(size)
    struct.pack_into("<I", data, 0, 0x3D)
    with pytest.raises(iPodDBParseError):
        parse_preferences(data, profile=PreferencesProfile.CLASSIC_120GB_2_0_1)


@pytest.mark.parametrize("version", (0, 0x3C, 0x3E, 0x1003D))
def test_classic201_profile_requires_exact_format_version(version: int) -> None:
    data = bytearray(_classic201_source())
    struct.pack_into("<I", data, 0, version)
    with pytest.raises(iPodDBParseError, match="version"):
        parse_preferences(data, profile=PreferencesProfile.CLASSIC_120GB_2_0_1)


@pytest.mark.parametrize(
    "field,value",
    (
        ("format_version", 0x3E),
        ("retained_dst_state", 1),
        ("clock_bias_days", 0),
        ("clock_bias_seconds", 0),
    ),
)
def test_classic201_clock_observations_cannot_be_edited(field: str, value: int) -> None:
    document = parse_preferences(
        _classic201_source(), profile=PreferencesProfile.CLASSIC_120GB_2_0_1
    )
    clock = document.extended_settings
    assert isinstance(clock, Classic201ClockPreferences)
    with pytest.raises(iPodDBWriteError) as error:
        write_preferences(
            replace(document, extended_settings=replace(clock, **{field: value}))
        )
    assert error.value.code == "preferences.read_only_clock"


def test_classic201_city_is_observation_only_and_raw_seconds_are_unsigned() -> None:
    data = bytearray(_classic201_source())
    struct.pack_into("<I", data, 0xB7C, 0xFFFFFFFF)
    document = parse_preferences(data, profile=PreferencesProfile.CLASSIC_120GB_2_0_1)
    assert isinstance(document.extended_settings, Classic201ClockPreferences)
    assert document.extended_settings.clock_bias_seconds == 0xFFFFFFFF
    assert write_preferences(document) == data
    with pytest.raises(iPodDBWriteError) as error:
        write_preferences(replace(document, settings=Classic201Preferences(0x69, 0)))
    assert error.value.code == "preferences.read_only_clock"


@pytest.mark.parametrize("raw", range(256))
def test_classic201_alternate_audio_retains_every_raw_byte(raw: int) -> None:
    source = _classic201_source(city_id=0x10029, alternate_audio=raw)
    document = parse_preferences(source, profile=PreferencesProfile.CLASSIC_120GB_2_0_1)
    assert isinstance(document.settings, Classic201Preferences)
    assert document.settings.alternate_audio == raw
    assert write_preferences(document) == source
    expected = bytearray(source)
    expected[2808] = 7
    edited = replace(document, settings=replace(document.settings, language_code=7))
    assert write_preferences(edited) == expected
    generic = parse_preferences(source)
    assert type(generic.settings) is CityPreferences
    assert write_preferences(generic) == source


@pytest.mark.parametrize("old,new", ((0, 1), (1, 0), (2, 0), (255, 1)))
def test_classic201_alternate_audio_edit_changes_only_its_byte(
    old: int, new: int
) -> None:
    source = _classic201_source(city_id=0x10029, dst=255, alternate_audio=old)
    document = parse_preferences(source, profile=PreferencesProfile.CLASSIC_120GB_2_0_1)
    assert isinstance(document.settings, Classic201Preferences)
    edited = replace(document, settings=replace(document.settings, alternate_audio=new))
    expected = bytearray(source)
    expected[0xB85] = new
    output = write_preferences(edited)
    assert output == expected
    reloaded = parse_preferences(output, profile=document.profile)
    assert reloaded.settings == edited.settings
    assert reloaded.extended_settings == document.extended_settings
    assert reloaded.timezone == document.timezone


@pytest.mark.parametrize("new", (-1, 2, 254, 255, 256))
def test_classic201_alternate_audio_rejects_new_unknown_values(new: int) -> None:
    document = parse_preferences(
        _classic201_source(), profile=PreferencesProfile.CLASSIC_120GB_2_0_1
    )
    assert isinstance(document.settings, Classic201Preferences)
    with pytest.raises(iPodDBWriteError) as error:
        write_preferences(
            replace(document, settings=replace(document.settings, alternate_audio=new))
        )
    assert error.value.code == "preferences.invalid_value"
    assert error.value.field == "alternate_audio"


@pytest.mark.parametrize("value", (False, True, 0.0, "0", None))
def test_classic201_alternate_audio_rejects_noninteger_values(value: object) -> None:
    document = parse_preferences(
        _classic201_source(), profile=PreferencesProfile.CLASSIC_120GB_2_0_1
    )
    assert isinstance(document.settings, Classic201Preferences)
    settings = replace(document.settings)
    object.__setattr__(settings, "alternate_audio", value)
    with pytest.raises(iPodDBWriteError, match="integers"):
        write_preferences(replace(document, settings=settings))


def test_classic201_alternate_audio_cannot_bypass_clock_protection() -> None:
    document = parse_preferences(
        _classic201_source(), profile=PreferencesProfile.CLASSIC_120GB_2_0_1
    )
    assert isinstance(document.settings, Classic201Preferences)
    clock = document.extended_settings
    assert isinstance(clock, Classic201ClockPreferences)
    alternate_edit = replace(
        document, settings=replace(document.settings, alternate_audio=1)
    )
    with pytest.raises(iPodDBWriteError) as error:
        write_preferences(
            replace(alternate_edit, extended_settings=replace(clock, clock_bias_days=0))
        )
    assert error.value.code == "preferences.read_only_clock"
    with pytest.raises(iPodDBWriteError) as error:
        write_preferences(
            replace(
                alternate_edit,
                settings=replace(document.settings, city_id=0x69, alternate_audio=1),
            )
        )
    assert error.value.code == "preferences.read_only_clock"
