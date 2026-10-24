"""Authored versions of the Classic's saved native Genius Playlist sidecar."""

import plistlib
from dataclasses import replace

import pytest

from iPodDB.sidecars import (
    MAX_SIDECAR_BYTES,
    GeniusPlaylist,
    create_genius_playlist,
    genius_playlist_number,
    is_playback_sidecar,
    parse_genius_playlist,
    remap_genius_playlist,
    validate_genius_playlist_tracks,
    write_genius_playlist,
)


def playlist() -> GeniusPlaylist:
    return GeniusPlaylist(
        saved_index=1,
        name="Seed title",
        seed_track_persistent_id=11,
        database_timestamp=1_792_806_454,
        track_master_indexes=(0, 2, 0),
        track_persistent_ids=(11, 33, 11),
    )


def fields() -> dict[str, object]:
    return {
        "savedIndex": 1,
        "seedTrackPersistentID": 11,
        "version": 0,
        "name": "Seed title",
        "DBTimestampMacOSDate": 1_792_806_454,
        "trackMasterIndexes": [0, 2, 0],
        "trackPersistentIDs": [11, 33, 11],
    }


@pytest.mark.parametrize("fmt", [plistlib.FMT_XML, plistlib.FMT_BINARY])
def test_known_fields_and_unknown_values_round_trip_without_any_byte_changes(
    fmt: plistlib.PlistFormat,
) -> None:
    data = plistlib.dumps(
        fields() | {"future": {"bytes": b"\x00\xff", "array": [False, 1.25, "x"]}},
        fmt=fmt,
        sort_keys=False,
    )
    document = parse_genius_playlist(data)
    assert document.playlist == playlist()
    assert document.serialize() == data
    assert write_genius_playlist(document) == data


@pytest.mark.parametrize("binary", [False, True])
def test_authored_fields_reparse_and_known_edits_retain_unknown_values(
    binary: bool,
) -> None:
    original = create_genius_playlist(playlist(), binary=binary)
    assert parse_genius_playlist(original.serialize()).playlist == playlist()
    source = plistlib.loads(original.source_bytes)
    source["future"] = {"blob": b"\x12\x34", "entries": [1, 2, 3]}
    if binary:
        source["reference"] = plistlib.UID(27)
    data = plistlib.dumps(
        source, fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML
    )
    document = parse_genius_playlist(data)
    changed = replace(document, playlist=replace(playlist(), name="Renamed & <saved>"))
    output = write_genius_playlist(changed)
    assert parse_genius_playlist(output).playlist == changed.playlist
    assert plistlib.loads(output)["future"] == source["future"]
    assert output.startswith(b"bplist00") is binary
    if binary:
        assert plistlib.loads(output)["reference"] == plistlib.UID(27)


def test_xml_edits_preserve_unknown_element_bytes_and_comments_exactly() -> None:
    data = plistlib.dumps(fields(), sort_keys=False)
    unknown = b"<!-- retained -->\n<key>extension</key> <data>\n AQID\n</data>\n"
    data = data.replace(b"</dict>", unknown + b"</dict>")
    data = data.replace(b"<integer>11</integer>", b"<integer>0xB</integer>")
    document = parse_genius_playlist(data)
    changed = replace(document, playlist=replace(playlist(), name="New name"))
    output = write_genius_playlist(changed)
    assert output == data.replace(
        b"<string>Seed title</string>", b"<string>New name</string>"
    )
    assert unknown in output


def test_self_closing_arrays_edit_without_losing_following_keys() -> None:
    empty = replace(playlist(), track_master_indexes=(), track_persistent_ids=())
    data = create_genius_playlist(empty).source_bytes
    assert b"<array/>" in data
    document = parse_genius_playlist(data)
    changed = replace(document, playlist=playlist())
    assert parse_genius_playlist(write_genius_playlist(changed)).playlist == playlist()


def test_self_closing_array_with_quoted_bracket_is_bounded_correctly() -> None:
    empty = replace(playlist(), track_master_indexes=(), track_persistent_ids=())
    data = create_genius_playlist(empty).source_bytes.replace(
        b"<array/>", b'<array retained="a > b"/>'
    )
    document = parse_genius_playlist(data)
    assert document.serialize() == data
    output = write_genius_playlist(replace(document, playlist=playlist()))
    assert parse_genius_playlist(output).playlist == playlist()


