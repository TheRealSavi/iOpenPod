"""Typed inverse encoders for every understood iTunesDB MHOD payload layout."""

import plistlib
import struct
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from types import MappingProxyType

from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataChapHeader,
    MhodChapterDataChapter,
    MhodChapterDataHedrHeader,
    MhodChapterDataNameHeader,
    MhodChapterDataPayload,
    MhodChapterDataRawAtom,
    MhodChapterDataSeanHeader,
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
    MhodLibraryJumpTablePayload,
    MhodLibraryJumpTablePrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.plist_mhod import (
    MhodPlistPayload,
    PlistValue,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.settings_mhod import (
    MhodSettingsPayload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPayload,
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    SMART_RULE_GROUP_MARKER,
    MhodSmartNumericRuleData,
    MhodSmartNumericRuleFields,
    MhodSmartRawRuleData,
    MhodSmartRule,
    MhodSmartRuleGroupData,
    MhodSmartRuleHeader,
    MhodSmartRulesContainerHeader,
    MhodSmartRulesPayload,
    MhodSmartRulesPrefix,
    MhodSmartStringRuleData,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.url_mhod import MhodUrlPayload
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.video_details_mhod import (
    MhodVideoDetailsPayload,
)
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind
from iPodDB.shared.binary_struct import (
    binary_struct_extent,
    write_binary_struct_into,
)
from iPodDB.shared.chunk import (
    BinaryStruct,
    MhodPayload,
    MhodPayloadPrefix,
    ParsedChunk,
)

_UINT32_LE = struct.Struct("<I")
_CHAPTER_PREAMBLE = struct.Struct("<III")

type WritablePlistValue = (
    bool
    | bytes
    | datetime
    | float
    | int
    | str
    | list[WritablePlistValue]
    | dict[str, WritablePlistValue]
)

type MhodPayloadShape = tuple[
    type[MhodPayloadPrefix] | None,
    type[MhodPayload],
]

_PAYLOAD_SHAPES: Mapping[MhodPayloadKind, MhodPayloadShape] = MappingProxyType(
    {
        MhodPayloadKind.STRING: (MhodStringPrefix, MhodStringPayload),
        MhodPayloadKind.URL: (None, MhodUrlPayload),
        MhodPayloadKind.OPAQUE: (None, MhodOpaquePayload),
        MhodPayloadKind.CHAPTER_DATA: (None, MhodChapterDataPayload),
        MhodPayloadKind.VIDEO_DETAILS: (None, MhodVideoDetailsPayload),
        MhodPayloadKind.SMART_PREFS: (MhodSmartPrefsPrefix, MhodSmartPrefsPayload),
        MhodPayloadKind.SMART_RULES: (MhodSmartRulesPrefix, MhodSmartRulesPayload),
        MhodPayloadKind.LIBRARY_INDEX: (
            MhodLibraryIndexPrefix,
            MhodLibraryIndexPayload,
        ),
        MhodPayloadKind.LIBRARY_JUMP_TABLE: (
            MhodLibraryJumpTablePrefix,
            MhodLibraryJumpTablePayload,
        ),
        MhodPayloadKind.PLIST: (None, MhodPlistPayload),
        MhodPayloadKind.PLAYLIST_POSITION: (
            MhodPlaylistPositionPrefix,
            MhodPlaylistPositionPayload,
        ),
        MhodPayloadKind.SETTINGS: (None, MhodSettingsPayload),
    }
)


def validate_mhod_body_representation(
    chunk: ParsedChunk[MhodHeader],
    payload_kind: MhodPayloadKind,
) -> None:
    """Require the one prefix/payload representation for a concrete MHOD kind."""

    shape = _PAYLOAD_SHAPES.get(payload_kind)
    if shape is None:
        raise ValueError(f"MHOD payload kind {payload_kind.value} is not concrete")

    prefix_type, payload_type = shape
    prefix_is_valid = (
        chunk.prefix is None
        if prefix_type is None
        else type(chunk.prefix) is prefix_type
    )
    if not prefix_is_valid or type(chunk.payload) is not payload_type:
        raise ValueError(
            f"MHOD type {chunk.header.mhod_type} requires a "
            f"{payload_kind.value} payload representation"
        )


def _binary_struct_bytes(value: BinaryStruct) -> bytes:
    size = binary_struct_extent(type(value))
    encoded = bytearray(size)
    write_binary_struct_into(encoded, value)
    return bytes(encoded)


def _prefix_bytes(
    chunk: ParsedChunk[MhodHeader],
    prefix: MhodPayloadPrefix,
) -> bytes:
    """Encode an absolute-offset prefix and return only its body portion."""

    header_size = len(chunk.raw_header) or MHOD_DEFINITION.default_header_size
    prefix_extent = binary_struct_extent(type(prefix))
    if prefix_extent < header_size:
        raise ValueError(
            f"{type(prefix).__name__} ends before the {header_size}-byte MHOD header"
        )

    retained = chunk.raw_header + chunk.raw_body
    encoded = bytearray(prefix_extent)
    retained_length = min(len(retained), prefix_extent)
    encoded[:retained_length] = retained[:retained_length]
    write_binary_struct_into(encoded, prefix, limit=prefix_extent)
    return bytes(encoded[header_size:])


def _string_trailing_data(
    chunk: ParsedChunk[MhodHeader],
) -> bytes:
    original_prefix = chunk.original_prefix
    if not chunk.raw_header or not isinstance(original_prefix, MhodStringPrefix):
        return b""

    payload_offset = binary_struct_extent(MhodStringPrefix) - len(chunk.raw_header)
    trailing_offset = payload_offset + original_prefix.string_length
    return chunk.raw_body[min(trailing_offset, len(chunk.raw_body)) :]


def _encode_string(chunk: ParsedChunk[MhodHeader]) -> bytes:
    prefix = chunk.prefix_as(MhodStringPrefix)
    payload = chunk.payload_as(MhodStringPayload)
    codec = "utf-8" if prefix.encoding_indicator == 2 else "utf-16-le"
    encoded_value = payload.value.encode(codec)
    if codec == "utf-16-le" and len(encoded_value) % 2:
        raise ValueError("an iTunesDB UTF-16 string encoded to an odd byte length")
    encoded_prefix = replace(prefix, string_length=len(encoded_value))
    return (
        _prefix_bytes(chunk, encoded_prefix)
        + encoded_value
        + _string_trailing_data(chunk)
    )


def _encode_url(chunk: ParsedChunk[MhodHeader]) -> bytes:
    if chunk.prefix is not None:
        raise ValueError("an iTunesDB URL MHOD cannot contain a payload prefix")
    payload = chunk.payload_as(MhodUrlPayload)
    trailing_nulls = b""
    if chunk.raw_body:
        trailing_nulls = chunk.raw_body[len(chunk.raw_body.rstrip(b"\x00")) :]
    return payload.value.encode("utf-8") + trailing_nulls


def _encode_opaque(chunk: ParsedChunk[MhodHeader]) -> bytes:
    if chunk.prefix is not None:
        raise ValueError("an opaque iTunesDB MHOD cannot contain a payload prefix")
    return chunk.payload_as(MhodOpaquePayload).data


def _encode_smart_preferences(chunk: ParsedChunk[MhodHeader]) -> bytes:
    prefix = chunk.prefix_as(MhodSmartPrefsPrefix)
    chunk.payload_as(MhodSmartPrefsPayload)
    return _prefix_bytes(chunk, prefix)


def _encode_playlist_position(chunk: ParsedChunk[MhodHeader]) -> bytes:
    prefix = chunk.prefix_as(MhodPlaylistPositionPrefix)
    chunk.payload_as(MhodPlaylistPositionPayload)
    return _prefix_bytes(chunk, prefix)


def _encode_library_index(chunk: ParsedChunk[MhodHeader]) -> bytes:
    prefix = chunk.prefix_as(MhodLibraryIndexPrefix)
    payload = chunk.payload_as(MhodLibraryIndexPayload)
    encoded_prefix = replace(prefix, entry_count=len(payload.indices))
    entries = b"".join(_UINT32_LE.pack(index) for index in payload.indices)
    return _prefix_bytes(chunk, encoded_prefix) + entries + payload.trailing_data


def _encode_library_jump_table(chunk: ParsedChunk[MhodHeader]) -> bytes:
    prefix = chunk.prefix_as(MhodLibraryJumpTablePrefix)
    payload = chunk.payload_as(MhodLibraryJumpTablePayload)
    encoded_prefix = replace(prefix, entry_count=len(payload.entries))
    entries = b"".join(_binary_struct_bytes(entry) for entry in payload.entries)
    return _prefix_bytes(chunk, encoded_prefix) + entries + payload.trailing_data


def _validate_raw_atom(atom: MhodChapterDataRawAtom) -> bytes:
    if len(atom.raw) < 8:
        raise ValueError("a retained chapter-data atom must contain an 8-byte header")
    declared_size = struct.unpack_from(">I", atom.raw, 0)[0]
    if declared_size != len(atom.raw) or atom.raw[4:8] != atom.atom_type:
        raise ValueError(
            f"retained chapter-data atom {atom.atom_type!r} has inconsistent bytes"
        )
    return atom.raw


def _encode_chapter(chapter: MhodChapterDataChapter) -> bytes:
    encoded_name = chapter.name.encode("utf-16-be")
    code_unit_count = len(encoded_name) // 2
    if code_unit_count > 0xFFFF:
        raise ValueError("a chapter title cannot exceed 65535 UTF-16 code units")

    include_name = chapter.name_header is not None or bool(chapter.name)
    child_atoms = [_validate_raw_atom(atom) for atom in chapter.other_atoms]
    if include_name:
        default_name_header = MhodChapterDataNameHeader(
            total_size=0,
            atom_type=b"name",
            unk_0x08=1,
            unk_0x0C=0,
            unk_0x10=0,
            string_length=0,
        )
        name_header = replace(
            chapter.name_header or default_name_header,
            total_size=(
                binary_struct_extent(MhodChapterDataNameHeader)
                + len(encoded_name)
                + len(chapter.name_trailing_data)
            ),
            atom_type=b"name",
            string_length=code_unit_count,
        )
        name_atom = (
            _binary_struct_bytes(name_header)
            + encoded_name
            + chapter.name_trailing_data
        )
        name_atom_index = (
            0 if chapter.name_atom_index is None else chapter.name_atom_index
        )
        if not 0 <= name_atom_index <= len(child_atoms):
            raise ValueError("a chapter name atom index is outside its child atoms")
        child_atoms.insert(name_atom_index, name_atom)

    children = b"".join(child_atoms) + chapter.trailing_data
    default_chapter_header = MhodChapterDataChapHeader(
        total_size=0,
        atom_type=b"chap",
        start_position_ms=0,
        child_count=0,
        unk_0x10=0,
    )
    chapter_header = replace(
        chapter.chap_header or default_chapter_header,
        total_size=binary_struct_extent(MhodChapterDataChapHeader) + len(children),
        atom_type=b"chap",
        start_position_ms=chapter.start_pos_ms,
        child_count=len(child_atoms),
    )
    return _binary_struct_bytes(chapter_header) + children


def _ordered_sean_children(
    payload: MhodChapterDataPayload,
    chapter_atoms: tuple[bytes, ...],
    other_atoms: tuple[bytes, ...],
    hedr_atom: bytes | None,
) -> tuple[bytes, ...]:
    has_retained_order = bool(payload.chapter_atom_indices) or (
        payload.hedr_atom_index is not None
    )
    if not has_retained_order:
        return (
            *chapter_atoms,
            *other_atoms,
            *((hedr_atom,) if hedr_atom is not None else ()),
        )

    if len(payload.chapter_atom_indices) != len(chapter_atoms):
        raise ValueError(
            "chapter membership changed without updating retained sean atom positions"
        )
    if (payload.hedr_atom_index is None) != (hedr_atom is None):
        raise ValueError(
            "hedr membership changed without updating its retained sean atom position"
        )

    atom_count = len(chapter_atoms) + len(other_atoms) + int(hedr_atom is not None)
    ordered: list[bytes | None] = [None] * atom_count

    def retain_at(index: int, atom: bytes, atom_type: str) -> None:
        if not 0 <= index < atom_count:
            raise ValueError(
                f"retained {atom_type} atom index is outside sean children"
            )
        if ordered[index] is not None:
            raise ValueError("retained sean atom indices overlap")
        ordered[index] = atom

    for index, chapter_atom in zip(
        payload.chapter_atom_indices,
        chapter_atoms,
        strict=True,
    ):
        retain_at(index, chapter_atom, "chap")
    if payload.hedr_atom_index is not None:
        assert hedr_atom is not None
        retain_at(payload.hedr_atom_index, hedr_atom, "hedr")

    retained_other_atoms = iter(other_atoms)
    for index, atom in enumerate(ordered):
        if atom is None:
            ordered[index] = next(retained_other_atoms)
    try:
        next(retained_other_atoms)
    except StopIteration:
        pass
    else:
        raise ValueError("retained sean atom positions do not cover every child")

    return tuple(atom for atom in ordered if atom is not None)


def _encode_chapter_data(chunk: ParsedChunk[MhodHeader]) -> bytes:
    if chunk.prefix is not None:
        raise ValueError("an iTunesDB chapter-data MHOD cannot contain a prefix")
    payload = chunk.payload_as(MhodChapterDataPayload)

    chapter_atoms = tuple(_encode_chapter(chapter) for chapter in payload.chapters)
    other_atoms = tuple(_validate_raw_atom(atom) for atom in payload.other_atoms)
    hedr_atom: bytes | None = None
    if payload.hedr is not None:
        hedr: MhodChapterDataHedrHeader = replace(
            payload.hedr,
            total_size=(
                binary_struct_extent(MhodChapterDataHedrHeader)
                + len(payload.hedr_trailing_data)
            ),
            atom_type=b"hedr",
        )
        hedr_atom = _binary_struct_bytes(hedr) + payload.hedr_trailing_data

    child_atoms = _ordered_sean_children(
        payload,
        chapter_atoms,
        other_atoms,
        hedr_atom,
    )
    children = b"".join(child_atoms)
    sean: MhodChapterDataSeanHeader = replace(
        payload.sean,
        total_size=binary_struct_extent(MhodChapterDataSeanHeader) + len(children),
        atom_type=b"sean",
        child_count=len(child_atoms),
    )
    preamble = _CHAPTER_PREAMBLE.pack(*payload.preamble)
    return preamble + _binary_struct_bytes(sean) + children


def _encode_smart_numeric_data(data: MhodSmartNumericRuleData) -> bytes:
    minimum_size = binary_struct_extent(MhodSmartNumericRuleFields)
    encoded = bytearray(data.raw_data)
    if len(encoded) < minimum_size:
        encoded.extend(bytes(minimum_size - len(encoded)))
    fields = MhodSmartNumericRuleFields(
        from_value=data.from_value,
        from_date=data.from_date,
        from_units=data.from_units,
        to_value=data.to_value,
        to_date=data.to_date,
        to_units=data.to_units,
        unk_0x30=data.unk_0x30,
        unk_0x34=data.unk_0x34,
        unk_0x38=data.unk_0x38,
        unk_0x3C=data.unk_0x3C,
        unk_0x40=data.unk_0x40,
    )
    write_binary_struct_into(encoded, fields)
    return bytes(encoded)


def _encode_smart_group(data: MhodSmartRuleGroupData) -> bytes:
    if data.magic != b"SLst":
        raise ValueError("a nested smart-rule group must use b'SLst'")
    rules = b"".join(_encode_smart_rule(rule) for rule in data.rules)
    header = MhodSmartRulesContainerHeader(
        magic=data.magic,
        unk_0x04=data.unk_0x04,
        rule_count=len(data.rules),
        conjunction=data.conjunction,
        header_data=data.header_data,
    )
    return _binary_struct_bytes(header) + rules + data.trailing_data


def _encode_smart_rule(rule: MhodSmartRule) -> bytes:
    data = rule.data
    if isinstance(data, MhodSmartStringRuleData):
        if data.raw_data.decode("utf-16-be", errors="replace") == data.value:
            encoded_data = data.raw_data
        else:
            encoded_data = data.value.encode("utf-16-be")
    elif isinstance(data, MhodSmartNumericRuleData):
        encoded_data = _encode_smart_numeric_data(data)
    elif isinstance(data, MhodSmartRawRuleData):
        encoded_data = data.raw_data
    else:
        encoded_data = _encode_smart_group(data)

    if isinstance(data, MhodSmartRuleGroupData):
        field_id = 0
        action_id = 1
        group_marker = SMART_RULE_GROUP_MARKER
    else:
        field_id = rule.field_id
        action_id = rule.action_id
        group_marker = rule.group_marker

    header = MhodSmartRuleHeader(
        field_id=field_id,
        action_id=action_id,
        group_marker=group_marker,
        header_data=rule.header_data,
        data_length=len(encoded_data),
    )
    return _binary_struct_bytes(header) + encoded_data


def _encode_smart_rules(chunk: ParsedChunk[MhodHeader]) -> bytes:
    prefix = chunk.prefix_as(MhodSmartRulesPrefix)
    if prefix.magic != b"SLst":
        raise ValueError("an iTunesDB smart-rules MHOD must use b'SLst'")
    payload = chunk.payload_as(MhodSmartRulesPayload)
    encoded_prefix = replace(prefix, rule_count=len(payload.rules))
    rules = b"".join(_encode_smart_rule(rule) for rule in payload.rules)
    return _prefix_bytes(chunk, encoded_prefix) + rules + payload.trailing_data


def _encode_plist(chunk: ParsedChunk[MhodHeader]) -> bytes:
    if chunk.prefix is not None:
        raise ValueError("an iTunesDB plist MHOD cannot contain a payload prefix")
    payload = chunk.payload_as(MhodPlistPayload)
    original = chunk.original_payload
    if isinstance(original, MhodPlistPayload) and original.properties is not None:
        if payload.data != original.data:
            raise ValueError(
                "decoded plist data is retained encoding; edit properties instead"
            )
        if payload.properties is None:
            raise ValueError("a decoded plist cannot discard its typed properties")
    if payload.properties is None:
        return payload.data
    return plistlib.dumps(
        _thaw_plist_value(payload.properties),
        fmt=plistlib.FMT_BINARY,
        sort_keys=False,
    )


def _thaw_plist_value(value: PlistValue) -> WritablePlistValue:
    if isinstance(value, tuple):
        return [_thaw_plist_value(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _thaw_plist_value(item) for key, item in value.items()}
    return value


def _encode_video_details(chunk: ParsedChunk[MhodHeader]) -> bytes:
    if chunk.prefix is not None:
        raise ValueError("an iTunesDB video-details MHOD cannot contain a prefix")
    payload = chunk.payload_as(MhodVideoDetailsPayload)
    encoded = bytearray(payload.data)
    if payload.codec_fourcc is not None:
        if len(payload.codec_fourcc) != 4:
            raise ValueError("a video codec FourCC must contain exactly four bytes")
        if len(encoded) < 0x10:
            raise ValueError("video-details data is too short to contain its FourCC")
        encoded[0x0C:0x10] = payload.codec_fourcc
    return bytes(encoded)


def _encode_settings(chunk: ParsedChunk[MhodHeader]) -> bytes:
    if chunk.prefix is not None:
        raise ValueError("an iTunesDB settings MHOD cannot contain a payload prefix")
    payload = chunk.payload_as(MhodSettingsPayload)
    original = chunk.original_payload
    if isinstance(original, MhodSettingsPayload):
        if payload.data != original.data:
            raise ValueError(
                "settings data is retained encoding; edit nonzero_fields instead"
            )
        aligned_length = len(original.data) - len(original.trailing_data)
    else:
        aligned_length = len(payload.data) - len(payload.trailing_data)
    if aligned_length < 0 or aligned_length % _UINT32_LE.size:
        raise ValueError("settings data and trailing data have inconsistent lengths")

    encoded = bytearray(aligned_length)
    previous_offset = -_UINT32_LE.size
    for field in payload.nonzero_fields:
        if (
            field.offset < 0
            or field.offset % _UINT32_LE.size
            or field.offset + _UINT32_LE.size > aligned_length
        ):
            raise ValueError(f"invalid settings field offset {field.offset}")
        if field.offset <= previous_offset:
            raise ValueError("settings field offsets must be strictly increasing")
        if not 1 <= field.value <= 0xFFFFFFFF:
            raise ValueError(
                f"nonzero settings field at {field.offset} must fit an unsigned "
                "32-bit value"
            )
        previous_offset = field.offset
        _UINT32_LE.pack_into(encoded, field.offset, field.value)
    return bytes(encoded) + payload.trailing_data


def encode_mhod_body(
    chunk: ParsedChunk[MhodHeader],
    payload_kind: MhodPayloadKind,
) -> tuple[bytes, MhodHeader]:
    """Encode one changed MHOD body through its mandatory typed inverse."""

    validate_mhod_body_representation(chunk, payload_kind)
    if payload_kind == MhodPayloadKind.STRING:
        body = _encode_string(chunk)
    elif payload_kind == MhodPayloadKind.URL:
        body = _encode_url(chunk)
    elif payload_kind == MhodPayloadKind.OPAQUE:
        body = _encode_opaque(chunk)
    elif payload_kind == MhodPayloadKind.CHAPTER_DATA:
        body = _encode_chapter_data(chunk)
    elif payload_kind == MhodPayloadKind.VIDEO_DETAILS:
        body = _encode_video_details(chunk)
    elif payload_kind == MhodPayloadKind.SMART_PREFS:
        body = _encode_smart_preferences(chunk)
    elif payload_kind == MhodPayloadKind.SMART_RULES:
        body = _encode_smart_rules(chunk)
    elif payload_kind == MhodPayloadKind.LIBRARY_INDEX:
        body = _encode_library_index(chunk)
    elif payload_kind == MhodPayloadKind.LIBRARY_JUMP_TABLE:
        body = _encode_library_jump_table(chunk)
    elif payload_kind == MhodPayloadKind.PLIST:
        body = _encode_plist(chunk)
    elif payload_kind == MhodPayloadKind.PLAYLIST_POSITION:
        body = _encode_playlist_position(chunk)
    elif payload_kind == MhodPayloadKind.SETTINGS:
        body = _encode_settings(chunk)
    else:
        raise ValueError(
            f"MHOD payload kind {payload_kind.value} has no concrete encoder"
        )
    return body, chunk.header
