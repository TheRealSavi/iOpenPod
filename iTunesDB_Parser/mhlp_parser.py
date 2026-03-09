"""MHLP (Playlist List) parser.

A pure-list container whose children are MHYP (Playlist) chunks.
Appears in MHSD types 2 (regular playlists), 3 (podcasts), and
5 (smart playlists).
"""

from __future__ import annotations

from ._parsing import ParseResult, parse_child_list


def parse_playlist_list(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    child_count: int,
) -> ParseResult:
    """Parse an MHLP chunk by iterating its MHYP children."""
    return parse_child_list(data, offset, header_length, child_count)
