"""MHBD (Database Header) parser.

The MHBD chunk is the root of the iTunesDB file.  It contains global
metadata (version, hashing scheme, persistent IDs, cryptographic hashes)
followed by one or more MHSD (DataSet) children.

Binary layout (offsets relative to chunk start)::

    +0x00  'mhbd'  magic
    +0x04  header_length
    +0x08  total_length (entire file size)
    +0x0C  compressed flag
    +0x10  database version
    +0x14  child_count (number of MHSD datasets)
    +0x18  db_id (u64)
    +0x20  platform (u16)  -- 1=Mac, 2=Windows
    ...    (see mhbd_defs.py for complete field map)
"""

from __future__ import annotations

from typing import Any

import iTunesDB_Shared as idb
from ._parsing import ParseResult, parse_children


def _parse_mhbd_header(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
) -> dict[str, Any]:
    """Extract all MHBD header fields into a flat dict."""
    return idb.read_fields(data, offset, "mhbd", header_length)


def parse_db(
    data: bytes | bytearray,
    offset: int,
    header_length: int,
    chunk_length: int,
) -> ParseResult:
    """Parse an MHBD (Database) chunk and its MHSD children."""
    mhbd = _parse_mhbd_header(data, offset, header_length)
    mhbd["children"], _ = parse_children(
        data, offset + header_length, mhbd["child_count"],
    )
    return {"next_offset": offset + chunk_length, "data": mhbd}
