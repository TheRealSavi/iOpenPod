"""
Chunk dispatcher / router for iTunesDB binary parsing.

Every chunk in the iTunesDB starts with the same 12-byte header:
    +0x00: chunk_type (4B)      — ASCII identifier (e.g. 'mhbd', 'mhit', 'mhod')
    +0x04: header_length (4B)   — bytes to end of type-specific header
    +0x08: total_length (4B)    — header + all children (or child count for mhlt/mhlp)

The total_length field has two interpretations:
    • Most chunks: byte offset to end of this chunk and all its children.
    • mhlt / mhlp / mhla: number of child items (tracks / playlists / albums),
      NOT a byte length.  The actual end must be discovered by parsing children.

This module reads the 12-byte header and dispatches to the appropriate parser
based on chunk_type via a match statement.  Each parser returns:
    {"nextOffset": int, "result": dict/list}

Cross-referenced against:
  - iPodLinux wiki § Chunk Encoding
  - libgpod itdb_itunesdb.c: parse_tracks() etc.
"""

import struct
from typing import Any


def parse_chunk(data, offset) -> dict[str, Any]:
    chunk_type = data[offset:offset + 4].decode("utf-8")
    header_length = struct.unpack("<I", data[offset + 4:offset + 8])[0]
    chunk_length = struct.unpack("<I", data[offset + 8:offset + 12])[0]

    match chunk_type:
        case "mhbd":
            # database
            from .mhbd_parser import parse_db
            result = parse_db(data, offset, header_length, chunk_length)
            return result
        case "mhsd":
            # dataset
            from .mhsd_parser import parse_dataset
            result = parse_dataset(data, offset, header_length, chunk_length)
            return result
        case "mhlt":
            # track list
            from .mhlt_parser import parse_trackList
            result = parse_trackList(data, offset, header_length, chunk_length)
            return result
        case "mhit":
            # Track Item
            from .mhit_parser import parse_trackItem
            result = parse_trackItem(data, offset, header_length, chunk_length)
            return result
        case "mhlp":
            # playlist list
            from .mhlp_parser import parse_playlistList
            result = parse_playlistList(data, offset, header_length, chunk_length)
            return result
        case "mhyp":
            # playlist
            from .mhyp_parser import parse_playlist
            result = parse_playlist(data, offset, header_length, chunk_length)
            return result
        case "mhip":
            # playlist item
            from .mhip_parser import parse_playlistItem
            result = parse_playlistItem(data, offset, header_length, chunk_length)
            return result
        case "mhod":
            # data object
            from .mhod_parser import parse_mhod
            result = parse_mhod(data, offset, header_length, chunk_length)
            return result
        case "mhla":
            # Album List
            from .mhla_parser import parse_albumList
            result = parse_albumList(data, offset, header_length, chunk_length)
            return result
        case "mhia":
            # Album Item
            from .mhia_parser import parse_albumItem
            result = parse_albumItem(data, offset, header_length, chunk_length)
            return result
        case _:
            # Unknown chunk — skip gracefully.  The parent (MHSD) uses its
            # own total_length so an imprecise nextOffset here is harmless.
            import logging
            logging.getLogger(__name__).warning(
                "Skipping unknown iTunesDB chunk type: %s at offset 0x%X",
                chunk_type, offset,
            )
            return {
                "nextOffset": offset + chunk_length,
                "result": {"chunkType": chunk_type, "skipped": True},
            }
