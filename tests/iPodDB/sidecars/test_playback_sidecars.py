import struct

import pytest

from iPodDB.sidecars import remap_playback_sidecar


def play_counts(rows: tuple[bytes, ...], endian: str = "<") -> bytes:
    header = bytearray(b"\x5a" * 96)
    header[:4] = b"mhdp" if endian == "<" else b"pdhm"
    struct.pack_into(endian + "III", header, 4, 96, 28, len(rows))
    return bytes(header) + b"".join(rows)


@pytest.mark.parametrize("endian", ["<", ">"])
def test_play_counts_preserve_opaque_rows_and_unknown_header_during_removal(
    endian: str,
) -> None:
    rows = tuple(bytes([i]) * 28 for i in (1, 2, 3))
    original = play_counts(rows, endian)
    result = remap_playback_sidecar(original, (10, 20, 30), (30, 10, -1))
    assert result[:12] == original[:12]
    assert struct.unpack_from(endian + "I", result, 12)[0] == 2
    assert result[16:96] == original[16:96]
    assert result[96:] == rows[2] + rows[0]


def test_appending_tracks_preserves_the_exact_pending_history() -> None:
    data = play_counts((b"\x01" * 28, b"\x02" * 28))
    assert remap_playback_sidecar(data, (1, 2), (1, 2, -1, -2)) == data


@pytest.mark.parametrize("endian", ["<", ">"])
def test_on_the_go_positions_follow_retained_tracks_and_preserve_duplicates(
    endian: str,
) -> None:
    header = (b"mhpo" if endian == "<" else b"ophm") + struct.pack(
        endian + "IIII", 20, 8, 3, 123
    )
    data = header + b"".join(struct.pack(endian + "II", p, 456) for p in (2, 0, 2))
    result = remap_playback_sidecar(data, (10, 20, 30), (30, 20, -1))
    assert struct.unpack_from(endian + "I", result, 12)[0] == 2
    assert result[16:20] == data[16:20]
    assert result[20:] == struct.pack(endian + "IIII", 0, 456, 0, 456)


@pytest.mark.parametrize("mutation", ["short", "count", "gap"])
def test_unrecognized_or_unrepresentable_history_is_rejected(mutation: str) -> None:
    data = play_counts((b"\x01" * 28,))
    if mutation == "short":
        data = data[:-1]
    with pytest.raises(ValueError):
        remap_playback_sidecar(
            data,
            () if mutation == "count" else (1,),
            (-1, 1) if mutation == "gap" else (1,),
        )
