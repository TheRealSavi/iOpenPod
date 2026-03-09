"""MHLI (Artist List) parser for iTunesDB.

A pure-list container whose children are MHII (Artist Item) chunks.
Present in MHSD type 8 (iTunes 9+).

NOTE: This is NOT the same as ArtworkDB's mhli (image list).  In the
iTunesDB context, mhli holds artist/composer items with mhii children.
"""

from __future__ import annotations

from ._parsing import ParseResult, parse_child_list


def parse_artist_list(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    child_count: int,
) -> ParseResult:
    """Parse an MHLI chunk by iterating its MHII artist-item children."""
    return parse_child_list(data, offset, header_length, child_count)
