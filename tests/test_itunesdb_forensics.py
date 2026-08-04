from __future__ import annotations

import struct
from io import BytesIO

from iopenpod.itunesdb_parser import parse_itunesdb
from iopenpod.itunesdb_parser._parsing import preserve_raw_chunks
from iopenpod.itunesdb_parser.chunk_parser import parse_chunk
from iopenpod.itunesdb_parser.forensics import (
    forensic_json_document,
    reconstruct_byte_walk,
)
from iopenpod.itunesdb_shared.extraction import extract_mhod_strings
from iopenpod.itunesdb_writer.mhbd_writer import write_mhbd
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo


def _phase_playlists(database: dict) -> list[dict]:
    found: list[dict] = []

    def visit(child: dict) -> None:
        if child["chunk_type"] == "mhyp":
            playlist = child["data"]
            title = extract_mhod_strings(playlist["mhod_children"]).get("Title")
            if title == "Phase Music":
                found.append(child)
        payload = child["data"]
        nested_children = payload if isinstance(payload, list) else payload.get("children", [])
        for nested in nested_children:
            visit(nested)
        if child["chunk_type"] == "mhyp":
            for nested in child["data"].get("mhod_children", []):
                visit(nested)
            for nested in child["data"].get("mhip_children", []):
                visit(nested)

    for child in database["children"]:
        visit(child)
    return found


def _raw_spans(database: dict) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []

    def record(raw: dict) -> None:
        offset = raw["offset"]
        spans.append((offset, offset + len(raw["raw_header"])))
        if raw["unparsed_bytes"]:
            spans.append((raw["end_offset"] - len(raw["unparsed_bytes"]), raw["end_offset"]))

    def visit(child: dict) -> None:
        record(child["_raw_chunk"])
        payload = child["data"]
        nested_children = payload if isinstance(payload, list) else payload.get("children", [])
        for nested in nested_children:
            visit(nested)
        if isinstance(payload, dict):
            for nested in payload.get("mhod_children", []):
                visit(nested)
            for nested in payload.get("mhip_children", []):
                visit(nested)

    record(database["_raw_chunk"])
    for child in database["children"]:
        visit(child)
    return spans


def _walk_byte_chunks(chunk: dict):
    yield chunk
    for entry in chunk["bytes"]:
        if "chunk" in entry:
            yield from _walk_byte_chunks(entry["chunk"])


def _byte_at(chunk: dict, offset: str) -> dict:
    return next(entry for entry in chunk["bytes"] if entry["at"] == offset)


def test_forensic_parse_preserves_phase_marker_headers_and_mhod_bodies() -> None:
    database = bytearray(
        write_mhbd([], playlists_type2=[PlaylistInfo(name="Phase Music")]),
    )
    phase_title = "Phase Music".encode("utf-16-le")
    cursor = 0
    while (title_offset := database.find(phase_title, cursor)) >= 0:
        playlist_offset = database.rfind(b"mhyp", 0, title_offset)
        struct.pack_into("<H", database, playlist_offset + 0x52, 0x19)
        cursor = title_offset + len(phase_title)

    ordinary = parse_itunesdb(BytesIO(database))
    assert "_raw_chunk" not in ordinary

    parsed = parse_itunesdb(BytesIO(database), preserve_raw=True)
    playlists = _phase_playlists(parsed)

    assert playlists
    for playlist_child in playlists:
        raw_playlist = playlist_child["_raw_chunk"]
        assert raw_playlist["raw_header"][0x52:0x54] == b"\x19\x00"
        title_child = playlist_child["data"]["mhod_children"][0]
        assert title_child["_raw_chunk"]["unparsed_bytes"].endswith(phase_title)


