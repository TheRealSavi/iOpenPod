"""Apple-evidenced HASHAB regressions without storing private device databases."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk, new_iTunesDB
from iPodDB.iTunesDB.cdb import compress_iTunesCDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhlt import DEFINITION as MHLT_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.writer.signature import (
    compute_hashab,
    sign_hashab,
    verify_hashab,
    verify_hashab_signature,
)
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library.writing import WriteChecksum
from iPodDB.shared.chunk import EmptyChunkHeader
from iPodDB.SQLiteDB.artifacts import SQLiteDatabaseSet
from iPodDB.SQLiteDB.checksum import verify_locations_cbk

_FIXTURE = Path(__file__).parents[2] / "fixtures/iTunesDB/nano6-hashab-envelopes.json"
_CAPTURE_ENV = "IOPENPOD_NANO6_CAPTURES"
_CDB_PATH = Path("iPod_Control/iTunes/iTunesCDB")


@dataclass(frozen=True)
class _SignatureCase:
    name: str
    guid: bytes
    database: bytes
    legacy_wrong_scheme: bytes
    expected_resigned: bytes
    random_part: bytes
    signature: bytes
    scheme3_digest: bytes
    scheme4_digest: bytes


def _cases() -> tuple[_SignatureCase, ...]:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return tuple(
        _SignatureCase(
            name=entry["name"],
            guid=bytes.fromhex(fixture["guid"]),
            database=base64.b64decode(entry["database_base64"], validate=True),
            legacy_wrong_scheme=base64.b64decode(
                entry["legacy_wrong_scheme_base64"], validate=True
            ),
            expected_resigned=base64.b64decode(
                entry["expected_resigned_base64"], validate=True
            ),
            random_part=bytes.fromhex(entry["random_part"]),
            signature=bytes.fromhex(entry["signature"]),
            scheme3_digest=bytes.fromhex(entry["scheme3_digest"]),
            scheme4_digest=bytes.fromhex(entry["scheme4_digest"]),
        )
        for entry in fixture["cases"]
    )


@pytest.fixture(params=_cases(), ids=lambda case: case.name)
def case(request: pytest.FixtureRequest) -> _SignatureCase:
    result = request.param
    assert isinstance(result, _SignatureCase)
    return result


def test_verifies_apple_style_random_envelope(case: _SignatureCase) -> None:
    assert verify_hashab(case.database, case.guid)


def test_randomized_envelope_matches_independent_reference(
    case: _SignatureCase,
) -> None:
    assert (
        compute_hashab(case.scheme3_digest, case.guid, random_part=case.random_part)
        == case.signature
    )
    assert verify_hashab_signature(case.scheme3_digest, case.guid, case.signature)
    assert not verify_hashab_signature(case.scheme4_digest, case.guid, case.signature)
    # Custom randomness cannot leak into a later deterministic signing call.
    assert (
        compute_hashab(case.scheme3_digest, case.guid)
        == (case.expected_resigned[0xAB:0xE4])
    )


@pytest.mark.parametrize("length", [0, 22, 24])
def test_compute_rejects_malformed_random_part(
    case: _SignatureCase, length: int
) -> None:
    with pytest.raises(ValueError, match="23"):
        compute_hashab(case.scheme3_digest, case.guid, random_part=bytes(length))


@pytest.mark.parametrize("length", [0, 19, 21])
def test_envelope_verifier_rejects_malformed_digest(
    case: _SignatureCase, length: int
) -> None:
    assert not verify_hashab_signature(bytes(length), case.guid, case.signature)


@pytest.mark.parametrize("length", [0, 56, 58])
def test_envelope_verifier_rejects_malformed_signature(
    case: _SignatureCase, length: int
) -> None:
    signature = (case.signature + b"\0")[:length]
    assert not verify_hashab_signature(case.scheme3_digest, case.guid, signature)


def test_signing_matches_independent_scheme_three_reference(
    case: _SignatureCase,
) -> None:
    # Expected bytes were fixed using the independently checked upstream routine,
    # not by sign_hashab or verify_hashab. A producer/verifier agreement is weaker.
    assert sign_hashab(case.database, case.guid) == case.expected_resigned
    assert sign_hashab(case.legacy_wrong_scheme, case.guid) == case.expected_resigned
    assert case.expected_resigned[:0xAB] == case.database[:0xAB]
    assert case.expected_resigned[0xE4:] == case.database[0xE4:]


@pytest.mark.parametrize("published_scheme", [0, 1, 2, 3, 4])
def test_rejects_legacy_signature_covering_scheme_four(
    case: _SignatureCase, published_scheme: int
) -> None:
    corrupt = bytearray(case.legacy_wrong_scheme)
    corrupt[0x30:0x32] = published_scheme.to_bytes(2, "little")
    assert not verify_hashab(bytes(corrupt), case.guid)


@pytest.mark.parametrize("offset", [0x46, 0xAB, 0xAC, 0xAD, 0xAE, -1])
def test_rejects_tampered_content_prefix_random_and_ciphertext(
    case: _SignatureCase, offset: int
) -> None:
    corrupt = bytearray(case.database)
    corrupt[offset] ^= 1
    assert not verify_hashab(bytes(corrupt), case.guid)


@pytest.mark.parametrize("guid", [b"", bytes(7), bytes(8), bytes(9)])
def test_rejects_wrong_or_malformed_guid(case: _SignatureCase, guid: bytes) -> None:
    assert not verify_hashab(case.database, guid)


@pytest.mark.parametrize("length", [0, 4, 11, 12, 0xAB, 0xE3])
def test_rejects_truncated_root(case: _SignatureCase, length: int) -> None:
    assert not verify_hashab(case.database[:length], case.guid)


@pytest.mark.parametrize("header_size", [0, 11, 0xAB, 0xE3, 0xFFFFFFFF])
def test_rejects_invalid_header_size(case: _SignatureCase, header_size: int) -> None:
    corrupt = bytearray(case.database)
    corrupt[4:8] = header_size.to_bytes(4, "little")
    assert not verify_hashab(bytes(corrupt), case.guid)


def test_fixture_contains_only_fresh_allowlisted_database_bytes(
    case: _SignatureCase,
) -> None:
    # The signature cannot survive anonymizing an Apple database. These examples
    # retain only its random-envelope bytes, then sign a fresh synthetic database.
    number = {"apple-empty-envelope": 1, "apple-synced-envelope": 2}[case.name]
    document = new_iTunesDB(
        MhbdHeader(
            compressed=2,
            version=117,
            db_id=1000 + number,
            platform=2,
            db_id_2=2000 + number,
            hashing_scheme=3,
            db_persistent_id=3000 + number,
            hash_type_indicator=4,
            unk_mhbd_0x50=0,
            unk_mhbd_0x54=0,
        ),
        datasets=(
            new_itunes_chunk(
                MHSD_DEFINITION,
                MhsdHeader(dataset_type=1),
                children=(new_itunes_chunk(MHLT_DEFINITION, EmptyChunkHeader()),),
            ),
        ),
    )
    expected = compress_iTunesCDB(write_iTunesDB(document))
    for stored in (case.database, case.legacy_wrong_scheme, case.expected_resigned):
        unsigned = bytearray(stored)
        unsigned[0xAB:0xE4] = bytes(57)
        assert bytes(unsigned) == expected
    assert case.guid == bytes.fromhex("0123456789abcdef")


@pytest.fixture
def private_captures() -> tuple[Path, bytes]:
    location = os.environ.get(_CAPTURE_ENV)
    if location is None:
        pytest.skip(f"Set {_CAPTURE_ENV} to run against the private Nano 6 captures.")
    root = Path(location)
    sysinfo = (root / "v2 bad/iPod_Control/Device/SysInfo").read_text(encoding="utf-8")
    match = re.search(r"(?im)^FirewireGuid:\s*0x([0-9a-f]{16})\s*$", sysinfo)
    assert match is not None, "Private capture lacks a usable device GUID"
    return root, bytes.fromhex(match.group(1))


@pytest.mark.parametrize(
    ("name", "expected"),
    [("fresh apple", True), ("apple", True), ("v1 bad ig", False), ("v2 bad", False)],
)
def test_private_cdb_captures(
    private_captures: tuple[Path, bytes], name: str, expected: bool
) -> None:
    root, guid = private_captures
    captured = (root / name / _CDB_PATH).read_bytes()
    assert verify_hashab(captured, guid) is expected


def test_private_v2_signature_only_repair_matches_diagnostic_candidate(
    private_captures: tuple[Path, bytes],
) -> None:
    root, guid = private_captures
    captured = (root / "v2 bad" / _CDB_PATH).read_bytes()
    corrected = sign_hashab(captured, guid)
    assert hashlib.sha256(corrected).hexdigest() == (
        "d6a93a6406547413e2a3a1c5d16f6743b4631ec75b576dbc17b94693545050d3"
    )
    assert corrected[:0xAB] == captured[:0xAB]
    assert corrected[0xE4:] == captured[0xE4:]
    assert verify_hashab(corrected, guid)


@pytest.mark.parametrize("name", ["fresh apple", "apple", "v1 bad ig", "v2 bad"])
def test_private_locations_checksum_books(
    private_captures: tuple[Path, bytes], name: str
) -> None:
    root, guid = private_captures
    directory = root / name / "iPod_Control/iTunes/iTunes Library.itlp"
    databases = SQLiteDatabaseSet(
        library=b"",
        locations=(directory / "Locations.itdb").read_bytes(),
        dynamic=b"",
        extras=b"",
        genius=b"",
        locations_cbk=(directory / "Locations.itdb.cbk").read_bytes(),
    )
    assert verify_locations_cbk(databases, WriteChecksum.HASHAB, guid)
