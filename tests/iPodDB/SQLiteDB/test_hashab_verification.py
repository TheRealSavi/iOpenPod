from dataclasses import replace

import pytest

from iPodDB.library.writing import WriteChecksum
from iPodDB.SQLiteDB.artifacts import SQLiteDatabaseSet
from iPodDB.SQLiteDB.checksum import build_locations_cbk, verify_locations_cbk

_GUID = bytes.fromhex("f832c65917da6785")
_LOCATIONS = bytes(range(256)) * 9 + b"final partial"
# Synthetic three-block book, computed with the pinned upstream primitive and
# bytes(range(23)) as its random input. Keep expected bytes independent of the
# production verifier and of build_locations_cbk's deterministic envelope.
_RANDOMIZED_CBK = bytes.fromhex(
    "030015d9060c07e8051308f903013f1a102bfa1459732d000b47350b0e028641fa25"
    "12500a04f702bd09d00de30f1112f79cf276820a923716"
    "c5cb9c35091dd9bf4b0b0ae573c6085534098e09"
    "5b00669c480d5cffbdfa8bdba99561160f2d1b77"
    "5b00669c480d5cffbdfa8bdba99561160f2d1b77"
    "0dc8b947d8548d5f24260d8429651e3847b52879"
)
_DETERMINISTIC_ENVELOPE = bytes.fromhex(
    "0300561c474d486946544983444295a55100e155aff2f741bc54864c4f438bae654e"
    "5398f5452900464a144ebd5052f7c2f782283b4b87a357"
)


def _databases() -> SQLiteDatabaseSet:
    return SQLiteDatabaseSet(
        library=b"",
        locations=_LOCATIONS,
        dynamic=b"",
        extras=b"",
        genius=b"",
        locations_cbk=_RANDOMIZED_CBK,
    )


def test_hashab_checksum_book_verifies_its_stored_randomized_envelope() -> None:
    assert verify_locations_cbk(_databases(), WriteChecksum.HASHAB, _GUID)


def test_hashab_checksum_book_construction_remains_deterministic() -> None:
    expected = _DETERMINISTIC_ENVELOPE + _RANDOMIZED_CBK[57:]

    assert build_locations_cbk(_LOCATIONS, WriteChecksum.HASHAB, _GUID) == expected
    assert verify_locations_cbk(
        replace(_databases(), locations_cbk=expected), WriteChecksum.HASHAB, _GUID
    )
    # A randomized verification must not change later deterministic construction.
    assert verify_locations_cbk(_databases(), WriteChecksum.HASHAB, _GUID)
    assert build_locations_cbk(_LOCATIONS, WriteChecksum.HASHAB, _GUID) == expected


@pytest.mark.parametrize(
    "offset",
    [0, 2, 3, 57, 77, len(_RANDOMIZED_CBK) - 1],
    ids=["prefix", "random", "ciphertext", "aggregate", "first-block", "last-block"],
)
def test_hashab_checksum_book_rejects_corruption(offset: int) -> None:
    changed = bytearray(_RANDOMIZED_CBK)
    changed[offset] ^= 1

    assert not verify_locations_cbk(
        replace(_databases(), locations_cbk=bytes(changed)), WriteChecksum.HASHAB, _GUID
    )


@pytest.mark.parametrize("length", [0, 1, 56, 57, 76, 77, len(_RANDOMIZED_CBK) - 1])
def test_hashab_checksum_book_rejects_truncation(length: int) -> None:
    assert not verify_locations_cbk(
        replace(_databases(), locations_cbk=_RANDOMIZED_CBK[:length]),
        WriteChecksum.HASHAB,
        _GUID,
    )


def test_hashab_checksum_book_rejects_trailing_bytes() -> None:
    assert not verify_locations_cbk(
        replace(_databases(), locations_cbk=_RANDOMIZED_CBK + b"\0"),
        WriteChecksum.HASHAB,
        _GUID,
    )


@pytest.mark.parametrize("guid", [bytes(8), b"", bytes(7), bytes(9)])
def test_hashab_checksum_book_rejects_wrong_or_invalid_guid(guid: bytes) -> None:
    assert not verify_locations_cbk(_databases(), WriteChecksum.HASHAB, guid)


def test_hashab_checksum_book_rejects_changed_locations_bytes() -> None:
    changed = bytearray(_LOCATIONS)
    changed[1024] ^= 1

    assert not verify_locations_cbk(
        replace(_databases(), locations=bytes(changed)), WriteChecksum.HASHAB, _GUID
    )
