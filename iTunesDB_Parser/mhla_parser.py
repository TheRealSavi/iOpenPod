"""MHLA (Album List) parser.

A pure-list container whose children are MHIA (Album Item) chunks.
Present in MHSD type 4 (iTunes 7.1+).
"""

from __future__ import annotations

from ._parsing import ParseResult, parse_child_list


def parse_album_list(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    child_count: int,
) -> ParseResult:
    """Parse an MHLA chunk by iterating its MHIA children."""
    return parse_child_list(data, offset, header_length, child_count)
