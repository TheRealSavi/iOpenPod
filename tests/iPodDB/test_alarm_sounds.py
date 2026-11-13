"""Native sound setter independence, exact framing and captured tone parsing."""

import struct
from dataclasses import replace

import pytest
from whenever import PlainDateTime

from iPodDB.alarms.codec import (
    add_alarm,
    empty_alarm_document,
    parse_alarms,
    update_alarm,
    write_alarms,
)
from iPodDB.alarms.tones import (
    AlarmToneNote,
    default_alarm_tone_name,
    parse_alarm_tone,
    saved_alarm_tone_name,
)
from iPodDB.preferences.definitions import NamedPreferencesProfile, PreferencesProfile
from iPodDB.shared.errors import iPodDBWriteError


def _source() -> bytes:
    return write_alarms(
        add_alarm(
            empty_alarm_document(),
            scheduled=PlainDateTime(2026, 11, 13, 7),
            tone_name="Beep",
        )
    )


def test_variable_tone_names_preserve_unknown_fields_and_other_records() -> None:
    original = _source()
    unknown = struct.pack("<II", 0x85, 5) + b"abcde" + struct.pack("<I", 0x80000085)
    source = original[:-8] + unknown + original[-8:-4] + original[4:]
    document = parse_alarms(source)
    assert len(document.records) == 2
    changed = update_alarm(document, 0, tone_name="目覚まし")
    changed = update_alarm(changed, 1, tone_name="")
    written = write_alarms(changed)
    restored = parse_alarms(written)
    assert [record.tone_name for record in restored.records] == ["目覚まし", ""]
    assert written.count(unknown) == 1
    assert write_alarms(restored) == written
    assert restored.records[0].control_word == 8
    assert restored.records[0].sound_selector == 0xFFFFFFFF


def test_playlist_setter_preserves_enabled_gate_and_tone_independently() -> None:
    source = _source()
    changed = update_alarm(parse_alarms(source), 0, playlist_selector=17)
    record = changed.records[0]
    assert (record.sound_selector, record.control_word, record.tone_name) == (
        17,
        8,
        "Beep",
    )
    assert record.can_edit_playlist and record.can_edit_tone
    written = write_alarms(changed)
    assert written[:80] == source[:80]
    assert written[84:] == source[84:]
    disabled = update_alarm(changed, 0, enabled=False)
    enabled = update_alarm(disabled, 0, enabled=True)
    assert enabled.records[0].control_word == 4
    assert parse_alarms(write_alarms(enabled)).records[0].control_word == 4


def test_category_change_explicitly_clears_other_sound() -> None:
    document = parse_alarms(_source())
    playlist = update_alarm(document, 0, tone_name="", playlist_selector=0)
    assert (playlist.records[0].tone_name, playlist.records[0].sound_selector) == (
        "",
        0,
    )
    tone = update_alarm(
        playlist, 0, tone_name="Signalton", playlist_selector=0xFFFFFFFF
    )
    assert tone.records[0].tone_name == "Signalton"
    assert tone.records[0].control_word == 8


def test_creation_uses_sound_fields_before_native_enable_transition() -> None:
    created = add_alarm(
        empty_alarm_document(),
        scheduled=PlainDateTime(2026, 11, 13),
        playlist_selector=9,
    )
    assert created.records[0].control_word == 4
    assert created.records[0].sound_selector == 9


@pytest.mark.parametrize("name", ("A\0B", "é" * 128, "\ud800"))
def test_new_tone_names_must_fit_native_utf8_payload(name: str) -> None:
    with pytest.raises(iPodDBWriteError):
        update_alarm(parse_alarms(_source()), 0, tone_name=name)


@pytest.mark.parametrize("selector", (-1, 0x100000000, True))
def test_playlist_selectors_are_unsigned_words(selector: int) -> None:
    with pytest.raises(iPodDBWriteError):
        update_alarm(parse_alarms(_source()), 0, playlist_selector=selector)


def test_ambiguous_tone_field_cannot_be_replaced() -> None:
    source = _source()
    field = struct.pack("<II", 0x3C, 2) + b"A\0" + struct.pack("<I", 0x8000003C)
    document = parse_alarms(source[:-8] + field + source[-8:])
    assert not document.records[0].can_edit_tone
    assert write_alarms(document) == document.source_bytes
    with pytest.raises(iPodDBWriteError):
        update_alarm(document, 0, tone_name="New")


def test_forged_sound_capability_does_not_authorize_a_write() -> None:
    document = parse_alarms(_source())
    changed = replace(
        document,
        records=(replace(document.records[0], can_edit_tone=False, label="New"),),
    )
    with pytest.raises(iPodDBWriteError):
        write_alarms(changed)


