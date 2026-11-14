"""Saved named values are observable without authorizing or normalizing them."""

import struct

import pytest

from iPodDB.preferences import (
    NamedPreferencesProfile,
    available_named_preferences,
    parse_named_preferences,
    write_named_preferences,
)
from iPodDB.preferences._named_catalog import (
    FIELDS_BY_PROFILE,
    FIRMWARE_CITIES,
)
from iPodDB.preferences.inspection_models import PreferenceObservation
from iPodDB.preferences.named_inspection import (
    inspect_named_binary_preferences,
    inspect_named_preferences,
)

N5 = NamedPreferencesProfile.NANO_5_1_0_2
N6 = NamedPreferencesProfile.NANO_6_1_2
N7 = NamedPreferencesProfile.NANO_7_1_0_4
REFRESH = NamedPreferencesProfile.NANO_UPDATER_39_1_1_2


def _xml(body: str) -> bytes:
    return ('<iPodSettings version="1.0">' + body + "</iPodSettings>").encode()


def _fields(
    source: bytes, profile: NamedPreferencesProfile = N7
) -> dict[str, PreferenceObservation]:
    return {
        row.key: row
        for row in inspect_named_preferences(source, profile=profile).observations
    }


@pytest.mark.parametrize(
    "profile,count",
    [
        (NamedPreferencesProfile.NANO_4_1_0_4, 6),
        (N5, 53),
        (N6, 87),
        (N7, 97),
        (REFRESH, 97),
    ],
)
def test_catalog_coverage_is_exact_per_store_and_all_present_fields_are_read(
    profile: NamedPreferencesProfile,
    count: int,
) -> None:
    specs = FIELDS_BY_PROFILE[profile]
    assert len(specs) == count
    assert len({spec.key for spec in specs}) == count
    sections: dict[str, list[str]] = {}
    for spec in specs:
        section, name = spec.key.split(".")
        sections.setdefault(section, []).append(f"<{name}>0</{name}>")
    source = _xml(
        "".join(
            f"<{section}>" + "".join(fields) + f"</{section}>"
            for section, fields in sections.items()
        )
    )
    result = inspect_named_preferences(source, profile=profile)
    assert len(result.observations) == count
    assert (
        write_named_preferences(parse_named_preferences(source, profile=profile))
        == source
    )


def test_native_strings_keep_case_sensitive_unknown_values_and_entity_spelling() -> (
    None
):
    source = _xml(
        "<Playback><Repeat>one</Repeat><Shuffle>ALBUMS</Shuffle>"
        "<AudiobookSpeed>fast</AudiobookSpeed><EQ>999</EQ></Playback>"
        "<General><Clicker>on</Clicker></General><Future><Text>A&amp;B</Text></Future>"
    )
    rows = _fields(source)
    assert rows["Playback.Repeat"].value == "Repeat current item"
    assert rows["Playback.Repeat"].known
    assert rows["Playback.Shuffle"].value == "ALBUMS"
    assert not rows["Playback.Shuffle"].known
    assert rows["Playback.AudiobookSpeed"].value == "Fast"
    assert "rate factors" in rows["Playback.AudiobookSpeed"].detail
    assert rows["eq_preset"].value == "999"
    assert not rows["eq_preset"].known
    assert rows["General.Clicker"].value == "On"
    assert rows["Future.Text"].raw_value == "A&amp;B"
    assert rows["Future.Text"].value == "A&B"
    assert not rows["Future.Text"].known
    assert (
        write_named_preferences(parse_named_preferences(source, profile=N7)) == source
    )


@pytest.mark.parametrize("profile", [N5, N6, N7, REFRESH])
def test_authorable_keys_match_inspection_and_eq_ids_have_names(
    profile: NamedPreferencesProfile,
) -> None:
    source = _xml(
        "<General><Brightness>0040</Brightness></General>"
        "<Playback><SoundCheck>1</SoundCheck><EQ>121</EQ></Playback>"
    )
    rows = _fields(source, profile)
    assert set(rows) == {"brightness", "sound_check", "eq_preset"}
    assert rows["brightness"].value == "40/100"
    assert rows["sound_check"].value == "On"
    assert rows["eq_preset"].value == "Vocal Booster"


@pytest.mark.parametrize("profile", [N5, N6, N7, REFRESH])
def test_ieee_weight_bits_are_kilograms_not_a_large_integer(
    profile: NamedPreferencesProfile,
) -> None:
    bits = struct.unpack("<Q", struct.pack("<d", 68.0388555))[0]
    source = _xml(
        f"<Trainer><Weight>{bits}</Weight><WeightCustomized>1</WeightCustomized></Trainer>"
    )
    rows = _fields(source, profile)
    assert rows["Trainer.Weight"].raw_value == str(bits)
    assert rows["Trainer.Weight"].value == "68.0388555 kg"
    assert rows["Trainer.Weight"].known
    assert "binary64" in rows["Trainer.Weight"].detail


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -1.0, 0.0])
def test_implausible_weight_bits_remain_raw_nonblocking(number: float) -> None:
    bits = struct.unpack("<Q", struct.pack("<d", number))[0]
    row = _fields(_xml(f"<Trainer><Weight>{bits}</Weight></Trainer>"))["Trainer.Weight"]
    assert row.value == str(bits)
    assert not row.known


