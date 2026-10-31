"""Phase's companion index and typed gameplay-chart codecs.

Formats verified with build 3168002; see docs/research/phase-playlist-contract.md.
This module has no device access. The RSA key is the game's public asset key.
"""

import struct
from dataclasses import dataclass
from hashlib import md5
from typing import Literal, Protocol, cast

from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.Hash import SHA1
from Crypto.PublicKey import RSA


class _EcbCipher(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...


class _EcbFactory(Protocol):
    def __call__(self, key: bytes, mode: Literal[1]) -> _EcbCipher: ...


# AES.new's unrelated CTR overload has an untyped counter parameter. Keep the
# upstream stub defect at this boundary and expose only the ECB signature used.
_NEW_ECB = cast("_EcbFactory", AES.new)  # pyright: ignore[reportUnknownMemberType]

_PUBLIC_KEY = bytes.fromhex(
    "305c300d06092a864886f70d0101010500034b003048024100d9a82573e52bfce95e63bc"
    "ac16e8df69de9b44b6a6c59111bf9253134df53b4ff0f64111da32def066b273576527"
    "6bba0ab5892145c7f5d87c358160437cab3d0203010001"
)


@dataclass(frozen=True, slots=True)
class PhaseTrack:
    persistent_id: int
    shard: int
    analysis_size: int


@dataclass(frozen=True, slots=True)
class PhaseLibrary:
    playlist_id: int
    tracks: tuple[PhaseTrack, ...] = ()


@dataclass(frozen=True, slots=True)
class PhaseTransient:
    time_q16: int
    low: int
    mid: int
    high: int


@dataclass(frozen=True, slots=True)
class PhaseBeat:
    time_q16: int
    strength: int
    accent: int


@dataclass(frozen=True, slots=True)
class PhaseChart:
    transients: tuple[PhaseTransient, ...] = ()
    beats: tuple[PhaseBeat, ...] = ()


def build_analysis(chart: PhaseChart) -> bytes:
    """Encode bounded event streams in the native PHZ envelope."""
    if len(chart.transients) > 20_000 or len(chart.beats) > 20_000:
        raise ValueError("Too many Phase analysis events.")
    transients = bytearray(struct.pack("<I", len(chart.transients)))
    beats = bytearray(struct.pack("<I", len(chart.beats)))
    previous = -1
    for transient in chart.transients:
        if not previous < transient.time_q16 <= 1801 << 16 or any(
            not 0 <= value <= 31
            for value in (transient.low, transient.mid, transient.high)
        ):
            raise ValueError("Invalid Phase transient time or magnitude.")
        previous = transient.time_q16
        transients.extend(
            b"\xff"
            + struct.pack(
                "<IH",
                transient.time_q16,
                transient.low | (transient.mid << 5) | (transient.high << 10),
            )
        )
    previous = -1
    for beat in chart.beats:
        if not previous < beat.time_q16 <= 1801 << 16 or any(
            not 0 <= value <= 15 for value in (beat.strength, beat.accent)
        ):
            raise ValueError("Invalid Phase beat time or magnitude.")
        previous = beat.time_q16
        beats.extend(
            b"\xff"
            + struct.pack("<IB", beat.time_q16, (beat.strength << 4) | beat.accent)
        )
    return _wrap_analysis(bytes(transients), bytes(beats))


def _wrap_analysis(transients: bytes, beats: bytes) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return tag + struct.pack("<I", len(payload)) + payload

    body = (
        chunk(b"head", struct.pack("<H", 1) + bytes(14))
        + chunk(b"tran", transients)
        + chunk(b"beat", beats)
    )
    body += bytes(-len(body) % 16)
    key = md5(body).digest()
    wrapped = PKCS1_OAEP.new(RSA.import_key(_PUBLIC_KEY), hashAlgo=SHA1).encrypt(key)
    return (
        b"pha\x02"
        + struct.pack("<IH", 1, len(wrapped))
        + wrapped
        + _NEW_ECB(key, AES.MODE_ECB).encrypt(body)
    )


def analysis_relative_path(track: PhaseTrack) -> str:
    return f"Phase Data/F{track.shard:03d}/{track.persistent_id:016X}"


def build_library(library: PhaseLibrary) -> bytes:
    """Encode the native-accepted minimal index; PID zero clears selection."""
    if not 0 <= library.playlist_id < 1 << 64:
        raise ValueError("Phase playlist persistent ID must fit uint64.")
    if not library.playlist_id and library.tracks:
        raise ValueError("An unselected Phase Library must have no tracks.")
    if len(library.tracks) > 100_000:
        raise ValueError("Too many Phase tracks.")
    seen: set[int] = set()
    root = bytearray(0x74)
    root[:4] = b"mhfd"
    struct.pack_into("<IIII", root, 4, 0x78, 1, 0, 1)
    struct.pack_into("<I", root, 0x1C, 100 + len(library.tracks))
    struct.pack_into("<Q", root, 0x24, library.playlist_id)
    section = bytearray(0x64)
    section[:4] = b"mhsd"
    struct.pack_into("<I", section, 4, 0x68)
    struct.pack_into("<H", section, 0x10, 1)
    listing = bytearray(0x5C)
    listing[:4] = b"mhlr"
    struct.pack_into("<II", listing, 4, 0x5C, len(library.tracks))
    records = bytearray()
    for record_id, track in enumerate(library.tracks, 100):
        if not 0 < track.persistent_id < 1 << 64 or track.persistent_id in seen:
            raise ValueError("Phase track persistent IDs must be nonzero and unique.")
        if not 0 <= track.shard < 1 << 32 or not 0 < track.analysis_size < 1 << 32:
            raise ValueError("Invalid Phase analysis size or shard.")
        seen.add(track.persistent_id)
        record = bytearray(0x4C)
        record[:4] = b"mhrd"
        struct.pack_into("<IIII", record, 4, 0x50, 0x50, 0, record_id)
        struct.pack_into(
            "<QII", record, 0x14, track.persistent_id, track.shard, track.analysis_size
        )
        records.extend(record)
    blob = root + section + listing + records
    struct.pack_into("<Q", blob, 0x14, len(blob))
    struct.pack_into("<Q", blob, len(root) + 8, len(blob) - len(root))
    return bytes(blob)


def parse_library(data: bytes) -> PhaseLibrary:
    """Read our minimal layout, rejecting unfamiliar data rather than losing it.

    Exact re-encoding is required: an extended index must be preserved until its
    additional fields have a lossless editing implementation.
    """
    if len(data) < 0x134 or len(data) > 8 * 1024 * 1024:
        raise ValueError("Unsupported Phase Library size.")
    count = struct.unpack_from("<I", data, 0xE0)[0]
    if count > 100_000 or len(data) != 0x134 + count * 0x4C:
        raise ValueError("Unsupported Phase Library record layout.")
    result = PhaseLibrary(
        struct.unpack_from("<Q", data, 0x24)[0],
        tuple(
            PhaseTrack(*struct.unpack_from("<QII", data, offset + 0x14))
            for offset in range(0x134, len(data), 0x4C)
        ),
    )
    if build_library(result) != data:
        raise ValueError("This extended Phase Library cannot yet be edited losslessly.")
    return result


def read_playlist_id(data: bytes) -> int:
    """Read selection from the index header without requiring an editable layout."""
    if (
        len(data) < 0x134
        or len(data) > 8 * 1024 * 1024
        or data[:4] != b"mhfd"
        or struct.unpack_from("<I", data, 4)[0] != 0x78
        or struct.unpack_from("<Q", data, 0x14)[0] != len(data)
        or data[0x74:0x78] != b"mhsd"
        or data[0xD8:0xDC] != b"mhlr"
    ):
        raise ValueError("Invalid Phase Library selection header.")
    return int.from_bytes(data[0x24:0x2C], "little")


def placeholder_analysis(length_ms: int) -> bytes:
    """One event per second; no audio decoding, tempo estimation or real analysis."""
    seconds = length_ms // 1000
    if not 30 <= seconds <= 1800:
        raise ValueError("Phase needs a whole-second duration from 30 to 1800.")

    return build_analysis(
        PhaseChart(
            tuple(
                PhaseTransient(second << 16, 16, 16, 16) for second in range(seconds)
            ),
            tuple(PhaseBeat(second << 16, 8, 8) for second in range(seconds)),
        )
    )
