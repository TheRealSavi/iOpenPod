"""Qualified XML edits preserve everything outside the selected scalar span."""

from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from iPodDB.preferences import (
    NamedPreferencesProfile,
    available_named_preferences,
    inspect_named_preferences,
    named_preference_value,
    parse_named_preferences,
    read_named_clock_evidence,
    update_named_preferences,
    write_named_preferences,
)
from iPodDB.preferences.definitions import PreferenceKey
from iPodDB.shared.errors import iPodDBWriteError

if TYPE_CHECKING:
    from collections.abc import Mapping

CAPTURE = (
    b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>\r\n'
    b'<!-- retained formatting -->\r\n<iPodSettings version="1.0">\r\n'
    b"  <General><Brightness> 0040\t</Brightness><Clock>bad date</Clock></General>\r\n"
    b"  <Playback><SoundCheck>0</SoundCheck><Shuffle>albums</Shuffle></Playback>\r\n"
    b'  <Unknown attr="x&gt;y"><Date>\xe2\x98\x83</Date></Unknown>\r\n'
    b"</iPodSettings>\r\n"
)


@pytest.mark.parametrize(
    "profile",
    [
        item
        for item in NamedPreferencesProfile
        if item is not NamedPreferencesProfile.NANO_4_1_0_4
    ],
)
def test_qualified_settings_retain_unknown_clock_and_exact_bytes(
    profile: NamedPreferencesProfile,
) -> None:
    document = parse_named_preferences(CAPTURE, profile=profile)
    assert document.issues == ()
    assert write_named_preferences(document) == CAPTURE
    assert [item.key for item in available_named_preferences(document)] == [
        PreferenceKey.BRIGHTNESS,
        PreferenceKey.SOUND_CHECK,
    ]
    assert named_preference_value(document, PreferenceKey.BRIGHTNESS) == 40
    edited = update_named_preferences(
        document, {PreferenceKey.BRIGHTNESS: 100, PreferenceKey.SOUND_CHECK: 1}
    )
    assert edited.source_bytes == CAPTURE
    assert named_preference_value(edited, PreferenceKey.BRIGHTNESS) == 100
    assert write_named_preferences(edited) == CAPTURE.replace(b"0040", b"100").replace(
        b">0<", b">1<"
    )


def test_same_value_preserves_original_spelling() -> None:
    document = parse_named_preferences(
        CAPTURE, profile=NamedPreferencesProfile.NANO_6_1_2
    )
    assert (
        write_named_preferences(
            update_named_preferences(document, {PreferenceKey.BRIGHTNESS: 40})
        )
        == CAPTURE
    )


def test_scalar_edit_preserves_independent_clock_evidence_and_utf8_spans() -> None:
    profile = NamedPreferencesProfile.NANO_6_1_2
    source = (
        '<iPodSettings version="1.0"><Unknown note="x>y">☃</Unknown>'
        "<DateTime><TimeZone>&#52;1</TimeZone></DateTime>"
        "<General><Brightness>0040</Brightness></General></iPodSettings>"
    ).encode()
    clock = read_named_clock_evidence(source, profile=profile)
    assert clock.city_id == 41
    assert clock.raw_value == b"&#52;1"
    document = parse_named_preferences(source, profile=profile)
    changed = write_named_preferences(
        update_named_preferences(document, {PreferenceKey.BRIGHTNESS: 70})
    )
    assert changed == source.replace(b"0040", b"70")
    assert read_named_clock_evidence(changed, profile=profile) == clock
    observations = inspect_named_preferences(changed, profile=profile).observations
    assert next(row for row in observations if row.key == "brightness").known


def test_self_closing_field_remains_observable_without_a_writable_span() -> None:
    profile = NamedPreferencesProfile.NANO_6_1_2
    source = (
        b'<iPodSettings version="1.0"><General><Brightness/></General></iPodSettings>'
    )
    document = parse_named_preferences(source, profile=profile)
    assert available_named_preferences(document) == ()
    assert write_named_preferences(document) == source
    observations = inspect_named_preferences(source, profile=profile).observations
    assert next(row for row in observations if row.key == "brightness").known is False


@pytest.mark.parametrize(
    "profile",
    [
        item
        for item in NamedPreferencesProfile
        if item is not NamedPreferencesProfile.NANO_4_1_0_4
    ],
)
@pytest.mark.parametrize("value", [0, *range(100, 122)])
def test_named_eq_writes_native_ids_and_preserves_other_bytes(
    profile: NamedPreferencesProfile, value: int
) -> None:
    source = (
        b'<iPodSettings version="1.0"><Playback><EQ> 999\t</EQ>'
        b"<Shuffle>FUTURE</Shuffle></Playback><DateTime><TimeZone>205</TimeZone>"
        b"</DateTime></iPodSettings>"
    )
    document = parse_named_preferences(source, profile=profile)
    changed = update_named_preferences(document, {PreferenceKey.EQ_PRESET: value})
    assert named_preference_value(changed, PreferenceKey.EQ_PRESET) == value
    assert write_named_preferences(changed) == source.replace(
        b"999", str(value).encode()
    )


