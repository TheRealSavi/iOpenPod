"""Pure Locations checksum-book generation and verification."""

import hashlib
import hmac

from iPodDB.library.writing import WriteChecksum
from iPodDB.SQLiteDB.artifacts import SQLiteDatabaseSet

_BLOCK_SIZE = 1024


def _cbk_parts(locations: bytes) -> tuple[bytes, bytes]:
    blocks = b"".join(
        hashlib.sha1(locations[offset : offset + _BLOCK_SIZE]).digest()
        for offset in range(0, len(locations), _BLOCK_SIZE)
    )
    return hashlib.sha1(blocks).digest(), blocks


def build_locations_cbk(
    locations: bytes,
    checksum: WriteChecksum,
    guid: bytes = b"",
    iv: bytes = b"",
    random_part: bytes = b"",
) -> bytes:
    """Build the checksum book for one serialized Locations database."""

    from iPodDB.iTunesDB.writer.signature import (
        compute_hash58,
        compute_hash72_signature,
        compute_hashab,
    )

    final, blocks = _cbk_parts(locations)
    if checksum is WriteChecksum.HASHAB:
        header = compute_hashab(final, guid)
    elif checksum is WriteChecksum.HASH72:
        header = compute_hash72_signature(final, iv, random_part)
    elif checksum is WriteChecksum.HASH58:
        header = compute_hash58(guid, final)
    elif checksum is WriteChecksum.NONE:
        header = final
    else:
        raise ValueError(f"Unsupported SQLite checksum: {checksum}")
    return header + final + blocks


def recover_hash72_cbk_material(locations: bytes, cbk: bytes) -> tuple[bytes, bytes]:
    """Recover HASH72 material only from a checksum book matching Locations bytes."""

    from iPodDB.iTunesDB.writer.signature import recover_hash72_signature

    final, blocks = _cbk_parts(locations)
    if len(cbk) != 46 + 20 + len(blocks) or not hmac.compare_digest(
        cbk[46:], final + blocks
    ):
        raise ValueError(
            "The retained Locations checksum book does not match Locations."
        )
    return recover_hash72_signature(final, cbk[:46])


def verify_locations_cbk(
    databases: SQLiteDatabaseSet,
    checksum: WriteChecksum,
    guid: bytes = b"",
    iv: bytes = b"",
    random_part: bytes = b"",
) -> bool:
    """Verify an already-read Locations checksum book without doing I/O."""

    try:
        expected = build_locations_cbk(
            databases.locations,
            checksum,
            guid,
            iv,
            random_part,
        )
    except ValueError:
        return False
    return hmac.compare_digest(databases.locations_cbk, expected)
