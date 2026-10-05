"""Authored firmware sidecars: fields, bounds, variants, and lossless retention."""

import plistlib
import struct

import pytest

from iPodDB.sidecars import (
    PlaybackDateKind,
    is_playback_sidecar,
    parse_itunes_stats,
    parse_otg_playlist,
    parse_play_counts,
    parse_play_counts_plist,
)


def counts(
    rows: tuple[tuple[int, ...], ...] = (
        (3, 3_800_000_000, 500, 80, 123, 2, 3_800_000_100),
    ),
    *,
    endian: str = "<",
    width: int = 28,
) -> bytes:
    header = bytearray(b"\x5a" * 96)
    header[:4] = b"mhdp" if endian == "<" else b"pdhm"
    struct.pack_into(endian + "III", header, 4, 96, width, len(rows))
    return bytes(header) + b"".join(
        struct.pack(endian + "I" * len(row), *row)[:width].ljust(width, b"\xa5")
        for row in rows
    )


def otg(positions: tuple[int, ...], *, endian: str = "<", width: int = 4) -> bytes:
    return (
        (b"mhpo" if endian == "<" else b"ophm")
        + struct.pack(endian + "IIII", 20, width, len(positions), 999)
        + b"".join(
            struct.pack(endian + "I", p).ljust(width, b"\x5a") for p in positions
        )
    )


def stats(word: int, plays: tuple[int, ...] = (3, 5)) -> bytes:
    rows: list[bytes] = []
    for count in plays:
        fields = (
            (18, 500, 11, 12, count, 1)
            if word == 3
            else (32, 500, count, 1_700_000_000, 1, 1_700_000_100, 11, 12)
        )
        rows.append(b"".join(value.to_bytes(word, "little") for value in fields))
    return len(rows).to_bytes(word, "little") + b"\x00" * word + b"".join(rows)


@pytest.mark.parametrize("endian", ["<", ">"])
@pytest.mark.parametrize("width", [12, 16, 20, 24, 28, 36])
def test_play_counts_variants_keep_every_original_byte(endian: str, width: int) -> None:
    data = counts(endian=endian, width=width)
    document = parse_play_counts(data)
    (entry,) = document.entries
    assert entry.play_count == 3
    assert entry.last_played == 3_800_000_000
    assert entry.bookmark_time_ms == 500
    assert entry.rating == (80 if width >= 16 else None)
    assert entry.skip_count == (2 if width >= 28 else 0)
    assert entry.last_skipped == (3_800_000_100 if width >= 28 else 0)
    assert document.serialize() == data


@pytest.mark.parametrize(
    ("rating", "expected"), [(0, 0), (100, 100), (0xFFFFFFFF, None)]
)
def test_binary_rating_zero_is_a_clear_and_all_ones_is_unavailable(
    rating: int, expected: int | None
) -> None:
    assert (
        parse_play_counts(counts(((0, 0, 0, rating),), width=16)).entries[0].rating
        == expected
    )


@pytest.mark.parametrize("endian", ["<", ">"])
def test_otg_retains_duplicate_positions_and_unknown_extensions(endian: str) -> None:
    data = otg((1, 0, 1), endian=endian, width=8)
    document = parse_otg_playlist(data)
    assert document.positions == (1, 0, 1)
    assert document.table.rows[0][4:] == b"\x5a" * 4
    assert document.serialize() == data


@pytest.mark.parametrize("word", [3, 4])
def test_stats_advances_each_record_and_retains_unknowns(word: int) -> None:
    data = stats(word)
    document = parse_itunes_stats(data)
    assert tuple(e.play_count for e in document.entries) == (3, 5)
    assert document.entries[1].skipped == 1
    assert document.entries[1].skip_count == 0
    assert document.entries[0].date_kind is PlaybackDateKind.UNIX
    assert document.serialize() == data


@pytest.mark.parametrize("fmt", [plistlib.FMT_XML, plistlib.FMT_BINARY])
def test_plist_uses_persistent_identity_and_preserves_unknown_keys(
    fmt: plistlib.PlistFormat,
) -> None:
    data = plistlib.dumps(
        {
            "tracks": [
                {
                    "persistentID": (1 << 63) + 12,
                    "playCount": 4,
                    "skipCount": 2,
                    "userRating": 0,
                    "unknown": b"retained",
                }
            ],
            "extra": [1, 2],
        },
        fmt=fmt,
    )
    document = parse_play_counts_plist(data)
    assert document.entries[0].persistent_id == (1 << 63) + 12
    assert document.entries[0].play_count == 4
    assert document.entries[0].skip_count == 2
    assert document.entries[0].rating is None
    assert document.serialize() == data


@pytest.mark.parametrize("value", [True, "3", -1, 1 << 32])
def test_plist_rejects_invalid_numeric_values(value: object) -> None:
    with pytest.raises(ValueError):
        parse_play_counts_plist(
            plistlib.dumps({"tracks": [{"persistentID": 1, "playCount": value}]})
        )


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"<broken",
        b"bplist00",
        plistlib.dumps({}),
        plistlib.dumps({"tracks": [1]}),
        plistlib.dumps({"tracks": [{"persistentID": 1}, {"persistentID": 1}]}),
    ],
)
def test_malformed_plists_fail_as_format_errors(data: bytes) -> None:
    with pytest.raises(ValueError):
        parse_play_counts_plist(data)


@pytest.mark.parametrize(
    "mutation", ["truncate", "huge_count", "header", "width", "rating"]
)
def test_counts_reject_invalid_framing_and_fields(mutation: str) -> None:
    data = bytearray(counts())
    if mutation == "truncate":
        del data[-1]
    else:
        offset, value = {
            "huge_count": (12, 0xFFFFFFFF),
            "header": (4, 16),
            "width": (8, 0),
            "rating": (108, 101),
        }[mutation]
        struct.pack_into("<I", data, offset, value)
    with pytest.raises(ValueError):
        parse_play_counts(bytes(data))


@pytest.mark.parametrize("word", [3, 4])
def test_stats_rejects_truncated_records(word: int) -> None:
    for data in (stats(word)[:-1], b"\xff" * 8):
        with pytest.raises(ValueError):
            parse_itunes_stats(data)


def test_detection_includes_plist_and_excludes_inactive_backups() -> None:
    assert is_playback_sidecar("PlayCounts.plist")
    assert is_playback_sidecar("OTGPlaylistInfo_20")
    assert not is_playback_sidecar("Play Counts.bak")
    assert not is_playback_sidecar("OTGPlaylistInfo_1.backup")


def test_signed_plist_persistent_ids_keep_the_same_64_bits() -> None:
    data = plistlib.dumps({"tracks": [{"persistentID": -2, "playCount": 1}]})
    assert parse_play_counts_plist(data).entries[0].persistent_id == (1 << 64) - 2


@pytest.mark.parametrize("width", [13, 15, 17, 23, 27, 29])
def test_partial_optional_words_remain_unknown_and_lossless(width: int) -> None:
    data = counts(width=width)
    parsed = parse_play_counts(data)
    assert parsed.serialize() == data
    if width < 16:
        assert parsed.entries[0].unknown == data[108:]
