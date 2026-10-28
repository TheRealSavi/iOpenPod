"""Literal-byte regressions for the Classic Smart metadata field consumers."""

import struct
from dataclasses import replace

import pytest
from tests.iPodDB.binary_fixtures import parse_mhod
from tests.iPodDB.library.test_writing import library

from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartRuleGroupData,
    MhodSmartRulesPayload,
    MhodSmartRulesPrefix,
    MhodSmartStringRuleData,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
)
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind
from iPodDB.iTunesDB.writer.mhod_encoder import encode_mhod_body
from iPodDB.library import (
    IPodLibrary,
    Playlist,
    PlaylistKind,
    SmartField,
    SmartMatch,
    SmartOperator,
    SmartPlaylist,
    SmartRule,
    SmartRuleGroup,
    UnsupportedSmartRule,
)
from iPodDB.library._smart_projection import project_smart
from iPodDB.library._smart_writing import smart_chunks
from iPodDB.shared.chunk import ParsedChunk


def _preferences(*, sort: int = 3, control: int = 0) -> bytes:
    # MHOD50 payload, independently specifying the firmware's full sort word.
    raw = bytearray(72)
    raw[:4] = bytes((1, 1, 1, 3))
    struct.pack_into("<II", raw, 4, sort, 20)
    raw[14] = control
    raw[15:] = bytes(range(57))
    return bytes(raw)


def _text_rule(text: str = "Track", *, flags: int = 0) -> bytes:
    data = text.encode("utf-16-be")
    return (
        struct.pack(">III", 2, 0x01000002, flags)
        + bytes(range(40))
        + struct.pack(">I", len(data))
        + data
    )


def _container(rule: bytes, *, version_word: int = 0x00010001) -> bytes:
    return b"SLst" + struct.pack(">III", version_word, 1, 0) + bytes(120) + rule


def _group(rule: bytes, *, flags: int, version_word: int = 0x00010001) -> bytes:
    data = _container(rule, version_word=version_word)
    return (
        struct.pack(">III", 0, 1, flags)
        + bytes(reversed(range(40)))
        + struct.pack(">I", len(data))
        + data
    )


def _rows(
    body: bytes, *, prefs: bytes | None = None
) -> tuple[ParsedChunk[MhodHeader], ParsedChunk[MhodHeader]]:
    return parse_mhod(50, prefs or _preferences()), parse_mhod(51, body)


@pytest.mark.parametrize("sort", (3, 0x103, 0x12345603, 0xFFFFFFFF))
def test_limit_sort_consumes_all_four_bytes_and_preserves_unrelated_edits(
    sort: int,
) -> None:
    original = _preferences(sort=sort)
    prefs, rules = _rows(_container(_text_rule()), prefs=original)
    prefix = prefs.prefix_as(MhodSmartPrefsPrefix)
    assert prefix.limit_sort == sort
    assert encode_mhod_body(prefs, MhodPayloadKind.SMART_PREFS)[0] == original
    projected = project_smart((prefs, rules))
    assert projected.editable is (sort == 3)

    edited = replace(prefs, prefix=replace(prefix, limit_value=7))
    expected = bytearray(original)
    struct.pack_into("<I", expected, 8, 7)
    assert encode_mhod_body(edited, MhodPayloadKind.SMART_PREFS)[0] == expected


@pytest.mark.parametrize(
    ("version_word", "version", "editable"),
    (
        (0, 0, True),
        (999, 0, True),
        (0x10001, 1, True),
        (0x1FFFF, 1, True),
        (0x20000, 2, False),
        (0xFFFF0001, 65535, False),
    ),
)
def test_version_view_uses_first_halfword_without_normalizing_second(
    version_word: int, version: int, editable: bool
) -> None:
    original = _container(_text_rule(), version_word=version_word)
    prefs, rules = _rows(original)
    prefix = rules.prefix_as(MhodSmartRulesPrefix)
    assert prefix.format_version == version
    assert prefix.unknown_0x1E == version_word & 0xFFFF
    assert encode_mhod_body(rules, MhodPayloadKind.SMART_RULES)[0] == original
    expected = bytearray(original)
    struct.pack_into(">H", expected, 4, 1)
    changed = replace(rules, prefix=replace(prefix, format_version=1))
    assert encode_mhod_body(changed, MhodPayloadKind.SMART_RULES)[0] == expected
    projected = project_smart((prefs, rules))
    assert projected.editable is editable
    if editable:
        edited = smart_chunks(replace(projected, checked_only=True), (prefs, rules))
        assert encode_mhod_body(edited[1], MhodPayloadKind.SMART_RULES)[0] == original
    else:
        assert isinstance(projected.rules.rules[0], UnsupportedSmartRule)


