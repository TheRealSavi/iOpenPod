"""
Generic chunk dispatcher for iTunesDB chunks.

Every chunk in the iTunesDB starts with the same 12-byte generic header::

    +0x00  chunk_type           (4 bytes ASCII)  e.g. ``mhbd``, ``mhit``
    +0x04  header_length        (u32 LE)         bytes to end of header
    +0x08  length_or_children   (u32 LE)         total length *or* child count

This module reads the generic header via :func:`_parsing.read_generic_header`,
then dispatches to the appropriate ``mh*_parser`` module.

Every parser returns::

    {"next_offset": int, "data": dict | list}

Child-iteration helpers (:func:`parse_children`, :func:`parse_child_list`)
also live here so that the recursive ``parse_chunk → parser → parse_children
→ parse_chunk`` loop stays within one module, eliminating the circular import
that previously existed between ``_parsing`` and ``chunk_parser``.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from ._parsing import ParseResult, read_generic_header

logger = logging.getLogger(__name__)

_unknown_chunk_counts: Counter[tuple[str, int]] = Counter()


def reset_unknown_chunk_summary() -> None:
    """Start a fresh unknown-chunk summary for one top-level parse."""
    _unknown_chunk_counts.clear()


def log_unknown_chunk_summary() -> None:
    """Emit a concise summary of unknown chunks seen during the parse."""
    if not _unknown_chunk_counts:
        return

    total = sum(_unknown_chunk_counts.values())
    examples = [
        f"{chunk_type!r} at 0x{offset:X}"
        for (chunk_type, offset), _count in _unknown_chunk_counts.most_common(5)
    ]
    suffix = "" if len(_unknown_chunk_counts) <= 5 else f"; +{len(_unknown_chunk_counts) - 5} more"
    logger.warning(
        "iTunesDB contained %d unknown chunk(s); ignored while parsing. Examples: %s%s",
        total,
        ", ".join(examples),
        suffix,
    )


# ── Child-iteration helpers ──────────────────────────────────────────


def parse_children(
    data: bytes | bytearray,
    offset: int,
    child_count: int,
) -> tuple[list[dict[str, Any]], int]:
    """Parse *child_count* consecutive child chunks starting at *offset*.

    Returns:
        Tuple of ``(children_list, next_offset)`` where each child is
        ``{"chunk_type": str, "data": <parsed>}``.
    """
    children: list[dict[str, Any]] = []
    current = offset
    for _ in range(child_count):
        parsed, chunk_type = parse_chunk(data, current)
        current = parsed["next_offset"]
        children.append({"chunk_type": chunk_type, "data": parsed["data"]})
    return children, current


def _parse_child_list(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    child_count: int,
) -> ParseResult:
    """Parse a pure-list container (mhlt, mhla, mhli, mhlp).

    These chunks consist solely of a thin header followed by *child_count*
    sub-chunks with no additional header fields.

    Returns:
        ``{"next_offset": int, "data": list[...]}``
    """
    children, next_offset = parse_children(data, offset + header_length, child_count)
    return {"next_offset": next_offset, "data": children}


# ── Top-level dispatcher ────────────────────────────────────────────


def parse_chunk(
    data: bytes | bytearray,
    offset: int,
) -> tuple[dict[str, Any], str]:
    """Read the generic header at *offset* and delegate to the typed parser.

    Args:
        data: Full iTunesDB byte buffer.
        offset: Byte position of the chunk to parse.

    Returns:
        Tuple of ``(result_dict, chunk_type)`` where *result_dict* contains
        ``"next_offset"`` and ``"data"`` keys.
    """
    chunk_type, header_length, length_or_children = read_generic_header(data, offset)

    match chunk_type:
        case "mhbd":
            from .mhbd_parser import parse_db
            result = parse_db(data, offset, header_length, length_or_children)
        case "mhsd":
            from .mhsd_parser import parse_dataset
            result = parse_dataset(data, offset, header_length, length_or_children)

        # Pure-list containers — no dedicated parser needed.
        case "mhlt" | "mhla" | "mhli" | "mhlp":
            result = _parse_child_list(data, offset, header_length, length_or_children)

        case "mhit":
            from .mhit_parser import parse_track_item
            result = parse_track_item(data, offset, header_length, length_or_children)
        case "mhyp":
            from .mhyp_parser import parse_playlist
            result = parse_playlist(data, offset, header_length, length_or_children)
        case "mhip":
            from .mhip_parser import parse_playlist_item
            result = parse_playlist_item(data, offset, header_length, length_or_children)
        case "mhod":
            from .mhod_parser import parse_mhod
            result = parse_mhod(data, offset, header_length, length_or_children)
        case "mhia":
            from .mhia_parser import parse_album_item
            result = parse_album_item(data, offset, header_length, length_or_children)
        case "mhii":
            # NOTE: shares the 'mhii' magic with ArtworkDB image items,
            # but in iTunesDB context this is an artist item.
            from .mhii_parser import parse_artist_item
            result = parse_artist_item(data, offset, header_length, length_or_children)
        case _:
            _unknown_chunk_counts[(chunk_type, offset)] += 1
            # NOTE: length_or_children may be a child count rather than
            # a byte length.  For unknown types we naively treat it as a
            # length — the worst case is skipping too little, which the
            # parent's child loop will catch on the next iteration.
            return {
                "next_offset": offset + length_or_children,
                "data": {
                    "chunk_type": chunk_type,
                    "header": bytes(data[offset:offset + header_length]),
                    "body": bytes(data[offset + header_length:offset + length_or_children]),
                },
            }, chunk_type

    return result, chunk_type
