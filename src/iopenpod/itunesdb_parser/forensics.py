"""Human-first, lossless JSON export for forensic iTunesDB analysis.

The exported document is a recursive byte walk, rather than a conventional
parsed-data tree with raw data attached elsewhere.  A chunk owns one ordered
``bytes`` list.  Every entry in that list is either a byte span (with its raw
hex and local interpretation) or a nested child chunk at the precise point
where that child occurs in the parent.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from iopenpod.itunesdb_shared import mhod_defs
from iopenpod.itunesdb_shared.constants import identifier_readable_map, mhod_type_map
from iopenpod.itunesdb_shared.field_base import GENERIC_HEADER_SIZE, get_fields

from .parser import parse_itunesdb

_MISSING = object()


def _offset(value: int) -> str:
    """Format an offset consistently for people reading a byte walk."""
    return f"0x{value:04X}"


def _hex(value: bytes) -> str:
    """Use spaced hex so a byte is visible without mentally grouping digits."""
    return value.hex(" ")


def _json_value(value: Any) -> Any:
    """Make a decoded parser value JSON-safe without discarding its bytes."""
    if isinstance(value, (bytes, bytearray)):
        return {"hex": _hex(bytes(value)), "byte_length": len(value)}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _chunk_type(raw_chunk: dict[str, Any]) -> str:
    return raw_chunk["raw_header"][:4].decode("ascii", errors="replace")


def _node_parts(
    node: dict[str, Any],
) -> tuple[str, dict[str, Any] | list[dict[str, Any]], dict[str, Any]]:
    """Normalize the root node and a parser child wrapper to one shape."""
    raw_chunk = node["_raw_chunk"]
    data = node.get("data", node)
    if not isinstance(data, (dict, list)):
        data = {}
    return _chunk_type(raw_chunk), data, raw_chunk


def _child_nodes(data: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return direct parser children once, in their physical file order."""
    children: list[dict[str, Any]] = []
    seen_offsets: set[int] = set()
    child_groups = [data] if isinstance(data, list) else [
        data.get(key, []) for key in ("children", "mhod_children", "mhip_children")
    ]
    for group in child_groups:
        for child in group:
            if not isinstance(child, dict) or "_raw_chunk" not in child:
                continue
            offset = child["_raw_chunk"]["offset"]
            if offset not in seen_offsets:
                children.append(child)
                seen_offsets.add(offset)
    return sorted(children, key=lambda child: child["_raw_chunk"]["offset"])


def _field_status(field_name: str) -> str:
    """Keep an established decoded value distinct from an unexplained name."""
    if (
        field_name.startswith("unk")
        or field_name.startswith("mhsd5")
        or field_name == "phase_game_flag"
    ):
        return "observed"
    return "known"


def _annotation(start: int, end: int, **details: Any) -> tuple[int, int, dict[str, Any]]:
    """Store an internal range annotation until gaps can be filled."""
    return start, end, details


