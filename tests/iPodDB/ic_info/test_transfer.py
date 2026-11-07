"""Standalone conversion/merge using tiny synthetic stores and real codecs."""

from dataclasses import replace

import pytest

from iPodDB.ic_info import transfer_and_merge
from iPodDB.ic_info.aes import ecb_cipher
from iPodDB.ic_info.binding import unwrap_value, wrap_value
from iPodDB.ic_info.envelope import decode_envelope, encode_envelope
from iPodDB.ic_info.records import (
    Account,
    Record,
    Store,
    inspect_store,
    key_kind,
    parse_records,
    write_records,
)
from iPodDB.ic_info.sessions import decode_session, encode_session

SOURCE_GUID = bytes.fromhex("0001020304050607")
TARGET_GUID = bytes.fromhex("1011121314151617")
SOURCE_SESSION = bytes(range(16))
TARGET_SESSION = bytes(range(16, 32))
ACCOUNT_VERSION = 0x10101
KeySpec = tuple[int, int, bytes]


def account(
    identifier: int,
    keys: tuple[KeySpec, ...],
    *,
    guid: bytes,
    session: bytes,
    family: int,
) -> Record:
    records: list[Record] = []
    for selector, kind, clear in keys:
        value = (
            ecb_cipher(session).encrypt(clear)
            if kind == 2
            else wrap_value(
                clear, session, guid, identifier, selector, ACCOUNT_VERSION, kind
            )
        )
        records.append(
            Record(
                b"key ",
                selector,
                reserved=41,
                children=(
                    Record(b"type", identifier=1, payload=kind.to_bytes(4, "big")),
                    Record(b"valu", identifier=1, payload=value),
                    Record(b"sign", identifier=1),
                ),
            )
        )
    return Record(
        b"user",
        identifier,
        reserved=29,
        children=(
            Record(b"vers", identifier=1, payload=ACCOUNT_VERSION.to_bytes(4, "big")),
            Record(b"sess", identifier=1, payload=encode_session(session, family)),
            Record(
                b"meta", identifier=3, reserved=19, payload=b"retain account metadata"
            ),
            *records,
        ),
    )


def store(guid: bytes, *users: Record, version: int = 0x60002) -> bytes:
    return encode_envelope(
        write_records(
            Record(
                b"sean",
                identifier=1,
                reserved=71,
                children=(
                    Record(b"root", payload=b"retain root extension"),
                    Record(
                        b"grup",
                        identifier=1,
                        reserved=81,
                        children=(
                            Record(
                                b"head",
                                identifier=1,
                                children=(Record(b"guid", identifier=1, payload=guid),),
                            ),
                            *users,
                            Record(
                                b"tail",
                                identifier=1,
                                reserved=11,
                                payload=b"retain group tail",
                            ),
                        ),
                    ),
                ),
            )
        ),
        guid,
        version,
    )


def decode(blob: bytes, guid: bytes) -> Store:
    _, clear = decode_envelope(blob, guid)
    return inspect_store(parse_records(clear), guid)


def selected_account(decoded: Store, identifier: int) -> Account:
    return next(row for row in decoded.accounts if row.record.identifier == identifier)


def selected_key(user: Account, identifier: int) -> Record:
    return next(row for row in user.keys if row.identifier == identifier)


def content_key(decoded: Store, account_id: int, key_id: int, family: int) -> bytes:
    user = selected_account(decoded, account_id)
    key = selected_key(user, key_id)
    return unwrap_value(
        key.child(b"valu").payload,
        decode_session(user.session, family),
        decoded.guid,
        account_id,
        key_id,
        user.version,
        key_kind(key),
    )


def source_account(*keys: KeySpec, identifier: int = 101) -> Record:
    return account(
        identifier, keys, guid=SOURCE_GUID, session=SOURCE_SESSION, family=33
    )


