from __future__ import annotations

import struct

import pytest

from iopenpod.itunesdb_parser.forensics import (
    forensic_json_document,
    reconstruct_byte_walk,
)
from iopenpod.itunesdb_parser.mhod_parser import parse_mhod
from iopenpod.itunesdb_writer.mhbd_writer import write_mhbd
from iopenpod.itunesdb_writer.mhod_spl_writer import (
    RuleGroup,
    SmartPlaylistPrefs,
    SmartPlaylistRule,
    SmartPlaylistRules,
    prefs_from_parsed,
    rules_from_parsed,
    write_mhod50,
    write_mhod51,
)
from iopenpod.itunesdb_writer.mhyp_writer import PlaylistInfo
from iopenpod.sync.spl_evaluator import spl_update


def _slst(*rules: bytes, conjunction: int = 0, unk004: int = 0x00010001) -> bytes:
    return (
        b"SLst"
        + struct.pack(">III", unk004, len(rules), conjunction)
        + bytes(120)
        + b"".join(rules)
    )


def _group_rule(
    nested: bytes,
    *,
    field_id: int = 0,
    action_id: int = 1,
    group_marker: int = 0x01000000,
    header_bytes: bytes = bytes(40),
) -> bytes:
    assert len(header_bytes) == 40
    return (
        struct.pack(">III", field_id, action_id, group_marker)
        + header_bytes
        + struct.pack(">I", len(nested))
        + nested
    )


def _mhod51(body: bytes) -> bytes:
    total_length = 24 + len(body)
    return struct.pack("<4sIIIII", b"mhod", 24, total_length, 51, 0, 0) + body


def _walk_chunks(chunk: dict):
    yield chunk
    for entry in chunk["bytes"]:
        if "chunk" in entry:
            yield from _walk_chunks(entry["chunk"])


def test_parser_exposes_nested_slst_as_a_semantic_group() -> None:
    header_bytes = bytes(range(40))
    nested = _slst(conjunction=1)
    blob = _mhod51(_slst(_group_rule(nested, header_bytes=header_bytes)))

    parsed = parse_mhod(blob, 0, 24, len(blob))
    root = parsed["data"]["data"]
    wrapper = root["rules"][0]

    assert root["unk004"] == 0x00010001
    assert root["conjunction"] == 0
    assert wrapper == {
        "field_id": 0,
        "action_id": 1,
        "header_bytes": header_bytes,
        "group_marker": 0x01000000,
        "data_length": len(nested),
        "group": {
            "unk004": 0x00010001,
            "rule_count": 0,
            "conjunction": 1,
            "rules": [],
        },
    }


def test_parser_requires_the_complete_observed_group_discriminator() -> None:
    nested = _slst(conjunction=1)
    candidates = (
        _group_rule(nested, field_id=7),
        _group_rule(nested, action_id=9),
        _group_rule(nested, group_marker=0),
    )

    parsed_rules = [
        parse_mhod(_mhod51(_slst(candidate)), 0, 24, 24 + 136 + len(candidate))[
            "data"
        ]["data"]["rules"][0]
        for candidate in candidates
    ]

    assert all("group" not in rule for rule in parsed_rules)


def test_parser_rejects_a_truncated_slst_container_header() -> None:
    truncated_slst = b"SLst" + struct.pack(">III", 0x00010001, 0, 0)
    blob = _mhod51(truncated_slst)

    parsed = parse_mhod(blob, 0, 24, len(blob))

    assert parsed["data"]["data"] == {}


def test_parser_keeps_a_truncated_group_payload_opaque() -> None:
    truncated_slst = b"SLst" + struct.pack(">III", 0x00010001, 0, 0)
    candidate = _group_rule(truncated_slst)
    blob = _mhod51(_slst(candidate))

    wrapper = parse_mhod(blob, 0, 24, len(blob))["data"]["data"]["rules"][0]

    assert "group" not in wrapper
    assert wrapper["raw_data"] == truncated_slst


def test_writer_round_trips_recursive_groups_and_exact_wrapper_bytes() -> None:
    header_bytes = bytes(range(40))
    rules = SmartPlaylistRules(
        rules=[
            RuleGroup(
                header_bytes=header_bytes,
                group=SmartPlaylistRules(conjunction="OR"),
            ),
        ],
    )

    blob = write_mhod51(rules)
    root_start = 24
    wrapper_start = root_start + 136
    nested_start = wrapper_start + 56

    assert struct.unpack_from(">I", blob, root_start + 4)[0] == 0x00010001
    assert struct.unpack_from(">II", blob, wrapper_start) == (0, 1)
    assert struct.unpack_from(">I", blob, wrapper_start + 8)[0] == 0x01000000
    assert blob[wrapper_start + 12:wrapper_start + 52] == header_bytes
    assert struct.unpack_from(">I", blob, wrapper_start + 52)[0] == 136
    assert blob[nested_start:nested_start + 4] == b"SLst"

    parsed = parse_mhod(blob, 0, 24, len(blob))["data"]["data"]

    assert write_mhod51(rules_from_parsed(parsed)) == blob


