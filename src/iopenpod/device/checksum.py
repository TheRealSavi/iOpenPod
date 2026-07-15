"""Checksum type enumeration and MHBD hashing-scheme mappings."""

from enum import IntEnum


class ChecksumType(IntEnum):
    """Checksum types for different iPod generations.

    NONE        — Pre-2007 iPods (iPod 1G–5.5G, Mini 1G–2G, Nano 1G–2G, Shuffle)
    HASH58      — iPod Classic (all gens), Nano 3G, Nano 4G
    HASH72      — Nano 5G
    HASHAB      — Nano 6G, Nano 7G (white-box AES, via WASM module)
    UNSUPPORTED — Reserved for any future unsupported scheme
    UNKNOWN     — Device not yet identified
    """
    NONE = 0
    HASH58 = 1
    HASH72 = 2
    HASHAB = 3
    UNSUPPORTED = 98
    UNKNOWN = 99


# ── MHBD hashing scheme ↔ ChecksumType mapping ──────────────────────────
#
# The mhbd header at offset 0x30 stores a 16-bit ``hashing_scheme`` value.
# These constants map between our ``ChecksumType`` enum and the raw wire
# values.  Note: HASHAB is enum 3 but wire 4.

CHECKSUM_MHBD_SCHEME: dict[ChecksumType, int] = {
    ChecksumType.NONE: 0,
    ChecksumType.HASH58: 1,
    ChecksumType.HASH72: 2,
    ChecksumType.HASHAB: 4,
}
"""Map ``ChecksumType`` → raw ``hashing_scheme`` field in mhbd header."""

MHBD_SCHEME_TO_CHECKSUM: dict[int, ChecksumType] = {
    v: k for k, v in CHECKSUM_MHBD_SCHEME.items()
}
"""Map raw ``hashing_scheme`` field in mhbd header → ``ChecksumType``."""
