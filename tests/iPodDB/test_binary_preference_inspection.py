"""Saved observations honor exact identities and model-specific native semantics."""

import struct
from dataclasses import replace

import pytest

from iPodDB.preferences import (
    PreferenceKey,
    PreferencesLayout,
    PreferencesProfile,
    available_preferences,
    parse_preferences,
    update_preferences,
    write_preferences,
)
from iPodDB.preferences._binary_inspection_data import BINARY_PROFILE_EVIDENCE
from iPodDB.preferences.binary_inspection import inspect_binary_preferences
from iPodDB.preferences.inspection_models import PreferenceObservation
from iPodDB.preferences.models import PreferencesDocument

TARGETS = (
    (PreferencesProfile.MINI_1_1_4_1, 2876, 0x16),
    (PreferencesProfile.MINI_2_1_4_1, 2876, 0x16),
    (PreferencesProfile.NANO_1_1_3_1, 2916, 0x37),
    (PreferencesProfile.NANO_3_1_1_3, 2952, 0x3C),
    (PreferencesProfile.NANO_4_1_0_4, 2960, 0x3E),
    (PreferencesProfile.VIDEO_1_3, 2924, 0x39),
    (PreferencesProfile.CLASSIC_6_1_1_2, 2952, 0x3C),
    (PreferencesProfile.CLASSIC_120GB_2_0_1, 2956, 0x3D),
    (PreferencesProfile.CLASSIC_UPDATER_35_2_0_4, 2956, 0x3E),
    (PreferencesProfile.CLASSIC_UPDATER_38_2_0_5, 2960, 0x3F),
)


def make_document(profile: PreferencesProfile, fill: int = 0) -> PreferencesDocument:
    _, size, version = next(target for target in TARGETS if target[0] is profile)
    source = bytearray([fill]) * size
    struct.pack_into("<II", source, 0, version, 0)
    return parse_preferences(source, profile=profile)


def with_value(
    document: PreferencesDocument, offset: int, value: int, size: int = 1
) -> PreferencesDocument:
    data = bytearray(document.source_bytes)
    data[offset : offset + size] = value.to_bytes(size, "little")
    return parse_preferences(data, profile=document.profile)


def rows(document: PreferencesDocument) -> dict[str, PreferenceObservation]:
    result = inspect_binary_preferences(document)
    return {item.key: item for item in result.observations}


