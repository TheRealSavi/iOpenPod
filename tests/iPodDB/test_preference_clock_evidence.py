"""Saved city evidence never becomes an invented current offset or clock write."""

from dataclasses import replace
from typing import cast

import pytest

from iPodDB.preferences import (
    NamedPreferencesProfile,
    parse_named_preferences,
    update_named_preferences,
    write_named_preferences,
)
from iPodDB.preferences._named_catalog import FIRMWARE_CITIES
from iPodDB.preferences.clock_evidence import read_named_clock_evidence
from iPodDB.preferences.definitions import PreferenceKey

N5 = NamedPreferencesProfile.NANO_5_1_0_2
N6 = NamedPreferencesProfile.NANO_6_1_2
N7 = NamedPreferencesProfile.NANO_7_1_0_4
REFRESH = NamedPreferencesProfile.NANO_UPDATER_39_1_1_2
PROFILES = (N5, N6, N7, REFRESH)


def _xml(body: str) -> bytes:
    return ('<iPodSettings version="1.0">' + body + "</iPodSettings>").encode()


def _city(value: int | str) -> bytes:
    return _xml(f"<DateTime><TimeZone>{value}</TimeZone></DateTime>")


@pytest.mark.parametrize("profile", PROFILES)
def test_primary_city_has_explicit_policy_separate_from_base_offset(
    profile: NamedPreferencesProfile,
) -> None:
    evidence = read_named_clock_evidence(_city(1), profile=profile)
    assert evidence.profile is profile
    assert evidence.raw_value == b"1"
    assert evidence.city_id == 1
    assert evidence.city_label == "California"
    assert evidence.iana_timezone == "America/Los_Angeles"
    assert evidence.firmware_base_offset_minutes == -480
    assert not evidence.issues
    assert "not a DST-effective offset" in evidence.detail
    if profile is N5:
        assert evidence.interpretation == "geographical_city"
        assert evidence.firmware_timezone_name is None
    else:
        assert evidence.interpretation == "firmware_record"
        assert evidence.firmware_timezone_name == "America/Los_Angeles"


@pytest.mark.parametrize("profile", PROFILES)
def test_all_registered_city_ids_are_handled_without_truncation_or_ordinal_join(
    profile: NamedPreferencesProfile,
) -> None:
    usable: list[int] = []
    for city_id in range(1, 206):
        evidence = read_named_clock_evidence(_city(city_id), profile=profile)
        assert evidence.city_id == city_id
        assert evidence.city_label is not None
        assert evidence.firmware_base_offset_minutes is not None
        if evidence.iana_timezone:
            usable.append(city_id)
            assert not evidence.issues
        else:
            assert evidence.issues
            assert evidence.interpretation == "unresolved"
    assert set(range(1, 206)) - set(usable) == (
        {38, 205} if profile is N5 else {38, 118, 185}
    )


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize(
    "city,label,key",
    [
        (79, "London", "Europe/London"),
        (194, "Tokyo", "Asia/Tokyo"),
        (204, "Kuwait", "Asia/Kuwait"),
    ],
)
def test_named_city_ids_are_independently_identified(
    profile: NamedPreferencesProfile,
    city: int,
    label: str,
    key: str,
) -> None:
    evidence = read_named_clock_evidence(_city(city), profile=profile)
    assert evidence.city_label == label
    assert evidence.iana_timezone == key


@pytest.mark.parametrize(
    "city,key",
    [
        (12, "America/Edmonton"),
        (24, "America/Costa_Rica"),
        (42, "America/Toronto"),
        (54, "America/Puerto_Rico"),
        (62, "America/Nuuk"),
        (65, "America/Sao_Paulo"),
        (93, "Europe/Zurich"),
        (96, "Europe/Ljubljana"),
        (111, "Europe/Zagreb"),
        (114, "Europe/Istanbul"),
        (124, "Europe/Kyiv"),
        (149, "Indian/Mahe"),
        (152, "Asia/Tashkent"),
        (171, "Australia/Sydney"),
        (175, "Australia/Sydney"),
        (185, "Asia/Kolkata"),
        (190, "Asia/Kathmandu"),
        (197, "Asia/Yangon"),
    ],
)
def test_nano5_geographic_policy_does_not_inherit_legacy_shifted_or_proxy_names(
    city: int,
    key: str,
) -> None:
    evidence = read_named_clock_evidence(_city(city), profile=N5)
    assert evidence.iana_timezone == key
    assert evidence.interpretation == "geographical_city"
    assert evidence.firmware_timezone_name is None


