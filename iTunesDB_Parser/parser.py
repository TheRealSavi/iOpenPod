"""
iTunesDB / iTunesCDB entry-point parser.

Accepts a file path (str) or file-like readable object pointing to
an iPod's ``/iPod_Control/iTunes/iTunesDB`` (or ``iTunesCDB``) binary
file.  Returns the fully-parsed database as a nested dict/list structure.

iTunesCDB format (Nano 5G, 6G, 7G)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The file begins with a standard 244-byte ``mhbd`` header (uncompressed)
followed by a **zlib-compressed** payload containing all the ``mhsd``
children.  The ``total_length`` field in the mhbd header equals the
*compressed* file size, not the decompressed size.

This parser transparently decompresses the payload and reconstructs a
standard in-memory representation that the rest of the parsing pipeline
can process unchanged.

Usage::

    from iTunesDB_Parser.parser import parse_itunesdb
    db = parse_itunesdb("/Volumes/IPOD/iPod_Control/iTunes/iTunesCDB")
"""

import logging
import struct
import zlib

logger = logging.getLogger(__name__)


def _decompress_itunescdb(data: bytes) -> bytes:
    """If *data* is an iTunesCDB (compressed), decompress and return a
    standard iTunesDB byte stream.  If it's already uncompressed, return
    as-is.

    Detection: the mhbd header's ``unk_0x0C`` field is 2 for compressed-DB
    capable devices, and the first byte after the header is 0x78 (zlib magic).
    """
    if len(data) < 16 or data[:4] != b"mhbd":
        return data  # not even a valid mhbd

    header_len = struct.unpack_from("<I", data, 4)[0]
    unk_0x0c = struct.unpack_from("<I", data, 0x0C)[0]

    # Quick check: is there a zlib stream immediately after the header?
    if unk_0x0c != 2 or header_len >= len(data):
        return data
    if data[header_len] != 0x78:  # zlib magic byte
        return data

    # Decompress the payload
    try:
        decompressed = zlib.decompress(data[header_len:])
    except zlib.error:
        return data  # not actually compressed, return as-is

    # Reconstruct: original header + decompressed children
    header = bytearray(data[:header_len])

    # Fix total_length to reflect the full uncompressed size
    full_size = header_len + len(decompressed)
    struct.pack_into("<I", header, 8, full_size)

    # Clear unk_0xA8 (compression flag) to 0, matching libgpod's read path.
    # This ensures the in-memory representation looks like a standard iTunesDB.
    struct.pack_into("<H", header, 0xA8, 0)

    logger.debug(
        "iTunesCDB decompressed: %d bytes → %d bytes (header=%d, payload=%d)",
        len(data), full_size, header_len, len(decompressed),
    )
    return bytes(header) + decompressed


def parse_itunesdb(file) -> dict:
    from .chunk_parser import parse_chunk

    if isinstance(file, str):  # If it's a file path, open the file
        with open(file, "rb") as f:
            data = f.read()
    elif hasattr(file, "read"):  # If it's a file-like object, read it directly
        data = file.read()
    else:
        raise TypeError("file must be a path (str) or a file-like object")

    # Transparently handle iTunesCDB (compressed database)
    data = _decompress_itunescdb(data)

    result = parse_chunk(data, 0)

    # Return just the parsed data, not the wrapper with nextOffset
    return result.get("result", result)
