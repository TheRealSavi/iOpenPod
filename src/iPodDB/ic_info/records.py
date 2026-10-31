"""Lossless, bounded decoded IC-Info records, independent of file protection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from struct import Struct

MAX_STORE_BYTES = 0x80000
_HEADER = Struct(">I4sIII")
_PREFIX = bytes(12)
_MAX_DEPTH = 16


@dataclass(frozen=True, slots=True)
class Record:
    """One record; unknown tags, identifier, reserved word and payload survive."""

    tag: bytes
    identifier: int = 0
    reserved: int = 0
    payload: bytes = b""
    children: tuple[Record, ...] = ()

    def child(self, tag: bytes) -> Record:
        """Require one unambiguous immediate child with the requested tag."""
        matches = tuple(row for row in self.children if row.tag == tag)
        if len(matches) != 1:
            raise ValueError(f"IC-Info requires exactly one {tag!r} record here.")
        return matches[0]

    def replace_child(self, replacement: Record) -> Record:
        """Replace a singleton field while retaining sibling order and metadata."""
        original = self.child(replacement.tag)
        return replace(
            self,
            children=tuple(
                replacement if row is original else row for row in self.children
            ),
        )


def parse_records(data: bytes) -> Record:
    """Read an already decrypted store; this does not authenticate an envelope."""
    if not 32 <= len(data) <= MAX_STORE_BYTES or data[:12] != _PREFIX:
        raise ValueError("Invalid decoded IC-Info size or prefix.")

    def read(start: int, end: int, depth: int) -> tuple[Record, int]:
        if depth > _MAX_DEPTH or end - start < _HEADER.size:
            raise ValueError("Truncated or excessively nested IC-Info record.")
        size, tag, identifier, count, reserved = _HEADER.unpack_from(data, start)
        if size < _HEADER.size or size > end - start:
            raise ValueError("IC-Info record crosses its parent boundary.")
        stop = start + size
        cursor = start + _HEADER.size
        if count > (size - _HEADER.size) // _HEADER.size:
            raise ValueError("IC-Info child count exceeds the record size.")
        children: list[Record] = []
        if count:
            for _ in range(count):
                child, cursor = read(cursor, stop, depth + 1)
                children.append(child)
            if cursor != stop:
                raise ValueError("IC-Info child count leaves unclaimed bytes.")
        return Record(
            tag,
            identifier,
            reserved,
            b"" if count else data[cursor:stop],
            tuple(children),
        ), stop

    root, end = read(12, len(data), 0)
    if root.tag != b"sean" or end != len(data):
        raise ValueError("IC-Info requires exactly one sean root record.")
    return root


def write_records(root: Record) -> bytes:
    """Serialize records, recalculating parent sizes and immediate-child counts."""
    output = bytearray(_PREFIX)

    def write(record: Record, depth: int) -> None:
        if depth > _MAX_DEPTH:
            raise ValueError("IC-Info nesting exceeds the supported bound.")
        if (
            len(record.tag) != 4
            or not 0 <= record.identifier <= 0xFFFFFFFF
            or not 0 <= record.reserved <= 0xFFFFFFFF
            or (record.children and record.payload)
        ):
            raise ValueError("Invalid IC-Info record fields.")
        start = len(output)
        output.extend(bytes(_HEADER.size))
        if record.children:
            for child in record.children:
                write(child, depth + 1)
        else:
            if len(record.payload) > MAX_STORE_BYTES - len(output):
                raise ValueError("IC-Info exceeds the supported byte limit.")
            output.extend(record.payload)
        if len(output) > MAX_STORE_BYTES:
            raise ValueError("IC-Info exceeds the supported byte limit.")
        _HEADER.pack_into(
            output,
            start,
            len(output) - start,
            record.tag,
            record.identifier,
            len(record.children),
            record.reserved,
        )

    if root.tag != b"sean":
        raise ValueError("IC-Info requires a sean root record.")
    write(root, 0)
    return bytes(output)


@dataclass(frozen=True, slots=True)
class Account:
    """Validated account selectors and leaves, retaining its complete record."""

    record: Record
    version: int
    session: bytes
    keys: tuple[Record, ...]


@dataclass(frozen=True, slots=True)
class Store:
    """One identity-bearing group and its uniquely addressable accounts."""

    root: Record
    group: Record
    guid: bytes
    accounts: tuple[Account, ...]


def key_kind(key: Record) -> int:
    """Read a key kind without assigning unsupported kinds a meaning."""
    kind = _field(key, b"type")
    if kind.children or len(kind.payload) != 4:
        raise ValueError("IC-Info key type must be a four-byte leaf.")
    return int.from_bytes(kind.payload, "big")


def _field(parent: Record, tag: bytes) -> Record:
    field = parent.child(tag)
    if field.identifier != 1:
        raise ValueError("IC-Info singleton fields require identifier one.")
    return field


def inspect_store(root: Record, guid: bytes) -> Store:
    """Validate selection and merge invariants without discarding unknown data."""
    if len(guid) != 8 or root.tag != b"sean":
        raise ValueError("IC-Info requires an eight-byte GUID and a sean root.")
    group = root.child(b"grup")
    identity = _field(group.child(b"head"), b"guid")
    if identity.children or identity.payload != guid:
        raise ValueError("IC-Info group GUID does not match the device.")
    accounts: list[Account] = []
    seen_accounts: set[int] = set()
    for user in group.children:
        if user.tag != b"user":
            continue
        if user.identifier in seen_accounts:
            raise ValueError("Duplicate IC-Info account selector.")
        seen_accounts.add(user.identifier)
        version = _field(user, b"vers")
        session = _field(user, b"sess")
        if version.children or len(version.payload) != 4:
            raise ValueError("IC-Info account version must be a four-byte leaf.")
        if session.children or len(session.payload) != 128:
            raise ValueError("IC-Info account session must be a 128-byte leaf.")
        keys = tuple(row for row in user.children if row.tag == b"key ")
        seen_keys: set[int] = set()
        for key in keys:
            if key.identifier in seen_keys:
                raise ValueError("Duplicate IC-Info key selector within an account.")
            seen_keys.add(key.identifier)
            kind = key_kind(key)
            value = _field(key, b"valu")
            if value.children:
                raise ValueError("IC-Info key value must be a leaf.")
            if kind in {0, 1, 2} and len(value.payload) != 16:
                raise ValueError("Known IC-Info key values must contain sixteen bytes.")
            if kind in {0, 1, 2} and _field(key, b"sign").children:
                raise ValueError("IC-Info key signature must be a leaf.")
            # Unknown kinds and lengths remain representable when untouched.
        accounts.append(
            Account(user, int.from_bytes(version.payload, "big"), session.payload, keys)
        )
    return Store(root, group, guid, tuple(accounts))