@pytest.mark.parametrize("value", [-1, 1, 22, 99, 122, True])
def test_named_eq_rejects_ui_indices_and_unqualified_ids(value: int) -> None:
    source = (
        b'<iPodSettings version="1.0"><Playback><EQ>0</EQ></Playback></iPodSettings>'
    )
    document = parse_named_preferences(
        source, profile=NamedPreferencesProfile.NANO_7_1_0_4
    )
    with pytest.raises(iPodDBWriteError):
        update_named_preferences(document, {PreferenceKey.EQ_PRESET: value})


def test_nano4_named_store_is_inspection_only_even_with_other_model_keys() -> None:
    source = CAPTURE.replace(b"<Playback>", b"<Playback><EQ>0</EQ>")
    document = parse_named_preferences(
        source, profile=NamedPreferencesProfile.NANO_4_1_0_4
    )
    assert available_named_preferences(document) == ()
    assert named_preference_value(document, PreferenceKey.BRIGHTNESS) is None
    assert write_named_preferences(document) == source
    with pytest.raises(iPodDBWriteError):
        update_named_preferences(document, {PreferenceKey.BRIGHTNESS: 40})
    with pytest.raises(iPodDBWriteError):
        write_named_preferences(
            replace(document, preference_edits=((PreferenceKey.EQ_PRESET, 0),))
        )


def test_structural_limits_keep_writer_nonblocking_and_unavailable() -> None:
    source = (
        b'<iPodSettings version="1.0">'
        + b"<x>" * 100
        + b"</x>" * 100
        + b"</iPodSettings>"
    )
    document = parse_named_preferences(
        source, profile=NamedPreferencesProfile.NANO_7_1_0_4
    )
    assert document.issues
    assert available_named_preferences(document) == ()
    assert write_named_preferences(document) == source


@pytest.mark.parametrize(
    "body",
    [
        b"<General><Brightness>4</Brightness><Brightness>8</Brightness></General>",
        b"<General><Brightness>4</Brightness></General><General/>",
        b"<General><Brightness><Value>40</Value></Brightness></General>",
        b"<General><Brightness><!-- value -->40</Brightness></General>",
        b"<General><Brightness><![CDATA[40]]></Brightness></General>",
        b'<General><Brightness value="40"/></General>',
        b"<General><Brightness/></General>",
        b'<General unknown="1"><Brightness>40</Brightness></General>',
    ],
)
def test_ambiguous_field_is_read_only_but_other_field_stays_editable(
    body: bytes,
) -> None:
    source = (
        b'<iPodSettings version="1.0">'
        + body
        + b"<Playback><SoundCheck>0</SoundCheck></Playback></iPodSettings>"
    )
    document = parse_named_preferences(
        source, profile=NamedPreferencesProfile.NANO_7_1_0_4
    )
    assert [item.key for item in available_named_preferences(document)] == [
        PreferenceKey.SOUND_CHECK
    ]
    assert document.issues
    with pytest.raises(iPodDBWriteError):
        update_named_preferences(document, {PreferenceKey.BRIGHTNESS: 30})
    assert write_named_preferences(
        update_named_preferences(document, {PreferenceKey.SOUND_CHECK: 1})
    ) == source.replace(b">0<", b">1<")


@pytest.mark.parametrize(
    "source",
    [
        b"",
        b"<iPodSettings>",
        b'<iPodSettings version="2.0"/>',
        b'<Preferences version="1.0"/>',
        b'<iPodSettings version="1.0" xmlns="unknown"/>',
        b'<!DOCTYPE iPodSettings [<!ENTITY x "40">]><iPodSettings version="1.0"><General><Brightness>&x;</Brightness></General></iPodSettings>',
        b'<!DOCTYPE iPodSettings SYSTEM "file:///secret"><iPodSettings version="1.0"/>',
        '<iPodSettings version="1.0"/>'.encode("utf-16"),
        '<iPodSettings version="1.0"/>'.encode("utf-16-le"),
    ],
)
def test_unqualified_xml_retained_read_only_without_raising(source: bytes) -> None:
    document = parse_named_preferences(
        source, profile=NamedPreferencesProfile.NANO_UPDATER_39_1_1_2
    )
    assert document.issues
    assert available_named_preferences(document) == ()
    assert write_named_preferences(document) == source


@pytest.mark.parametrize("value", [-1, 101, True, 2**32])
def test_invalid_brightness_rejected_at_update_and_publication(value: int) -> None:
    document = parse_named_preferences(
        CAPTURE, profile=NamedPreferencesProfile.NANO_6_1_2
    )
    with pytest.raises(iPodDBWriteError):
        update_named_preferences(document, {PreferenceKey.BRIGHTNESS: value})
    with pytest.raises(iPodDBWriteError):
        write_named_preferences(
            replace(document, preference_edits=((PreferenceKey.BRIGHTNESS, value),))
        )


