from __future__ import annotations

import struct
from io import BytesIO

import pytest

from iopenpod.itunesdb_parser import parse_itunesdb
from iopenpod.itunesdb_shared.constants import MHOD_TYPE_PODCAST_RSS_URL
from iopenpod.itunesdb_shared.extraction import extract_mhod_strings
from iopenpod.itunesdb_writer.mhbd_writer import write_mhbd
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhod_writer import (
    MHOD_URL_MAX_UTF8_BYTES,
    write_mhod_podcast_url,
)
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo, PlaylistItemMeta


def _first_track(data: bytes) -> dict:
    db = parse_itunesdb(BytesIO(data))
    track_dataset = next(
        child["data"]
        for child in db["children"]
        if child["chunk_type"] == "mhsd" and child["data"]["dataset_type"] == 1
    )
    return track_dataset["children"][0]["data"][0]["data"]


def _first_mhit_child_count(data: bytes) -> tuple[int, int]:
    offset = data.find(b"mhit")
    assert offset >= 0
    header_length = struct.unpack_from("<I", data, offset + 4)[0]
    total_length = struct.unpack_from("<I", data, offset + 8)[0]
    declared_count = struct.unpack_from("<I", data, offset + 0x0C)[0]

    actual_count = 0
    child_offset = offset + header_length
    end = offset + total_length
    while child_offset < end:
        assert data[child_offset:child_offset + 4] == b"mhod"
        child_length = struct.unpack_from("<I", data, child_offset + 8)[0]
        child_offset += child_length
        actual_count += 1

    return declared_count, actual_count


def test_track_writer_sanitizes_poisoned_scalar_metadata() -> None:
    track = TrackInfo(
        title="",
        location=":iPod_Control:Music:F00:BAD.mp3",
        size=-1,
        length=180_000,
        sample_rate=96_000,
        rating=250,
        volume=999,
        start_time=200_000,
        stop_time=1_000,
        bookmark_time=999_999,
        play_count=-3,
        skip_count=-4,
        bpm="fast",  # type: ignore[arg-type]
        db_track_id=-5,
    )

    data = write_mhbd([track])
    parsed = _first_track(data)
    strings = extract_mhod_strings(parsed["children"])

    assert strings["Title"] == "Unknown Title"
    assert parsed["size"] == 0
    assert parsed["sample_rate_1"] == 48_000
    assert parsed["rating"] == 100
    assert parsed["volume"] == 255
    assert parsed["start_time"] == 0
    assert parsed["stop_time"] == 0
    assert parsed["bookmark_time"] == 180_000
    assert parsed["play_count_1"] == 0
    assert parsed["skip_count"] == 0
    assert parsed["bpm"] == 0
    assert parsed["db_track_id"] > 0
    assert _first_mhit_child_count(data) == (2, 2)


def test_track_writer_refuses_missing_ipod_location() -> None:
    with pytest.raises(ValueError, match="iPod location"):
        write_mhbd([TrackInfo(title="No Path", location="")])


def test_podcast_url_mhod_is_capped() -> None:
    blob = write_mhod_podcast_url(
        MHOD_TYPE_PODCAST_RSS_URL,
        "https://example.test/" + ("a" * 20_000),
    )

    assert len(blob) == 24 + MHOD_URL_MAX_UTF8_BYTES
    assert len(blob[24:]) == MHOD_URL_MAX_UTF8_BYTES


def test_playlist_remap_drops_stale_item_metadata_instead_of_misaligning() -> None:
    tracks = [
        TrackInfo("One", ":iPod_Control:Music:F00:ONE.mp3", db_track_id=101),
        TrackInfo("Two", ":iPod_Control:Music:F00:TWO.mp3", db_track_id=202),
    ]
    playlist = PlaylistInfo(
        name="",
        track_ids=[101, 202],
        playlist_description="",
        item_metadata=[PlaylistItemMeta(group_id=123)],
    )

    data = write_mhbd(tracks, playlists_type2=[playlist])
    db = parse_itunesdb(BytesIO(data))
    playlist_dataset = next(
        child["data"]
        for child in db["children"]
        if child["chunk_type"] == "mhsd" and child["data"]["dataset_type"] == 2
    )
    user_playlist = playlist_dataset["children"][0]["data"][1]["data"]
    strings = extract_mhod_strings(user_playlist["mhod_children"])

    assert strings["Title"] == "Playlist"
    assert len(user_playlist["mhip_children"]) == 2