def test_writer_rejects_group_header_tails_that_are_not_40_bytes() -> None:
    rules = SmartPlaylistRules(
        rules=[RuleGroup(header_bytes=bytes(39))],
    )

    with pytest.raises(ValueError, match="exactly 40 bytes"):
        write_mhod51(rules)


def test_evaluator_recurses_through_mixed_and_or_groups() -> None:
    rules = SmartPlaylistRules(
        conjunction="AND",
        rules=[
            RuleGroup(
                group=SmartPlaylistRules(
                    conjunction="OR",
                    rules=[
                        SmartPlaylistRule(
                            field_id=0x04,
                            action_id=0x01000002,
                            string_value="Mariah Carey",
                        ),
                        SmartPlaylistRule(
                            field_id=0x02,
                            action_id=0x01000002,
                            string_value="Mariah Carey",
                        ),
                    ],
                ),
            ),
            RuleGroup(
                group=SmartPlaylistRules(
                    conjunction="AND",
                    rules=[
                        SmartPlaylistRule(
                            field_id=0x08,
                            action_id=0x03000001,
                            string_value="Holiday",
                        ),
                        SmartPlaylistRule(
                            field_id=0x16,
                            action_id=0x00000010,
                            from_value=17,
                        ),
                    ],
                ),
            ),
        ],
    )
    tracks = [
        {"track_id": 1, "Artist": "Mariah Carey", "Genre": "Pop", "play_count_1": 20},
        {"track_id": 2, "Artist": "Mariah Carey", "Genre": "Holiday", "play_count_1": 20},
        {"track_id": 3, "Title": "Mariah Carey Live", "Genre": "Pop", "play_count_1": 18},
        {"track_id": 4, "Artist": "Someone Else", "Genre": "Pop", "play_count_1": 30},
    ]

    assert spl_update(SmartPlaylistPrefs(), rules, tracks) == [1, 3]


def test_evaluator_uses_boolean_identity_for_empty_nested_groups() -> None:
    tracks = [{"track_id": 1}, {"track_id": 2}]

    empty_any = SmartPlaylistRules(
        conjunction="AND",
        rules=[RuleGroup(group=SmartPlaylistRules(conjunction="OR"))],
    )
    empty_all = SmartPlaylistRules(
        conjunction="AND",
        rules=[RuleGroup(group=SmartPlaylistRules(conjunction="AND"))],
    )

    assert spl_update(SmartPlaylistPrefs(), empty_any, tracks) == []
    assert spl_update(SmartPlaylistPrefs(), empty_all, tracks) == [1, 2]


def test_byte_walk_labels_group_marker_and_nested_slst(tmp_path) -> None:
    smart_rules = SmartPlaylistRules(
        rules=[RuleGroup(group=SmartPlaylistRules(conjunction="OR"))],
    )
    source = tmp_path / "iTunesDB"
    source.write_bytes(
        write_mhbd(
            [],
            playlists_type2=[],
            playlists_type3=[],
            playlists_type5=[
                PlaylistInfo(
                    name="Grouped",
                    smart_prefs=SmartPlaylistPrefs(),
                    smart_rules=smart_rules,
                ),
            ],
        ),
    )

    document = forensic_json_document(source)
    assert reconstruct_byte_walk(document) == source.read_bytes()
    rules_chunk = next(
        chunk
        for chunk in _walk_chunks(document["file"])
        if chunk["chunk"] == "mhod"
        and any(entry.get("value") == 51 for entry in chunk["bytes"])
    )
    group_marker = next(
        entry for entry in rules_chunk["bytes"] if entry.get("field") == "group_marker"
    )
    slst_magics = [
        entry
        for entry in rules_chunk["bytes"]
        if entry.get("field") == "slst_magic"
    ]

    assert group_marker == {
        "at": "0x00A8",
        "byte_length": 4,
        "field": "group_marker",
        "value": 0x01000000,
        "encoding": "u32be",
        "hex": "01 00 00 00",
        "status": "known",
    }
    assert [entry["at"] for entry in slst_magics] == ["0x0018", "0x00D8"]


def test_mhod50_writer_uses_observed_72_byte_body_for_parsed_preferences() -> None:
    prefs = prefs_from_parsed(
        {
            "live_update": 1,
            "check_rules": 1,
            "check_limits": 1,
            "limit_type": 3,
            "limit_sort": 2,
            "limit_value": 25,
            "match_checked_only": 1,
            "reverse_sort": 1,
        },
    )

    blob = write_mhod50(prefs)
    parsed = parse_mhod(blob, 0, 24, len(blob))["data"]["data"]

    assert len(blob) == 96
    assert struct.unpack_from("<I", blob, 8)[0] == 96
    assert parsed == {
        "live_update": 1,
        "check_rules": 1,
        "check_limits": 1,
        "limit_type": 3,
        "limit_sort": 2,
        "limit_value": 25,
        "match_checked_only": 1,
        "reverse_sort": 1,
    }
