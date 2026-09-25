"""Public Library helpers for device-retained signing material.

The Application Layer owns reading device files.  These pure helpers let it
interpret already-read bytes without importing iTunesDB implementation modules.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Hash72Material:
    """Device-retained HASH72 signing material and its optional identity binding."""

    uuid: bytes | None
    random_part: bytes
    iv: bytes

    def __post_init__(self) -> None:
        if self.uuid is not None and len(self.uuid) != 20:
            raise ValueError("A HashInfo UUID must be exactly 20 bytes.")
        if len(self.random_part) != 12:
            raise ValueError("HASH72 material requires exactly 12 random bytes.")
        if len(self.iv) != 16:
            raise ValueError("HASH72 material requires exactly 16 IV bytes.")

    def belongs_to_guid(self, guid: bytes) -> bool:
        """Return whether a HashInfo UUID is this zero-padded FireWire GUID."""

        if self.uuid is None or len(guid) != 8:
            return False
        return hmac.compare_digest(self.uuid, guid + bytes(12))

    def matches(self, other: Hash72Material) -> bool:
        """Compare retained signing material without timing-sensitive byte equality."""

        uuids_match = (self.uuid is None and other.uuid is None) or (
            self.uuid is not None
            and other.uuid is not None
            and hmac.compare_digest(self.uuid, other.uuid)
        )
        random_parts_match = hmac.compare_digest(self.random_part, other.random_part)
        ivs_match = hmac.compare_digest(self.iv, other.iv)
        return uuids_match & random_parts_match & ivs_match


def parse_hash72_info(data: bytes) -> Hash72Material:
    """Return typed device-bound material from one ``HashInfo`` record."""

    from iPodDB.iTunesDB.writer.signature import parse_hash_info

    material = parse_hash_info(data)
    return Hash72Material(material.uuid, material.random_part, material.iv)


def recover_hash72_material(data: bytes) -> Hash72Material:
    """Recover unbound typed material from one retained HASH72 database."""

    from iPodDB.iTunesDB.writer.signature import extract_hash72_material

    iv, random_part = extract_hash72_material(data)
    return Hash72Material(None, random_part, iv)
