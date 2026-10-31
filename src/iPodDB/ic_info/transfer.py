"""Standalone Classic-source conversion and preservation-first account merge."""

from dataclasses import replace

from iPodDB.ic_info import TransferResult
from iPodDB.ic_info.aes import ecb_cipher
from iPodDB.ic_info.binding import rebind_value
from iPodDB.ic_info.envelope import decode_envelope, encode_envelope
from iPodDB.ic_info.merge import merge_prepared_stores
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

_FAMILIES = frozenset({13, 20, 25, 24, 33, 35, 38, 26, 31, 34})
_CLASSIC_FAMILIES = frozenset({24, 33, 35, 38})


def prepare_transfer(
    source: bytes,
    source_guid: bytes,
    destination_guid: bytes,
    destination_family: int,
    existing: bytes | None,
) -> TransferResult:
    """Return verified file bytes; source is the supplied Classic 6.5 format.

    Existing envelopes must authenticate before preparation. Shared accounts keep
    their destination session and unrelated values; incoming values are rewrapped
    for that session before merging. A failed conversion never returns file bytes.
    """
    if destination_family not in _FAMILIES:
        raise ValueError("Unsupported IC-Info destination updater family.")
    if len(source_guid) != 8 or len(destination_guid) != 8:
        raise ValueError("IC-Info device GUIDs must contain exactly eight bytes.")
    version, backing = decode_envelope(source, source_guid)
    if version != 0x60002:
        raise ValueError("The Classic source must use IC-Info version 0x00060002.")
    incoming = inspect_store(parse_records(backing), source_guid)
    destination: Store | None = None
    destination_backing: bytes | None = None
    if existing is not None:
        version, destination_backing = decode_envelope(existing, destination_guid)
        destination = inspect_store(
            parse_records(destination_backing), destination_guid
        )
    prepared = _convert_store(
        incoming, destination, destination_guid, destination_family
    )
    if destination is None:
        result = TransferResult(
            b"", sum(len(row.keys) for row in prepared.accounts), 0, 0
        )
        merged = prepared
    else:
        merge = merge_prepared_stores(destination, prepared)
        merged = merge.store
        result = TransferResult(
            b"", merge.added_keys, merge.replaced_keys, merge.unchanged_keys
        )
    output_backing = write_records(merged.root)
    if existing is not None and output_backing == destination_backing:
        # Preserve the entire existing envelope on a no-op, including any
        # authenticated representation differences in a genuine iTunes file.
        return replace(result, data=existing)
    output = encode_envelope(output_backing, destination_guid, version)
    checked_version, checked_backing = decode_envelope(output, destination_guid)
    if checked_version != version or checked_backing != output_backing:
        raise ValueError("Prepared IC-Info failed its authentication round trip.")
    inspect_store(parse_records(checked_backing), destination_guid)
    return replace(result, data=output)


def _convert_store(
    incoming: Store, destination: Store | None, guid: bytes, family: int
) -> Store:
    existing = (
        {}
        if destination is None
        else {row.record.identifier: row for row in destination.accounts}
    )
    converted = {
        row.record.identifier: _convert_account(
            row, existing.get(row.record.identifier), incoming.guid, guid, family
        )
        for row in incoming.accounts
    }
    group = replace(
        incoming.group,
        children=tuple(
            converted[row.identifier] if row.tag == b"user" else row
            for row in incoming.group.children
        ),
    )
    head = group.child(b"head")
    group = group.replace_child(
        head.replace_child(replace(head.child(b"guid"), payload=guid))
    )
    return inspect_store(incoming.root.replace_child(group), guid)


def _convert_account(
    incoming: Account,
    destination: Account | None,
    source_guid: bytes,
    guid: bytes,
    family: int,
) -> Record:
    if destination is not None and destination.version != incoming.version:
        raise ValueError("Cannot merge incompatible IC-Info account versions.")
    source_session = decode_session(incoming.session, 33)
    if destination is None:
        target_session = source_session
        target_session_record = replace(
            incoming.record.child(b"sess"),
            payload=(
                incoming.session
                if family in _CLASSIC_FAMILIES
                else encode_session(source_session, family)
            ),
        )
    else:
        target_session = decode_session(destination.session, family)
        target_session_record = destination.record.child(b"sess")
    keys: dict[int, Record] = {}
    for key in incoming.keys:
        kind = key_kind(key)
        value = key.child(b"valu")
        if kind not in {0, 1, 2} or len(value.payload) != 16:
            raise ValueError("Unsupported bundled IC-Info key kind or length.")
        signature = key.child(b"sign")
        if signature.children or signature.payload:
            raise ValueError("Signed IC-Info key conversion is not supported.")
        if kind == 2:
            # Only its session layer is understood. Retain the inner bytes;
            # do not claim to derive a final device key for this kind.
            rebound = value.payload
        else:
            rebound = rebind_value(
                value.payload,
                source_session,
                source_guid,
                guid,
                incoming.record.identifier,
                key.identifier,
                incoming.version,
                kind,
            )
        if target_session != source_session:
            if not incoming.version & 0x100:
                raise ValueError("Cannot reconcile an unprotected account session.")
            rebound = ecb_cipher(target_session).encrypt(
                ecb_cipher(source_session).decrypt(rebound)
            )
        keys[key.identifier] = key.replace_child(replace(value, payload=rebound))
    user = replace(
        incoming.record,
        children=tuple(
            keys[row.identifier] if row.tag == b"key " else row
            for row in incoming.record.children
        ),
    )
    return user.replace_child(target_session_record)
