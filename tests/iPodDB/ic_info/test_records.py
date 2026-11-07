"""Small synthetic record fixtures; no firmware or captured account data."""

from dataclasses import replace
from struct import pack

import pytest

from iPodDB.ic_info.records import Record, inspect_store, parse_records, write_records

GUID = bytes.fromhex("0123456789abcdef")


def test_unknown_records_and_reserved_words_round_trip_exactly() -> None:
    leaf = pack(">I4sIII", 25, b"\xff???", 99, 0, 0xABCDEF01) + b"\x00test"
    data = bytes(12) + pack(">I4sIII", 45, b"sean", 7, 1, 42) + leaf
    assert write_records(parse_records(data)) == data


@pytest.mark.parametrize("mutation", ["prefix", "size", "count", "trailing", "root"])
def test_malformed_records_fail(mutation: str) -> None:
    data = bytearray(
        write_records(Record(b"sean", children=(Record(b"vers", payload=b"1234"),)))
    )
    if mutation == "prefix":
        data[0] = 1
    elif mutation == "size":
        data[12:16] = (19).to_bytes(4, "big")
    elif mutation == "count":
        data[24:28] = (2).to_bytes(4, "big")
    elif mutation == "root":
        data[16:20] = b"nope"
    else:
        data += b"trailing"
    with pytest.raises(ValueError):
        parse_records(bytes(data))


def test_extra_child_bytes_are_rejected_even_with_valid_parent_bounds() -> None:
    root = Record(b"sean", children=(Record(b"aaaa"), Record(b"bbbb")))
    data = bytearray(write_records(root))
    data[24:28] = (1).to_bytes(4, "big")
    with pytest.raises(ValueError, match="unclaimed"):
        parse_records(bytes(data))


def test_rebuilt_sizes_and_counts_after_nested_addition() -> None:
    root = Record(b"sean", children=(Record(b"grup", children=(Record(b"head"),)),))
    group = root.child(b"grup")
    changed = root.replace_child(
        replace(
            group,
            children=(
                *group.children,
                Record(b"user", children=(Record(b"valu", payload=b"new"),)),
            ),
        )
    )
    data = write_records(changed)
    assert len(data) == 115
    assert parse_records(data) == changed
    assert int.from_bytes(data[12:16], "big") == len(data) - 12


def test_deep_and_oversized_trees_fail() -> None:
    nested = Record(b"leaf")
    for _ in range(18):
        nested = Record(b"sean", children=(nested,))
    with pytest.raises(ValueError, match="nesting"):
        write_records(nested)
    with pytest.raises(ValueError, match="limit"):
        write_records(Record(b"sean", payload=bytes(0x80000)))


def test_group_guid_is_checked() -> None:
    root = Record(
        b"sean",
        children=(
            Record(
                b"grup",
                children=(
                    Record(b"head", children=(Record(b"guid", 1, payload=GUID),)),
                ),
            ),
        ),
    )
    assert inspect_store(root, GUID).guid == GUID
    with pytest.raises(ValueError, match="GUID"):
        inspect_store(root, bytes(8))


def test_ambiguous_singleton_is_not_silently_selected() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        Record(b"head", children=(Record(b"guid"), Record(b"guid"))).child(b"guid")
