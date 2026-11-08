"""Native-emitted framing vectors plus lossless optional alarm edit boundaries.

GOLDEN is the unaligned UTF-8 record emitted independently by latest families
24/33/35/38 in the firmware lab's classic-alarm-20261106-v1/native-v7.json.
Receipt script SHA256: 548eed4720ce9d313877ebfb874ab730820ecfbc24ba82b366923d8465ce09c9.
Tests need neither that sibling lab nor any physical device.
"""

import struct
from dataclasses import replace

import pytest
from whenever import PlainDateTime, Time

from iPodDB.alarms import (
    parse_alarms,
    parse_preferences_alarm,
    patch_preferences_alarm,
    update_alarm,
    write_alarms,
)
from iPodDB.shared.errors import iPodDBWriteError

GOLDEN = bytes.fromhex(
    "3a0000400500004006000000040000001896e66a060000800700000004000000"
    "08000000070000803b00000004000000010000003b0000801f00000004000000"
    "030000001f0000800800000004000000ffffffff080000803c00000003000000"
    "c384003c000080050000c03a0000c0"
)


def _field(token: int, payload: bytes) -> bytes:
    return (
        struct.pack("<II", token, len(payload))
        + payload
        + struct.pack("<I", 0x80000000 | token)
    )


def test_native_utf8_unaligned_record_is_lossless_and_not_a_media_epoch() -> None:
    document = parse_alarms(GOLDEN)
    assert document.issues == ()
    (alarm,) = document.records
    assert alarm.scheduled_seconds == 1793496600
    assert alarm.scheduled == PlainDateTime(2026, 11, 1, 1, 30)
    assert alarm.repeat == 1
    assert alarm.label == "Ä"
    assert (alarm.control_word, alarm.selection, alarm.sound_selector) == (
        8,
        3,
        0xFFFFFFFF,
    )
    assert alarm.editable
    assert write_alarms(document) == GOLDEN


@pytest.mark.parametrize("raw", (0, 0xFFFFFFFF))
def test_all_native_date_words_survive_unrelated_repeat_edits(raw: int) -> None:
    source = GOLDEN[:16] + struct.pack("<I", raw) + GOLDEN[20:]
    original = parse_alarms(source)
    assert original.records[0].scheduled is not None
    assert write_alarms(original) == source
    result = write_alarms(update_alarm(original, 0, repeat_mode=4))
    assert result[:48] == source[:48]
    assert result[52:] == source[52:]
    assert parse_alarms(result).records[0].scheduled_seconds == raw


def test_patch_tracks_variable_offsets_and_preserves_unknown_nested_data() -> None:
    unknown = (
        struct.pack("<I", 0x40000041)
        + _field(0x44, b"opaque\x00\xff")
        + struct.pack("<I", 0xC0000041)
    )
    source = GOLDEN[:8] + unknown + _field(0x89, b"abc") + GOLDEN[8:]
    document = parse_alarms(source)
    result = write_alarms(
        update_alarm(
            document, 0, scheduled=PlainDateTime(2026, 3, 8, 2, 30), repeat_mode=2
        )
    )
    parsed = parse_alarms(result)
    assert parsed.records[0].scheduled == PlainDateTime(2026, 3, 8, 2, 30)
    assert parsed.records[0].repeat_mode == 2
    assert result[8 : 8 + len(unknown)] == unknown
    date_offset = 16 + len(unknown) + len(_field(0x89, b"abc"))
    repeat_offset = date_offset + 32
    changed = {
        index
        for index, (before, after) in enumerate(zip(source, result, strict=True))
        if before != after
    }
    assert changed <= set(range(date_offset, date_offset + 4)) | set(
        range(repeat_offset, repeat_offset + 4)
    )
    assert len(result) == len(source)


@pytest.mark.parametrize(
    "source",
    (
        b"",
        b"not an alarm",
        GOLDEN[:-1],
        GOLDEN + b"tail",
        GOLDEN[:12] + b"\xff" * 4 + GOLDEN[16:],
    ),
)
def test_malformed_sources_remain_opaque_and_byte_exact(source: bytes) -> None:
    document = parse_alarms(source)
    assert document.issues and not document.records
    assert write_alarms(document) == source


