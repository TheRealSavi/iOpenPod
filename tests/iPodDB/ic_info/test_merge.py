"""Merge identity, preservation, conflict and idempotence contracts."""

from dataclasses import replace

import pytest

from iPodDB.ic_info.merge import merge_prepared_stores
from iPodDB.ic_info.records import (
    Record,
    Store,
    inspect_store,
    parse_records,
    write_records,
)

GUID = bytes.fromhex("0123456789abcdef")


def key(identifier: int, payload: bytes = b"original") -> Record:
    return Record(
        b"key ",
        identifier,
        children=(
            Record(b"type", 1, payload=bytes(4)),
            Record(b"valu", 1, payload=payload.ljust(16, b"\0")),
            Record(b"sign", 1),
        ),
    )


def account(
    identifier: int, *keys: Record, session: bytes = bytes(128), version: int = 0x10101
) -> Record:
    return Record(
        b"user",
        identifier,
        reserved=77,
        children=(
            Record(b"vers", 1, payload=version.to_bytes(4, "big")),
            Record(b"sess", 1, payload=session),
            Record(b"dval", payload=b"retained metadata"),
            *keys,
            Record(b"unkn", payload=b"account extension"),
        ),
    )


def store(*accounts: Record, guid: bytes = GUID) -> Store:
    return inspect_store(
        Record(
            b"sean",
            reserved=99,
            children=(
                Record(b"vers", payload=b"tree"),
                Record(
                    b"grup",
                    children=(
                        Record(b"head", children=(Record(b"guid", 1, payload=guid),)),
                        *accounts,
                        Record(b"tail", payload=b"retained tail"),
                    ),
                ),
                Record(b"unkn", payload=b"root extension"),
            ),
        ),
        guid,
    )


def test_incoming_conflict_wins_unrelated_records_survive_and_repeated_merge_is_noop() -> (
    None
):
    destination = store(account(1, key(1), key(2)), account(2, key(1)))
    incoming = store(account(1, key(1, b"replacement"), key(3)), account(3, key(1)))
    merged = merge_prepared_stores(destination, incoming)
    assert (merged.added_keys, merged.replaced_keys, merged.unchanged_keys) == (2, 1, 0)
    result = merged.store
    assert [row.record.identifier for row in result.accounts] == [1, 2, 3]
    assert [row.identifier for row in result.accounts[0].keys] == [1, 2, 3]
    assert result.accounts[0].keys[0] == key(1, b"replacement")
    assert result.accounts[0].keys[1] == destination.accounts[0].keys[1]
    assert result.accounts[1] == destination.accounts[1]
    assert result.root.child(b"unkn") == destination.root.child(b"unkn")
    assert result.group.child(b"tail") == destination.group.child(b"tail")
    assert result.accounts[0].record.child(b"dval") == destination.accounts[
        0
    ].record.child(b"dval")
    data = write_records(result.root)
    assert parse_records(data) == result.root
    again = merge_prepared_stores(result, incoming)
    assert again.store == result
    assert (again.added_keys, again.replaced_keys, again.unchanged_keys) == (0, 0, 3)


def test_equal_values_with_different_selectors_remain_addressable() -> None:
    merged = merge_prepared_stores(store(account(1, key(1))), store(account(1, key(2))))
    assert len(merged.store.accounts[0].keys) == 2


@pytest.mark.parametrize("changed", ["session", "version"])
def test_unreconciled_account_context_is_rejected(changed: str) -> None:
    incoming = (
        account(1, key(2), session=b"x" * 128)
        if changed == "session"
        else account(1, key(2), version=0x10001)
    )
    with pytest.raises(ValueError, match="reconciled"):
        merge_prepared_stores(store(account(1, key(1))), store(incoming))


def test_different_device_groups_rejected() -> None:
    with pytest.raises(ValueError, match="different devices"):
        merge_prepared_stores(store(), store(guid=bytes(8)))


def test_duplicate_account_or_key_selectors_rejected() -> None:
    with pytest.raises(ValueError, match=r"Duplicate.*account"):
        store(account(1, key(1)), account(1, key(2)))
    with pytest.raises(ValueError, match=r"Duplicate.*key"):
        store(account(1, key(1), key(1)))


def test_existing_unknown_key_kind_and_payload_are_preserved() -> None:
    unknown = key(9, b"unfamiliar payload")
    unknown = unknown.replace_child(
        replace(unknown.child(b"type"), payload=(999).to_bytes(4, "big"))
    )
    destination = store(account(1, unknown))
    merged = merge_prepared_stores(destination, store(account(1, key(1))))
    assert merged.store.accounts[0].keys[0] == unknown


def test_replaced_key_retains_unknown_destination_metadata() -> None:
    previous = key(1)
    extension = Record(b"more", reserved=123, payload=b"unknown")
    previous = replace(previous, reserved=456, children=(*previous.children, extension))
    incoming = store(account(1, key(1, b"replacement")))
    result = merge_prepared_stores(store(account(1, previous)), incoming)
    merged = result.store.accounts[0].keys[0]
    assert merged.reserved == 456
    assert merged.child(b"more") == extension
    assert merged.child(b"valu") == key(1, b"replacement").child(b"valu")
    again = merge_prepared_stores(result.store, incoming)
    assert again.store == result.store
    assert again.unchanged_keys == 1


def test_malformed_known_existing_value_is_rejected() -> None:
    malformed = key(1)
    malformed = malformed.replace_child(
        replace(malformed.child(b"valu"), payload=b"bad")
    )
    with pytest.raises(ValueError, match="sixteen"):
        store(account(1, malformed))