@pytest.mark.parametrize("family", [33, 34])
def test_absent_destination_converts_guid_session_and_final_keys(family: int) -> None:
    source = store(SOURCE_GUID, source_account((1, 0, b"a" * 16), (2, 1, b"b" * 16)))
    result = transfer_and_merge(source, SOURCE_GUID, TARGET_GUID, family)
    target = decode(result.data, TARGET_GUID)
    assert (result.added_keys, result.replaced_keys, result.unchanged_keys) == (2, 0, 0)
    assert target.guid == TARGET_GUID
    assert decode_session(target.accounts[0].session, family) == SOURCE_SESSION
    assert content_key(target, 101, 1, family) == b"a" * 16
    assert content_key(target, 101, 2, family) == b"b" * 16


@pytest.mark.parametrize("version", [0x60002, 0x60003])
def test_merge_reconciles_sessions_replaces_conflicts_and_preserves_unrelated_data(
    version: int,
) -> None:
    source = store(
        SOURCE_GUID,
        source_account((1, 1, b"new content key!"), (3, 0, b"added contentkey")),
        source_account((1, 1, b"new account key!"), identifier=202),
    )
    previous_user = account(
        101,
        ((1, 0, b"old content key!"), (2, 1, b"keep contentkey!")),
        guid=TARGET_GUID,
        session=TARGET_SESSION,
        family=34,
    )
    old_conflict = next(
        row
        for row in previous_user.children
        if row.tag == b"key " and row.identifier == 1
    )
    extension = Record(
        b"xtra", identifier=17, reserved=73, payload=b"retain key extension"
    )
    previous_user = replace(
        previous_user,
        children=tuple(
            replace(row, children=(*row.children, extension))
            if row is old_conflict
            else row
            for row in previous_user.children
        ),
    )
    unrelated_user = account(
        303,
        ((1, 0, b"unrelated key!!!"),),
        guid=TARGET_GUID,
        session=b"q" * 16,
        family=34,
    )
    existing = store(TARGET_GUID, previous_user, unrelated_user, version=version)
    previous = decode(existing, TARGET_GUID)
    result = transfer_and_merge(source, SOURCE_GUID, TARGET_GUID, 34, existing)
    merged = decode(result.data, TARGET_GUID)
    assert decode_envelope(result.data, TARGET_GUID)[0] == version
    assert (result.added_keys, result.replaced_keys, result.unchanged_keys) == (2, 1, 0)
    assert [row.record.identifier for row in merged.accounts] == [101, 303, 202]
    user = selected_account(merged, 101)
    assert user.session == selected_account(previous, 101).session
    assert decode_session(user.session, 34) == TARGET_SESSION
    assert [row.identifier for row in user.keys] == [1, 2, 3]
    assert content_key(merged, 101, 1, 34) == b"new content key!"
    assert key_kind(selected_key(user, 1)) == 1
    assert content_key(merged, 101, 3, 34) == b"added contentkey"
    assert content_key(merged, 202, 1, 34) == b"new account key!"
    assert selected_key(user, 2) == selected_key(selected_account(previous, 101), 2)
    assert selected_account(merged, 303) == selected_account(previous, 303)
    assert selected_key(user, 1).child(b"xtra") == extension
    assert user.record.child(b"meta") == previous_user.child(b"meta")
    assert merged.root.child(b"root") == previous.root.child(b"root")
    assert merged.group.child(b"tail") == previous.group.child(b"tail")
    assert (merged.root.reserved, merged.group.reserved, user.record.reserved) == (
        71,
        81,
        29,
    )
    repeated = transfer_and_merge(source, SOURCE_GUID, TARGET_GUID, 34, result.data)
    assert repeated.data == result.data
    assert (repeated.added_keys, repeated.replaced_keys, repeated.unchanged_keys) == (
        0,
        0,
        3,
    )


def test_distinct_oaep_ciphertexts_with_same_session_do_not_create_duplicates() -> None:
    source_user = source_account((1, 1, b"identical key!!!"))
    existing_user = account(
        101,
        ((1, 1, b"identical key!!!"),),
        guid=TARGET_GUID,
        session=SOURCE_SESSION,
        family=33,
    )
    assert source_user.child(b"sess").payload != existing_user.child(b"sess").payload
    existing = store(TARGET_GUID, existing_user)
    result = transfer_and_merge(
        store(SOURCE_GUID, source_user), SOURCE_GUID, TARGET_GUID, 33, existing
    )
    assert result.data == existing
    assert (result.added_keys, result.replaced_keys, result.unchanged_keys) == (0, 0, 1)