def test_duplicate_known_tokens_do_not_authorize_guessing_which_to_edit() -> None:
    source = GOLDEN[:8] + _field(6, struct.pack("<I", 123)) + GOLDEN[8:]
    document = parse_alarms(source)
    assert document.issues and not document.records[0].editable
    assert write_alarms(document) == source
    with pytest.raises(iPodDBWriteError):
        update_alarm(document, 0, repeat_mode=4)


def test_unknown_repeat_code_does_not_block_date_edit_or_get_normalized() -> None:
    source = GOLDEN[:48] + struct.pack("<I", 81) + GOLDEN[52:]
    result = write_alarms(
        update_alarm(parse_alarms(source), 0, scheduled=PlainDateTime(2027, 1, 1))
    )
    assert parse_alarms(result).records[0].repeat_mode == 81


def test_subsecond_coordinate_edit_floors_without_host_zone_resolution() -> None:
    result = update_alarm(
        parse_alarms(GOLDEN),
        0,
        scheduled=PlainDateTime(2026, 11, 1, 1, 30, nanosecond=999_999_999),
    )
    assert write_alarms(result) == GOLDEN


@pytest.mark.parametrize(
    "date", (PlainDateTime(1969, 12, 31), PlainDateTime(2107, 1, 1))
)
def test_out_of_native_range_is_an_edit_validation_error_only(
    date: PlainDateTime,
) -> None:
    document = parse_alarms(GOLDEN)
    with pytest.raises(iPodDBWriteError):
        update_alarm(document, 0, scheduled=date)
    assert write_alarms(document) == GOLDEN


def test_public_dataclass_replacement_cannot_invent_records_or_patch_other_fields() -> (
    None
):
    document = parse_alarms(GOLDEN)
    alarm = document.records[0]
    for changed in (
        replace(document, records=(alarm, alarm)),
        replace(document, records=(replace(alarm, label="New label"),)),
        replace(document, records=(replace(alarm, source_offset=0),)),
        replace(document, records=(replace(alarm, control_word=0),)),
    ):
        with pytest.raises(iPodDBWriteError):
            write_alarms(changed)
    with pytest.raises(iPodDBWriteError):
        update_alarm(document, 0, repeat_mode=7)
    with pytest.raises(IndexError):
        update_alarm(document, -1, repeat_mode=0)


@pytest.mark.parametrize(
    "format,size,version", (("mini", 2876, 0x16), ("video", 2924, 0x39))
)
def test_preferences_time_patch_preserves_high_bits_and_every_unrelated_byte(
    format: str, size: int, version: int
) -> None:
    source = bytearray((index * 31 + 17) % 256 for index in range(size))
    struct.pack_into("<I", source, 0, version)
    struct.pack_into("<H", source, 0xB22, 0xD05A)
    document = parse_preferences_alarm(source, format)
    assert document.time == Time(1, 30)
    assert document.editable
    result = patch_preferences_alarm(document, Time(8, 15, 59))
    assert result[:0xB22] == source[:0xB22]
    assert result[0xB24:] == source[0xB24:]
    assert int.from_bytes(result[0xB22:0xB24], "little") == 0xD000 | 495
    assert parse_preferences_alarm(result, format).time == Time(8, 15)
    source[0] ^= 1
    unknown = parse_preferences_alarm(source, format)
    assert unknown.time is None and not unknown.editable and unknown.issues
    with pytest.raises(iPodDBWriteError):
        patch_preferences_alarm(unknown, Time(12))


def test_corrupt_saved_minutes_are_observed_without_a_datetime_exception() -> None:
    source = bytearray(2924)
    struct.pack_into("<I", source, 0, 0x39)
    struct.pack_into("<H", source, 0xB22, 0xFFFF)
    document = parse_preferences_alarm(source, "video")
    assert document.time is None and document.raw_word == 0xFFFF
    repaired = patch_preferences_alarm(document, Time(0))
    assert parse_preferences_alarm(repaired, "video").raw_word == 0xF000
