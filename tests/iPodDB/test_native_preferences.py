"""Firmware-qualified edits preserve all bytes outside explicitly chosen fields."""

import struct
from dataclasses import replace

import pytest

from iPodDB.preferences import (
    FirmwareLanguagePreferences,
    FixedOffsetTimezone,
    Mini2Preferences,
    PreferenceKey,
    PreferencesLayout,
    PreferencesProfile,
    available_preferences,
    parse_preferences,
    preference_value,
    update_preferences,
    write_preferences,
)
from iPodDB.shared.errors import iPodDBParseError, iPodDBWriteError

CLASSIC_TARGETS = (
    (PreferencesProfile.CLASSIC_6_1_1_2, 2952, 0x3C),
    (PreferencesProfile.CLASSIC_120GB_2_0_1, 2956, 0x3D),
    (PreferencesProfile.CLASSIC_UPDATER_35_2_0_4, 2956, 0x3E),
    (PreferencesProfile.CLASSIC_UPDATER_38_2_0_5, 2960, 0x3F),
)

TARGETS = (
    *CLASSIC_TARGETS,
    (PreferencesProfile.MINI_1_1_4_1, 2876, 0x16),
    (PreferencesProfile.MINI_2_1_4_1, 2876, 0x16),
    (PreferencesProfile.NANO_1_1_3_1, 2916, 0x37),
    (PreferencesProfile.VIDEO_1_3, 2924, 0x39),
)

NANO_TARGETS = (
    (PreferencesProfile.NANO_3_1_1_3, 2952, 0x3C),
    (PreferencesProfile.NANO_4_1_0_4, 2960, 0x3E),
)


def source(size: int, version: int) -> bytes:
    data = bytearray((i * 37 + 11) % 256 for i in range(size))
    struct.pack_into("<II", data, 0, version, 0)
    data[0x18] = 1
    data[0x8A] = 1
    struct.pack_into("<I", data, 0xAFC, 0xA5A50003)
    return bytes(data)