def test_type_two_preserves_inner_bytes_when_reconciling_account_sessions() -> None:
    inner = b"opaque kind two!"
    source = store(SOURCE_GUID, source_account((2, 2, inner)))
    existing = store(
        TARGET_GUID,
        account(
            101,
            ((1, 1, b"keep contentkey!"),),
            guid=TARGET_GUID,
            session=TARGET_SESSION,
            family=34,
        ),
    )
    result = transfer_and_merge(source, SOURCE_GUID, TARGET_GUID, 34, existing)
    user = selected_account(decode(result.data, TARGET_GUID), 101)
    key = selected_key(user, 2)
    assert key_kind(key) == 2
    assert ecb_cipher(TARGET_SESSION).decrypt(key.child(b"valu").payload) == inner
    assert result.added_keys == 1
    # This checks session-layer preservation only, never a Type 2 final-key claim.


@pytest.mark.parametrize(
    "failure", ["damaged-existing", "source-guid", "destination-guid"]
)
def test_authentication_failure_does_not_return_a_replacement(failure: str) -> None:
    source = store(SOURCE_GUID, source_account((1, 1, b"a" * 16)))
    existing = store(TARGET_GUID)
    source_guid, destination_guid = SOURCE_GUID, TARGET_GUID
    if failure == "damaged-existing":
        existing = existing[:-1] + bytes([existing[-1] ^ 1])
    elif failure == "source-guid":
        source_guid = bytes(8)
    else:
        destination_guid = bytes(8)
    with pytest.raises(ValueError, match="authentication failed"):
        transfer_and_merge(source, source_guid, destination_guid, 34, existing)


@pytest.mark.parametrize(
    "failure", ["family", "source-version", "signed-key", "account-version"]
)
def test_unsupported_input_is_rejected(failure: str) -> None:
    user = source_account((1, 1, b"a" * 16))
    version, family = 0x60002, 34
    if failure == "family":
        family = 999
    elif failure == "source-version":
        version = 0x60003
    elif failure == "account-version":
        user = user.replace_child(
            Record(b"vers", identifier=1, payload=(0x10102).to_bytes(4, "big"))
        )
    else:
        key = user.child(b"key ")
        user = user.replace_child(
            key.replace_child(Record(b"sign", identifier=1, payload=b"signed"))
        )
    source = store(SOURCE_GUID, user, version=version)
    with pytest.raises(ValueError):
        transfer_and_merge(source, SOURCE_GUID, TARGET_GUID, family)


@pytest.mark.parametrize("tag", [b"guid", b"vers", b"sess", b"type", b"valu", b"sign"])
def test_native_singleton_selector_must_be_one(tag: bytes) -> None:
    source = store(SOURCE_GUID, source_account((1, 1, b"a" * 16)))
    version, clear = decode_envelope(source, SOURCE_GUID)

    def wrong_selector(row: Record) -> Record:
        return replace(
            row,
            identifier=7 if row.tag == tag else row.identifier,
            children=tuple(wrong_selector(child) for child in row.children),
        )

    damaged = encode_envelope(
        write_records(wrong_selector(parse_records(clear))), SOURCE_GUID, version
    )
    with pytest.raises(ValueError, match="identifier one"):
        transfer_and_merge(damaged, SOURCE_GUID, TARGET_GUID, 34)


@pytest.mark.parametrize("malformation", ["duplicate", "container"])
def test_ambiguous_or_nonleaf_signature_is_rejected(malformation: str) -> None:
    user = source_account((1, 1, b"a" * 16))
    key = user.child(b"key ")
    if malformation == "duplicate":
        key = replace(key, children=(*key.children, Record(b"sign", identifier=1)))
    else:
        key = key.replace_child(
            Record(
                b"sign", identifier=1, children=(Record(b"data", payload=b"nested"),)
            )
        )
    source = store(SOURCE_GUID, user.replace_child(key))
    with pytest.raises(ValueError, match=r"exactly one|signature must be a leaf"):
        transfer_and_merge(source, SOURCE_GUID, TARGET_GUID, 34)
