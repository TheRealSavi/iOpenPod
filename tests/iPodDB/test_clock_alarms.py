"""Native-emitted Video and independently replayed Nano 1 Clock framing.

The 125-byte city record is emitted by original ARM serializers; the root pair
follows their collection writers. See alarms-legacy-firmware-2026-11-13.md.
The tests are standalone and require no sibling firmware lab or physical iPod.
"""

import struct
from dataclasses import replace

import pytest
from tests.iPodDB.alarm_fixtures import clock_field
from whenever import Time

from iPodDB.alarms.clock import (
    parse_clock_alarms,
    update_clock_alarm,
    write_clock_alarms,
)
from iPodDB.alarms.codec import parse_preferences_alarm, patch_preferences_alarm
from iPodDB.shared.errors import iPodDBWriteError

CITY = bytes.fromhex(
    "010000400200000004000000050000000200008003000000040000006d000000"
    "0300008014000000010000000114000080050000400600000004000000e00100"
    "0006000080070000000400000004000000070000801f00000004000000785634"
    "121f00008008000000040000001100000008000080050000c0010000c0"
)
GOLDEN = struct.pack("<I", 0x40000000) + CITY + struct.pack("<I", 0xC0000000)


def test_native_record_has_unaligned_minute_and_separate_city_identity() -> None:
    document = parse_clock_alarms(GOLDEN)
    assert not document.issues
    (alarm,) = document.records
    assert (alarm.region, alarm.city, alarm.daylight_saving) == (5, 109, 1)
    assert alarm.time == Time(8)
    assert (alarm.kind, alarm.selection, alarm.sound_selector) == (4, 0x12345678, 17)
    assert alarm.editable and alarm.enabled and alarm.can_edit_enabled
    assert write_clock_alarms(document) == GOLDEN
    result = write_clock_alarms(update_clock_alarm(document, 0, time=Time(23, 59, 48)))
    changed = {
        index
        for index, (old, new) in enumerate(zip(GOLDEN, result, strict=True))
        if old != new
    }
    assert changed <= set(range(65, 69))
    assert parse_clock_alarms(result).records[0].time == Time(23, 59)


def test_unknown_fields_nested_containers_and_multiple_clocks_survive() -> None:
    unknown = (
        struct.pack("<I", 0x40000044)
        + clock_field(6, b"opaque")
        + struct.pack("<I", 0xC0000044)
    )
    source = GOLDEN[:8] + unknown + GOLDEN[8:-4] + CITY + GOLDEN[-4:]
    document = parse_clock_alarms(source)
    assert len(document.records) == 2
    result = write_clock_alarms(update_clock_alarm(document, 1, time=Time(1, 30)))
    assert result[: 129 + len(unknown)] == source[: 129 + len(unknown)]
    assert parse_clock_alarms(result).records[0].time == Time(8)
    assert parse_clock_alarms(result).records[1].time == Time(1, 30)


@pytest.mark.parametrize(
    "source",
    (b"not clocks", GOLDEN[:-1], GOLDEN + b"x", GOLDEN[:40] + b"\xff" * 20),
)
def test_unqualified_sources_remain_opaque_and_byte_exact(source: bytes) -> None:
    document = parse_clock_alarms(source)
    assert document.issues and not document.records
    assert write_clock_alarms(document) == source


def test_duplicate_known_field_blocks_that_city_but_not_other_cities() -> None:
    source = (
        GOLDEN[:8]
        + clock_field(2, struct.pack("<I", 5))
        + GOLDEN[8:-4]
        + CITY
        + GOLDEN[-4:]
    )
    document = parse_clock_alarms(source)
    assert document.issues and not document.records[0].editable
    assert document.records[1].editable
    with pytest.raises(iPodDBWriteError):
        update_clock_alarm(document, 0, time=Time(9))
    result = write_clock_alarms(update_clock_alarm(document, 1, time=Time(9)))
    assert parse_clock_alarms(result).records[1].time == Time(9)


def test_duplicate_alarm_container_is_not_silently_selected() -> None:
    alarm = CITY[49:-4]
    source = GOLDEN[:-8] + alarm + GOLDEN[-8:]
    document = parse_clock_alarms(source)
    assert document.issues and not document.records[0].editable
    assert write_clock_alarms(document) == source


@pytest.mark.parametrize(
    "kind,enabled", ((0, True), (4, True), (8, False), (12, True), (0xFFF8, None))
)
def test_unknown_kind_is_preserved_without_masked_enable_guess(
    kind: int, enabled: bool | None
) -> None:
    source = bytearray(GOLDEN)
    struct.pack_into("<I", source, 81, kind)
    document = parse_clock_alarms(source)
    assert document.records[0].enabled is enabled
    result = write_clock_alarms(update_clock_alarm(document, 0, time=Time(12)))
    assert parse_clock_alarms(result).records[0].kind == kind