def test_missing_nodes_are_never_synthesized() -> None:
    source = b'<iPodSettings version="1.0"><Unknown>1</Unknown></iPodSettings>'
    document = parse_named_preferences(
        source, profile=NamedPreferencesProfile.NANO_6_1_2
    )
    assert available_named_preferences(document) == ()
    with pytest.raises(iPodDBWriteError):
        update_named_preferences(document, {PreferenceKey.SOUND_CHECK: 1})
    assert write_named_preferences(document) == source


@pytest.mark.parametrize(
    "value", [b"101", b"-1", b"broken", b"4294967296", b"9" * 5000]
)
def test_unknown_existing_value_requires_explicit_replacement(value: bytes) -> None:
    source = CAPTURE.replace(b"0040", value)
    document = parse_named_preferences(
        source, profile=NamedPreferencesProfile.NANO_6_1_2
    )
    assert write_named_preferences(document) == source
    assert write_named_preferences(
        update_named_preferences(document, {PreferenceKey.BRIGHTNESS: 40})
    ) == CAPTURE.replace(b"0040", b"40")


def test_duplicate_injected_edits_are_rejected() -> None:
    document = parse_named_preferences(
        CAPTURE, profile=NamedPreferencesProfile.NANO_6_1_2
    )
    forged = replace(
        document,
        preference_edits=(
            (PreferenceKey.SOUND_CHECK, 0),
            (PreferenceKey.SOUND_CHECK, 1),
        ),
    )
    with pytest.raises(iPodDBWriteError):
        write_named_preferences(forged)


def test_mutable_capture_is_snapshotted() -> None:
    source = bytearray(CAPTURE)
    document = parse_named_preferences(
        source, profile=NamedPreferencesProfile.NANO_6_1_2
    )
    source[:] = b"changed"
    assert type(document.source_bytes) is bytes
    assert write_named_preferences(document) == CAPTURE


def test_whitespace_only_scalar_keeps_whitespace_once() -> None:
    source = CAPTURE.replace(b" 0040\t", b" \r\n\t")
    document = parse_named_preferences(
        source, profile=NamedPreferencesProfile.NANO_6_1_2
    )
    changed = update_named_preferences(document, {PreferenceKey.BRIGHTNESS: 20})
    output = write_named_preferences(changed)
    assert output == source.replace(b" \r\n\t</Brightness>", b" \r\n\t20</Brightness>")
    assert (
        named_preference_value(
            parse_named_preferences(output, profile=document.profile),
            PreferenceKey.BRIGHTNESS,
        )
        == 20
    )


@pytest.mark.parametrize(
    "changes", [{"brightness": 20}, {PreferenceKey.BRIGHTNESS: True}]
)
def test_incoming_edit_types_cannot_alias_existing_enum_key(changes: object) -> None:
    document = update_named_preferences(
        parse_named_preferences(CAPTURE, profile=NamedPreferencesProfile.NANO_6_1_2),
        {PreferenceKey.BRIGHTNESS: 30},
    )
    with pytest.raises(iPodDBWriteError):
        update_named_preferences(document, cast("Mapping[PreferenceKey, int]", changes))


@pytest.mark.parametrize("invalid", ["text", None, 123])
def test_parser_requires_bytes(invalid: object) -> None:
    with pytest.raises(TypeError):
        parse_named_preferences(
            cast("bytes", invalid), profile=NamedPreferencesProfile.NANO_6_1_2
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"source_bytes": bytearray(CAPTURE)},
        {"source_bytes": "text"},
        {"profile": "nano_6_1_2"},
        {"profile": None},
    ],
)
def test_writer_rejects_forged_document_even_without_edits(
    changes: dict[str, object],
) -> None:
    document = parse_named_preferences(
        CAPTURE, profile=NamedPreferencesProfile.NANO_6_1_2
    )
    forged = (
        replace(document, source_bytes=cast("bytes", changes["source_bytes"]))
        if "source_bytes" in changes
        else replace(
            document, profile=cast("NamedPreferencesProfile", changes["profile"])
        )
    )
    assert available_named_preferences(forged) == ()
    with pytest.raises(iPodDBWriteError):
        write_named_preferences(forged)


@pytest.mark.parametrize(
    "profile",
    [
        item
        for item in NamedPreferencesProfile
        if item is not NamedPreferencesProfile.NANO_4_1_0_4
    ],
)
@pytest.mark.parametrize("raw", [b" 1 ", b"\t0\r\n", b"\n\t"])
def test_authored_sound_check_does_not_retain_native_significant_whitespace(
    profile: NamedPreferencesProfile, raw: bytes
) -> None:
    source = CAPTURE.replace(
        b"<SoundCheck>0</SoundCheck>", b"<SoundCheck>" + raw + b"</SoundCheck>"
    )
    document = parse_named_preferences(source, profile=profile)
    assert named_preference_value(document, PreferenceKey.SOUND_CHECK) is None
    assert write_named_preferences(document) == source
    edited = update_named_preferences(document, {PreferenceKey.SOUND_CHECK: 1})
    assert write_named_preferences(edited) == CAPTURE.replace(
        b"<SoundCheck>0</SoundCheck>", b"<SoundCheck>1</SoundCheck>"
    )
