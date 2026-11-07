"""Standalone GUID-bound key transformations for the evidenced account format.

The fixed transform contains only substitution and mixing data. Runtime code
never loads firmware, executes ARM instructions, or invokes the research lab.
"""

import hashlib
import struct
from functools import lru_cache
from importlib.resources import files

from iPodDB.ic_info.aes import ecb_cipher
from iPodDB.ic_info.cipher import TableCipher
from iPodDB.ic_info.derivation import mix_byte, next_word
from iPodDB.ic_info.device_cipher_tables import DEVICE

_SHIFT = (0, 5, 10, 15, 4, 9, 14, 3, 8, 13, 2, 7, 12, 1, 6, 11)
_PREFIX = bytes.fromhex("5b53bae2a66f0167732910c52099b73381")
_SUFFIX = bytes.fromhex("54da7b97e1f90ec3ae646e3a")


@lru_cache(maxsize=1)
def _tables() -> tuple[bytes, tuple[int, ...], bytes, bytes]:
    data = files("iPodDB.ic_info").joinpath("binding_tables.bin").read_bytes()
    if (
        len(data) != 42496
        or hashlib.sha256(data).hexdigest()
        != "c1615b52eee01c4628a0f19f94b700ea30e3e538700c8d1487c34ce0e020a8f1"
    ):
        raise ValueError("Invalid IC-Info device-binding constants")
    words: tuple[int, ...] = struct.unpack(">256I", data[40960:41984])
    return data[:40960], words, data[41984:42240], data[42240:]


def _rotate(value: int, count: int) -> int:
    return ((value >> count) | (value << (32 - count))) & 0xFFFFFFFF


def _fixed_transform(value: bytes) -> bytes:
    tables, mixing, _, _ = _tables()
    state = value
    for round_index in range(9):
        result = bytearray()
        for column in range(4):
            word = 0
            for row in range(4):
                position = column * 4 + row
                substituted = tables[
                    round_index * 4096 + position * 256 + state[_SHIFT[position]]
                ]
                word ^= _rotate(mixing[substituted], row * 8)
            result.extend(word.to_bytes(4, "big"))
        state = bytes(result)
    return bytes(
        tables[9 * 4096 + position * 256 + state[_SHIFT[position]]]
        for position in range(16)
    )


def derive_device_key(
    guid: bytes, account: int, key: int, account_version: int, kind: int
) -> bytes:
    """Derive the native cipher-key representation for a supported license kind."""
    if len(guid) != 8 or not 0 <= account <= 0xFFFFFFFF or not 0 <= key <= 0xFFFFFFFF:
        raise ValueError("Invalid IC-Info GUID or account/key selector")
    if (
        not 0 <= account_version <= 0xFFFFFFFF
        or account_version & 0x00FF00FF != 0x00010001
    ):
        raise ValueError("Unsupported IC-Info account-version binding")
    identity = guid + key.to_bytes(4, "big") + account.to_bytes(4, "big")
    if kind == 1:
        digest = hashlib.sha1(_PREFIX + identity + _SUFFIX).digest()
        transformed = _fixed_transform(digest[:16])
        generated = b"".join(
            next_word(int.from_bytes(digest[offset : offset + 2], "big")).to_bytes(
                4, "big"
            )
            for offset in (16, 18)
        )
        output = bytearray()
        for position in range(16):
            value = 0
            for index, left in enumerate(generated):
                value ^= mix_byte(left, transformed[(position + index) & 7])
            output.append((value * 239 + 154) & 255)
        return bytes(output)
    if kind == 0:
        transformed = _fixed_transform(identity)
        _, _, first, second = _tables()
        expanded = bytes(
            part for value in transformed for part in (first[value], second[value])
        )
        generated = b"".join(
            next_word(int.from_bytes(transformed[offset : offset + 2], "big")).to_bytes(
                4, "big"
            )
            for offset in (0, 2)
        )
        swapped = bytes(
            transformed[index]
            for column in range(4)
            for index in (column * 4, column * 4 + 2, column * 4 + 1, column * 4 + 3)
        )
        tail = bytes(
            part for value in swapped for part in (first[value], second[value])
        )
        digest = hashlib.md5(generated + expanded[8:] + tail).digest()
        return bytes((value * 239 + 154) & 255 for value in digest)
    raise ValueError("This IC-Info kind has no evidenced final device-key transform")


def unwrap_value(
    value: bytes,
    session: bytes,
    guid: bytes,
    account: int,
    key: int,
    account_version: int,
    kind: int,
) -> bytes:
    """Return the final 16-byte content key for a supported type-0/1 value."""
    if len(value) != 16 or len(session) != 16:
        raise ValueError("IC-Info values and account sessions must contain 16 bytes")
    cipher = TableCipher(
        DEVICE, derive_device_key(guid, account, key, account_version, kind)
    )
    inner = ecb_cipher(session).decrypt(value) if account_version & 0x100 else value
    return cipher.encrypt(inner)


def wrap_value(
    value: bytes,
    session: bytes,
    guid: bytes,
    account: int,
    key: int,
    account_version: int,
    kind: int,
) -> bytes:
    """Wrap a final content key under a GUID, selector pair, and account session."""
    if len(value) != 16 or len(session) != 16:
        raise ValueError("IC-Info values and account sessions must contain 16 bytes")
    cipher = TableCipher(
        DEVICE, derive_device_key(guid, account, key, account_version, kind)
    )
    inner = cipher.decrypt(value)
    return ecb_cipher(session).encrypt(inner) if account_version & 0x100 else inner


def rebind_value(
    value: bytes,
    session: bytes,
    source_guid: bytes,
    destination_guid: bytes,
    account: int,
    key: int,
    account_version: int,
    kind: int,
) -> bytes:
    """Preserve a final key while changing its GUID binding, with a forward check."""
    final = unwrap_value(
        value, session, source_guid, account, key, account_version, kind
    )
    rebound = wrap_value(
        final, session, destination_guid, account, key, account_version, kind
    )
    if (
        unwrap_value(
            rebound, session, destination_guid, account, key, account_version, kind
        )
        != final
    ):
        raise ValueError("IC-Info final-key verification failed")
    return rebound