def test_other_xml_encoding_is_lossless_but_cannot_be_patched_with_utf8() -> None:
    data = create_genius_playlist(playlist()).source_bytes.replace(
        b'encoding="UTF-8"', b'encoding="ISO-8859-1"'
    )
    document = parse_genius_playlist(data)
    assert document.serialize() == data
    with pytest.raises(ValueError, match="Only UTF-8"):
        write_genius_playlist(
            replace(document, playlist=replace(playlist(), name="Renamed"))
        )


def test_signed_persistent_ids_are_normalized_but_spelling_is_retained() -> None:
    source = fields() | {
        "seedTrackPersistentID": -2,
        "trackPersistentIDs": [-2, 33, -2],
    }
    data = plistlib.dumps(source)
    document = parse_genius_playlist(data)
    assert document.playlist is not None
    assert document.playlist.seed_track_persistent_id == (1 << 64) - 2
    assert document.playlist.track_persistent_ids == ((1 << 64) - 2, 33, (1 << 64) - 2)
    changed = replace(document, playlist=replace(document.playlist, name="New name"))
    assert write_genius_playlist(changed).count(b"<integer>-2</integer>") == 3


@pytest.mark.parametrize("fmt", [plistlib.FMT_XML, plistlib.FMT_BINARY])
def test_unknown_versions_are_opaque_and_uneditable(fmt: plistlib.PlistFormat) -> None:
    data = plistlib.dumps({"version": 99, "future": b"opaque"}, fmt=fmt)
    document = parse_genius_playlist(data)
    assert document.playlist is None
    assert write_genius_playlist(document) == data
    assert remap_genius_playlist(data, (11, 22), (11, 22, 33)) == data
    with pytest.raises(ValueError, match="cannot be edited"):
        write_genius_playlist(replace(document, playlist=playlist()))
    with pytest.raises(ValueError, match="cannot be remapped"):
        remap_genius_playlist(data, (11, 22), (22, 11))


def test_reference_validation_preserves_duplicates_and_checks_both_representations() -> (
    None
):
    validate_genius_playlist_tracks(playlist(), (11, 22, 33))
    with pytest.raises(ValueError, match="disagree"):
        validate_genius_playlist_tracks(playlist(), (11, 33, 22))
    with pytest.raises(ValueError, match="unavailable seed"):
        validate_genius_playlist_tracks(
            replace(playlist(), seed_track_persistent_id=44), (11, 22, 33)
        )
    with pytest.raises(ValueError, match="unique"):
        validate_genius_playlist_tracks(playlist(), (11, 11, 33))


def test_remapping_removes_members_keeps_duplicates_and_never_invents_a_timestamp() -> (
    None
):
    data = create_genius_playlist(playlist()).source_bytes
    assert remap_genius_playlist(data, (11, 22, 33), (11, 22, 33, 44)) == data
    output = remap_genius_playlist(data, (11, 22, 33), (44, 22, 11))
    result = parse_genius_playlist(output).playlist
    assert result == replace(
        playlist(), track_master_indexes=(2, 2), track_persistent_ids=(11, 11)
    )
    with pytest.raises(ValueError, match="seed Track cannot be removed"):
        remap_genius_playlist(data, (11, 22, 33), (22, 33))


@pytest.mark.parametrize(
    ("name", "number"),
    [
        ("GeniusPlaylist_1.plist", 1),
        ("GENIUSPLAYLIST_23.PLIST", 23),
        ("GeniusPlaylist_0.plist", None),
        ("GeniusPlaylist_01.plist", None),
        ("GeniusPlaylist_1.plist.bak", None),
        ("GeniusPlaylist_1.plist.backup", None),
        ("prefixGeniusPlaylist_1.plist", None),
        ("GeniusPlaylist.plist", None),
    ],
)
def test_saved_filename_recognition_is_exact(name: str, number: int | None) -> None:
    assert genius_playlist_number(name) == number
    assert is_playback_sidecar(name) is (number is not None)


