"""Small synthetic stores and native known answers; no captured authorizations."""

import struct

import pytest

from iPodDB.ic_info.cipher import TableCipher
from iPodDB.ic_info.device_cipher_tables import DEVICE
from iPodDB.ic_info.envelope import MAX_ENVELOPE_BYTES, decode_envelope, encode_envelope
from iPodDB.ic_info.envelope_tables import AUTH, BODY

GUID = bytes(range(8))
# Independent stock Classic 2.0.1 serializer output for a synthetic empty root.
# Lab receipt: artifacts/standalone-envelope-validation.json; no game/account data.
EMPTY_NATIVE = bytes.fromhex(
    "00060002e465e2ab2827b5e910be58b865b2f0a3254918f6bc2000ecdf62ca8ba1676bb9"
    "084c58311de25566aefd675002734d74"
)
PADDED_NATIVE = bytes.fromhex(
    "0006000293c7f802e468a1764fcea3e8ede69f83f8a90ed5c1c2ab14339732be4f548d21"
    "06f75788e82e4f7d58e8d3b4a7b78a4261ac87d6bb91e195f828ce295abddc73"
)


def root(payload: bytes = b"") -> bytes:
    return (
        bytes(12)
        + struct.pack(">I4sIII", 20 + len(payload), b"sean", 1, 0, 0)
        + payload
    )


@pytest.mark.parametrize("version", [0x60002, 0x60003])
@pytest.mark.parametrize("length", [0, 1, 15, 16, 17, 96])
def test_round_trip_padding_boundaries(version: int, length: int) -> None:
    backing = root(bytes((index * 31 + 17) & 255 for index in range(length)))
    encoded = encode_envelope(backing, GUID, version)
    assert len(encoded) == ((len(backing) + 15) & ~15) + 20
    assert decode_envelope(encoded, GUID) == (version, backing)
    assert encode_envelope(backing, GUID, version) == encoded


def test_native_known_answers() -> None:
    assert encode_envelope(root(), GUID) == EMPTY_NATIVE
    assert decode_envelope(EMPTY_NATIVE, GUID) == (0x60002, root())
    padded = root(bytes((index * 31 + 17) & 255 for index in range(15)))
    assert encode_envelope(padded, GUID) == PADDED_NATIVE
    assert decode_envelope(PADDED_NATIVE, GUID) == (0x60002, padded)


@pytest.mark.parametrize("offset", [4, 20, 36, 51])
def test_rejects_body_and_trailer_changes(offset: int) -> None:
    damaged = bytearray(EMPTY_NATIVE)
    damaged[offset] ^= 1
    with pytest.raises(ValueError, match="authentication failed"):
        decode_envelope(bytes(damaged), GUID)


def test_rejects_wrong_guid() -> None:
    with pytest.raises(ValueError, match="authentication failed"):
        decode_envelope(EMPTY_NATIVE, bytes(8))


@pytest.mark.parametrize("guid", [b"", bytes(7), bytes(9)])
def test_rejects_invalid_guid_size(guid: bytes) -> None:
    with pytest.raises(ValueError, match="eight bytes"):
        encode_envelope(root(), guid)
    with pytest.raises(ValueError, match="eight bytes"):
        decode_envelope(EMPTY_NATIVE, guid)


@pytest.mark.parametrize(
    "blob",
    [b"", EMPTY_NATIVE[:-1], bytes(MAX_ENVELOPE_BYTES + 1)],
    ids=["empty", "unaligned", "oversize"],
)
def test_rejects_invalid_envelope_size(blob: bytes) -> None:
    with pytest.raises(ValueError, match="size"):
        decode_envelope(blob, GUID)


def test_rejects_unknown_version() -> None:
    with pytest.raises(ValueError, match="version"):
        encode_envelope(root(), GUID, 0x60004)
    with pytest.raises(ValueError, match="version"):
        decode_envelope(b"\0\x06\0\x04" + EMPTY_NATIVE[4:], GUID)


@pytest.mark.parametrize("backing", [bytes(32), root() + b"\0", root()[1:]])
def test_rejects_invalid_root_or_trailing_data(backing: bytes) -> None:
    with pytest.raises(ValueError):
        encode_envelope(backing, GUID)


def test_rejects_oversize_tree() -> None:
    with pytest.raises(ValueError, match="size limit"):
        encode_envelope(root(bytes(MAX_ENVELOPE_BYTES)), GUID)


def test_block_inverse_for_both_profiles() -> None:
    for tables in (BODY, AUTH, DEVICE):
        cipher = TableCipher(tables, bytes(range(16)))
        for index in range(16):
            value = bytes((index * 19 + position * 7) & 255 for position in range(16))
            assert cipher.decrypt(cipher.encrypt(value)) == value


@pytest.mark.parametrize(
    ("key", "block", "native"),
    [
        (
            "00000000000000000000000000000000",
            "00070e151c232a31383f464d545b6269",
            "6cedc0e3023aa6eaf544a93949d945a8",
        ),
        (
            "0102030405060708090a0b0c0d0e0f10",
            "1f262d343b424950575e656c737a8188",
            "07aecfb5da9f0eb292f2dc1b4b2634e8",
        ),
        (
            "020406080a0c0e10121416181a1c1e20",
            "3e454c535a61686f767d848b9299a0a7",
            "1a7f6bccb6fa452a4a091011b5b43a7e",
        ),
    ],
)
def test_native_device_cipher_known_answers(key: str, block: str, native: str) -> None:
    cipher = TableCipher(DEVICE, bytes.fromhex(key))
    assert cipher.encrypt(bytes.fromhex(block)) == bytes.fromhex(native)
    assert cipher.decrypt(bytes.fromhex(native)) == bytes.fromhex(block)


@pytest.mark.parametrize("length", [0, 15, 17])
def test_rejects_invalid_cipher_block_length(length: int) -> None:
    cipher = TableCipher(AUTH, bytes(16))
    with pytest.raises(ValueError, match="sixteen bytes"):
        cipher.encrypt(bytes(length))
    with pytest.raises(ValueError, match="sixteen bytes"):
        cipher.decrypt(bytes(length))
