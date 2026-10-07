from __future__ import annotations

import hashlib
import struct

import pytest

from iPodDB.iTunesDB.writer.signature import (
    compute_hash72_signature,
    compute_hashab,
    extract_hash72_material,
    sign_hash72,
    sign_hashab,
    verify_hash72,
    verify_hashab,
)


def _database() -> bytes:
    header = bytearray(244)
    header[:4] = b"mhbd"
    struct.pack_into("<III", header, 4, 244, 244, 1)
    struct.pack_into("<I", header, 0x10, 0x6F)
    struct.pack_into("<Q", header, 0x18, 0x0102030405060708)
    return bytes(header)


def test_hash72_signs_verifies_and_recovers_device_material() -> None:
    iv = bytes(range(16))
    random_part = bytes(range(20, 32))

    signed = sign_hash72(_database(), iv, random_part)

    assert int.from_bytes(signed[0x30:0x32], "little") == 2
    assert signed[0x72:0x74] == b"\x01\x00"
    assert verify_hash72(signed, iv, random_part)
    assert extract_hash72_material(signed) == (iv, random_part)


def test_hash72_envelope_matches_original_iopenpod_vector() -> None:
    assert compute_hash72_signature(
        bytes(range(20)), bytes(range(16)), bytes(range(20, 32))
    ).hex() == (
        "01001415161718191a1b1c1d1e1f34a8f220c7c4330b3ceab271e37a96"
        "6339a42961b1a767e6747e0fb951a38bce"
    )


def test_hash72_recovery_uses_the_retained_scheme_for_a_dual_signed_database() -> None:
    iv = bytes(range(16))
    random_part = bytes(range(20, 32))
    retained = bytearray(_database())
    struct.pack_into("<H", retained, 0x30, 1)
    normalized = bytearray(retained)
    normalized[0x18:0x20] = bytes(8)
    retained[0x72:0xA0] = compute_hash72_signature(
        hashlib.sha1(normalized).digest(), iv, random_part
    )

    assert extract_hash72_material(bytes(retained)) == (iv, random_part)


@pytest.mark.parametrize("offset", [0x80, 0x90])
def test_hash72_recovery_rejects_corruption_in_either_ciphertext_block(
    offset: int,
) -> None:
    signed = bytearray(sign_hash72(_database(), bytes(range(16)), bytes(range(20, 32))))
    signed[offset] ^= 1

    with pytest.raises(ValueError, match="invalid HASH72 signature"):
        extract_hash72_material(bytes(signed))


def test_hash72_recovery_rejects_a_modified_cleartext_random_part() -> None:
    signed = bytearray(sign_hash72(_database(), bytes(range(16)), bytes(range(20, 32))))
    signed[0x74] ^= 1

    with pytest.raises(ValueError, match="invalid HASH72 signature"):
        extract_hash72_material(bytes(signed))


def test_hash72_recovery_rejects_an_invalid_prefix() -> None:
    signed = bytearray(sign_hash72(_database(), bytes(range(16)), bytes(range(20, 32))))
    signed[0x72] ^= 1

    with pytest.raises(ValueError, match="no recoverable HASH72 signature"):
        extract_hash72_material(bytes(signed))


def test_hash72_recovery_rejects_a_short_root_header() -> None:
    signed = bytearray(sign_hash72(_database(), bytes(range(16)), bytes(range(20, 32))))
    struct.pack_into("<I", signed, 4, 0x80)

    with pytest.raises(ValueError, match="cannot hold hash72"):
        extract_hash72_material(bytes(signed))


def test_hashab_matches_clean_room_reference_vector() -> None:
    assert compute_hashab(
        bytes.fromhex("915dd7203086aeea302740e97febb7aefa9ca9f1"),
        bytes.fromhex("f832c65917da6785"),
    ) == bytes.fromhex(
        "030056d7474d4843465449bd444266eb516bf4552726b94169d1424c4f433a82"
        "08fc5345e34507c3fe4a8f4e8a5052664515aad30e4b195c57"
    )


def test_hashab_signs_and_verifies_a_physical_database() -> None:
    guid = bytes.fromhex("f832c65917da6785")

    signed = sign_hashab(_database(), guid)

    assert int.from_bytes(signed[0x30:0x32], "little") == 3
    assert signed[0xAB : 0xAB + 57] != bytes(57)
    assert verify_hashab(signed, guid)
    assert not verify_hashab(signed, bytes(8))
