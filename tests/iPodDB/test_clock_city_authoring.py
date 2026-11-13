"""Native city identities, creation defaults and lossless collection edits."""

import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iPodDB.alarm_fixtures import clock_field
from tests.iPodDB.test_clock_alarms import CITY, GOLDEN
from whenever import Time

from iPodDB.alarms import (
    CLOCK_CITIES,
    add_clock_alarm,
    clock_city,
    empty_clock_document,
    parse_clock_alarms,
    remove_clock_alarm,
    update_clock_alarm,
    write_clock_alarms,
)
from iPodDB.shared.errors import iPodDBWriteError


def test_native_city_catalog_and_all_wire_identities_roundtrip() -> None:
    assert len(CLOCK_CITIES) == 204
    assert len({(city.region, city.ordinal) for city in CLOCK_CITIES}) == 204
    assert clock_city(5, 109) is not None
    for city in CLOCK_CITIES:
        document = add_clock_alarm(empty_clock_document(), city, daylight_saving=True)
        record = parse_clock_alarms(write_clock_alarms(document)).records[0]
        assert clock_city(record.region, record.city) == city
        assert (
            record.minutes,
            record.kind,
            record.selection,
            record.sound_selector,
        ) == (0, 8, 0, 0)
        assert record.daylight_saving == 1
        assert len(document.source_bytes) == 133


def test_new_city_bytes_match_native_serializer_field_order_and_widths() -> None:
    city = clock_city(5, 109)
    assert city is not None
    created = add_clock_alarm(empty_clock_document(), city, daylight_saving=True)
    expected = bytearray(GOLDEN)
    for offset, value in ((65, 0), (81, 8), (97, 0), (113, 0)):
        struct.pack_into("<I", expected, offset, value)
    assert write_clock_alarms(created) == bytes(expected)


def test_append_duplicate_city_and_remove_exact_span_preserve_unknown_data() -> None:
    city = clock_city(5, 109)
    assert city is not None
    opaque = clock_field(0x77, b"future city metadata")
    source = GOLDEN[:8] + opaque + GOLDEN[8:-4] + opaque + GOLDEN[-4:]
    original = parse_clock_alarms(source)
    appended = add_clock_alarm(original, city, daylight_saving=False)
    assert appended.source_bytes[: len(source) - 4] == source[:-4]
    assert len(appended.records) == 2
    assert write_clock_alarms(remove_clock_alarm(appended, 1)) == source
    removed_first = remove_clock_alarm(appended, 0)
    assert len(removed_first.records) == 1
    assert opaque in removed_first.source_bytes
    assert removed_first.records[0].daylight_saving == 0


def test_remove_last_city_keeps_empty_native_container_and_can_add_again() -> None:
    empty = remove_clock_alarm(parse_clock_alarms(GOLDEN), 0)
    assert empty == empty_clock_document()
    again = add_clock_alarm(empty, CLOCK_CITIES[0], daylight_saving=False)
    assert len(again.records) == 1


def test_manual_dst_change_only_patches_its_single_saved_byte() -> None:
    changed = update_clock_alarm(parse_clock_alarms(GOLDEN), 0, daylight_saving=False)
    expected = bytearray(GOLDEN)
    expected[48] = 0
    assert write_clock_alarms(changed) == expected
    edited = update_clock_alarm(
        changed, 0, time=Time(6, 30), sound_playlist_index=-1, enabled=False
    )
    assert (
        edited.records[0].minutes,
        edited.records[0].kind,
        edited.records[0].daylight_saving,
    ) == (390, 8, 0)


def test_unknown_city_is_preserved_and_invalid_authoring_is_rejected() -> None:
    assert clock_city(99, 99) is None
    city = replace(CLOCK_CITIES[0], ordinal=9999)
    with pytest.raises(iPodDBWriteError, match="catalog"):
        add_clock_alarm(empty_clock_document(), city, daylight_saving=False)
    for source in (GOLDEN[:-1], GOLDEN[:4] + CITY[:4] + GOLDEN[-4:]):
        with pytest.raises((iPodDBWriteError, ValueError)):
            add_clock_alarm(
                parse_clock_alarms(source), CLOCK_CITIES[0], daylight_saving=False
            )


def test_empty_file_stays_exact_until_explicit_city_creation() -> None:
    document = parse_clock_alarms(b"")
    assert not document.issues and not document.records
    assert write_clock_alarms(document) == b""
    added = add_clock_alarm(document, CLOCK_CITIES[0], daylight_saving=False)
    assert added.records[0].city == CLOCK_CITIES[0].ordinal


def test_all_new_city_bytes_match_original_firmware_fixture() -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/alarms/native_clock_cities.json"
        ).read_text(encoding="utf-8")
    )
    for native in fixture["cities"]:
        city = clock_city(native["region"], native["ordinal"])
        assert city is not None and city.name == native["name"]
        actual = write_clock_alarms(
            add_clock_alarm(empty_clock_document(), city, daylight_saving=False)
        )
        assert actual[4:-4] == bytes.fromhex(native["record_hex"])
