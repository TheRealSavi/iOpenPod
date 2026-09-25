from __future__ import annotations

import struct

import pytest

from iPodDB.iTunesDB.cdb import (
    compress_iTunesCDB,
    decompress_iTunesCDB,
    is_iTunesCDB,
)
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary


def _database() -> bytes:
    header = bytearray(244)
    header[:4] = b"mhbd"
    struct.pack_into("<III", header, 4, 244, 244, 1)
    struct.pack_into("<I", header, 0x10, 0x6F)
    return bytes(header)


def test_cdb_framing_roundtrips_through_the_shared_parser() -> None:
    logical = _database()
    physical = compress_iTunesCDB(logical)

    assert is_iTunesCDB(physical)
    assert physical[244] == 0x78
    assert int.from_bytes(physical[8:12], "little") == len(physical)
    assert int.from_bytes(physical[0xA8:0xAA], "little") == 1

    unwrapped = decompress_iTunesCDB(physical)
    assert unwrapped.source_bytes == physical
    assert unwrapped.logical_bytes[244:] == logical[244:]
    assert int.from_bytes(unwrapped.logical_bytes[8:12], "little") == len(logical)
    assert int.from_bytes(unwrapped.logical_bytes[0xA8:0xAA], "little") == 0
    assert (
        write_iTunesDB(parse_iTunesDB(unwrapped.logical_bytes))
        == unwrapped.logical_bytes
    )
    with pytest.raises(ValueError, match="decompress iTunesCDB framing first"):
        parse_iTunesDB(physical)
    assert IPodLibrary.parse(physical).serialize().itunes == physical


def test_cdb_rejects_trailing_or_corrupt_payloads() -> None:
    physical = compress_iTunesCDB(_database())
    trailing = bytearray(physical + b"trailing")
    trailing[8:12] = len(trailing).to_bytes(4, "little")

    with pytest.raises(ValueError, match="trailing"):
        decompress_iTunesCDB(trailing)
    corrupt = bytearray(physical[:244] + b"x-not-zlib")
    corrupt[8:12] = len(corrupt).to_bytes(4, "little")
    with pytest.raises(ValueError, match="malformed"):
        decompress_iTunesCDB(corrupt)