@pytest.mark.parametrize("disabled_byte", (1, 2, 255))
@pytest.mark.parametrize("nested", (False, True))
def test_disabled_leaf_and_nested_rules_never_project_as_active(
    disabled_byte: int, nested: bool
) -> None:
    flags = disabled_byte << 16
    rule = (
        _group(_text_rule(), flags=flags | 0x01000000)
        if nested
        else _text_rule(flags=flags)
    )
    body = _container(rule)
    rows = _rows(body)
    native = rows[1].payload_as(MhodSmartRulesPayload).rules[0]
    assert native.disabled == disabled_byte
    assert native.is_nested == int(nested)
    assert encode_mhod_body(rows[1], MhodPayloadKind.SMART_RULES)[0] == body
    projected = project_smart(rows)
    assert not projected.editable
    assert isinstance(projected.rules.rules[0], UnsupportedSmartRule)


@pytest.mark.parametrize("nested_byte", (1, 2, 255))
@pytest.mark.parametrize("disabled_byte", (0, 2))
def test_editing_nested_payload_retains_all_marker_bytes(
    nested_byte: int, disabled_byte: int
) -> None:
    flags = (nested_byte << 24) | (disabled_byte << 16) | 0xABCD
    body = _container(_group(_text_rule("Miles"), flags=flags, version_word=0x1BEEF))
    rows = _rows(body)
    payload = rows[1].payload_as(MhodSmartRulesPayload)
    native = payload.rules[0]
    assert native.is_nested == nested_byte
    assert native.disabled == disabled_byte
    assert native.unknown_0x0A == b"\xab\xcd"
    group = native.data
    assert isinstance(group, MhodSmartRuleGroupData)
    assert group.format_version == 1
    assert group.unknown_0x06 == 0xBEEF
    child = group.rules[0]
    assert isinstance(child.data, MhodSmartStringRuleData)
    changed_child = replace(child, data=replace(child.data, value="Jones"))
    changed = replace(
        rows[1],
        payload=replace(
            payload,
            rules=(replace(native, data=replace(group, rules=(changed_child,))),),
        ),
    )
    # Same-length text edit should affect only those character bytes.
    expected = body.replace("Miles".encode("utf-16-be"), "Jones".encode("utf-16-be"))
    assert encode_mhod_body(changed, MhodPayloadKind.SMART_RULES)[0] == expected


def test_nested_unknown_version_is_unsupported_and_lossless() -> None:
    body = _container(_group(_text_rule(), flags=0x01000000, version_word=0x20001))
    rows = _rows(body)
    projected = project_smart(rows)
    assert not projected.editable
    assert isinstance(projected.rules.rules[0], UnsupportedSmartRule)
    assert encode_mhod_body(rows[1], MhodPayloadKind.SMART_RULES)[0] == body


@pytest.mark.parametrize("nested_byte", (2, 255))
def test_semantic_nested_edit_preserves_noncanonical_marker_and_version_halfword(
    nested_byte: int,
) -> None:
    flags = (nested_byte << 24) | 0xABCD
    original = _container(
        _group(_text_rule("Miles"), flags=flags, version_word=0x1BEEF)
    )
    rows = _rows(original)
    projected = project_smart(rows)
    assert projected.editable
    group = projected.rules.rules[0]
    assert isinstance(group, SmartRuleGroup)
    child = group.rules[0]
    assert isinstance(child, SmartRule)
    changed = replace(
        projected,
        rules=replace(
            projected.rules,
            rules=(replace(group, rules=(replace(child, value="Jones"),)),),
        ),
    )

    edited = smart_chunks(changed, rows)
    encoded = encode_mhod_body(edited[1], MhodPayloadKind.SMART_RULES)[0]

    assert struct.unpack_from(">I", encoded, 0x88 + 8)[0] == flags
    assert struct.unpack_from(">I", encoded, 0x88 + 0x38 + 4)[0] == 0x1BEEF
    # Unidentified outer-rule bytes also survive an explicit nested text edit.
    assert encoded[0x88 + 12 : 0x88 + 52] == original[0x88 + 12 : 0x88 + 52]
    assert project_smart((edited[0], parse_mhod(51, encoded))) == changed


@pytest.mark.parametrize("control", (0, 1, 2, 255))
def test_attachment_control_keeps_unrepresentable_configuration_read_only(
    control: int,
) -> None:
    original = _preferences(control=control)
    rows = _rows(_container(_text_rule()), prefs=original)
    assert rows[0].prefix_as(MhodSmartPrefsPrefix).attachment_inhibit == control
    assert rows[0].prefix_as(MhodSmartPrefsPrefix).padding_0x27 == bytes(range(57))
    assert project_smart(rows).editable is (control == 0)
    assert encode_mhod_body(rows[0], MhodPayloadKind.SMART_PREFS)[0] == original


