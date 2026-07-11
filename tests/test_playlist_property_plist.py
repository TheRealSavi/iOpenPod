import plistlib

from iopenpod.itunesdb_parser.mhod_parser import parse_mhod
from iopenpod.itunesdb_shared.constants import MHOD_TYPE_PLAYLIST_PROPERTY_PLIST
from iopenpod.itunesdb_shared.extraction import extract_playlist_extras
from iopenpod.itunesdb_shared.mhod_defs import MHOD_HEADER_SIZE, write_mhod_header
from iopenpod.itunesdb_shared.playlist_properties import (
    normalize_playlist_description,
    playlist_description_from_row,
    playlist_description_update_fields,
    playlist_property_raw_body_for_write,
)
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo, write_playlist


def test_mhod55_playlist_property_plist_decodes_and_preserves_raw_body() -> None:
    body = plistlib.dumps({"description": "inside folder?"}, fmt=plistlib.FMT_BINARY)
    blob = write_mhod_header(
        MHOD_TYPE_PLAYLIST_PROPERTY_PLIST,
        MHOD_HEADER_SIZE + len(body),
    ) + body

    parsed = parse_mhod(blob, 0, MHOD_HEADER_SIZE, len(blob))["data"]

    assert parsed["mhod_type"] == MHOD_TYPE_PLAYLIST_PROPERTY_PLIST
    assert parsed["data"]["description"] == "inside folder?"
    assert parsed["data"]["raw_body"] == body

    extras = extract_playlist_extras([{"data": parsed}])
    assert extras["playlist_description"] == "inside folder?"
    assert extras["playlist_property_plist"]["raw_body"] == body


def test_playlist_writer_keeps_description_string_and_property_plist() -> None:
    body = plistlib.dumps({"description": "wow"}, fmt=plistlib.FMT_BINARY)
    playlist = PlaylistInfo(
        name="Every Rule",
        playlist_description="wow",
        raw_mhod55=body,
    )

    blob = write_playlist(playlist, db_id_2=123)

    assert blob.count(b"mhod") == 4
    assert write_mhod_header(
        MHOD_TYPE_PLAYLIST_PROPERTY_PLIST,
        MHOD_HEADER_SIZE + len(body),
    ) + body in blob
    assert "wow".encode("utf-16-le") in blob


def test_playlist_property_lifecycle_normalizes_from_raw_body() -> None:
    body = plistlib.dumps({"description": "lalal"}, fmt=plistlib.FMT_BINARY)
    row = {"playlist_property_plist": {"raw_body": body}}

    normalize_playlist_description(row)

    assert row["playlist_description"] == "lalal"
    assert row["Album"] == "lalal"
    assert playlist_description_from_row(row) == "lalal"
    assert playlist_property_raw_body_for_write(row) == body


def test_playlist_description_edit_preserves_unknown_plist_keys() -> None:
    body = plistlib.dumps(
        {"description": "old", "future": {"flag": 1}},
        fmt=plistlib.FMT_BINARY,
    )
    row = {"playlist_property_plist": {"raw_body": body}}

    fields = playlist_description_update_fields("new", row)
    raw_body = playlist_property_raw_body_for_write(fields)

    assert fields["playlist_description"] == "new"
    assert fields["Album"] == "new"
    assert raw_body is not None
    assert plistlib.loads(raw_body) == {
        "description": "new",
        "future": {"flag": 1},
    }