@pytest.mark.parametrize(
    "source,name,notes,valid",
    (
        (b"", "", (), True),
        (b"Beep\n540 200\n676 400\n", "Beep", ((540, 200), (676, 400)), True),
        (b"\r\nName\r\n1 2\r\n", "Name", ((1, 2),), True),
        (b"Name\n1\n", "Name", (), False),
        (b"Name\n1\t2\n", "Name", (), False),
        (
            b"Name\n1 2tail\n-3 +4\n65537 65538\n",
            "Name",
            ((1, 2), (0, 0), (1, 2)),
            True,
        ),
        (b"Name\n1  2\n", "Name", ((1, 0),), True),
        (b"A" * 253 + b"\n1 2\n", "A" * 253, ((1, 2),), True),
        (b"A" * 254 + b"\n1 2\n", "", ((1, 2),), True),
        (b"A" * 254, "A" * 254, (), True),
        (b"Name\0" + b"1 2\0", "Name", ((1, 2),), True),
    ),
)
def test_tone_parser_matches_native_classic_and_nano3_vectors(
    source: bytes, name: str, notes: tuple[tuple[int, int], ...], valid: bool
) -> None:
    parsed = parse_alarm_tone(source, profile=PreferencesProfile.CLASSIC_120GB_2_0_1)
    assert parsed.source_bytes == source
    assert parsed.name == name
    assert parsed.valid is valid
    assert parsed.notes == tuple(AlarmToneNote(*note) for note in notes)
    assert parsed.selectable is (valid and bool(name))


def test_tone_parser_native_note_limit_and_utf8_qualification() -> None:
    assert len(parse_alarm_tone(b"Name\n" + b"1 2\n" * 1001).notes) == 1000
    malformed = parse_alarm_tone(b"\xff\n1 2\n")
    assert not malformed.valid and not malformed.selectable
    assert malformed.source_bytes == b"\xff\n1 2\n"


@pytest.mark.parametrize(
    "profile",
    (PreferencesProfile.NANO_4_1_0_4, NamedPreferencesProfile.NANO_5_1_0_2),
)
def test_nano45_native_parser_accepts_signs_with_unsigned_note_storage(
    profile: PreferencesProfile | NamedPreferencesProfile,
) -> None:
    data = b"Name\n-3 +4\n"
    parsed = parse_alarm_tone(data, profile=profile)
    assert parsed.notes == (AlarmToneNote(65533, 4),)
    assert parsed.selectable
    assert not parse_alarm_tone(data).selectable


@pytest.mark.parametrize(
    "profile,language,name",
    (
        (PreferencesProfile.CLASSIC_6_1_1_2, 3, "Signalton"),
        (PreferencesProfile.CLASSIC_120GB_2_0_1, 10, "ビープ音"),
        (PreferencesProfile.CLASSIC_UPDATER_35_2_0_4, 17, "嘟嘟声"),
        (PreferencesProfile.CLASSIC_UPDATER_38_2_0_5, 22, "sygnał"),
        (PreferencesProfile.NANO_3_1_1_3, 23, "Сигнал"),
        (PreferencesProfile.NANO_4_1_0_4, 4, "Signalton"),
        (PreferencesProfile.NANO_4_1_0_4, 1, "Beep"),
        (NamedPreferencesProfile.NANO_5_1_0_2, "pt-BR", "Bipe"),
        (NamedPreferencesProfile.NANO_5_1_0_2, "th-TH", "บี๊บ"),
        (NamedPreferencesProfile.NANO_5_1_0_2, "en-GB", "Beep"),
        (PreferencesProfile.NANO_4_1_0_4, 3, None),
        (PreferencesProfile.NANO_3_1_1_3, 2, None),
        (PreferencesProfile.NANO_3_1_1_3, True, None),
        (PreferencesProfile.NANO_3_1_1_3, None, None),
        (PreferencesProfile.STANDARD, 0, None),
        (NamedPreferencesProfile.NANO_4_1_0_4, "en-US", None),
        (NamedPreferencesProfile.NANO_6_1_2, "en-US", None),
        (NamedPreferencesProfile.NANO_5_1_0_2, "en_US", None),
    ),
)
def test_packaged_default_names_use_exact_firmware_language_domain(
    profile: PreferencesProfile | NamedPreferencesProfile,
    language: int | str | None,
    name: str | None,
) -> None:
    assert default_alarm_tone_name(profile, language) == name


def test_saved_binary_language_is_framed_before_default_name_lookup() -> None:
    source = bytearray(2960)
    struct.pack_into("<I", source, 0, 0x3E)
    struct.pack_into("<I", source, 0xAF8, 4)
    assert saved_alarm_tone_name(source, PreferencesProfile.NANO_4_1_0_4) == "Signalton"
    assert saved_alarm_tone_name(source, PreferencesProfile.NANO_3_1_1_3) is None
    assert saved_alarm_tone_name(source[:-1], PreferencesProfile.NANO_4_1_0_4) is None
    struct.pack_into("<I", source, 0xAF8, 0x10000004)
    assert saved_alarm_tone_name(source, PreferencesProfile.NANO_4_1_0_4) is None


@pytest.mark.parametrize(
    "general,name",
    (
        (b"<General><Language>de-DE</Language></General>", "Signalton"),
        (b"<General><Language>unknown</Language></General>", None),
        (b"<General><Language>de_DE</Language></General>", None),
        (b"<General><Language/></General>", None),
        (
            b"<General><Language>de-DE</Language><Language>en-US</Language></General>",
            None,
        ),
        (b"<General/><General><Language>de-DE</Language></General>", None),
        (b"<General><Language>de&#45;DE</Language></General>", None),
    ),
)
def test_saved_named_language_requires_one_plain_qualified_scalar(
    general: bytes, name: str | None
) -> None:
    source = b'<iPodSettings version="1.0">' + general + b"</iPodSettings>"
    assert saved_alarm_tone_name(source, NamedPreferencesProfile.NANO_5_1_0_2) == name