def test_public_dataclass_changes_cannot_invent_city_or_invalid_changes() -> None:
    document = parse_clock_alarms(GOLDEN)
    alarm = document.records[0]
    for changed in (
        replace(document, records=(alarm, alarm)),
        replace(document, records=()),
        replace(document, records=(replace(alarm, region=7),)),
        replace(document, records=(replace(alarm, kind=0),)),
        replace(document, records=(replace(alarm, source_offset=0),)),
        replace(document, records=(replace(alarm, minutes=1440),)),
    ):
        with pytest.raises(iPodDBWriteError):
            write_clock_alarms(changed)
    with pytest.raises(IndexError):
        update_clock_alarm(document, -1, time=Time(0))


def test_invalid_saved_minute_is_preserved_until_explicitly_repaired() -> None:
    source = bytearray(GOLDEN)
    struct.pack_into("<I", source, 65, 0xFFFFFFFF)
    document = parse_clock_alarms(source)
    assert document.records[0].time is None
    assert write_clock_alarms(document) == source
    repaired = write_clock_alarms(update_clock_alarm(document, 0, time=Time(0)))
    assert parse_clock_alarms(repaired).records[0].time == Time(0)


@pytest.mark.parametrize(
    "kind,selection,enabled,expected",
    (
        (0, 0, False, 8),
        (4, 17, False, 8),
        (8, 17, True, 4),
        (8, 0, True, 0),
        (8, 0xFFFFFFFF, True, 0),
        (8, 0x80000000, True, 0),
        (8, 0x7FFFFFFF, True, 4),
        (4, 0, True, 4),
        (8, 17, False, 8),
        (12, 0xFFFFFFFF, False, 8),
    ),
)
def test_enabled_edit_matches_native_signed_selection_and_preserves_other_bytes(
    kind: int, selection: int, enabled: bool, expected: int
) -> None:
    source = bytearray(GOLDEN)
    struct.pack_into("<I", source, 81, kind)
    struct.pack_into("<I", source, 113, selection)
    document = parse_clock_alarms(source)
    result = write_clock_alarms(update_clock_alarm(document, 0, enabled=enabled))
    wanted = bytearray(source)
    struct.pack_into("<I", wanted, 81, expected)
    assert result == wanted
    assert parse_clock_alarms(result).records[0].enabled is enabled


def test_unknown_kind_can_change_time_but_cannot_be_normalized_by_enable_edit() -> None:
    source = bytearray(GOLDEN)
    struct.pack_into("<I", source, 81, 0xFFF8)
    document = parse_clock_alarms(source)
    assert not document.records[0].can_edit_enabled
    with pytest.raises(iPodDBWriteError):
        update_clock_alarm(document, 0, enabled=False)
    updated = update_clock_alarm(document, 0, time=Time(7))
    assert parse_clock_alarms(write_clock_alarms(updated)).records[0].kind == 0xFFF8


def test_mini1_qualified_preferences_share_minute_bits_but_not_device_identity() -> (
    None
):
    source = bytearray(0xB3C)
    struct.pack_into("<I", source, 0, 0x16)
    struct.pack_into("<H", source, 0xB22, 0xD05A)
    document = parse_preferences_alarm(source, "mini1")
    assert document.time == Time(1, 30)
    result = patch_preferences_alarm(document, Time(8, 15))
    assert result[:0xB22] == source[:0xB22]
    assert result[0xB24:] == source[0xB24:]
    assert result[0xB22:0xB24] == struct.pack("<H", 0xD000 | 495)


@pytest.mark.parametrize("format", ("mini", "mini1"))
@pytest.mark.parametrize(
    "flags,enabled,expected",
    ((0xA5A0, False, 0xA5A8), (0xA5A4, False, 0xA5A8), (0xA5A8, True, 0xA5A0)),
)
def test_mini_zero_playlist_toggle_matches_native_and_preserves_other_flags(
    format: str, flags: int, enabled: bool, expected: int
) -> None:
    source = bytearray(0xB3C)
    struct.pack_into("<I", source, 0, 0x16)
    struct.pack_into("<H", source, 0xB18, flags)
    struct.pack_into("<H", source, 0xB22, 0xD05A)
    document = parse_preferences_alarm(source, format)
    assert document.can_edit_enabled
    result = patch_preferences_alarm(document, enabled=enabled)
    wanted = bytearray(source)
    struct.pack_into("<H", wanted, 0xB18, expected)
    assert result == wanted
    assert parse_preferences_alarm(result, format).enabled is enabled


