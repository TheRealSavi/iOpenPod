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
"""

from __future__ import annotations

import logging
from typing import Any

from ._parsing import read_generic_header

logger = logging.getLogger(__name__)


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
        case "mhlt":
            from .mhlt_parser import parse_track_list
            result = parse_track_list(data, offset, header_length, length_or_children)
        case "mhit":
            from .mhit_parser import parse_track_item
            result = parse_track_item(data, offset, header_length, length_or_children)
        case "mhlp":
            from .mhlp_parser import parse_playlist_list
            result = parse_playlist_list(data, offset, header_length, length_or_children)
        case "mhyp":
            from .mhyp_parser import parse_playlist
            result = parse_playlist(data, offset, header_length, length_or_children)
        case "mhip":
            from .mhip_parser import parse_playlist_item
            result = parse_playlist_item(data, offset, header_length, length_or_children)
        case "mhod":
            from .mhod_parser import parse_mhod
            result = parse_mhod(data, offset, header_length, length_or_children)
        case "mhla":
            from .mhla_parser import parse_album_list
            result = parse_album_list(data, offset, header_length, length_or_children)
        case "mhia":
            from .mhia_parser import parse_album_item
            result = parse_album_item(data, offset, header_length, length_or_children)
        case "mhli":
            from .mhli_parser import parse_artist_list
            result = parse_artist_list(data, offset, header_length, length_or_children)
        case "mhii":
            # NOTE: shares the 'mhii' magic with ArtworkDB image items,
            # but in iTunesDB context this is an artist item.
            from .mhii_parser import parse_artist_item
            result = parse_artist_item(data, offset, header_length, length_or_children)
        case _:
            logger.warning(
                "Skipping unknown iTunesDB chunk type %r at offset 0x%X",
                chunk_type, offset,
            )
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

    # Attach raw header bytes for data-collection / analysis of
    # uninspected regions.  Only for dict-shaped results (item/container
    # chunks); list-shaped results (mhlt, mhlp, mhla, mhli) have
    # trivial 12-byte headers already fully described by the generic header.
    if isinstance(result.get("data"), dict):
        result["data"]["_raw_header"] = bytes(data[offset:offset + header_length])

    return result, chunk_type
