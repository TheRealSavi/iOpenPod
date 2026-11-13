"""New tone files use the common native syntax, including real rests."""

import hashlib
import json
from pathlib import Path

import pytest

from iPodDB.alarms import AlarmToneNote, create_alarm_tone, parse_alarm_tone
from iPodDB.preferences import NamedPreferencesProfile, PreferencesProfile


def test_native_execution_receipt_vectors_are_preserved() -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/alarms/native_tone_authoring.json"
        ).read_text(encoding="utf-8")
    )
    for case in fixture["cases"]:
        source = case["payload_utf8"].encode("utf-8")
        assert hashlib.sha256(source).hexdigest() == case["sha256"]
        notes = tuple(
            AlarmToneNote(frequency, duration) for frequency, duration in case["notes"]
        )
        parsed = parse_alarm_tone(source)
        assert (
            parsed.selectable and parsed.name == case["name"] and parsed.notes == notes
        )
        # Reads retain native zero-duration operands; new notes require time.
        if all(note.duration_ms > 0 for note in notes):
            assert create_alarm_tone(case["name"], notes) == source


@pytest.mark.parametrize(
    "profile",
    [
        PreferencesProfile.CLASSIC_6_1_1_2,
        PreferencesProfile.CLASSIC_120GB_2_0_1,
        PreferencesProfile.CLASSIC_UPDATER_35_2_0_4,
        PreferencesProfile.CLASSIC_UPDATER_38_2_0_5,
        PreferencesProfile.NANO_3_1_1_3,
        PreferencesProfile.NANO_4_1_0_4,
        NamedPreferencesProfile.NANO_5_1_0_2,
    ],
)
def test_authored_phrase_round_trips_on_every_tone_family(
    profile: PreferencesProfile | NamedPreferencesProfile,
) -> None:
    notes = (
        AlarmToneNote(262, 400),
        AlarmToneNote(0, 100),
        AlarmToneNote(330, 500),
    ) * 7
    source = create_alarm_tone("朝のメロディ", notes)
    parsed = parse_alarm_tone(source, profile=profile)
    assert parsed.selectable and parsed.name == "朝のメロディ"
    assert parsed.notes == notes
    assert parsed.source_bytes == source
    assert sum(note.duration_ms for note in parsed.notes) == 7000


@pytest.mark.parametrize(
    "name",
    ["", " ", " Leading", "Trailing ", "New\nline", "Nul\0name", "a" * 254, "朝" * 85],
)
def test_names_cannot_change_the_native_line_framing(name: str) -> None:
    with pytest.raises(ValueError):
        create_alarm_tone(name, (AlarmToneNote(440, 500),))


def test_limits_are_bytes_and_native_words() -> None:
    source = create_alarm_tone("a" * 253, (AlarmToneNote(65535, 65535),) * 1000)
    parsed = parse_alarm_tone(source)
    assert parsed.selectable and len(parsed.notes) == 1000
    for notes in [
        (),
        (AlarmToneNote(1, 1),) * 1001,
        (AlarmToneNote(-1, 100),),
        (AlarmToneNote(65536, 100),),
        (AlarmToneNote(440, 0),),
        (AlarmToneNote(440, 65536),),
    ]:
        with pytest.raises(ValueError):
            create_alarm_tone("Test", notes)
