"""Native Alarm constructors, toggle routing and lossless collection edits."""

import struct
from dataclasses import replace

import pytest
from whenever import PlainDateTime

from iPodDB.alarms.codec import (
    MAX_ALARM_BYTES,
    add_alarm,
    empty_alarm_document,
    parse_alarms,
    remove_alarm,
    update_alarm,
    write_alarms,
)
from iPodDB.shared.errors import iPodDBWriteError

# Independently emitted by the Nano4 and Nano5 native record serializer probes.
DEFAULT_RECORD = bytes.fromhex(
    "3a0000400500004006000000040000001896e66a060000800700000004000000"
    "08000000070000803b00000004000000010000003b0000801f00000004000000"
    "030000001f0000800800000004000000ffffffff080000803c00000001000000"
    "003c000080050000c03a0000c0"
)


def test_create_uses_native_constructor_defaults_and_emitted_framing() -> None:
    created = add_alarm(
        empty_alarm_document(),
        scheduled=PlainDateTime(2026, 11, 1, 1, 30),
        repeat_mode=1,
    )
    assert write_alarms(created) == DEFAULT_RECORD
    assert created.records[0].enabled is True
    assert created.records[0].can_edit_enabled
    assert (created.records[0].selection, created.records[0].label) == (3, "")


@pytest.mark.parametrize("selector,expected", ((0xFFFFFFFF, 8), (0, 4), (42, 4)))
def test_enable_uses_native_selector_gate_and_preserves_other_bytes(
    selector: int, expected: int
) -> None:
    source = bytearray(DEFAULT_RECORD)
    struct.pack_into("<I", source, 80, selector)
    document = parse_alarms(source)
    disabled = update_alarm(document, 0, enabled=False)
    assert disabled.records[0].enabled is False
    enabled = update_alarm(parse_alarms(write_alarms(disabled)), 0, enabled=True)
    assert enabled.records[0].control_word == expected
    result = write_alarms(enabled)
    assert result[:32] == source[:32]
    assert result[36:] == source[36:]


def test_unknown_control_cannot_be_overwritten_but_date_remains_editable() -> None:
    source = bytearray(DEFAULT_RECORD)
    struct.pack_into("<I", source, 32, 0x40000008)
    document = parse_alarms(source)
    assert document.records[0].enabled is True
    assert not document.records[0].can_edit_enabled
    with pytest.raises(iPodDBWriteError):
        update_alarm(document, 0, enabled=False)
    changed = update_alarm(document, 0, scheduled=PlainDateTime(2027, 1, 1))
    assert write_alarms(changed)[32:36] == source[32:36]


def test_label_selection_patches_index_without_changing_retained_sound_name() -> None:
    document = parse_alarms(DEFAULT_RECORD)
    assert document.records[0].can_edit_label
    changed = update_alarm(document, 0, label_index=22)
    result = write_alarms(changed)
    assert result[:64] == DEFAULT_RECORD[:64]
    assert result[68:] == DEFAULT_RECORD[68:]
    assert parse_alarms(result).records[0].selection == 22
    unknown = bytearray(DEFAULT_RECORD)
    struct.pack_into("<I", unknown, 64, 0xFFFFFFFF)
    original = parse_alarms(unknown)
    assert write_alarms(original) == unknown
    assert write_alarms(update_alarm(original, 0, label_index=3)) == DEFAULT_RECORD
    created = add_alarm(
        empty_alarm_document(), scheduled=PlainDateTime(2027, 1, 1), label_index=12
    )
    assert created.records[0].selection == 12


@pytest.mark.parametrize("label", (-1, 23, True))
def test_label_authoring_rejects_non_native_indices(label: int) -> None:
    document = parse_alarms(DEFAULT_RECORD)
    with pytest.raises(iPodDBWriteError):
        update_alarm(document, 0, label_index=label)
    with pytest.raises(iPodDBWriteError):
        add_alarm(document, scheduled=PlainDateTime(2027, 1, 1), label_index=label)


def test_insert_and_remove_preserve_unknown_siblings_and_remaining_records() -> None:
    unknown = struct.pack("<III", 0x91, 3, 0x00636261)[:11] + struct.pack(
        "<I", 0x80000091
    )
    source = DEFAULT_RECORD[:-4] + unknown + DEFAULT_RECORD[4:]
    original = parse_alarms(source)
    assert len(original.records) == 2
    added = add_alarm(original, scheduled=PlainDateTime(2027, 1, 1), enabled=False)
    assert len(added.records) == 3
    assert not added.records[2].enabled
    assert write_alarms(added).startswith(source[:-4])
    assert write_alarms(remove_alarm(added, 2)) == source
    removed_first = remove_alarm(original, 0)
    assert write_alarms(removed_first) == source[:4] + unknown + DEFAULT_RECORD[4:]
    assert write_alarms(remove_alarm(parse_alarms(DEFAULT_RECORD), 0)) == write_alarms(
        empty_alarm_document()
    )


@pytest.mark.parametrize("source", (b"", DEFAULT_RECORD[:-1], DEFAULT_RECORD + b"tail"))
def test_structural_edits_reject_opaque_framing(source: bytes) -> None:
    document = parse_alarms(source)
    with pytest.raises(iPodDBWriteError):
        add_alarm(document, scheduled=PlainDateTime(2027, 1, 1))
    with pytest.raises(iPodDBWriteError):
        remove_alarm(document, 0)


def test_structural_edits_reject_forged_source_extents() -> None:
    document = parse_alarms(DEFAULT_RECORD)
    forged = replace(
        document,
        records=(replace(document.records[0], source_end=len(DEFAULT_RECORD)),),
    )
    with pytest.raises(iPodDBWriteError):
        remove_alarm(forged, 0)


@pytest.mark.parametrize("index", (-1, 1, True))
def test_remove_rejects_invalid_index(index: int) -> None:
    with pytest.raises(IndexError):
        remove_alarm(parse_alarms(DEFAULT_RECORD), index)


@pytest.mark.parametrize("mode", (-1, 7, True))
def test_new_alarm_rejects_unknown_repeat_codes(mode: int) -> None:
    with pytest.raises(iPodDBWriteError):
        add_alarm(
            empty_alarm_document(),
            scheduled=PlainDateTime(2027, 1, 1),
            repeat_mode=mode,
        )


def test_new_alarm_obeys_the_existing_resource_bound() -> None:
    payload = b"x" * (MAX_ALARM_BYTES - 20)
    source = (
        struct.pack("<III", 0x4000003A, 0x91, len(payload))
        + payload
        + struct.pack("<II", 0x80000091, 0xC000003A)
    )
    document = parse_alarms(source)
    assert not document.issues
    with pytest.raises(iPodDBWriteError):
        add_alarm(document, scheduled=PlainDateTime(2027, 1, 1))