@pytest.mark.parametrize("profile,size,version", TARGETS)
def test_exact_studied_profiles_observe_without_mutating_or_authorizing(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    document = make_document(profile, 0xA5)
    source = document.source_bytes
    prior_fields = available_preferences(document)
    result = inspect_binary_preferences(document)
    keys = [item.key for item in result.observations]
    assert len(keys) == len(set(keys))
    assert {"language", "repeat_mode", "shuffle_mode", "unknown_data"} <= set(keys)
    assert rows(document)["format_version"].value == f"0x{version:X}"
    assert len(result.observations) <= 64
    assert len(result.issues) <= 17
    assert len(source) == size
    assert document.source_bytes is source
    assert write_preferences(document) == source
    assert available_preferences(document) == prior_fields
    assert document.preference_edits == ()


@pytest.mark.parametrize("profile,size,version", TARGETS)
def test_wrong_frames_and_generic_layouts_never_inherit_a_binary_catalog(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    document = make_document(profile)
    wrong_version = bytearray(document.source_bytes)
    wrong_version[0] ^= 1
    candidates = (
        replace(document, source_bytes=bytes(wrong_version)),
        replace(document, source_bytes=document.source_bytes + b"\0"),
        replace(document, source_bytes=document.source_bytes[:-1]),
        replace(document, layout=PreferencesLayout.UNKNOWN),
        replace(document, settings=None),
        parse_preferences(document.source_bytes),
    )
    for candidate in candidates:
        result = inspect_binary_preferences(candidate)
        assert result.observations == ()
        assert result.issues


@pytest.mark.parametrize("profile,size,version", TARGETS)
def test_reset_requested_bytes_are_readable_with_discard_caveat(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    document = with_value(make_document(profile), 4, 0xFFFFFFFF, 4)
    result = inspect_binary_preferences(document)
    assert result.observations
    assert "discard" in result.issues[0]
    assert rows(document)["reset_request"].value == "Defaults requested"
    assert available_preferences(document) == ()
    assert write_preferences(document) == document.source_bytes


def test_shared_sizes_do_not_select_a_different_models_transition_catalog() -> None:
    nano = with_value(make_document(PreferencesProfile.NANO_4_1_0_4), 0xB3B, 254)
    classic = with_value(
        make_document(PreferencesProfile.CLASSIC_UPDATER_38_2_0_5), 0xB3B, 254
    )
    nano = with_value(nano, 0xB49, 25)
    classic = with_value(classic, 0xB49, 25)
    assert rows(nano)["photo_transition"].value == "None"
    assert rows(nano)["photo_transition"].raw_value == "Mode 0xFE, effect 0x19"
    assert rows(classic)["photo_transition"].known is False


@pytest.mark.parametrize(
    "profile,expected",
    (
        (PreferencesProfile.MINI_1_1_4_1, "Always On"),
        (PreferencesProfile.NANO_1_1_3_1, "20 seconds"),
        (PreferencesProfile.VIDEO_1_3, "20 seconds"),
        (PreferencesProfile.NANO_3_1_1_3, "Always On"),
        (PreferencesProfile.CLASSIC_6_1_1_2, "Always On"),
    ),
)
def test_backlight_is_a_model_specific_selector(
    profile: PreferencesProfile, expected: str
) -> None:
    document = with_value(make_document(profile), 0xAF0, 6, 4)
    assert rows(document)["backlight_timeout"].value == expected


def test_video_clicker_routes_are_reversed_from_mini_and_upper_bits_stay_visible() -> (
    None
):
    mini = with_value(make_document(PreferencesProfile.MINI_2_1_4_1), 0xAFC, 1, 4)
    video = with_value(make_document(PreferencesProfile.VIDEO_1_3), 0xAFC, 1, 4)
    assert rows(mini)["clicker"].value == "Speaker"
    assert rows(video)["clicker"].value == "Headphones"
    video = with_value(video, 0xAFC, 0x80000001, 4)
    clicker = rows(video)["clicker"]
    assert clicker.value == "Headphones; unknown bits 0x80000000"
    assert not clicker.known
    assert "80000001" in clicker.raw_value


def test_sparse_language_catalog_and_nano4_english_split() -> None:
    nano3 = with_value(make_document(PreferencesProfile.NANO_3_1_1_3), 0xAF8, 1, 4)
    nano4 = with_value(make_document(PreferencesProfile.NANO_4_1_0_4), 0xAF8, 1, 4)
    mini = with_value(make_document(PreferencesProfile.MINI_1_1_4_1), 0xAF8, 15, 4)
    assert rows(nano3)["language"].value == "Dansk"
    assert rows(nano4)["language"].value == "English (UK)"
    assert rows(mini)["language"].value == "Unknown (15)"
    assert not rows(mini)["language"].known


def test_legacy_eq_count_bounds_utf16_errors_and_retained_suffix_are_nonblocking() -> (
    None
):
    original = make_document(PreferencesProfile.VIDEO_1_3)
    data = bytearray(original.source_bytes)
    struct.pack_into("<H", data, 0x8EA, 4)
    data[0x8EC : 0x8EC + 8] = "Jazz".encode("utf-16-le")
    data[0x8F4:0x8FC] = b"retained"
    data[0x8E0] = 1
    document = parse_preferences(data, profile=original.profile)
    assert rows(document)["eq_preset"].value == "Jazz"
    assert write_preferences(document) == data
    excessive = with_value(document, 0x8EA, 256, 2)
    assert "exceeds" in rows(excessive)["eq_preset"].value
    assert inspect_binary_preferences(excessive).issues
    data[0x8EC:0x8EE] = b"\0\xd8"
    bad_text = parse_preferences(data, profile=original.profile)
    assert "invalid UTF-16" in rows(bad_text)["eq_preset"].value
    assert rows(bad_text)["repeat_mode"].value == "Off"
    data[0x8EC : 0x8EC + 8] = "Nope".encode("utf-16-le")
    unknown_name = parse_preferences(data, profile=original.profile)
    assert "compiled preset match unverified" in rows(unknown_name)["eq_preset"].value
    assert not rows(unknown_name)["eq_preset"].known


def test_slideshow_duration_selector_differs_from_signed_seconds() -> None:
    video = with_value(make_document(PreferencesProfile.VIDEO_1_3), 0xB3E, 3)
    nano3 = with_value(make_document(PreferencesProfile.NANO_3_1_1_3), 0xB3E, 3)
    assert rows(video)["photo_duration"].value.replace(" ", "") == "5seconds"
    assert rows(nano3)["photo_duration"].value == "3 seconds"
    nano3 = with_value(nano3, 0xB3E, 255)
    assert rows(nano3)["photo_duration"].raw_value == "-1 (0xFF)"
    assert not rows(nano3)["photo_duration"].known


def test_nano4_transitions_and_music_do_not_inherit_nano3_effects() -> None:
    nano3 = with_value(make_document(PreferencesProfile.NANO_3_1_1_3), 0xB3B, 254)
    nano4 = with_value(make_document(PreferencesProfile.NANO_4_1_0_4), 0xB3B, 254)
    nano3 = with_value(nano3, 0xB49, 14)
    nano4 = with_value(nano4, 0xB49, 14)
    assert rows(nano3)["photo_transition"].value == "Cross Fade"
    assert rows(nano4)["photo_transition"].value == "Unknown (14)"
    nano4 = with_value(nano4, 0xB49, 26)
    assert rows(nano4)["photo_transition"].value == "Dissolve"
    assert "track_extras_cache" in rows(nano3)
    assert "track_extras_cache" not in rows(nano4)
    assert "internal_flag_b4c" in rows(nano4)


def test_classic33_dynamic_music_evidence_is_not_promoted_to_other_images() -> None:
    classic33 = with_value(
        make_document(PreferencesProfile.CLASSIC_120GB_2_0_1), 0xB3F, 5
    )
    classic35 = with_value(
        make_document(PreferencesProfile.CLASSIC_UPDATER_35_2_0_4), 0xB3F, 5
    )
    assert "partly unknown" in rows(classic33)["slideshow_music"].value
    assert rows(classic35)["slideshow_music"].value == "Unknown (5)"


def test_signed_audiobook_speed_balance_and_raw_overflow_limit() -> None:
    video = make_document(PreferencesProfile.VIDEO_1_3)
    video = with_value(video, 0xB38, 255)
    video = with_value(video, 0x0C, 50, 4)
    video = with_value(video, 0xB50, 0xFFFFFFFF, 4)
    result = rows(video)
    assert result["audiobook_speed"].value == "Slower"
    assert result["audiobook_speed"].raw_value == "-1 (0xFF)"
    assert result["stereo_balance"].value == "50 (50 is centered)"
    assert result["volume_limit"].raw_value == "4294967295 (0xFFFFFFFF)"
    assert "modulo 2^32" in result["volume_limit"].detail
    mini = make_document(PreferencesProfile.MINI_2_1_4_1)
    assert "stereo_balance" not in rows(mini)


def test_datetime_unknowns_preserve_raw_values_without_blocking_other_fields() -> None:
    classic = make_document(PreferencesProfile.CLASSIC_120GB_2_0_1)
    classic = with_value(classic, 0xB70, 0x26, 4)
    classic = with_value(classic, 0xB78, 0xFFFFFFFF, 4)
    classic = with_value(classic, 0xB7C, 0xFFFFFFFF, 4)
    classic = with_value(classic, 0xB6C, 255)
    result = rows(classic)
    assert "unresolved" in result["city_id"].value
    assert result["clock_bias_days"].raw_value == "-1 (0xFFFFFFFF)"
    assert result["clock_bias_seconds"].value == "4294967295"
    assert not result["saved_dst"].known
    assert result["repeat_mode"].value == "Off"
    assert write_preferences(classic) == classic.source_bytes
    mini = with_value(make_document(PreferencesProfile.MINI_1_1_4_1), 0xB10, 26, 4)
    assert rows(mini)["legacy_timezone_selector"].value == "UTC+01:00; saved DST On"
    invalid = with_value(mini, 0xB10, 0xFFFFFFFF, 4)
    assert not rows(invalid)["legacy_timezone_selector"].known


def test_menu_masks_show_named_bits_and_unknown_residuals_in_one_observation() -> None:
    mini = with_value(
        make_document(PreferencesProfile.MINI_1_1_4_1), 0xB2C, 0x80000001, 4
    )
    menu = rows(mini)["main_menu_visibility"]
    assert menu.value == "Music; unknown bits 0x80000000"
    assert not menu.known
    unknown = rows(mini)["unknown_data"]
    assert "bytes in" in unknown.raw_value
    assert len(unknown.detail) < 500
    assert "padding" in unknown.detail


def test_observations_remain_source_based_when_the_editor_has_pending_changes() -> None:
    document = make_document(PreferencesProfile.VIDEO_1_3)
    edited = update_preferences(document, {PreferenceKey.REPEAT_MODE: 2})
    result = inspect_binary_preferences(edited)
    assert rows(edited)["repeat_mode"].value == "Off"
    assert any("before pending edits" in issue for issue in result.issues)
    assert edited.preference_edits == ((PreferenceKey.REPEAT_MODE, 2),)


def test_evidence_metadata_has_unique_keys_and_in_bounds_named_fields() -> None:
    for profile, size, _ in TARGETS:
        evidence = BINARY_PROFILE_EVIDENCE[profile]
        keys = [field.key for field in evidence.fields]
        assert len(set(keys)) == len(keys)
        assert evidence.firmware_sha256
        assert all(len(digest) == 64 for digest in evidence.firmware_sha256)
        assert all(
            0 <= field.offset < field.offset + field.size <= size
            for field in evidence.fields
        )


def test_editable_keys_match_observation_keys_without_creating_write_authority() -> (
    None
):
    for profile, _, _ in TARGETS:
        document = make_document(profile)
        observed = rows(document)
        for field in available_preferences(document):
            assert field.key.value in observed, (profile, field.key)
