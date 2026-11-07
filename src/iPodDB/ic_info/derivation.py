"""Bounded cryptographic helper tables, exhaustively matched to the native code.

The generator is only consumed immediately after a 16-bit seed in the supported
key paths. This table describes its first word, not a general random generator.
No ARM instructions, memory map or emulator are included.
"""

import hashlib
from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=1)
def _table(name: str, size: int) -> bytes:
    data = files("iPodDB.ic_info").joinpath(name).read_bytes()
    expected = {
        "derivation_words.bin": "462ae8313110e255cea762776834a41fa9505a366b00a1c6b8e5168dbc3d39f8",
    }
    if len(data) != size or hashlib.sha256(data).hexdigest() != expected[name]:
        raise ValueError("Invalid IC-Info derivation table size or digest.")
    return data


def next_word(seed: int) -> int:
    """Return the canonical first derivation word for one canonical 16-bit seed."""
    if not 0 <= seed < 65536:
        raise ValueError("IC-Info derivation seed must fit in sixteen bits.")
    raw_seed = (seed * 0x8945 + 0xE16B) & 0xFFFF
    data = _table("derivation_words.bin", 65536 * 4)
    raw = int.from_bytes(data[raw_seed * 4 : raw_seed * 4 + 4], "little")
    return (raw * 0xD6DDF37F + 0x5C2CD6FF) & 0xFFFFFFFF


def mix_byte(left: int, right: int) -> int:
    """Multiply canonical bytes in GF(256), using the AES polynomial 0x11B.

    All 65,536 argument pairs matched the decoded native 0x082CD1BC helper.
    Its obfuscated logarithm tables are unnecessary in this representation.
    """
    if not 0 <= left < 256 or not 0 <= right < 256:
        raise ValueError("IC-Info byte mixing arguments must fit in one byte.")
    result = 0
    for _ in range(8):
        if right & 1:
            result ^= left
        left = ((left << 1) ^ (0x11B if left & 128 else 0)) & 255
        right >>= 1
    return result