def test_forensic_json_keeps_readable_fields_and_raw_phase_evidence(tmp_path) -> None:
    source = tmp_path / "iTunesDB"
    database = bytearray(
        write_mhbd([], playlists_type2=[PlaylistInfo(name="Phase Music")]),
    )
    phase_title = "Phase Music".encode("utf-16-le")
    title_offset = database.find(phase_title)
    playlist_offset = database.rfind(b"mhyp", 0, title_offset)
    struct.pack_into("<H", database, playlist_offset + 0x52, 0x19)
    source.write_bytes(database)

    document = forensic_json_document(source)
    phase = next(
        chunk
        for chunk in _walk_byte_chunks(document["file"])
        if chunk["chunk"] == "mhyp" and chunk["caption"] == "Playlist: Phase Music"
    )
    marker = _byte_at(phase, "0x0052")
    gap = _byte_at(phase, "0x004C")
    title = next(
        chunk
        for chunk in _walk_byte_chunks(phase)
        if chunk["chunk"] == "mhod"
        and any(entry.get("value") == "Phase Music" for entry in chunk["bytes"])
    )
    title_text = next(entry for entry in title["bytes"] if entry.get("field") == "text")

    assert document["format"] == "iopenpod-byte-walk/v1"
    assert document["source"]["byte_length"] == len(database)
    assert reconstruct_byte_walk(document) == bytes(database)
    assert marker["hex"] == "19 00"
    assert marker["field"] == "phase_game_flag"
    assert marker["value"] == 25
    assert marker["status"] == "observed"
    assert gap == {
        "at": "0x004C",
        "byte_length": 4,
        "hex": "00 00 00 00",
        "status": "unmapped",
    }
    assert title_text["hex"] == _spaced_hex(phase_title)
    assert title_text["value"] == "Phase Music"


def test_phase_game_flag_round_trips_through_parser_and_writer() -> None:
    database = write_mhbd(
        [],
        playlists_type2=[PlaylistInfo(name="Phase Music", phase_game_flag=25)],
    )

    parsed = parse_itunesdb(BytesIO(database), preserve_raw=True)
    playlists = _phase_playlists(parsed)

    assert len(playlists) == 2
    for playlist_child in playlists:
        playlist = playlist_child["data"]
        assert playlist["phase_game_flag"] == 25
        assert playlist_child["_raw_chunk"]["raw_header"][0x52:0x54] == b"\x19\x00"


def _spaced_hex(value: bytes) -> str:
    return value.hex(" ")


def test_forensic_parse_preserves_unknown_mhod_body_verbatim() -> None:
    body = b"\x00\xFFPhase\x19"
    chunk = bytearray(24 + len(body))
    struct.pack_into("<4sII", chunk, 0, b"mhod", 24, len(chunk))
    struct.pack_into("<I", chunk, 12, 0xBEEF)
    chunk[24:] = body

    with preserve_raw_chunks(True):
        parsed, chunk_type = parse_chunk(chunk, 0)

    assert chunk_type == "mhod"
    assert parsed["data"]["mhod_type"] == 0xBEEF
    assert parsed["_raw_chunk"]["raw_header"] == bytes(chunk[:24])
    assert parsed["_raw_chunk"]["unparsed_bytes"] == body


def test_forensic_parse_preserves_genius_dataset_payload_verbatim() -> None:
    body = b"41bac68ce330182aeedfdc61bdb677e8"
    chunk = bytearray(96 + len(body))
    struct.pack_into("<4sII", chunk, 0, b"mhsd", 96, len(chunk))
    struct.pack_into("<I", chunk, 0x0C, 9)
    chunk[96:] = body

    with preserve_raw_chunks(True):
        parsed, chunk_type = parse_chunk(chunk, 0)

    assert chunk_type == "mhsd"
    assert parsed["data"]["raw_payload"] == body
    assert parsed["_raw_chunk"]["unparsed_bytes"] == body


def test_forensic_parse_records_every_byte_without_container_duplication() -> None:
    source = write_mhbd([], playlists_type2=[PlaylistInfo(name="Forensics")])
    parsed = parse_itunesdb(BytesIO(source), preserve_raw=True)
    merged: list[list[int]] = []

    for start, end in sorted(_raw_spans(parsed)):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)

    assert merged == [[0, len(source)]]


def test_forensic_parse_preserves_container_trailer_bytes() -> None:
    playlist = bytearray(184 + 3)
    struct.pack_into("<4sII", playlist, 0, b"mhyp", 184, len(playlist))

    with preserve_raw_chunks(True):
        parsed, chunk_type = parse_chunk(playlist, 0)

    assert chunk_type == "mhyp"
    assert parsed["_raw_chunk"]["unparsed_bytes"] == b"\x00\x00\x00"