def test_nano5_mapping_requires_the_exact_audited_city_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        FIRMWARE_CITIES, 1, replace(FIRMWARE_CITIES[1], label="Unknown place")
    )
    evidence = read_named_clock_evidence(_city(1), profile=N5)
    assert evidence.city_label == "Unknown place"
    assert evidence.iana_timezone is None
    assert evidence.issues


@pytest.mark.parametrize("profile", [N6, N7, REFRESH])
@pytest.mark.parametrize(
    "city,raw_name",
    [
        (38, "America/New_York"),
        (118, "Africa/Bissau"),
        (185, "Asia/Colombo"),
    ],
)
def test_contradictory_native_bindings_remain_observable_but_unresolved(
    profile: NamedPreferencesProfile,
    city: int,
    raw_name: str,
) -> None:
    evidence = read_named_clock_evidence(_city(city), profile=profile)
    assert evidence.firmware_timezone_name == raw_name
    assert evidence.iana_timezone is None
    assert evidence.firmware_base_offset_minutes is not None
    assert evidence.interpretation == "unresolved"
    assert evidence.issues


@pytest.mark.parametrize("profile", [N6, N7, REFRESH])
@pytest.mark.parametrize(
    "city,raw_name", [(33, "America/New_York"), (101, "Europe/Warsaw")]
)
def test_other_later_packaged_proxies_remain_an_explicit_firmware_record_policy(
    profile: NamedPreferencesProfile,
    city: int,
    raw_name: str,
) -> None:
    evidence = read_named_clock_evidence(_city(city), profile=profile)
    assert evidence.iana_timezone == evidence.firmware_timezone_name == raw_name
    assert evidence.interpretation == "firmware_record"
    assert "historical rules" in evidence.detail


def test_nano5_cape_town_is_independently_geographical_not_later_bissau_binding() -> (
    None
):
    evidence = read_named_clock_evidence(_city(118), profile=N5)
    assert evidence.iana_timezone == "Africa/Johannesburg"
    assert evidence.firmware_base_offset_minutes == 120
    assert evidence.firmware_timezone_name is None


def test_nano5_out_of_range_205_is_not_a_claim_of_loader_adoption() -> None:
    evidence = read_named_clock_evidence(_city(205), profile=N5)
    assert evidence.city_label == "Phnom Penh"
    assert evidence.city_id == 205
    assert evidence.firmware_base_offset_minutes == 420
    assert evidence.iana_timezone is None
    assert "maximum 204" in evidence.issues[0]
    assert (
        read_named_clock_evidence(_city(205), profile=N7).iana_timezone
        == "Asia/Phnom_Penh"
    )


def test_profile_specific_labels_and_historical_base_differences_are_retained() -> None:
    assert read_named_clock_evidence(_city(190), profile=N6).city_label == "Katmandu"
    assert read_named_clock_evidence(_city(190), profile=N7).city_label == "Kathmandu"
    nano6 = read_named_clock_evidence(_city(140), profile=N6)
    nano7 = read_named_clock_evidence(_city(140), profile=N7)
    assert nano6.iana_timezone == nano7.iana_timezone == "Europe/Moscow"
    assert nano6.firmware_base_offset_minutes == 180
    assert nano7.firmware_base_offset_minutes == 240


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("raw", ["0", "206", "65537", "4294967295"])
def test_unmapped_ids_are_not_masked_or_interpreted_as_fixed_offsets(
    profile: NamedPreferencesProfile,
    raw: str,
) -> None:
    evidence = read_named_clock_evidence(_city(raw), profile=profile)
    assert evidence.city_id == int(raw)
    assert evidence.raw_value == raw.encode()
    assert evidence.iana_timezone is None
    assert evidence.firmware_base_offset_minutes is None
    assert evidence.issues


@pytest.mark.parametrize(
    "raw",
    ["-1", "1junk", "4294967296", "9" * 5000, ""],
    ids=["negative", "suffix", "overflow", "huge", "empty"],
)
def test_noncanonical_numeric_input_retains_raw_without_native_parser_fallback(
    raw: str,
) -> None:
    evidence = read_named_clock_evidence(_city(raw), profile=N7)
    assert evidence.raw_value == raw.encode()
    assert evidence.city_id is None
    assert evidence.iana_timezone is None
    assert evidence.issues


