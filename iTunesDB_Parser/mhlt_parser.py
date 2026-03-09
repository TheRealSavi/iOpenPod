"""MHLT (Track List) parser.

A pure-list container whose children are MHIT (Track Item) chunks.
The third generic-header field is ``child_count`` (number of tracks).
"""

from __future__ import annotations

from ._parsing import ParseResult, parse_child_list


def parse_track_list(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    child_count: int,
) -> ParseResult:
    """Parse an MHLT chunk by iterating its MHIT children."""
    return parse_child_list(data, offset, header_length, child_count)
