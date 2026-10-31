"""Small synthetic Phase format fixtures; no firmware or game assets required."""

import struct
from dataclasses import replace
from hashlib import md5
from typing import Literal, Protocol, cast

import pytest
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA1
from Crypto.PublicKey import RSA
from tests.iPodDB.library.test_writing import library

from iPodDB.games import (
    PhaseBeat,
    PhaseChart,
    PhaseTransient,
    build_phase_analysis,
    phase,
)
from iPodDB.games.phase import PhaseLibrary, PhaseTrack, build_library, parse_library
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.library import IPodLibrary


class _EcbCipher(Protocol):
    def decrypt(self, ciphertext: bytes) -> bytes: ...


class _EcbFactory(Protocol):
    def __call__(self, key: bytes, mode: Literal[1]) -> _EcbCipher: ...


# Keep verification independent of Phase's encryption adapter, while isolating
# the upstream AES.new CTR overload's untyped counter parameter.
_NEW_ECB = cast("_EcbFactory", AES.new)  # pyright: ignore[reportUnknownMemberType]


def test_index_native_offsets_and_lossless_roundtrip() -> None:
    record = PhaseTrack(0x8877665544332211, 7, 154)
    index = PhaseLibrary(0xFEDCBA9876543210, (record,))
    data = build_library(index)
    assert len(data) == 384
    assert data[0x24:0x2C] == bytes.fromhex("1032547698BADCFE")
    assert data[0x148:0x158] == bytes.fromhex("1122334455667788070000009A000000")
    assert phase.analysis_relative_path(record) == "Phase Data/F007/8877665544332211"
    assert parse_library(data) == index
    assert parse_library(build_library(PhaseLibrary(0))) == PhaseLibrary(0)
    with pytest.raises(ValueError):
        build_library(PhaseLibrary(1, (record, record)))
    with pytest.raises(ValueError):
        parse_library(data[:-1])
    changed = bytearray(data)
    changed[0x40] = 1
    with pytest.raises(ValueError, match="losslessly"):
        parse_library(bytes(changed))


@pytest.mark.parametrize("length_ms", [30_000, 180_000, 1_800_999])
def test_placeholder_envelope_integrity_events_and_duration(
    monkeypatch: pytest.MonkeyPatch, length_ms: int
) -> None:
    # Our test key permits independent inspection without the game's private key.
    key = RSA.generate(1024)
    monkeypatch.setattr(phase, "_PUBLIC_KEY", key.public_key().export_key(format="DER"))
    encoded = phase.placeholder_analysis(length_ms)
    assert encoded[:8] == b"pha\x02\x01\0\0\0"
    wrapped_size = struct.unpack_from("<H", encoded, 8)[0]
    secret = PKCS1_OAEP.new(key, hashAlgo=SHA1).decrypt(encoded[10 : 10 + wrapped_size])
    plain = _NEW_ECB(secret, AES.MODE_ECB).decrypt(encoded[10 + wrapped_size :])
    assert md5(plain).digest() == secret
    assert plain[:8] == b"head\x10\0\0\0"
    cursor = 24
    for tag, stride in ((b"tran", 7), (b"beat", 6)):
        assert plain[cursor : cursor + 4] == tag
        size, count = struct.unpack_from("<II", plain, cursor + 4)
        assert count == length_ms // 1000
        assert size == 4 + count * stride
        events = cursor + 12
        assert plain[events] == 255
        assert struct.unpack_from("<I", plain, events + 1)[0] == 0
        final = events + (count - 1) * stride
        assert struct.unpack_from("<I", plain, final + 1)[0] == (count - 1) << 16
        cursor += 8 + size
    assert plain[cursor:] == bytes(len(plain) - cursor)


def test_native_key_width_and_duration_limits() -> None:
    assert struct.unpack_from("<H", phase.placeholder_analysis(30_000), 8)[0] == 64
    for duration in (0, 29_999, 1_801_000):
        with pytest.raises(ValueError):
            phase.placeholder_analysis(duration)


@pytest.mark.parametrize(
    "chart",
    [
        PhaseChart((PhaseTransient(1, 32, 0, 0),)),
        PhaseChart((PhaseTransient(-1, 1, 1, 1),)),
        PhaseChart((PhaseTransient(2, 1, 1, 1), PhaseTransient(1, 1, 1, 1))),
        PhaseChart(beats=(PhaseBeat(0, 16, 0),)),
    ],
)
def test_general_chart_rejects_invalid_magnitudes_and_event_order(
    chart: PhaseChart,
) -> None:
    with pytest.raises(ValueError):
        build_phase_analysis(chart)


def test_phase_selection_writes_both_playlist_mirrors_and_can_be_cleared() -> None:
    source = library(mirrored=True)
    for selected in (True, False):
        desired = replace(
            source.snapshot,
            playlists=tuple(
                replace(p, is_phase=selected) for p in source.snapshot.playlists
            ),
        )
        result = source.prepare(source.analyze(source.begin_draft(desired)))
        assert result.prepared is not None, result.issues
        document = parse_iTunesDB(result.prepared.itunes)
        headers = [
            s.chunk.header
            for s in document.find_chunks(MhypHeader)
            if s.chunk.header.playlist_id == 10
        ]
        assert len(headers) == 2
        assert all(h.phase_game_flag == (25 if selected else 0) for h in headers)
        source = IPodLibrary(result.prepared.itunes)
        assert not source.snapshot.playlists[0].is_phase  # Value 25 is not selection.
        source = source.with_phase_playlist(10 if selected else 0)
        assert source.snapshot.playlists[0].is_phase is selected
        noop = source.prepare(source.analyze(source.begin_draft()))
        assert noop.prepared is not None
        assert noop.prepared.itunes == result.prepared.itunes