def _spans_with_gaps(
    source: bytes,
    *,
    chunk_offset: int,
    start: int,
    end: int,
    annotations: list[tuple[int, int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Turn annotated ranges into an ordered, complete local byte listing."""
    entries: list[dict[str, Any]] = []
    cursor = start
    for annotation_start, annotation_end, details in sorted(annotations):
        if annotation_start < start or annotation_end > end:
            raise ValueError("byte-walk annotation falls outside its chunk")
        if annotation_start < cursor:
            raise ValueError("byte-walk annotations overlap")
        if cursor < annotation_start:
            entries.append(
                _span(
                    source,
                    chunk_offset,
                    cursor,
                    annotation_start,
                    status="unmapped",
                ),
            )
        entry = {
            "at": _offset(annotation_start),
            "byte_length": annotation_end - annotation_start,
            **details,
        }
        if "chunk" not in entry:
            entry["hex"] = _hex(
                source[
                    chunk_offset + annotation_start:chunk_offset + annotation_end
                ],
            )
        entries.append(entry)
        cursor = annotation_end
    if cursor < end:
        entries.append(_span(source, chunk_offset, cursor, end, status="unmapped"))
    return entries


def _span(
    source: bytes,
    chunk_offset: int,
    start: int,
    end: int,
    **details: Any,
) -> dict[str, Any]:
    """Create a leaf byte span from a chunk-relative range."""
    return {
        "at": _offset(start),
        "byte_length": end - start,
        "hex": _hex(source[chunk_offset + start:chunk_offset + end]),
        **details,
    }


def _playlist_title(data: dict[str, Any]) -> str | None:
    """Return an MHYP title when the playlist carries an MHOD title child."""
    for child in data.get("mhod_children", []):
        child_data = child.get("data", {})
        if child_data.get("mhod_type") == 1:
            value = child_data.get("string")
            if isinstance(value, str):
                return value
    return None


def _chunk_caption(chunk_type: str, data: dict[str, Any]) -> str:
    """Provide a terse human landmark without replacing the byte listing."""
    readable = identifier_readable_map.get(chunk_type, chunk_type)
    if chunk_type == "mhyp":
        title = _playlist_title(data)
        if title:
            return f"{readable}: {title}"
    if chunk_type == "mhod":
        mhod_type = data.get("mhod_type")
        if isinstance(mhod_type, int):
            return f"{readable}: {mhod_type_map.get(mhod_type, f'type {mhod_type}')}"
    return readable


def _header_annotations(
    chunk_type: str,
    data: dict[str, Any],
    raw_chunk: dict[str, Any],
) -> list[tuple[int, int, dict[str, Any]]]:
    """Describe every parser-defined header field in local byte order."""
    raw_header = raw_chunk["raw_header"]
    header_length = len(raw_header)
    third_value = int.from_bytes(raw_header[8:12], "little")
    annotations = [
        _annotation(
            0,
            4,
            field="chunk_type",
            value=chunk_type,
            encoding="ascii",
            status="known",
        ),
        _annotation(
            4,
            8,
            field="header_length",
            value=int.from_bytes(raw_header[4:8], "little"),
            encoding="u32le",
            status="known",
        ),
        _annotation(
            8,
            GENERIC_HEADER_SIZE,
            field="declared_length_or_child_count",
            value=third_value,
            encoding="u32le",
            status="known",
        ),
    ]

    phase_playlist = _playlist_title(data) == "Phase Music"
    for field in get_fields(chunk_type, header_length):
        if field.offset < GENERIC_HEADER_SIZE:
            continue
        end = field.offset + field.size
        if end > header_length:
            continue
        details: dict[str, Any] = {
            "field": field.name,
            "value": _json_value(data.get(field.name)),
            "status": _field_status(field.name),
        }
        if chunk_type == "mhyp" and field.name == "phase_game_flag" and phase_playlist:
            details.update(
                {
                    "field": "phase_game_flag",
                    "note": (
                        "Observed value 25 (0x0019) occurs in both mirrored "
                        "Phase Music playlists; its purpose is not yet proven."
                    ),
                },
            )
        annotations.append(_annotation(field.offset, end, **details))
    return annotations


def _mhod_string_annotations(
    data: dict[str, Any],
    body_start: int,
    body_end: int,
    chunk_offset: int,
    source: bytes,
) -> list[tuple[int, int, dict[str, Any]]]:
    """Map the variable string sub-header and text payload of an MHOD."""
    if body_end - body_start < mhod_defs.MHOD_STRING_SUBHEADER_SIZE:
        return []
    encoding = int.from_bytes(
        source[chunk_offset + body_start:chunk_offset + body_start + 4],
        "little",
    )
    text_length = int.from_bytes(
        source[chunk_offset + body_start + 4:chunk_offset + body_start + 8],
        "little",
    )
    text_start = body_start + mhod_defs.MHOD_STRING_SUBHEADER_SIZE
    text_end = min(text_start + text_length, body_end)
    annotations = [
        _annotation(
            body_start,
            body_start + 4,
            field="string_encoding",
            value=encoding,
            encoding="u32le",
            status="known",
        ),
        _annotation(
            body_start + 4,
            body_start + 8,
            field="string_byte_length",
            value=text_length,
            encoding="u32le",
            status="known",
        ),
        _annotation(
            body_start + 8,
            body_start + 12,
            field="unk_0x20",
            value=_json_value(data.get("unk_0x20")),
            status="observed",
        ),
        _annotation(
            body_start + 12,
            text_start,
            field="unk_0x24",
            value=_json_value(data.get("unk_0x24")),
            status="observed",
        ),
    ]
    if text_end > text_start:
        annotations.append(
            _annotation(
                text_start,
                text_end,
                field="text",
                value=_json_value(data.get("string")),
                encoding="utf-8" if encoding == 2 else "utf-16le",
                status="known",
            ),
        )
    return annotations


def _mhod_splpref_annotations(
    body_start: int,
    body_end: int,
    parsed_body: dict[str, Any],
) -> list[tuple[int, int, dict[str, Any]]]:
    """Map the defined leading fields of an MHOD type-50 preference record."""
    fields = (
        (0, 1, "live_update", "u8"),
        (1, 2, "check_rules", "u8"),
        (2, 3, "check_limits", "u8"),
        (3, 4, "limit_type", "u8"),
        (4, 5, "limit_sort", "u8"),
        (8, 12, "limit_value", "u32le"),
        (12, 13, "match_checked_only", "u8"),
        (13, 14, "reverse_sort", "u8"),
    )
    annotations: list[tuple[int, int, dict[str, Any]]] = []
    for start, end, field, encoding in fields:
        if body_start + end <= body_end:
            annotations.append(
                _annotation(
                    body_start + start,
                    body_start + end,
                    field=field,
                    value=_json_value(parsed_body.get(field)),
                    encoding=encoding,
                    status="known",
                ),
            )
    if body_start + 8 <= body_end:
        annotations.append(
            _annotation(body_start + 5, body_start + 8, status="padding"),
        )
    return annotations


def _mhod_slst_annotations(
    body_start: int,
    body_end: int,
    parsed_body: dict[str, Any],
) -> list[tuple[int, int, dict[str, Any]]]:
    """Map an SLst smart-playlist rule blob without hiding its padding."""
    if body_end - body_start < 16:
        return []
    annotations = [
        _annotation(
            body_start,
            body_start + 4,
            field="slst_magic",
            value="SLst",
            encoding="ascii",
            status="known",
        ),
        _annotation(
            body_start + 4,
            body_start + 8,
            field="unk004",
            value=_json_value(parsed_body.get("unk004")),
            encoding="u32be",
            status="observed",
        ),
        _annotation(
            body_start + 8,
            body_start + 12,
            field="rule_count",
            value=_json_value(parsed_body.get("rule_count")),
            encoding="u32be",
            status="known",
        ),
        _annotation(
            body_start + 12,
            body_start + 16,
            field="conjunction",
            value=_json_value(parsed_body.get("conjunction")),
            encoding="u32be",
            status="known",
        ),
    ]
    rules_start = body_start + mhod_defs.SLST_HEADER_SIZE
    if rules_start <= body_end:
        annotations.append(_annotation(body_start + 16, rules_start, status="padding"))

    cursor = rules_start
    for rule in parsed_body.get("rules", []):
        if cursor + mhod_defs.SPL_RULE_HEADER_SIZE > body_end:
            break
        data_length = rule.get("data_length")
        if not isinstance(data_length, int) or data_length < 0:
            break
        rule_data_start = cursor + mhod_defs.SPL_RULE_HEADER_SIZE
        rule_end = min(rule_data_start + data_length, body_end)
        annotations.extend(
            (
                _annotation(
                    cursor,
                    cursor + 4,
                    field="rule_field_id",
                    value=_json_value(rule.get("field_id")),
                    encoding="u32be",
                    status="known",
                ),
                _annotation(
                    cursor + 4,
                    cursor + 8,
                    field="rule_action_id",
                    value=_json_value(rule.get("action_id")),
                    encoding="u32be",
                    status="known",
                ),
                _annotation(cursor + 8, cursor + 52, status="padding"),
                _annotation(
                    cursor + 52,
                    cursor + 56,
                    field="rule_data_length",
                    value=data_length,
                    encoding="u32be",
                    status="known",
                ),
            ),
        )
        if "string_value" in rule:
            annotations.append(
                _annotation(
                    rule_data_start,
                    rule_end,
                    field="rule_text",
                    value=_json_value(rule["string_value"]),
                    encoding="utf-16be",
                    status="known",
                ),
            )
        elif rule_end - rule_data_start >= mhod_defs.SPL_RULE_DATA_SIZE:
            numeric_fields = (
                (0, 8, "from_value"),
                (8, 16, "from_date"),
                (16, 24, "from_units"),
                (24, 32, "to_value"),
                (32, 40, "to_date"),
                (40, 48, "to_units"),
                (48, 52, "unk052"),
                (52, 56, "unk056"),
                (56, 60, "unk060"),
                (60, 64, "unk064"),
                (64, 68, "unk068"),
            )
            for start, end, field in numeric_fields:
                annotations.append(
                    _annotation(
                        rule_data_start + start,
                        rule_data_start + end,
                        field=field,
                        value=_json_value(rule.get(field)),
                        encoding="u64be" if end - start == 8 else "u32be",
                        status=_field_status(field),
                    ),
                )
        elif rule_end > rule_data_start:
            annotations.append(
                _annotation(
                    rule_data_start,
                    rule_end,
                    field="rule_data",
                    value=_json_value(rule),
                    status="partially_decoded",
                ),
            )
        cursor = rule_end
    return annotations


def _mhod_index_annotations(
    mhod_type: int,
    body_start: int,
    body_end: int,
    parsed_body: dict[str, Any],
) -> list[tuple[int, int, dict[str, Any]]]:
    """Map type-52 sorted-index and type-53 jump-table bodies."""
    if body_end - body_start < 8:
        return []
    annotations = [
        _annotation(
            body_start,
            body_start + 4,
            field="sort_type",
            value=_json_value(parsed_body.get("sort_type")),
            encoding="u32le",
            status="known",
        ),
        _annotation(
            body_start + 4,
            body_start + 8,
            field="count",
            value=_json_value(parsed_body.get("count")),
            encoding="u32le",
            status="known",
        ),
    ]
    if mhod_type == 52:
        entries_start = body_start + mhod_defs.MHOD52_BODY_HEADER_SIZE
        if entries_start <= body_end:
            annotations.append(_annotation(body_start + 8, entries_start, status="padding"))
        for index, value in enumerate(parsed_body.get("indices", [])):
            start = entries_start + index * 4
            if start + 4 > body_end:
                break
            annotations.append(
                _annotation(
                    start,
                    start + 4,
                    field="track_index",
                    value=_json_value(value),
                    encoding="u32le",
                    status="known",
                ),
            )
    else:
        entries_start = body_start + mhod_defs.MHOD53_BODY_HEADER_SIZE
        if entries_start <= body_end:
            annotations.append(_annotation(body_start + 8, entries_start, status="padding"))
        for index, entry in enumerate(parsed_body.get("entries", [])):
            start = entries_start + index * mhod_defs.MHOD53_ENTRY_SIZE
            if start + mhod_defs.MHOD53_ENTRY_SIZE > body_end:
                break
            annotations.append(
                _annotation(
                    start,
                    start + mhod_defs.MHOD53_ENTRY_SIZE,
                    field="jump_table_entry",
                    value=_json_value(entry),
                    status="known",
                ),
            )
    return annotations


def _mhod_observed_fields_annotations(
    body_start: int,
    body_end: int,
    parsed_body: dict[str, Any],
) -> list[tuple[int, int, dict[str, Any]]]:
    """Show the parser's nonzero-u32 observations in opaque preference blobs."""
    annotations: list[tuple[int, int, dict[str, Any]]] = []
    for offset, value in parsed_body.get("fields", {}).items():
        try:
            start = body_start + int(offset, 0)
        except (TypeError, ValueError):
            continue
        if start + 4 <= body_end:
            annotations.append(
                _annotation(
                    start,
                    start + 4,
                    field="observed_nonzero_u32",
                    value=_json_value(value),
                    encoding="u32le",
                    status="observed",
                ),
            )
    return annotations


def _mhod_body_annotations(
    data: dict[str, Any],
    *,
    body_start: int,
    body_end: int,
    chunk_offset: int,
    source: bytes,
) -> list[tuple[int, int, dict[str, Any]]]:
    """Return local byte annotations for the MHOD body family in use."""
    mhod_type = data.get("mhod_type")
    if not isinstance(mhod_type, int) or body_start >= body_end:
        return []
    parsed_body = data.get("data", {})
    if not isinstance(parsed_body, dict):
        parsed_body = {}
    if mhod_type in mhod_defs.STRING_MHOD_TYPES:
        return _mhod_string_annotations(
            data,
            body_start,
            body_end,
            chunk_offset,
            source,
        )
    if mhod_type in mhod_defs.PODCAST_URL_MHOD_TYPES:
        return [
            _annotation(
                body_start,
                body_end,
                field="text",
                value=_json_value(data.get("string")),
                encoding="utf-8",
                status="known",
            ),
        ]
    if mhod_type == 50:
        return _mhod_splpref_annotations(body_start, body_end, parsed_body)
    if mhod_type == 51:
        return _mhod_slst_annotations(body_start, body_end, parsed_body)
    if mhod_type in {52, 53}:
        return _mhod_index_annotations(mhod_type, body_start, body_end, parsed_body)
    if mhod_type in {100, 102}:
        if mhod_type == 100 and "position" in parsed_body and body_end - body_start >= 4:
            return [
                _annotation(
                    body_start,
                    body_start + 4,
                    field="position",
                    value=_json_value(parsed_body["position"]),
                    encoding="u32le",
                    status="known",
                ),
                _annotation(body_start + 4, body_end, status="padding"),
            ]
        return _mhod_observed_fields_annotations(body_start, body_end, parsed_body)
    if mhod_type == 17:
        return [
            _annotation(
                body_start,
                body_end,
                field="chapter_atom_tree",
                value=_json_value(parsed_body),
                status="partially_decoded",
            ),
        ]
    if mhod_type in {32, 55}:
        return [
            _annotation(
                body_start,
                body_end,
                field="opaque_payload",
                value=_json_value(parsed_body),
                status="opaque",
            ),
        ]
    return [
        _annotation(
            body_start,
            body_end,
            field="unclassified_mhod_payload",
            status="opaque",
        ),
    ]


def _leaf_body_annotations(
    chunk_type: str,
    data: dict[str, Any],
    *,
    body_start: int,
    body_end: int,
    chunk_offset: int,
    source: bytes,
) -> list[tuple[int, int, dict[str, Any]]]:
    """Describe a non-container body while keeping its bytes at their location."""
    if chunk_type == "mhod":
        return _mhod_body_annotations(
            data,
            body_start=body_start,
            body_end=body_end,
            chunk_offset=chunk_offset,
            source=source,
        )
    if chunk_type == "mhsd" and "genius_cuid" in data:
        return [
            _annotation(
                body_start,
                body_end,
                field="genius_cuid",
                value=_json_value(data["genius_cuid"]),
                encoding="ascii",
                status="known",
            ),
        ]
    if body_start < body_end:
        return [
            _annotation(body_start, body_end, field="opaque_payload", status="opaque"),
        ]
    return []


def _chunk_json(node: dict[str, Any], source: bytes) -> dict[str, Any]:
    """Render one parser node as an independently readable byte object."""
    chunk_type, data, raw_chunk = _node_parts(node)
    field_data = data if isinstance(data, dict) else {}
    chunk_offset = raw_chunk["offset"]
    chunk_length = raw_chunk["end_offset"] - chunk_offset
    header_length = min(raw_chunk["header_length"], chunk_length)
    annotations = _header_annotations(chunk_type, field_data, raw_chunk)
    entries = _spans_with_gaps(
        source,
        chunk_offset=chunk_offset,
        start=0,
        end=header_length,
        annotations=annotations,
    )

    children = _child_nodes(data)
    if children:
        body_annotations: list[tuple[int, int, dict[str, Any]]] = []
        for child in children:
            child_raw = child["_raw_chunk"]
            child_offset = child_raw["offset"] - chunk_offset
            child_length = child_raw["end_offset"] - child_raw["offset"]
            child_json = _chunk_json(child, source)
            body_annotations.append(
                _annotation(
                    child_offset,
                    child_offset + child_length,
                    chunk=child_json,
                ),
            )
    else:
        body_annotations = _leaf_body_annotations(
            chunk_type,
            field_data,
            body_start=header_length,
            body_end=chunk_length,
            chunk_offset=chunk_offset,
            source=source,
        )
    entries.extend(
        _spans_with_gaps(
            source,
            chunk_offset=chunk_offset,
            start=header_length,
            end=chunk_length,
            annotations=body_annotations,
        ),
    )
    return {
        "chunk": chunk_type,
        "caption": _chunk_caption(chunk_type, field_data),
        "file_offset": _offset(chunk_offset),
        "byte_length": chunk_length,
        "bytes": entries,
    }


def _reconstruct_chunk(chunk: dict[str, Any]) -> bytes:
    """Rebuild one chunk from its byte listing and assert its local coverage."""
    pieces: list[bytes] = []
    cursor = 0
    for entry in chunk["bytes"]:
        entry_offset = int(entry["at"], 0)
        if entry_offset != cursor:
            raise ValueError(
                f"byte walk for {chunk['chunk']} skips or overlaps at {_offset(cursor)}",
            )
        if "chunk" in entry:
            piece = _reconstruct_chunk(entry["chunk"])
        else:
            piece = bytes.fromhex(entry["hex"])
        if len(piece) != entry["byte_length"]:
            raise ValueError("byte-walk entry length does not match its bytes")
        pieces.append(piece)
        cursor += len(piece)
    if cursor != chunk["byte_length"]:
        raise ValueError(
            f"byte walk for {chunk['chunk']} ends at {_offset(cursor)}, "
            f"not {_offset(chunk['byte_length'])}",
        )
    return b"".join(pieces)


def reconstruct_byte_walk(document: dict[str, Any]) -> bytes:
    """Return the exact byte stream represented by a forensic JSON document."""
    return _reconstruct_chunk(document["file"])


def forensic_json_document(source: str | Path) -> dict[str, Any]:
    """Export *source* as a recursive, byte-for-byte forensic JSON document.

    No byte information lives in a sidecar.  Within each chunk, ``bytes`` is
    an ordered sequence of decoded spans, explicit gaps, opaque payloads, and
    nested chunks.  Flattening that sequence reconstructs the input exactly.
    """
    source_path = Path(source)
    source_bytes = source_path.read_bytes()
    parsed = parse_itunesdb(source_path, preserve_raw=True)
    document = {
        "format": "iopenpod-byte-walk/v1",
        "source": {
            "filename": source_path.name,
            "byte_length": len(source_bytes),
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
        },
        "file": _chunk_json(parsed, source_bytes),
    }
    reconstructed = reconstruct_byte_walk(document)
    if reconstructed != source_bytes:
        raise ValueError("byte-walk reconstruction does not match the source file")
    return document


def export_forensic_json(source: str | Path, destination: str | Path) -> Path:
    """Write a human-first, lossless forensic JSON document to *destination*."""
    output_path = Path(destination)
    document = forensic_json_document(source)
    output_path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return output_path