@pytest.mark.parametrize("fmt", [plistlib.FMT_XML, plistlib.FMT_BINARY])
def test_identity_only_nano_variant_keeps_absent_indexes_and_playlist_identity(
    fmt: plistlib.PlistFormat,
) -> None:
    source = fields() | {"playlistPersistentID": (1 << 63) + 123}
    del source["trackMasterIndexes"]
    data = plistlib.dumps(source, fmt=fmt)
    document = parse_genius_playlist(data)
    expected = replace(
        playlist(),
        track_master_indexes=None,
        playlist_persistent_id=(1 << 63) + 123,
    )
    assert document.playlist == expected
    assert document.serialize() == data
    validate_genius_playlist_tracks(expected, (33, 22, 11))
    assert remap_genius_playlist(data, (11, 22, 33), (33, 22, 11)) == data
    output = remap_genius_playlist(data, (11, 22, 33), (22, 11))
    assert parse_genius_playlist(output).playlist == replace(
        expected, track_persistent_ids=(11, 11)
    )
    assert "trackMasterIndexes" not in plistlib.loads(output)
    assert plistlib.loads(output)["playlistPersistentID"] == (1 << 63) + 123
    assert (
        create_genius_playlist(expected, binary=fmt is plistlib.FMT_BINARY).playlist
        == expected
    )


def test_identity_only_references_are_validated_and_variant_is_not_invented() -> None:
    item = replace(playlist(), track_master_indexes=None)
    with pytest.raises(ValueError, match="unavailable Track"):
        validate_genius_playlist_tracks(item, (11, 22))
    document = create_genius_playlist(item)
    with pytest.raises(ValueError, match="field presence"):
        write_genius_playlist(replace(document, playlist=playlist()))


def test_signed_playlist_identity_is_normalized_without_rewriting_its_spelling() -> (
    None
):
    data = plistlib.dumps(fields() | {"playlistPersistentID": -2})
    document = parse_genius_playlist(data)
    assert document.playlist is not None
    assert document.playlist.playlist_persistent_id == (1 << 64) - 2
    renamed = replace(document, playlist=replace(document.playlist, name="Renamed"))
    assert plistlib.loads(write_genius_playlist(renamed))["playlistPersistentID"] == -2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", True),
        ("savedIndex", -1),
        ("savedIndex", 1 << 32),
        ("name", 1),
        ("seedTrackPersistentID", 0),
        ("seedTrackPersistentID", True),
        ("DBTimestampMacOSDate", -1),
        ("trackMasterIndexes", [True, 2, 0]),
        ("trackMasterIndexes", [0, 2]),
        ("trackMasterIndexes", "0,2,0"),
        ("trackPersistentIDs", [0, 33, 11]),
        ("playlistPersistentID", 0),
        ("playlistPersistentID", True),
    ],
)
def test_invalid_known_values_fail_without_producing_an_editable_document(
    field: str, value: object
) -> None:
    with pytest.raises(ValueError):
        parse_genius_playlist(plistlib.dumps(fields() | {field: value}))


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"bplist00",
        b"<plist><dict>",
        plistlib.dumps([]),
        plistlib.dumps({}),
        b"x" * (MAX_SIDECAR_BYTES + 1),
        plistlib.dumps(fields()).replace(
            b"</dict>", b"<key>name</key><string>ambiguous</string></dict>"
        ),
        b'<?xml version="1.0"?><!DOCTYPE plist [<!ENTITY value "bad">]><plist><dict><key>name</key><string>&value;</string></dict></plist>',
    ],
)
def test_malformed_oversized_duplicate_key_and_entity_inputs_are_rejected(
    data: bytes,
) -> None:
    with pytest.raises(ValueError):
        parse_genius_playlist(data)


@pytest.mark.parametrize(
    "invalid",
    [
        replace(playlist(), version=1),
        replace(playlist(), track_master_indexes=(0, 2)),
        replace(playlist(), seed_track_persistent_id=-1),
    ],
)
def test_authoring_rejects_noncanonical_fields(invalid: GeniusPlaylist) -> None:
    with pytest.raises(ValueError):
        create_genius_playlist(invalid)
