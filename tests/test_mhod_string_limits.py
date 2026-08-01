from __future__ import annotations

import struct
from io import BytesIO

from iopenpod.application.database_storage import truncate_track_mhod_values
from iopenpod.device import capabilities_for_family_gen
from iopenpod.itunesdb_parser import parse_itunesdb
from iopenpod.itunesdb_shared.constants import MHOD_TYPE_LYRICS, MHOD_TYPE_TITLE
from iopenpod.itunesdb_writer.mhbd_writer import write_mhbd
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhod_writer import (
    MHOD_LONG_TEXT_MAX_UTF16_BYTES,
    MHOD_STRING_MAX_UTF16_BYTES,
    write_mhod_string,
)


def _mhod_string_length(blob: bytes) -> int:
    return struct.unpack_from("<I", blob, 0x1C)[0]


def _first_track(data: bytes) -> dict:
    db = parse_itunesdb(BytesIO(data))
    track_dataset = next(
        child["data"]
        for child in db["children"]
        if child["chunk_type"] == "mhsd" and child["data"]["dataset_type"] == 1
    )
    return track_dataset["children"][0]["data"][0]["data"]


def test_standard_mhod_strings_are_capped() -> None:
    blob = write_mhod_string(MHOD_TYPE_TITLE, "A" * 10_000)

    assert _mhod_string_length(blob) == MHOD_STRING_MAX_UTF16_BYTES
    assert len(blob) == 40 + MHOD_STRING_MAX_UTF16_BYTES


def test_long_text_mhod_strings_are_capped() -> None:
    blob = write_mhod_string(MHOD_TYPE_LYRICS, "A" * 100_000)

    assert _mhod_string_length(blob) == MHOD_LONG_TEXT_MAX_UTF16_BYTES
    assert len(blob) == 40 + MHOD_LONG_TEXT_MAX_UTF16_BYTES


def test_huge_lyrics_tag_does_not_make_a_huge_legacy_itunesdb() -> None:
    data = write_mhbd(
        [
            TrackInfo(
                title="Track With Bad Lyrics",
                location=":iPod_Control:Music:F00:HUGE.m4a",
                lyrics="A" * 1_000_000,
            )
        ],
        capabilities=capabilities_for_family_gen("iPod Mini", "2nd Gen"),
    )

    track = _first_track(data)
    lyrics = next(
        child["data"]["string"]
        for child in track["children"]
        if child["data"]["mhod_type"] == MHOD_TYPE_LYRICS
    )

    assert len(lyrics.encode("utf-16-le")) == MHOD_LONG_TEXT_MAX_UTF16_BYTES
    assert len(data) < 30_000


def test_zero_byte_lyrics_limit_removes_mhod_and_lyrics_flag() -> None:
    track = TrackInfo(
        title="Track With Lyrics",
        location=":iPod_Control:Music:F00:LYRICS.m4a",
        has_lyrics=True,
        lyrics="A lyric that should be removed",
    )

    assert truncate_track_mhod_values([track], MHOD_TYPE_LYRICS, 0) == 1
    assert track.lyrics is None
    assert track.has_lyrics is False

    data = write_mhbd([track])
    parsed_track = _first_track(data)

    assert parsed_track["lyrics_flag"] == 0
    assert all(
        child["data"]["mhod_type"] != MHOD_TYPE_LYRICS
        for child in parsed_track["children"]
    )


def test_truncation_keeps_only_complete_utf16_codepoints() -> None:
    track = TrackInfo(
        title="Track",
        location=":iPod_Control:Music:F00:UNICODE.m4a",
        lyrics="A🙂B",
    )

    assert truncate_track_mhod_values([track], MHOD_TYPE_LYRICS, 6) == 1
    assert track.lyrics == "A🙂"
    assert len(track.lyrics.encode("utf-16-le")) == 6