@pytest.mark.parametrize("profile", [N6, N7, REFRESH])
def test_height_units_are_not_changed_by_imperial_preference(
    profile: NamedPreferencesProfile,
) -> None:
    bits = struct.unpack("<Q", struct.pack("<d", 177.8))[0]
    rows = _fields(
        _xml(
            f"<Trainer><Height>{bits}</Height><MeasurementSystem>1</MeasurementSystem></Trainer>"
        ),
        profile,
    )
    assert rows["Trainer.Height"].value == "177.8 cm"
    assert rows["Trainer.MeasurementSystem"].value == "English"


def test_transition_labels_do_not_inherit_another_models_hidden_effects() -> None:
    source = _xml("<Photos><Transitions>3</Transitions></Photos>")
    assert _fields(source, N5)["Photos.Transitions"].value == "Slide"
    assert _fields(source, N6)["Photos.Transitions"].value == "Slide"
    assert "legacy label switch" in _fields(source, N6)["Photos.Transitions"].detail
    assert not _fields(source, N7)["Photos.Transitions"].known
    source = _xml("<Photos><Transitions>9</Transitions></Photos>")
    assert _fields(source, N5)["Photos.Transitions"].value == "Flip"
    assert _fields(source, N6)["Photos.Transitions"].value == "Page Flip"


def test_unsigned_serialized_word_retains_signed_sentinel_without_guessing_effect() -> (
    None
):
    rows = _fields(
        _xml("<General><BacklightTimer>4294967295</BacklightTimer></General>"), N5
    )
    row = rows["General.BacklightTimer"]
    assert row.raw_value == "4294967295"
    assert row.value == "-1"
    assert not row.known
    assert "sentinel" in row.detail


@pytest.mark.parametrize(
    "text",
    ["-1", "1garbage", "4294967296", "9" * 5000],
    ids=["minus", "suffix", "overflow", "huge"],
)
def test_unknown_integer_lexemes_never_inherit_native_prefix_fallback(
    text: str,
) -> None:
    row = _fields(_xml(f"<General><Brightness>{text}</Brightness></General>"))[
        "brightness"
    ]
    assert not row.known
    assert row.raw_value.startswith(text[:512])
    assert len(row.raw_value) < 550


@pytest.mark.parametrize("text", [" 1", "\t1", "\n1", "2", "-1"])
def test_boolean_does_not_normalize_odd_native_spellings(text: str) -> None:
    row = _fields(_xml(f"<Playback><SoundCheck>{text}</SoundCheck></Playback>"))[
        "sound_check"
    ]
    assert not row.known
    assert row.raw_value == text
    assert row.value not in ("Off", "On")


@pytest.mark.parametrize("profile", [N5, N6, N7, REFRESH])
def test_city_ids_are_not_row_ordinals_or_host_timezones(
    profile: NamedPreferencesProfile,
) -> None:
    rows = _fields(_xml("<DateTime><TimeZone>1</TimeZone></DateTime>"), profile)
    assert rows["DateTime.TimeZone"].value == "California"
    assert "base offset -480 minutes" in rows["DateTime.TimeZone"].detail
    assert "not a current UTC offset" in rows["DateTime.TimeZone"].detail
    rows = _fields(_xml("<DateTime><TimeZone>205</TimeZone></DateTime>"), profile)
    assert rows["DateTime.TimeZone"].value == "Phnom Penh"
    assert ("maximum 204" in rows["DateTime.TimeZone"].detail) == (profile is N5)
    assert len(FIRMWARE_CITIES) == 205


def test_profile_specific_city_labels_and_anomalous_binding_are_preserved() -> None:
    source = _xml("<DateTime><TimeZone>190</TimeZone></DateTime>")
    assert _fields(source, N6)["DateTime.TimeZone"].value == "Katmandu"
    assert _fields(source, N7)["DateTime.TimeZone"].value == "Kathmandu"
    source = _xml("<DateTime><TimeZone>118</TimeZone></DateTime>")
    assert "+120 minutes" in _fields(source, N5)["DateTime.TimeZone"].detail
    assert "Africa/Bissau" in _fields(source, N6)["DateTime.TimeZone"].detail
    assert (
        _fields(_xml("<DateTime><TimeZone>999</TimeZone></DateTime>"))[
            "DateTime.TimeZone"
        ].known
        is False
    )


def test_language_and_explicit_clock_choice_remain_distinct_saved_values() -> None:
    source = _xml(
        "<General><Language>en-GB</Language></General><DateTime>"
        "<TwentyFourHourClock>0</TwentyFourHourClock>"
        "<UserSet24HourSetting>1</UserSet24HourSetting></DateTime>"
    )
    rows = _fields(source)
    assert rows["General.Language"].value == "English (UK)"
    assert rows["DateTime.TwentyFourHourClock"].value == "Off"
    assert rows["DateTime.UserSet24HourSetting"].value == "On"
    assert "preserves" in rows["DateTime.UserSet24HourSetting"].detail
    assert not _fields(source, N6)[
        "General.Language"
    ].known  # Not a Nano 6 UI language.