@pytest.mark.parametrize("playlist,flags", ((123, 8), (0, 12)))
def test_mini_unknown_mode_or_saved_playlist_does_not_authorize_enable(
    playlist: int, flags: int
) -> None:
    source = bytearray(0xB3C)
    struct.pack_into("<I", source, 0, 0x16)
    struct.pack_into("<H", source, 0xB18, flags)
    struct.pack_into("<Q", source, 0xB24, playlist)
    document = parse_preferences_alarm(source, "mini")
    assert not document.can_edit_enabled
    with pytest.raises(iPodDBWriteError):
        patch_preferences_alarm(document, enabled=True)


def test_video_projection_is_not_a_mini_enable_setting() -> None:
    source = bytearray(0xB6C)
    struct.pack_into("<I", source, 0, 0x39)
    document = parse_preferences_alarm(source, "video")
    assert document.enabled is None and not document.can_edit_enabled
    with pytest.raises(iPodDBWriteError):
        patch_preferences_alarm(document, enabled=True)


# Original Nano1/Video sound menus emit these three fields, then serialize and
# reload them. Receipt: alarm-sounds-legacy-20261113-v6 (all five image inputs).
@pytest.mark.parametrize(
    "choice,mode,selector", ((-1, 0, 0xFFFFFFFF), (1, 4, 1), (3, 4, 3))
)
@pytest.mark.parametrize("enabled", (None, True, False))
def test_sound_choice_matches_native_wire_and_explicit_enable_intent(
    choice: int, mode: int, selector: int, enabled: bool | None
) -> None:
    document = parse_clock_alarms(GOLDEN)
    result = write_clock_alarms(
        update_clock_alarm(
            document, 0, time=Time(8, 15), sound_playlist_index=choice, enabled=enabled
        )
    )
    expected = bytearray(GOLDEN)
    struct.pack_into("<I", expected, 65, 495)
    struct.pack_into("<I", expected, 81, 8 if enabled is False else mode)
    struct.pack_into("<I", expected, 97, mode)
    struct.pack_into("<I", expected, 113, selector)
    assert result == expected
    after = parse_clock_alarms(result).records[0]
    assert (after.sound_mode, after.sound_selector) == (mode, selector)
    assert after.enabled is (enabled is not False)


def test_radio_is_observed_preserved_and_native_toggle_retains_saved_sound() -> None:
    source = bytearray(GOLDEN)
    struct.pack_into("<I", source, 81, 12)
    struct.pack_into("<I", source, 97, 12)
    struct.pack_into("<I", source, 113, 0xFFFFFFFF)
    document = parse_clock_alarms(source)
    assert document.records[0].enabled and document.records[0].can_edit_enabled
    disabled = update_clock_alarm(document, 0, enabled=False)
    reenabled = update_clock_alarm(disabled, 0, enabled=True)
    # Native toggle independently chooses the active mode from signed index;
    # it does not restore retained Radio. Preserve this distinction.
    after = parse_clock_alarms(write_clock_alarms(reenabled)).records[0]
    assert (after.kind, after.sound_mode, after.sound_selector) == (0, 12, 0xFFFFFFFF)


def test_reselecting_saved_sound_enables_and_explicit_choice_repairs_unknown_mode() -> (
    None
):
    first = update_clock_alarm(
        parse_clock_alarms(GOLDEN), 0, sound_playlist_index=3, enabled=False
    )
    second = update_clock_alarm(first, 0, sound_playlist_index=3)
    assert second.records[0].enabled
    source = bytearray(GOLDEN)
    struct.pack_into("<I", source, 81, 0xFFF8)
    repaired = update_clock_alarm(
        parse_clock_alarms(source), 0, sound_playlist_index=-1
    )
    assert repaired.records[0].kind == 0


@pytest.mark.parametrize("choice", (0, -2, 0x80000000, True))
def test_sound_choice_rejects_non_native_array_indices(choice: int) -> None:
    with pytest.raises(iPodDBWriteError):
        update_clock_alarm(parse_clock_alarms(GOLDEN), 0, sound_playlist_index=choice)


def test_sound_writer_rejects_incoherent_pairs_and_new_radio_selection() -> None:
    document = parse_clock_alarms(GOLDEN)
    original = document.records[0]
    for mode, selector, kind in ((0, 1, 0), (4, 0, 4), (12, 0xFFFFFFFF, 12), (4, 1, 0)):
        record = replace(original, kind=kind, selection=mode, sound_selector=selector)
        with pytest.raises(iPodDBWriteError):
            write_clock_alarms(replace(document, records=(record,)))