@pytest.mark.parametrize("raw", ["  +00079\t", "&#55;&#57;"])
def test_unique_numeric_text_uses_decoded_xml_but_retains_exact_original_bytes(
    raw: str,
) -> None:
    evidence = read_named_clock_evidence(_city(raw), profile=N7)
    assert evidence.raw_value == raw.encode()
    assert evidence.city_id == 79
    assert evidence.iana_timezone == "Europe/London"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "<DateTime/>",
        "<General><TimeZone>79</TimeZone></General>",
        "<DateTime><WorldClock1TimeZone>79</WorldClock1TimeZone><WorldClock2TimeZone>194</WorldClock2TimeZone></DateTime>",
        "<DateTime><TwentyFourHourClock>1</TwentyFourHourClock><UserSet24HourSetting>1</UserSet24HourSetting></DateTime>",
    ],
)
def test_missing_primary_zone_does_not_inherit_defaults_world_clocks_or_format(
    body: str,
) -> None:
    evidence = read_named_clock_evidence(_xml(body), profile=N7)
    assert evidence.city_id is None
    assert evidence.iana_timezone is None
    assert evidence.raw_value is None
    assert evidence.issues


@pytest.mark.parametrize(
    "body",
    [
        "<DateTime><TimeZone>1</TimeZone><TimeZone>79</TimeZone></DateTime>",
        "<DateTime><TimeZone>1</TimeZone></DateTime><DateTime/>",
        '<DateTime extra="1"><TimeZone>1</TimeZone></DateTime>',
        '<DateTime><TimeZone extra="1">1</TimeZone></DateTime>',
        "<DateTime><TimeZone><value>1</value></TimeZone></DateTime>",
        "<DateTime><TimeZone><![CDATA[1]]></TimeZone></DateTime>",
        "<DateTime><TimeZone><!--x-->1</TimeZone></DateTime>",
    ],
)
def test_ambiguous_or_complex_clock_field_does_not_choose_a_winner(body: str) -> None:
    evidence = read_named_clock_evidence(_xml(body), profile=N7)
    assert evidence.city_id is None
    assert evidence.iana_timezone is None
    assert evidence.raw_value is None
    assert evidence.issues


@pytest.mark.parametrize(
    "source",
    [
        b"",
        b"<iPodSettings>",
        b'<iPodSettings version="2.0"/>',
        b'<!DOCTYPE iPodSettings [<!ENTITY x "1">]><iPodSettings version="1.0"><DateTime><TimeZone>&x;</TimeZone></DateTime></iPodSettings>',
        b'<!DOCTYPE iPodSettings SYSTEM "file:///secret"><iPodSettings version="1.0"/>',
        '<iPodSettings version="1.0"/>'.encode("utf-16"),
        _xml("<a>" * 10 + "</a>" * 10),
        _xml("<a/>" * 4097),
        b"x" * (4 * 1024 * 1024 + 1),
    ],
    ids=[
        "empty",
        "unclosed",
        "version",
        "entity",
        "external",
        "utf16",
        "deep",
        "nodes",
        "bytes",
    ],
)
def test_unqualified_xml_is_nonblocking_without_semantic_guesses(source: bytes) -> None:
    evidence = read_named_clock_evidence(source, profile=N7)
    assert evidence.profile is N7
    assert evidence.iana_timezone is None
    assert evidence.issues


def test_nano4_and_forged_caller_profiles_are_not_upgraded_by_xml_keys() -> None:
    source = _city(1)
    nano4 = read_named_clock_evidence(
        source, profile=NamedPreferencesProfile.NANO_4_1_0_4
    )
    assert nano4.iana_timezone is None
    assert nano4.issues
    forged = read_named_clock_evidence(
        source, profile=cast("NamedPreferencesProfile", "nano_7_1_0_4")
    )
    assert forged.profile is None
    assert forged.iana_timezone is None
    assert forged.issues
    malformed = read_named_clock_evidence(cast("bytes", None), profile=N7)
    assert malformed.iana_timezone is None
    assert malformed.issues


def test_evidence_is_host_independent_and_never_changes_original_xml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _xml(
        "<General><Brightness>40</Brightness></General><DateTime><TimeZone> 00118 </TimeZone></DateTime>"
    )
    monkeypatch.setenv("TZ", "Pacific/Honolulu")
    west = read_named_clock_evidence(source, profile=N7)
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    east = read_named_clock_evidence(source, profile=N7)
    assert west == east
    assert west.iana_timezone is None
    document = parse_named_preferences(source, profile=N7)
    assert write_named_preferences(document) == source
    edited = update_named_preferences(document, {PreferenceKey.BRIGHTNESS: 50})
    output = write_named_preferences(edited)
    assert output == source.replace(b">40<", b">50<")
    assert read_named_clock_evidence(output, profile=N7).raw_value == b" 00118 "
