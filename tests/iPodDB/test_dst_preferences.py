"""Authored DST file fixtures distinguish verified firmware formats and raw data."""

import struct

import pytest

from iPodDB.preferences import (
    DSTRule,
    DSTTableIssueCode,
    DSTTableProfile,
    DSTTransition,
    DSTWeek,
    parse_dst_table,
)
from iPodDB.shared.binary_struct import validate_binary_struct_definition

_CLASSIC201 = DSTTableProfile.CLASSIC_120GB_2_0_1
_LATER = (
    DSTTableProfile.CLASSIC_UPDATER_35_2_0_4,
    DSTTableProfile.CLASSIC_UPDATER_38_2_0_5,
)


def _row(city: int, enabled: int = 1, week: int = 2) -> bytes:
    return struct.pack(
        "<HBBB3sHHHH", city, enabled, 0, 6, b"\xa5\xff\x17", 3, week, 11, 1
    )


def _table() -> bytes:
    return b"".join(_row(city) for city in range(1, 206))


def test_shared_definition_reads_exact_fields_without_normalizing_bytes() -> None:
    validate_binary_struct_definition(DSTRule, supported_sizes=(16,))
    source = bytearray(_row(0, 255) + _table()[16:])
    document = parse_dst_table(source, profile=_CLASSIC201)
    source[0] = 1
    rule = document.rules[0]
    assert rule.city_id == 0  # Zero is searchable, not a terminator.
    assert rule.enabled_raw == 255 and rule.enabled
    assert rule.reserved == b"\xa5\xff\x17"
    assert rule.start == DSTTransition(3, 0, 2)
    assert rule.end == DSTTransition(11, 6, 1)
    assert document.complete and document.expected_rows == 205
    assert document.issues == ()
    assert document.prefix_bytes == document.unparsed_bytes == b""
    assert document.serialize() == _row(0, 255) + _table()[16:]


@pytest.mark.parametrize("profile", (_CLASSIC201, *_LATER))
@pytest.mark.parametrize("size", (0, 1, 2, 15, 16, 17, 3279, 3280, 3281, 3282, 3300))
def test_short_and_long_files_preserve_bytes_and_never_invent_rows(
    profile: DSTTableProfile, size: int
) -> None:
    prefix = b"\xff\x9a" if profile in _LATER else b""
    source = (prefix + _table() + b"opaque-tail" * 3)[:size]
    document = parse_dst_table(source, profile=profile)
    extent = len(prefix) + 3280
    expected_count = min(max(0, size - len(prefix)) // 16, 205)
    assert len(document.rules) == expected_count
    assert document.complete == (size >= extent)
    assert document.prefix_bytes == source[: len(prefix)]
    assert document.unparsed_bytes == source[len(prefix) + expected_count * 16 :]
    assert document.serialize() == source
    codes = {issue.code for issue in document.issues}
    assert (DSTTableIssueCode.INCOMPLETE in codes) == (size < extent)
    assert (DSTTableIssueCode.TRAILING_DATA in codes) == (size > extent)
    if document.rules:
        assert document.rules[0].city_id == 1


@pytest.mark.parametrize(
    "source",
    (b"", _table(), b"\x02\x00" + _table()),
    ids=("empty", "unprefixed", "prefixed"),
)
def test_unknown_profiles_are_opaque_regardless_of_length(source: bytes) -> None:
    document = parse_dst_table(source)
    assert document.rules == ()
    assert document.issues == ()
    assert document.expected_rows is None and not document.complete
    assert document.prefix_bytes == b""
    assert document.unparsed_bytes == document.serialize() == source


@pytest.mark.parametrize("profile", _LATER)
@pytest.mark.parametrize(
    "prefix",
    (b"\x00\x00", b"\x01\x00", b"\x00\x01", b"\xcd\x00", b"\x00\xcd", b"\xff\xff"),
)
def test_prefix_does_not_select_version_row_count_or_byte_order(
    profile: DSTTableProfile, prefix: bytes
) -> None:
    rows = _table()
    document = parse_dst_table(prefix + rows, profile=profile)
    assert document.prefix_bytes == prefix
    assert document.complete and document.expected_rows == len(document.rules) == 205
    assert document.issues == ()
    assert document.rules == parse_dst_table(rows, profile=_CLASSIC201).rules
    assert document.serialize() == prefix + rows


def test_duplicate_cities_and_disabled_rows_keep_order_without_narrowing_ids() -> None:
    document = parse_dst_table(
        _row(41, 0) + _row(41, 255) + _row(41, 1), profile=_CLASSIC201
    )
    assert [rule.enabled_raw for rule in document.rules_for_city(41)] == [0, 255, 1]
    assert document.rules_for_city(0x10029) == ()
    assert document.rules_for_city(-1) == ()
    assert [
        issue.row_index
        for issue in document.issues
        if issue.code is DSTTableIssueCode.DUPLICATE_CITY
    ] == [1, 2]


@pytest.mark.parametrize("profile", (_CLASSIC201, *_LATER))
def test_week_selectors_have_explicit_firmware_meanings(
    profile: DSTTableProfile,
) -> None:
    assert DSTTransition(3, 0, 1).week_occurrence(profile) is DSTWeek.FIRST
    assert DSTTransition(3, 0, 2).week_occurrence(profile) is DSTWeek.SECOND
    assert DSTTransition(3, 0, 3).week_occurrence(profile) is DSTWeek.THIRD
    assert DSTTransition(3, 0, 4).week_occurrence(profile) is (
        DSTWeek.LAST if profile is _CLASSIC201 else DSTWeek.FOURTH
    )
    assert DSTTransition(3, 0, 5).week_occurrence(profile) is (
        None if profile is _CLASSIC201 else DSTWeek.LAST
    )
    for transition in (
        DSTTransition(0, 0, 1),
        DSTTransition(13, 0, 1),
        DSTTransition(3, 7, 1),
        DSTTransition(3, 0, 0),
        DSTTransition(3, 0, 6),
    ):
        assert not transition.supported(profile)
    assert not DSTTransition(3, 0, 1).supported(DSTTableProfile.UNKNOWN)


@pytest.mark.parametrize("profile", (_CLASSIC201, *_LATER))
def test_unusual_active_rules_are_observations_instead_of_parse_errors(
    profile: DSTTableProfile,
) -> None:
    prefix = b"\x01\x00" if profile in _LATER else b""
    source = prefix + _row(41, 1, 5) + _row(42, 0, 65535) + _row(43, 1, 65535)
    document = parse_dst_table(source, profile=profile)
    assert document.serialize() == source
    assert [
        issue.row_index
        for issue in document.issues
        if issue.code is DSTTableIssueCode.UNUSUAL_TRANSITION
    ] == ([0, 2] if profile is _CLASSIC201 else [2])
