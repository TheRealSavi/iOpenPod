import plistlib
import struct
from dataclasses import replace

import pytest

from iPodDB.iTunesDB.parser.parser_definition import PARSER_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPayload,
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTableEntry,
    MhodLibraryJumpTablePayload,
    MhodLibraryJumpTablePrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.plist_mhod import MhodPlistPayload
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.settings_mhod import (
    MhodSettingsField,
    MhodSettingsPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPayload,
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartNumericRuleData,
    MhodSmartRuleGroupData,
    MhodSmartRulesPayload,
    MhodSmartRulesPrefix,
    MhodSmartStringRuleData,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.url_mhod import MhodUrlPayload
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.video_details_mhod import (
    MhodVideoDetailsPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind
from iPodDB.iTunesDB.writer.mhod_encoder import encode_mhod_body
from iPodDB.shared.chunk import (
    ChunkAncestor,
    GenericHeader,
    ParsedChunk,
    ParsedMhodPayload,
)
from iPodDB.shared.chunk_reader import parse_chunk_as, parse_mhod_payload


def _mhod(mhod_type: int, body: bytes) -> bytes:
    return (
        struct.pack(
            "<4sIIIII",
            b"mhod",
            0x18,
            0x18 + len(body),
            mhod_type,
            0,
            0,
        )
        + body
    )


def _parse_mhod(mhod_type: int, body: bytes) -> ParsedChunk[MhodHeader]:
    data = _mhod(mhod_type, body)
    chunk, next_offset = parse_chunk_as(
        data,
        0,
        MHOD_DEFINITION,
        parser_definition=PARSER_DEFINITION,
    )
    assert next_offset == len(data)
    return chunk


def _encode_and_reparse(
    chunk: ParsedChunk[MhodHeader],
    payload_kind: MhodPayloadKind,
) -> ParsedChunk[MhodHeader]:
    body, header = encode_mhod_body(chunk, payload_kind)
    return _parse_mhod(header.mhod_type, body)


def _chapter_atom_types_and_bytes(body: bytes) -> tuple[tuple[bytes, bytes], ...]:
    sean_offset = 12
    sean_size, sean_type, _, child_count, _ = struct.unpack_from(
        ">I4sIII", body, sean_offset
    )
    assert sean_type == b"sean"
    sean_end = sean_offset + sean_size
    child_offset = sean_offset + 20
    result: list[tuple[bytes, bytes]] = []
    for _ in range(child_count):
        child_size, child_type = struct.unpack_from(">I4s", body, child_offset)
        child_end = child_offset + child_size
        result.append((child_type, body[child_offset:child_end]))
        child_offset = child_end
    assert child_offset == sean_end == len(body)
    return tuple(result)


def _chapter_name_atom(value: str, *, marker: int) -> bytes:
    encoded = value.encode("utf-16-be")
    return (
        struct.pack(
            ">I4sIIIH",
            22 + len(encoded),
            b"name",
            marker,
            marker + 1,
            marker + 2,
            len(encoded) // 2,
        )
        + encoded
    )


def _chapter_atom(start_ms: int, *children: bytes) -> bytes:
    child_data = b"".join(children)
    return (
        struct.pack(
            ">I4sIII", 20 + len(child_data), b"chap", start_ms, len(children), 0
        )
        + child_data
    )


def _smart_rule(
    field_id: int,
    action_id: int,
    data: bytes,
    *,
    group_marker: int = 0,
    header_data: bytes = bytes(40),
) -> bytes:
    assert len(header_data) == 40
    return (
        struct.pack(">III", field_id, action_id, group_marker)
        + header_data
        + struct.pack(">I", len(data))
        + data
    )


def _smart_rules_container(*rules: bytes, conjunction: int = 0) -> bytes:
    return (
        b"SLst"
        + struct.pack(">III", 0x00010001, len(rules), conjunction)
        + bytes(120)
        + b"".join(rules)
    )


def _ancestor(header: MhipHeader | MhypHeader) -> ChunkAncestor:
    marker = b"mhip" if isinstance(header, MhipHeader) else b"mhyp"
    return ChunkAncestor(
        offset=0,
        generic_header=GenericHeader(marker, 0, 0),
        header=header,
    )


def _parse_contextual_100(
    body: bytes,
    parent: MhipHeader | MhypHeader,
) -> ParsedMhodPayload:
    data = _mhod(100, body)
    return parse_mhod_payload(
        data,
        chunk_offset=0,
        header_end=0x18,
        chunk_end=len(data),
        header=MhodHeader(mhod_type=100),
        ancestors=(_ancestor(parent),),
        parser_definition=PARSER_DEFINITION,
    )


def test_parses_video_details_without_inventing_unknown_field_meanings() -> None:
    body = bytearray(range(84))
    body[0x0C:0x10] = b"avc1"

    chunk = _parse_mhod(32, bytes(body))
    payload = chunk.payload_as(MhodVideoDetailsPayload)

    assert payload.data == body
    assert payload.codec_fourcc == b"avc1"


def test_video_details_fourcc_edits_preserve_the_other_opaque_bytes() -> None:
    body = bytearray(range(84))
    body[0x0C:0x10] = b"avc1"
    chunk = _parse_mhod(32, bytes(body))
    edited = chunk.edit_payload(
        MhodVideoDetailsPayload,
        lambda payload: replace(payload, codec_fourcc=b"hvc1"),
    )

    reparsed = _encode_and_reparse(edited, MhodPayloadKind.VIDEO_DETAILS)
    reparsed_payload = reparsed.payload_as(MhodVideoDetailsPayload)

    expected = bytearray(body)
    expected[0x0C:0x10] = b"hvc1"
    assert reparsed_payload.data == expected
    assert reparsed_payload.codec_fourcc == b"hvc1"


def test_url_edits_have_a_typed_inverse() -> None:
    chunk = _parse_mhod(15, b"https://old.example\x00\x00")
    edited = chunk.edit_payload(
        MhodUrlPayload,
        lambda payload: replace(payload, value="https://new.example"),
    )

    reparsed = _encode_and_reparse(edited, MhodPayloadKind.URL)

    assert reparsed.payload_as(MhodUrlPayload).value == "https://new.example"
    assert reparsed.raw_body.endswith(b"\x00\x00")


def test_smart_preferences_are_entirely_header_like() -> None:
    body = struct.pack("<BBBBB3xI2B", 1, 1, 1, 3, 5, 25, 1, 0) + bytes(58)

    chunk = _parse_mhod(50, body)
    prefix = chunk.prefix_as(MhodSmartPrefsPrefix)
    payload = chunk.payload_as(MhodSmartPrefsPayload)

    assert prefix.limit_value == 25
    assert prefix.padding_0x26 == bytes(58)
    assert payload == MhodSmartPrefsPayload()


def test_smart_preferences_prefix_edits_have_a_typed_inverse() -> None:
    body = struct.pack("<BBBBB3xI2B", 1, 1, 1, 3, 5, 25, 1, 0) + bytes(58)
    chunk = _parse_mhod(50, body)
    edited = chunk.edit_prefix(
        MhodSmartPrefsPrefix,
        lambda prefix: replace(prefix, limit_value=50),
    )

    reparsed = _encode_and_reparse(edited, MhodPayloadKind.SMART_PREFS)

    assert reparsed.prefix_as(MhodSmartPrefsPrefix).limit_value == 50


def test_parses_recursive_smart_rules_and_big_endian_numeric_values() -> None:
    string_data = "Miles".encode("utf-16-be")
    nested = _smart_rules_container(
        _smart_rule(0x04, 0x01000002, string_data),
        conjunction=1,
    )
    group_rule = _smart_rule(
        0,
        1,
        nested,
        group_marker=0x01000000,
        header_data=bytes(range(40)),
    )
    numeric_data = struct.pack(
        ">QqQQqQIIIII",
        320,
        -7,
        2,
        640,
        -14,
        4,
        1,
        2,
        3,
        4,
        5,
    )
    body = _smart_rules_container(
        group_rule,
        _smart_rule(0x05, 0x00000100, numeric_data),
    )

    chunk = _parse_mhod(51, body)
    prefix = chunk.prefix_as(MhodSmartRulesPrefix)
    payload = chunk.payload_as(MhodSmartRulesPayload)

    assert prefix.magic == b"SLst"
    assert prefix.rule_count == 2
    assert len(payload.rules) == 2

    group = payload.rules[0].data
    assert isinstance(group, MhodSmartRuleGroupData)
    assert group.conjunction == 1
    assert group.header_data == bytes(120)
    nested_string = group.rules[0].data
    assert isinstance(nested_string, MhodSmartStringRuleData)
    assert nested_string.value == "Miles"

    numeric = payload.rules[1].data
    assert isinstance(numeric, MhodSmartNumericRuleData)
    assert numeric.from_value == 320
    assert numeric.from_date == -7
    assert numeric.to_value == 640
    assert numeric.unk_0x40 == 5


def test_recursive_smart_rule_edits_recalculate_nested_lengths() -> None:
    nested = _smart_rules_container(
        _smart_rule(0x04, 0x01000002, "Miles".encode("utf-16-be")),
        conjunction=1,
    )
    body = _smart_rules_container(
        _smart_rule(0, 1, nested, group_marker=0x01000000),
    )
    chunk = _parse_mhod(51, body)
    payload = chunk.payload_as(MhodSmartRulesPayload)
    group = payload.rules[0].data
    assert isinstance(group, MhodSmartRuleGroupData)
    string_rule = group.rules[0]
    string_data = string_rule.data
    assert isinstance(string_data, MhodSmartStringRuleData)
    edited_string_rule = replace(
        string_rule,
        data=replace(string_data, value="Coltrane"),
    )
    edited_group = replace(group, rules=(edited_string_rule,))
    edited_payload = replace(
        payload,
        rules=(replace(payload.rules[0], data=edited_group),),
    )
    edited = replace(chunk, payload=edited_payload)

    reparsed = _encode_and_reparse(edited, MhodPayloadKind.SMART_RULES)
    reparsed_group = reparsed.payload_as(MhodSmartRulesPayload).rules[0].data
    assert isinstance(reparsed_group, MhodSmartRuleGroupData)
    reparsed_string = reparsed_group.rules[0].data
    assert isinstance(reparsed_string, MhodSmartStringRuleData)
    assert reparsed_string.value == "Coltrane"


def test_rejects_a_smart_rules_container_with_the_wrong_magic() -> None:
    with pytest.raises(ValueError, match="expected b'SLst'"):
        _parse_mhod(51, b"NOPE" + bytes(132))


def test_parses_library_index() -> None:
    body = struct.pack("<II", 5, 3) + bytes(range(40)) + struct.pack("<III", 7, 2, 9)

    chunk = _parse_mhod(52, body)
    prefix = chunk.prefix_as(MhodLibraryIndexPrefix)
    payload = chunk.payload_as(MhodLibraryIndexPayload)

    assert prefix.sort_type == 5
    assert prefix.entry_count == 3
    assert prefix.padding_0x20 == bytes(range(40))
    assert payload.indices == (7, 2, 9)
    assert payload.trailing_data == b""


def test_library_index_edits_recalculate_the_entry_count() -> None:
    body = struct.pack("<II", 5, 1) + bytes(range(40)) + struct.pack("<I", 7)
    chunk = _parse_mhod(52, body)
    edited = chunk.edit_payload(
        MhodLibraryIndexPayload,
        lambda payload: replace(payload, indices=(9, 3, 11)),
    )

    reparsed = _encode_and_reparse(edited, MhodPayloadKind.LIBRARY_INDEX)

    assert reparsed.prefix_as(MhodLibraryIndexPrefix).entry_count == 3
    assert reparsed.payload_as(MhodLibraryIndexPayload).indices == (9, 3, 11)


def test_library_index_requires_all_declared_entries() -> None:
    body = struct.pack("<II", 3, 2) + bytes(40) + struct.pack("<I", 7)

    with pytest.raises(ValueError, match="declares 2 entries"):
        _parse_mhod(52, body)


def test_parses_library_jump_table() -> None:
    body = (
        struct.pack("<II", 3, 2)
        + bytes(8)
        + struct.pack("<HHII", ord("A"), 0, 0, 4)
        + struct.pack("<HHII", ord("B"), 9, 4, 3)
    )

    chunk = _parse_mhod(53, body)
    prefix = chunk.prefix_as(MhodLibraryJumpTablePrefix)
    payload = chunk.payload_as(MhodLibraryJumpTablePayload)

    assert prefix.sort_type == 3
    assert payload.entries == (
        MhodLibraryJumpTableEntry(ord("A"), 0, 0, 4),
        MhodLibraryJumpTableEntry(ord("B"), 9, 4, 3),
    )


def test_library_jump_table_edits_recalculate_the_entry_count() -> None:
    body = struct.pack("<II", 3, 1) + bytes(8) + struct.pack("<HHII", ord("A"), 0, 0, 4)
    chunk = _parse_mhod(53, body)
    edited = chunk.edit_payload(
        MhodLibraryJumpTablePayload,
        lambda payload: replace(
            payload,
            entries=(
                *payload.entries,
                MhodLibraryJumpTableEntry(ord("B"), 0, 4, 3),
            ),
        ),
    )

    reparsed = _encode_and_reparse(edited, MhodPayloadKind.LIBRARY_JUMP_TABLE)

    assert reparsed.prefix_as(MhodLibraryJumpTablePrefix).entry_count == 2
    assert len(reparsed.payload_as(MhodLibraryJumpTablePayload).entries) == 2


def test_chapter_title_edits_preserve_retained_atom_fields_and_bytes() -> None:
    raw_atom = struct.pack(">I4s", 8, b"junk")
    encoded_name = "First".encode("utf-16-be")
    name_trailing = b"\xaa\xbb"
    name_atom = (
        struct.pack(
            ">I4sIIIH",
            22 + len(encoded_name) + len(name_trailing),
            b"name",
            7,
            8,
            9,
            len(encoded_name) // 2,
        )
        + encoded_name
        + name_trailing
    )
    chapter_trailing = b"\xcc\xdd"
    chapter_children = raw_atom + name_atom + chapter_trailing
    chapter_atom = (
        struct.pack(
            ">I4sIII",
            20 + len(chapter_children),
            b"chap",
            250,
            2,
            11,
        )
        + chapter_children
    )
    hedr_atom = struct.pack(">I4sIIIII", 28, b"hedr", 12, 0, 13, 14, 15)
    sean_children = chapter_atom + hedr_atom
    body = (
        struct.pack("<III", 1, 2, 3)
        + struct.pack(">I4sIII", 20 + len(sean_children), b"sean", 4, 2, 5)
        + sean_children
    )
    chunk = _parse_mhod(17, body)
    edited = chunk.edit_payload(
        MhodChapterDataPayload,
        lambda current: replace(
            current,
            chapters=(replace(current.chapters[0], name="Second"),),
        ),
    )

    reparsed = _encode_and_reparse(edited, MhodPayloadKind.CHAPTER_DATA)
    reparsed_chapter = reparsed.payload_as(MhodChapterDataPayload).chapters[0]

    assert reparsed_chapter.name == "Second"
    assert reparsed_chapter.name_atom_index == 1
    assert reparsed_chapter.name_trailing_data == name_trailing
    assert reparsed_chapter.trailing_data == chapter_trailing
    assert reparsed_chapter.chap_header is not None
    assert reparsed_chapter.chap_header.unk_0x10 == 11
    assert reparsed_chapter.name_header is not None
    assert reparsed_chapter.name_header.unk_0x08 == 7
    assert reparsed_chapter.name_header.unk_0x0C == 8
    assert reparsed_chapter.name_header.unk_0x10 == 9


def test_chapter_edits_preserve_top_level_atom_order_and_unknown_bytes() -> None:
    unknown_before = struct.pack(">I4sI", 12, b"u001", 0x01020304)
    unknown_between = struct.pack(">I4sI", 12, b"u002", 0x11121314)
    unknown_before_hedr = struct.pack(">I4sI", 12, b"u003", 0x21222324)
    unknown_after_hedr = struct.pack(">I4sI", 12, b"u004", 0x31323334)
    first_chapter = _chapter_atom(100, _chapter_name_atom("First", marker=1))
    second_chapter = _chapter_atom(200, _chapter_name_atom("Second", marker=5))
    hedr_atom = struct.pack(">I4sIIIII", 28, b"hedr", 9, 0, 10, 11, 12)
    sean_children = b"".join(
        (
            unknown_before,
            first_chapter,
            unknown_between,
            second_chapter,
            unknown_before_hedr,
            hedr_atom,
            unknown_after_hedr,
        )
    )
    body = (
        struct.pack("<III", 1, 2, 3)
        + struct.pack(">I4sIII", 20 + len(sean_children), b"sean", 4, 7, 5)
        + sean_children
    )
    chunk = _parse_mhod(17, body)
    edited = chunk.edit_payload(
        MhodChapterDataPayload,
        lambda current: replace(
            current,
            chapters=(
                replace(current.chapters[0], name="Renamed", start_pos_ms=150),
                current.chapters[1],
            ),
        ),
    )

    encoded, _ = encode_mhod_body(edited, MhodPayloadKind.CHAPTER_DATA)
    atoms = _chapter_atom_types_and_bytes(encoded)

    assert tuple(atom_type for atom_type, _ in atoms) == (
        b"u001",
        b"chap",
        b"u002",
        b"chap",
        b"u003",
        b"hedr",
        b"u004",
    )
    assert tuple(raw for atom_type, raw in atoms if atom_type.startswith(b"u")) == (
        unknown_before,
        unknown_between,
        unknown_before_hedr,
        unknown_after_hedr,
    )
    reparsed = _parse_mhod(17, encoded).payload_as(MhodChapterDataPayload)
    assert (reparsed.chapters[0].name, reparsed.chapters[0].start_pos_ms) == (
        "Renamed",
        150,
    )


def test_duplicate_name_and_hedr_atoms_remain_in_place_during_an_edit() -> None:
    first_name = _chapter_name_atom("Earlier", marker=1)
    last_name = _chapter_name_atom("Effective", marker=5)
    chapter_atom = _chapter_atom(100, first_name, last_name)
    first_hedr = struct.pack(">I4sIIIII", 28, b"hedr", 10, 0, 11, 12, 13)
    last_hedr = struct.pack(">I4sIIIII", 28, b"hedr", 20, 0, 21, 22, 23)
    sean_children = first_hedr + chapter_atom + last_hedr
    body = (
        struct.pack("<III", 1, 2, 3)
        + struct.pack(">I4sIII", 20 + len(sean_children), b"sean", 4, 3, 5)
        + sean_children
    )
    chunk = _parse_mhod(17, body)
    payload = chunk.payload_as(MhodChapterDataPayload)

    assert payload.chapters[0].name == "Effective"
    assert payload.chapters[0].other_atoms[0].raw == first_name
    assert payload.hedr is not None
    assert payload.hedr.unk_0x08 == 20
    assert payload.other_atoms[0].raw == first_hedr

    edited = chunk.edit_payload(
        MhodChapterDataPayload,
        lambda current: replace(
            current,
            chapters=(replace(current.chapters[0], name="Renamed"),),
        ),
    )
    encoded, _ = encode_mhod_body(edited, MhodPayloadKind.CHAPTER_DATA)
    atoms = _chapter_atom_types_and_bytes(encoded)

    assert tuple(atom_type for atom_type, _ in atoms) == (b"hedr", b"chap", b"hedr")
    assert atoms[0][1] == first_hedr
    chapter_children = atoms[1][1][20:]
    assert chapter_children.startswith(first_name)


def test_conventional_chapter_order_reencodes_identically() -> None:
    chapter_atom = _chapter_atom(100, _chapter_name_atom("Title", marker=1))
    hedr_atom = struct.pack(">I4sIIIII", 28, b"hedr", 10, 0, 11, 12, 13)
    sean_children = chapter_atom + hedr_atom
    body = (
        struct.pack("<III", 1, 2, 3)
        + struct.pack(">I4sIII", 20 + len(sean_children), b"sean", 4, 2, 5)
        + sean_children
    )

    encoded, _ = encode_mhod_body(
        _parse_mhod(17, body),
        MhodPayloadKind.CHAPTER_DATA,
    )

    assert encoded == body


def test_parses_playlist_property_plist_and_preserves_its_bytes() -> None:
    body = plistlib.dumps(
        {"description": "Road trip", "shuffle": True},
        fmt=plistlib.FMT_BINARY,
        sort_keys=True,
    )

    payload = _parse_mhod(55, body).payload_as(MhodPlistPayload)

    assert payload.data == body
    assert payload.properties == {"description": "Road trip", "shuffle": True}


def test_playlist_property_edits_encode_from_typed_properties() -> None:
    body = plistlib.dumps(
        {"description": "Road trip", "shuffle": True},
        fmt=plistlib.FMT_BINARY,
    )
    chunk = _parse_mhod(55, body)
    edited = chunk.edit_payload(
        MhodPlistPayload,
        lambda payload: replace(
            payload,
            properties={"description": "Night drive", "shuffle": False},
        ),
    )

    reparsed = _encode_and_reparse(edited, MhodPayloadKind.PLIST)

    assert reparsed.payload_as(MhodPlistPayload).properties == {
        "description": "Night drive",
        "shuffle": False,
    }


def test_decoded_plist_rejects_an_ambiguous_raw_data_edit() -> None:
    body = plistlib.dumps({"description": "Road trip"}, fmt=plistlib.FMT_BINARY)
    chunk = _parse_mhod(55, body)
    edited = chunk.edit_payload(
        MhodPlistPayload,
        lambda payload: replace(payload, data=b"ambiguous"),
    )

    with pytest.raises(ValueError, match="edit properties instead"):
        encode_mhod_body(edited, MhodPayloadKind.PLIST)


def test_malformed_playlist_property_plist_remains_preserved() -> None:
    payload = _parse_mhod(55, b"not a plist").payload_as(MhodPlistPayload)

    assert payload.data == b"not a plist"
    assert payload.properties is None


def test_mhod_100_uses_parent_context_for_playlist_position() -> None:
    parsed = _parse_contextual_100(
        struct.pack("<I", 42) + bytes(range(16)),
        MhipHeader(),
    )

    assert parsed.prefix == MhodPlaylistPositionPrefix(42, bytes(range(16)))
    assert parsed.payload == MhodPlaylistPositionPayload()


def test_mhod_100_preserves_playlist_preferences_as_opaque_data() -> None:
    body = bytes(range(256)) + bytes(368)

    parsed = _parse_contextual_100(body, MhypHeader())

    assert parsed.prefix is None
    assert parsed.payload == MhodOpaquePayload(body)


def test_mhod_100_requires_a_playlist_or_playlist_item_parent() -> None:
    data = _mhod(100, bytes(20))

    with pytest.raises(ValueError, match="requires an MHIP or MHYP parent"):
        parse_mhod_payload(
            data,
            chunk_offset=0,
            header_end=0x18,
            chunk_end=len(data),
            header=MhodHeader(mhod_type=100),
            ancestors=(),
            parser_definition=PARSER_DEFINITION,
        )


def test_parses_nonzero_playlist_settings_words_without_naming_them() -> None:
    body = bytearray(332)
    struct.pack_into("<I", body, 0x00, 1)
    struct.pack_into("<I", body, 0x4C, 4)
    struct.pack_into("<I", body, 0x8C, 120)

    payload = _parse_mhod(102, bytes(body)).payload_as(MhodSettingsPayload)

    assert payload.data == body
    assert payload.nonzero_fields == (
        MhodSettingsField(0x00, 1),
        MhodSettingsField(0x4C, 4),
        MhodSettingsField(0x8C, 120),
    )
    assert payload.trailing_data == b""


def test_playlist_settings_edits_encode_from_typed_fields() -> None:
    body = bytearray(333)
    struct.pack_into("<I", body, 0x00, 1)
    body[-1] = 0xAA
    chunk = _parse_mhod(102, bytes(body))
    edited = chunk.edit_payload(
        MhodSettingsPayload,
        lambda payload: replace(
            payload,
            nonzero_fields=(
                MhodSettingsField(0x04, 7),
                MhodSettingsField(0x10, 12),
            ),
            trailing_data=b"\xbb\xcc",
        ),
    )

    reparsed = _encode_and_reparse(edited, MhodPayloadKind.SETTINGS)
    reparsed_payload = reparsed.payload_as(MhodSettingsPayload)

    assert reparsed_payload.nonzero_fields == (
        MhodSettingsField(0x04, 7),
        MhodSettingsField(0x10, 12),
    )
    assert reparsed_payload.trailing_data == b"\xbb\xcc"