@pytest.mark.parametrize("control", (0, 1, 2, 255))
def test_string_composition_control_is_a_real_byte_field_preserving_neighbor_bytes(
    control: int,
) -> None:
    original = (
        struct.pack("<II", 1, 10)
        + bytes((control, 0xAB, 0xCD, 0xEF))
        + b"\x12\x34\x56\x78"
        + "Miles".encode("utf-16-le")
    )
    row = parse_mhod(1, original)
    prefix = row.prefix_as(MhodStringPrefix)
    assert prefix.bypass_pair_composition == control
    assert prefix.unknown_0x21 == b"\xab\xcd\xef"
    assert encode_mhod_body(row, MhodPayloadKind.STRING)[0] == original
    changed = replace(row, prefix=replace(prefix, bypass_pair_composition=2))
    expected = original[:8] + b"\x02" + original[9:]
    assert encode_mhod_body(changed, MhodPayloadKind.STRING)[0] == expected
    text_edit = replace(
        row, payload=replace(row.payload_as(MhodStringPayload), value="Jones")
    )
    assert encode_mhod_body(text_edit, MhodPayloadKind.STRING)[0] == (
        original[:16] + "Jones".encode("utf-16-le")
    )


def test_semantic_leaf_edit_retains_unknown_flag_bytes_and_header() -> None:
    original = _container(_text_rule("Miles", flags=0xABCD))
    rows = _rows(original)
    projected = project_smart(rows)
    assert projected.editable
    leaf = projected.rules.rules[0]
    assert isinstance(leaf, SmartRule)
    changed = replace(
        projected, rules=replace(projected.rules, rules=(replace(leaf, value="Jones"),))
    )
    edited = smart_chunks(changed, rows)
    expected = original.replace(
        "Miles".encode("utf-16-be"), "Jones".encode("utf-16-be")
    )
    assert encode_mhod_body(edited[1], MhodPayloadKind.SMART_RULES)[0] == expected


def test_numeric_leaf_edit_retains_header_unknown_operands_and_suffix() -> None:
    operand = (
        struct.pack(">QqQQqQIIIII", 320, 0, 1, 320, 0, 1, 11, 12, 13, 14, 15) + b"tail"
    )
    raw_rule = (
        struct.pack(">III", 5, 1, 0xABCD)
        + bytes(range(40))
        + struct.pack(">I", len(operand))
        + operand
    )
    original = _container(raw_rule)
    rows = _rows(original)
    projected = project_smart(rows)
    assert projected.editable
    leaf = projected.rules.rules[0]
    assert isinstance(leaf, SmartRule)
    changed = replace(
        projected, rules=replace(projected.rules, rules=(replace(leaf, value=256),))
    )
    edited = smart_chunks(changed, rows)
    expected = bytearray(original)
    struct.pack_into(">Q", expected, 0x88 + 0x38, 256)
    struct.pack_into(">Q", expected, 0x88 + 0x38 + 24, 256)
    assert encode_mhod_body(edited[1], MhodPayloadKind.SMART_RULES)[0] == expected


def test_edited_rule_does_not_reuse_unchanged_reordered_rules_private_header() -> None:
    original = bytearray(_container(_text_rule("Alpha", flags=0xABCD)))
    struct.pack_into(">I", original, 8, 2)
    original.extend(_text_rule("Bravo", flags=0xEF12))
    rows = _rows(bytes(original))
    projected = project_smart(rows)
    first = projected.rules.rules[0]
    assert isinstance(first, SmartRule)
    changed = replace(
        projected,
        rules=replace(
            projected.rules,
            rules=(
                replace(first, value="Cider"),
                first,
            ),
        ),
    )
    edited = smart_chunks(changed, rows)
    native = edited[1].payload_as(MhodSmartRulesPayload).rules
    assert native[0].unknown_0x0A == bytes(2)
    assert native[0].header_data == bytes(40)
    assert native[1] == rows[1].payload_as(MhodSmartRulesPayload).rules[0]


