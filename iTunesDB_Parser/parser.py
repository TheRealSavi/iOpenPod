"""
iTunesDB / iTunesCDB entry-point parser.

This module provides the public parsing API for Apple's proprietary
iTunesDB binary database format (and its zlib-compressed variant,
iTunesCDB).  It accepts either a file path or a file-like object and
returns a nested dict tree representing the full database hierarchy.

Typical usage::

    from iTunesDB_Parser import parse_itunesdb

    db = parse_itunesdb("/media/ipod/iPod_Control/iTunes/iTunesDB")
"""

from __future__ import annotations

import logging
import os
import zlib
from typing import Any, BinaryIO, Union

from ._parsing import UINT32_LE
from .exceptions import CorruptHeaderError

logger = logging.getLogger(__name__)

# Recognized mhbd magic at file offset 0.
_MHBD_MAGIC = b"mhbd"

# Minimum length to contain the mhbd generic header (magic + header_len + total_len + compressed).
_MIN_MHBD_HEADER = 16

# iTunesCDB compressed-flag value (mhbd offset 0x0C).
_COMPRESSED_DB_FLAG = 0x02


def decompress_itunescdb(data: bytes | bytearray) -> bytes | bytearray:
    """Transparently decompress an iTunesCDB into a standard iTunesDB stream.

    If *data* is already an uncompressed iTunesDB (or is too short / has the
    wrong magic), it is returned as-is.

    Detection logic: the mhbd ``compressed`` field at offset 0x0C is ``2`` for
    compressed-DB-capable devices, and the payload after the header is a zlib
    stream.

    Args:
        data: Raw bytes of an iTunesDB or iTunesCDB file.

    Returns:
        Decompressed iTunesDB byte stream (original header preserved).
    """
    if len(data) < _MIN_MHBD_HEADER or data[:4] != _MHBD_MAGIC:
        return data

    header_length = UINT32_LE.unpack_from(data, 0x04)[0]
    compressed_flag = UINT32_LE.unpack_from(data, 0x0C)[0]

    if compressed_flag != _COMPRESSED_DB_FLAG:
        return data

    try:
        decompressed = zlib.decompress(data[header_length:])
    except zlib.error:
        return data  # not actually compressed — return as-is

    # Reconstruct: original (unmodified) header + decompressed children.
    # Header's total_length (offset 8) and compression flag are preserved
    # as-is.  MHBD children are parsed by child_count so the stale
    # total_length is harmless.
    logger.debug("iTunesCDB decompressed: %d -> %d payload bytes",
                 len(data) - header_length, len(decompressed))
    return data[:header_length] + decompressed


def parse_itunesdb(file: Union[str, os.PathLike[str], BinaryIO]) -> dict[str, Any]:
    """Parse an iTunesDB (or iTunesCDB) file into a nested dict tree.

    Args:
        file: A filesystem path (``str`` or ``os.PathLike``) or an open
              binary file-like object positioned at the start of the data.

    Returns:
        Dict representation of the mhbd root chunk and all children.

    Raises:
        TypeError: If *file* is not a path or file-like object.
        ITunesDBParseError: If the binary data cannot be parsed.
        OSError: If a file path cannot be read.
    """
    from .chunk_parser import parse_chunk

    if isinstance(file, (str, os.PathLike)):
        with open(file, "rb") as fh:
            data: bytes | bytearray = fh.read()
    elif hasattr(file, "read"):
        data = file.read()
    else:
        raise TypeError(
            f"file must be a path (str/PathLike) or a file-like object, "
            f"got {type(file).__name__}"
        )

    if not data:
        raise CorruptHeaderError(0, "empty file")

    # Transparently handle iTunesCDB (compressed database)
    data = decompress_itunescdb(data)

    parsed, _chunk_type = parse_chunk(data, 0)
    return parsed["data"]