def test_duplicate_and_complex_values_expose_raw_without_choosing_winner() -> None:
    source = _xml(
        "<General><Brightness>30</Brightness><Brightness>70</Brightness></General>"
        '<Playback><EQ><![CDATA[100]]></EQ><SoundCheck a="b">1</SoundCheck></Playback>'
    )
    result = inspect_named_preferences(source, profile=N7)
    assert len(result.observations) == 4
    assert len(result.issues) == 4
    assert [row.raw_value for row in result.observations[:2]] == ["30", "70"]
    assert all(not row.known for row in result.observations)
    assert all(
        row.key not in ("brightness", "sound_check", "eq_preset")
        for row in result.observations
    )
    assert (
        available_named_preferences(parse_named_preferences(source, profile=N7)) == ()
    )


@pytest.mark.parametrize(
    "source",
    [
        b"",
        b"<iPodSettings>",
        b'<iPodSettings version="2.0"/>',
        b'<!DOCTYPE iPodSettings [<!ENTITY x "100">]><iPodSettings version="1.0"><General><Brightness>&x;</Brightness></General></iPodSettings>',
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
def test_invalid_or_excessive_xml_is_nonblocking_and_has_no_guessed_values(
    source: bytes,
) -> None:
    result = inspect_named_preferences(source, profile=N7)
    assert result.issues
    assert result.observations == ()


def test_unknown_extension_budget_preserves_known_rows_and_reports_omission() -> None:
    source = _xml(
        "<Future>"
        + "".join(f"<k{i}>x</k{i}>" for i in range(600))
        + "</Future><General><Brightness>40</Brightness></General>"
    )
    result = inspect_named_preferences(source, profile=N7)
    assert len(result.observations) == 512
    assert result.observations[0].key == "brightness"
    assert any("89 additional fields" in issue for issue in result.issues)


def test_nano4_named_keys_are_read_only_and_not_borrowed_from_nano5() -> None:
    source = _xml(
        "<Settings><FontSize>1</FontSize><ShakeSetting>1</ShakeSetting></Settings>"
        "<NowPlaying><Crossfade>0</Crossfade></NowPlaying><General><Brightness>40</Brightness></General>"
    )
    rows = _fields(source, NamedPreferencesProfile.NANO_4_1_0_4)
    assert rows["Settings.FontSize"].value == "Large"
    assert rows["Settings.ShakeSetting"].value == "On"
    assert rows["NowPlaying.Crossfade"].value == "Off"
    assert not rows["General.Brightness"].known


@pytest.mark.parametrize("profile", [N5, N6, N7, REFRESH])
def test_legacy_binary_inspection_does_not_inherit_classic_or_percent_units(
    profile: NamedPreferencesProfile,
) -> None:
    blob = bytearray(b"\xaa" * 2960)
    struct.pack_into("<I", blob, 0, 0x3E)
    struct.pack_into("<I", blob, 8, 128)
    source = bytes(blob)
    result = inspect_named_binary_preferences(source, profile=profile)
    assert not result.issues
    rows = {row.key: row for row in result.observations}
    assert rows["legacy.volume"].value == "128"
    assert not rows["legacy.volume"].known
    assert "not a percentage" in rows["legacy.volume"].detail
    assert rows["legacy.unresolved"].value == "2956 bytes retain unresolved semantics"
    assert source == bytes(blob)


def test_unqualified_binary_does_not_block_independent_xml_inspection() -> None:
    assert inspect_named_binary_preferences(b"bad", profile=N7).issues
    assert inspect_named_binary_preferences(bytes(2960), profile=N7).issues
    assert inspect_named_binary_preferences(
        bytes(2960), profile=NamedPreferencesProfile.NANO_4_1_0_4
    ).issues
    assert _fields(_xml("<General><Brightness>40</Brightness></General>"))[
        "brightness"
    ].known


@pytest.mark.parametrize("profile", [N6, N7, REFRESH])
def test_removed_timer_fields_remain_uninterpreted_and_byte_preserved(
    profile: NamedPreferencesProfile,
) -> None:
    source = _xml(
        "<Timer><Hours>3</Hours><Minutes>15</Minutes><SleepiPod>1</SleepiPod><SoundIndex>24</SoundIndex><DateTime>invalid date</DateTime></Timer>"
    )
    result = inspect_named_preferences(source, profile=profile)
    assert len(result.observations) == 5
    assert not result.issues
    assert all(
        not row.known and row.value == row.raw_value for row in result.observations
    )
    assert all(not spec.key.startswith("Timer.") for spec in FIELDS_BY_PROFILE[profile])
    assert (
        write_named_preferences(parse_named_preferences(source, profile=profile))
        == source
    )