@pytest.mark.parametrize("profile,size,version", TARGETS)
def test_qualified_fields_roundtrip_without_defaulting_unknowns(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = source(size, version)
    document = parse_preferences(raw, profile=profile)
    assert write_preferences(document) == raw
    assert document.settings is not None
    assert document.settings.language_code == int.from_bytes(raw[0xAF8:0xAFC], "little")
    assert preference_value(document, PreferenceKey.SOUND_CHECK) == raw[0xB16]
    assert preference_value(document, PreferenceKey.REPEAT_MODE) == int.from_bytes(
        raw[0x14:0x18], "little"
    )
    assert preference_value(document, PreferenceKey.CLICKER) == 3
    assert preference_value(document, PreferenceKey.SHUFFLE_MODE) == 2
    assert PreferenceKey.BACKLIGHT_TIMEOUT in {
        field.key for field in available_preferences(document)
    }


@pytest.mark.parametrize("profile,size,version", TARGETS)
def test_changes_retain_source_and_patch_only_the_chosen_fields(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = source(size, version)
    document = parse_preferences(raw, profile=profile)
    edited = update_preferences(
        document,
        {
            PreferenceKey.SHUFFLE_MODE: 1,
            PreferenceKey.REPEAT_MODE: 2,
            PreferenceKey.SOUND_CHECK: 1,
            PreferenceKey.CLICKER: 0,
        },
    )
    expected = bytearray(raw)
    expected[0x8A] = 0
    struct.pack_into("<I", expected, 0x14, 2)
    expected[0xB16] = 1
    struct.pack_into("<I", expected, 0xAFC, 0xA5A50000)
    assert edited.source_bytes is document.source_bytes
    assert write_preferences(edited) == expected
    assert preference_value(edited, PreferenceKey.SHUFFLE_MODE) == 1
    reloaded = parse_preferences(expected, profile=profile)
    assert preference_value(reloaded, PreferenceKey.REPEAT_MODE) == 2
    assert write_preferences(reloaded) == expected
    # Reverting an explicit choice removes it, rather than normalizing the file.
    reverted = update_preferences(edited, {PreferenceKey.SHUFFLE_MODE: 2})
    assert PreferenceKey.SHUFFLE_MODE not in dict(reverted.preference_edits)


@pytest.mark.parametrize("profile,size,version", CLASSIC_TARGETS)
def test_classic_eq_brightness_and_clicker_have_proven_domains(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = source(size, version)
    document = parse_preferences(raw, profile=profile)
    fields = {field.key: field for field in available_preferences(document)}
    assert fields[PreferenceKey.EQ_PRESET].allowed_values == (0, *range(100, 122))
    assert fields[PreferenceKey.CLICKER].allowed_values == (0, 3)
    assert fields[PreferenceKey.BRIGHTNESS].minimum == 0
    assert fields[PreferenceKey.BRIGHTNESS].maximum == 100
    edited = update_preferences(
        document, {PreferenceKey.EQ_PRESET: 109, PreferenceKey.BRIGHTNESS: 100}
    )
    expected = bytearray(raw)
    struct.pack_into("<H", expected, 0xB60, 109)
    expected[0xB54] = 100
    assert write_preferences(edited) == expected
    for key, invalid in (
        (PreferenceKey.CLICKER, 1),
        (PreferenceKey.EQ_PRESET, 99),
        (PreferenceKey.BRIGHTNESS, 101),
    ):
        with pytest.raises(iPodDBWriteError):
            update_preferences(document, {key: invalid})


@pytest.mark.parametrize("profile,size,version", TARGETS)
def test_malformed_shuffle_does_not_alias_a_known_choice(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = bytearray(source(size, version))
    raw[0x18] = 255
    document = parse_preferences(raw, profile=profile)
    assert preference_value(document, PreferenceKey.SHUFFLE_MODE) is None
    assert write_preferences(document) == raw
    edited = update_preferences(document, {PreferenceKey.SHUFFLE_MODE: 0})
    raw[0x18] = raw[0x8A] = 0
    assert write_preferences(edited) == raw


@pytest.mark.parametrize("profile,size,version", (*TARGETS, *NANO_TARGETS))
def test_profile_framing_and_reset_conditions_gate_edits(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = bytearray(source(size, version))
    generic = parse_preferences(raw)
    assert available_preferences(generic) == ()
    with pytest.raises(iPodDBWriteError):
        update_preferences(generic, {PreferenceKey.SOUND_CHECK: 1})
    raw[4] = 1
    reset = parse_preferences(raw, profile=profile)
    assert available_preferences(reset) == ()
    assert write_preferences(reset) == raw
    with pytest.raises(iPodDBWriteError):
        update_preferences(reset, {PreferenceKey.SOUND_CHECK: 1})
    raw[0] ^= 1
    with pytest.raises(iPodDBParseError, match="version"):
        parse_preferences(raw, profile=profile)


@pytest.mark.parametrize("invalid", (True, False, -1, 2, 256, 1.0, "1", None))
def test_public_and_forged_edits_reject_invalid_typed_values(invalid: object) -> None:
    document = parse_preferences(
        source(2956, 0x3D), profile=PreferencesProfile.CLASSIC_120GB_2_0_1
    )
    forged = replace(document)
    object.__setattr__(
        forged, "preference_edits", ((PreferenceKey.SOUND_CHECK, invalid),)
    )
    with pytest.raises(iPodDBWriteError):
        write_preferences(forged)


def test_disabled_shuffle_preserves_its_irrelevant_albums_byte() -> None:
    raw = bytearray(source(2956, 0x3D))
    raw[0x18] = 0
    document = parse_preferences(raw, profile=PreferencesProfile.CLASSIC_120GB_2_0_1)
    edited = update_preferences(document, {PreferenceKey.SHUFFLE_MODE: 0})
    assert edited.preference_edits == ()
    assert write_preferences(edited) == raw


@pytest.mark.parametrize(
    "profile", (PreferencesProfile.MINI_1_1_4_1, PreferencesProfile.MINI_2_1_4_1)
)
def test_mini_clock_words_are_read_only_but_invalid_words_do_not_block_edits(
    profile: PreferencesProfile,
) -> None:
    raw = bytearray(source(2876, 0x16))
    struct.pack_into("<I", raw, 0xB10, 0xFFFFFFFF)
    document = parse_preferences(raw, profile=profile)
    assert isinstance(document.settings, Mini2Preferences)
    assert document.timezone is None
    with pytest.raises(iPodDBWriteError) as error:
        write_preferences(
            replace(document, settings=replace(document.settings, timezone_selector=25))
        )
    assert error.value.code == "preferences.read_only_clock"
    edited = update_preferences(document, {PreferenceKey.SOUND_CHECK: 1})
    raw[0xB16] = 1
    assert write_preferences(edited) == raw


@pytest.mark.parametrize(
    "profile,size,version",
    [
        (PreferencesProfile.NANO_1_1_3_1, 2916, 0x37),
        *NANO_TARGETS,
    ],
)
def test_new_firmware_language_is_observed_without_inventing_a_clock_contract(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = source(size, version)
    document = parse_preferences(raw, profile=profile)
    assert isinstance(document.settings, FirmwareLanguagePreferences)
    assert document.timezone is None
    with pytest.raises(iPodDBWriteError, match="observation-only"):
        write_preferences(
            replace(document, settings=replace(document.settings, language_code=0))
        )
    # Arbitrary date/clock words cannot prevent an unrelated explicit change.
    expected = bytearray(raw)
    expected[0xB16] = 1
    assert (
        write_preferences(update_preferences(document, {PreferenceKey.SOUND_CHECK: 1}))
        == expected
    )


@pytest.mark.parametrize(
    "profile", (PreferencesProfile.MINI_1_1_4_1, PreferencesProfile.MINI_2_1_4_1)
)
@pytest.mark.parametrize(
    "selector,offset",
    [
        (1, -43200),
        (2, -39600),
        (25, 0),
        (26, 3600),
        (49, 43200),
        (50, 46800),
        (0, None),
        (51, None),
        (0x10019, None),
    ],
)
def test_mini_selector_preserves_standard_dst_pair_and_unknown_full_word(
    profile: PreferencesProfile, selector: int, offset: int | None
) -> None:
    raw = bytearray(source(2876, 0x16))
    struct.pack_into("<I", raw, 0xB10, selector)
    document = parse_preferences(raw, profile=profile)
    assert document.timezone == (
        None if offset is None else FixedOffsetTimezone(offset)
    )
    assert write_preferences(document) == raw


def test_alternate_audio_is_independently_qualified_for_all_classics() -> None:
    for profile, size, version in TARGETS:
        raw = bytearray(source(size, version))
        if size > 0xB85:
            raw[0xB85] = 255
        document = parse_preferences(raw, profile=profile)
        fields = {field.key for field in available_preferences(document)}
        if profile not in {target[0] for target in CLASSIC_TARGETS}:
            assert PreferenceKey.ALTERNATE_AUDIO not in fields
            continue
        assert preference_value(document, PreferenceKey.ALTERNATE_AUDIO) == 255
        unrelated = update_preferences(document, {PreferenceKey.SOUND_CHECK: 1})
        assert write_preferences(unrelated)[0xB85] == 255
        edited = update_preferences(document, {PreferenceKey.ALTERNATE_AUDIO: 1})
        raw[0xB85] = 1
        assert write_preferences(edited) == raw
        with pytest.raises(iPodDBWriteError):
            update_preferences(document, {PreferenceKey.ALTERNATE_AUDIO: 2})


@pytest.mark.parametrize("profile,size,version", (*TARGETS, *NANO_TARGETS))
def test_backlight_authors_only_the_exact_models_visible_selectors(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = bytearray(source(size, version))
    struct.pack_into("<I", raw, 0xAF0, 0xFEDCBA98)
    document = parse_preferences(raw, profile=profile)
    offered: tuple[int, ...]
    hidden: tuple[int, ...]
    if profile in (PreferencesProfile.MINI_1_1_4_1, PreferencesProfile.MINI_2_1_4_1):
        offered, hidden = (0, 2, 3, 4, 5, 6), (1, 7, 8)
    elif profile in (PreferencesProfile.NANO_1_1_3_1, PreferencesProfile.VIDEO_1_3):
        offered, hidden = (0, 2, 3, 4, 5, 6, 8), (1, 7)
    else:
        offered, hidden = (0, 1, 2, 3, 4, 5, 6), (7, 8)
    field = next(
        item
        for item in available_preferences(document)
        if item.key is PreferenceKey.BACKLIGHT_TIMEOUT
    )
    assert field.allowed_values == offered
    assert preference_value(document, PreferenceKey.BACKLIGHT_TIMEOUT) == 0xFEDCBA98
    assert write_preferences(document) == raw
    for value in offered:
        edited = update_preferences(document, {PreferenceKey.BACKLIGHT_TIMEOUT: value})
        expected = bytearray(raw)
        struct.pack_into("<I", expected, 0xAF0, value)
        assert write_preferences(edited) == expected
        assert edited.source_bytes == raw
    for value in hidden:
        with pytest.raises(iPodDBWriteError):
            update_preferences(document, {PreferenceKey.BACKLIGHT_TIMEOUT: value})


@pytest.mark.parametrize("profile,size,version", NANO_TARGETS)
@pytest.mark.parametrize("value", (0, 1, 2, 3))
def test_nano_clicker_keeps_unexplained_upper_bits(
    profile: PreferencesProfile, size: int, version: int, value: int
) -> None:
    raw = source(size, version)
    document = parse_preferences(raw, profile=profile)
    edited = update_preferences(document, {PreferenceKey.CLICKER: value})
    expected = bytearray(raw)
    struct.pack_into("<I", expected, 0xAFC, 0xA5A50000 | value)
    assert write_preferences(edited) == expected


@pytest.mark.parametrize("profile,size,version", TARGETS[4:])
def test_legacy_signed_audiobook_speed_and_contact_words(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = bytearray(source(size, version))
    raw[0xB38] = 0x80
    document = parse_preferences(raw, profile=profile)
    assert preference_value(document, PreferenceKey.AUDIOBOOK_SPEED) == -128
    assert write_preferences(document) == raw
    unchanged_speed = update_preferences(document, {PreferenceKey.SOUND_CHECK: 1})
    assert write_preferences(unchanged_speed)[0xB38] == 0x80
    for speed in (-1, 0, 1):
        edited = update_preferences(
            document,
            {
                PreferenceKey.AUDIOBOOK_SPEED: speed,
                PreferenceKey.CONTACT_SORT: 1,
                PreferenceKey.CONTACT_DISPLAY: 0,
            },
        )
        expected = bytearray(raw)
        struct.pack_into("<b", expected, 0xB38, speed)
        struct.pack_into("<H", expected, 0xB0C, 1)
        struct.pack_into("<H", expected, 0xB14, 0)
        assert write_preferences(edited) == expected
        assert (
            preference_value(
                parse_preferences(expected, profile=profile),
                PreferenceKey.AUDIOBOOK_SPEED,
            )
            == speed
        )
    for invalid in (-2, 2, 255):
        with pytest.raises(iPodDBWriteError):
            update_preferences(document, {PreferenceKey.AUDIOBOOK_SPEED: invalid})


@pytest.mark.parametrize("profile,size,version", (*CLASSIC_TARGETS, *NANO_TARGETS))
def test_modern_photo_seconds_preserve_unknown_clock_and_compound_state(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = bytearray(source(size, version))
    raw[0xB3E] = 0x80
    document = parse_preferences(raw, profile=profile)
    assert preference_value(document, PreferenceKey.PHOTO_DURATION) == -128
    assert write_preferences(document) == raw
    for seconds in (0, 2, 3, 5, 10, 20):
        edited = update_preferences(document, {PreferenceKey.PHOTO_DURATION: seconds})
        expected = bytearray(raw)
        expected[0xB3E] = seconds
        assert write_preferences(edited) == expected
    for invalid in (-128, -1, 1, 4, 255):
        with pytest.raises(iPodDBWriteError):
            update_preferences(document, {PreferenceKey.PHOTO_DURATION: invalid})


@pytest.mark.parametrize(
    "profile,size,version", (*CLASSIC_TARGETS, *NANO_TARGETS, TARGETS[-1])
)
@pytest.mark.parametrize("shuffle,repeat", ((0, 0), (0, 1), (1, 0), (1, 1)))
def test_photo_toggles_leave_music_identity_and_transition_pair_exact(
    profile: PreferencesProfile, size: int, version: int, shuffle: int, repeat: int
) -> None:
    raw = source(size, version)
    document = parse_preferences(raw, profile=profile)
    edited = update_preferences(
        document,
        {PreferenceKey.PHOTO_SHUFFLE: shuffle, PreferenceKey.PHOTO_REPEAT: repeat},
    )
    expected = bytearray(raw)
    expected[0xB3C] = shuffle
    expected[0xB3D] = repeat
    assert write_preferences(edited) == expected


@pytest.mark.parametrize("profile,size,version", (*CLASSIC_TARGETS, *NANO_TARGETS))
def test_transition_choices_patch_both_bytes_using_each_native_catalog(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = bytearray(source(size, version))
    raw[0xB3B], raw[0xB49] = 0x80, 0x90
    document = parse_preferences(raw, profile=profile)
    assert preference_value(document, PreferenceKey.PHOTO_TRANSITION) is None
    assert write_preferences(document) == raw
    if profile is PreferencesProfile.NANO_4_1_0_4:
        choices, random_id = (25, -1, 26, 27, 6, 5, 21), 28
        excluded = (0, 1, 3, 14, 24)
    else:
        choices, random_id = (0, -1, 14, 5, 24, 1, 3), 25
        excluded = (6, 21, 25, 26, 27)
    for choice in choices:
        edited = update_preferences(document, {PreferenceKey.PHOTO_TRANSITION: choice})
        expected = bytearray(raw)
        expected[0xB3B] = 0xFF if choice == -1 else 0xFE
        expected[0xB49] = random_id if choice == -1 else choice
        assert write_preferences(edited) == expected
        reloaded = parse_preferences(expected, profile=profile)
        assert preference_value(reloaded, PreferenceKey.PHOTO_TRANSITION) == choice
    for invalid in (*excluded, -2, 255):
        with pytest.raises(iPodDBWriteError):
            update_preferences(document, {PreferenceKey.PHOTO_TRANSITION: invalid})


@pytest.mark.parametrize("profile,size,version", (*CLASSIC_TARGETS, *NANO_TARGETS))
def test_transition_random_noop_and_revert_retain_original_ignored_id(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = bytearray(source(size, version))
    raw[0xB3B], raw[0xB49] = 0xFF, 123
    document = parse_preferences(raw, profile=profile)
    unchanged = update_preferences(document, {PreferenceKey.PHOTO_TRANSITION: -1})
    assert unchanged.preference_edits == ()
    assert write_preferences(unchanged) == raw
    changed = update_preferences(document, {PreferenceKey.PHOTO_TRANSITION: 5})
    reverted = update_preferences(changed, {PreferenceKey.PHOTO_TRANSITION: -1})
    assert reverted.preference_edits == ()
    assert write_preferences(reverted) == raw
    # Even if a native getter treats arbitrary modes as Specific, the Host must
    # not silently label an unqualified mode as a valid menu choice.
    raw[0xB3B], raw[0xB49] = 0, 5
    malformed = parse_preferences(raw, profile=profile)
    assert preference_value(malformed, PreferenceKey.PHOTO_TRANSITION) is None
    assert write_preferences(malformed) == raw


@pytest.mark.parametrize("profile,size,version", NANO_TARGETS)
def test_nano_video_and_contact_ui_choices_only_replace_their_saved_fields(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = source(size, version)
    document = parse_preferences(raw, profile=profile)
    for key, offset, width, values in (
        (PreferenceKey.TV_OUT, 0xB39, 1, (0, 1, 2)),
        (PreferenceKey.TV_SIGNAL, 0xB3A, 1, (0, 1)),
        (PreferenceKey.TV_SCREEN, 0xB84, 1, (0, 1)),
        (PreferenceKey.FIT_TO_SCREEN_DISABLED, 0xB4D, 1, (0, 1)),
        (PreferenceKey.ALTERNATE_AUDIO, 0xB85, 1, (0, 1)),
        (PreferenceKey.CONTACT_SORT, 0xB0C, 2, (0, 1)),
    ):
        for value in values:
            expected = bytearray(raw)
            expected[offset : offset + width] = value.to_bytes(width, "little")
            edited = update_preferences(document, {key: value})
            assert write_preferences(edited) == expected


def test_video_widescreen_and_recording_quality_do_not_inherit_modern_meanings() -> (
    None
):
    raw = source(2924, 0x39)
    document = parse_preferences(raw, profile=PreferencesProfile.VIDEO_1_3)
    for value in (0, 1):
        edited = update_preferences(
            document,
            {PreferenceKey.WIDESCREEN: value, PreferenceKey.VOICE_MEMO_QUALITY: value},
        )
        expected = bytearray(raw)
        expected[0xB4D] = expected[0xB60] = value
        assert write_preferences(edited) == expected
    keys = {item.key for item in available_preferences(document)}
    assert not keys & {
        PreferenceKey.EQ_PRESET,
        PreferenceKey.FIT_TO_SCREEN_DISABLED,
        PreferenceKey.TV_SCREEN,
        PreferenceKey.NIKE_SPOKEN_FEEDBACK,
    }


def test_nano1_nike_changes_preserve_units_powersong_and_receiver_latch() -> None:
    raw = bytearray(source(2916, 0x37))
    struct.pack_into("<Q", raw, 0xB58, 0x0123456789ABCDEF)
    raw[0xB55], raw[0xB60] = 0x91, 0xA7
    document = parse_preferences(raw, profile=PreferencesProfile.NANO_1_1_3_1)
    for voice in (0, 1, 2):
        for remote in (0, 1):
            edited = update_preferences(
                document,
                {
                    PreferenceKey.NIKE_SPOKEN_FEEDBACK: voice,
                    PreferenceKey.NIKE_REMOTE_COMMANDS_DISABLED: remote,
                },
            )
            expected = bytearray(raw)
            expected[0xB56], expected[0xB57] = voice, remote
            assert write_preferences(edited) == expected


@pytest.mark.parametrize("profile,size,version", (*TARGETS, *NANO_TARGETS))
def test_new_fields_never_gain_authority_from_a_shared_offset(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    document = parse_preferences(source(size, version), profile=profile)
    keys = {item.key for item in available_preferences(document)}
    legacy = {target[0] for target in TARGETS[4:]}
    modern = {target[0] for target in (*CLASSIC_TARGETS, *NANO_TARGETS)}
    assert (PreferenceKey.AUDIOBOOK_SPEED in keys) is (profile in legacy)
    assert (PreferenceKey.PHOTO_TRANSITION in keys) is (profile in modern)
    assert (PreferenceKey.PHOTO_DURATION in keys) is (profile in modern)
    assert (PreferenceKey.VOICE_MEMO_QUALITY in keys) is (
        profile is PreferencesProfile.VIDEO_1_3
    )
    assert (PreferenceKey.NIKE_SPOKEN_FEEDBACK in keys) is (
        profile is PreferencesProfile.NANO_1_1_3_1
    )
    assert (PreferenceKey.TV_SCREEN in keys) is (
        profile in {t[0] for t in NANO_TARGETS}
    )


@pytest.mark.parametrize("profile,size,version", (*TARGETS, *NANO_TARGETS))
@pytest.mark.parametrize("reset_word", (0, 1, 0x100, 0x80000000, 0xFFFFFFFF))
def test_reset_observation_reads_full_word_only_in_qualified_frames(
    profile: PreferencesProfile, size: int, version: int, reset_word: int
) -> None:
    raw = bytearray(source(size, version))
    struct.pack_into("<I", raw, 4, reset_word)
    document = parse_preferences(raw, profile=profile)
    assert document.reset_requested is (reset_word != 0)
    assert write_preferences(document) == raw
    assert bool(available_preferences(document)) is (reset_word == 0)
    assert parse_preferences(raw).reset_requested is None
    assert (
        parse_preferences(raw, layout=PreferencesLayout.UNKNOWN).reset_requested is None
    )


@pytest.mark.parametrize("profile,size,version", (*TARGETS, *NANO_TARGETS))
def test_reset_observation_rechecks_current_source_framing(
    profile: PreferencesProfile, size: int, version: int
) -> None:
    raw = bytearray(source(size, version))
    raw[4] = 1
    document = parse_preferences(raw, profile=profile)
    assert replace(document, source_bytes=bytes(raw[:-1])).reset_requested is None
    for other_version in (0, version + 1, 0x10000 | version):
        struct.pack_into("<I", raw, 0, other_version)
        assert replace(document, source_bytes=bytes(raw)).reset_requested is None