@pytest.mark.parametrize("mode", (0, 1, 2, 99, 255))
@pytest.mark.parametrize("nested", (False, True))
def test_conjunction_byte_preserves_unknown_prefix_and_noncanonical_any_on_edits(
    mode: int, nested: bool
) -> None:
    original = bytearray(
        _container(
            _group(_text_rule("Miles"), flags=0x0200ABCD)
            if nested
            else _text_rule("Miles")
        )
    )
    target = 0x88 + 0x38 if nested else 0
    original[target + 12 : target + 16] = bytes((0xAB, 0xCD, 0xEF, mode))
    rows = _rows(bytes(original))
    if nested:
        native_group = rows[1].payload_as(MhodSmartRulesPayload).rules[0].data
        assert isinstance(native_group, MhodSmartRuleGroupData)
        assert native_group.unknown_0x0C == b"\xab\xcd\xef"
        assert native_group.conjunction == mode
    else:
        prefix = rows[1].prefix_as(MhodSmartRulesPrefix)
        assert prefix.unknown_0x24 == b"\xab\xcd\xef"
        assert prefix.conjunction == mode
    assert encode_mhod_body(rows[1], MhodPayloadKind.SMART_RULES)[0] == original
    projected = project_smart(rows)
    assert projected.editable
    group = projected.rules.rules[0] if nested else projected.rules
    assert isinstance(group, SmartRuleGroup)
    assert group.match is (SmartMatch.ANY if mode else SmartMatch.ALL)

    preference_edit = smart_chunks(replace(projected, checked_only=True), rows)
    assert (
        encode_mhod_body(preference_edit[1], MhodPayloadKind.SMART_RULES)[0] == original
    )
    leaf = group.rules[0]
    assert isinstance(leaf, SmartRule)
    edited_group = replace(group, rules=(replace(leaf, value="Jones"),))
    edited = replace(
        projected,
        rules=(
            replace(projected.rules, rules=(edited_group,)) if nested else edited_group
        ),
    )
    encoded = smart_chunks(edited, rows)
    assert encode_mhod_body(encoded[1], MhodPayloadKind.SMART_RULES)[
        0
    ] == original.replace("Miles".encode("utf-16-be"), "Jones".encode("utf-16-be"))

    # Explicit ALL/ANY changes update just the operative byte to canonical 0/1.
    toggled = replace(group, match=SmartMatch.ALL if mode else SmartMatch.ANY)
    changed_match = replace(
        projected,
        rules=(replace(projected.rules, rules=(toggled,)) if nested else toggled),
    )
    encoded = smart_chunks(changed_match, rows)
    expected = bytearray(original)
    expected[target + 15] = 0 if mode else 1
    assert encode_mhod_body(encoded[1], MhodPayloadKind.SMART_RULES)[0] == expected


@pytest.mark.parametrize("kind", ("disabled", "version", "attachment"))
def test_unsupported_metadata_preserves_saved_membership_and_bytes_on_track_edit(
    kind: str,
) -> None:
    source = library()
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.TITLE, SmartOperator.CONTAINS, "Earlier"),)
        )
    )
    desired = replace(
        source.snapshot,
        playlists=(
            *source.snapshot.playlists,
            Playlist(
                -1,
                "Native smart",
                PlaylistKind.SMART,
                entries=source.snapshot.playlists[-1].entries,
                smart=smart,
            ),
        ),
    )
    prepared = source.prepare(source.analyze(source.begin_draft(desired)))
    assert prepared.prepared is not None, prepared.issues
    original = bytearray(prepared.prepared.itunes)
    # Both hierarchy and flat companion datasets retain the metadata.
    metadata_copies: list[bytes] = []
    slst = original.find(b"SLst")
    while slst >= 0:
        prefs_start = slst - 24 - 96
        assert original[prefs_start : prefs_start + 4] == b"mhod"
        assert struct.unpack_from("<I", original, prefs_start + 12)[0] == 50
        if kind == "disabled":
            original[slst + 0x88 + 9] = 2
        elif kind == "version":
            struct.pack_into(">H", original, slst + 4, 2)
        else:
            original[prefs_start + 0x26] = 255
        rules_length = struct.unpack_from("<I", original, slst - 24 + 8)[0]
        metadata_copies.append(bytes(original[prefs_start : slst - 24 + rules_length]))
        slst = original.find(b"SLst", slst + 4)
    assert len(metadata_copies) == 2
    source = IPodLibrary(bytes(original))
    assert source.serialize().itunes == original
    saved = source.snapshot.playlists[-1]
    assert saved.smart is not None and not saved.smart.editable
    assert saved.entries
    track = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(
            replace(track, title="No longer matches"),
            *source.snapshot.tracks[1:],
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    reloaded = IPodLibrary(result.prepared.itunes)
    assert reloaded.snapshot.playlists[-1].entries == saved.entries
    # Both original MHODs remain contiguous and byte-exact despite Track rewrite.
    for metadata in metadata_copies:
        assert result.prepared.itunes.count(metadata) == original.count(metadata)
