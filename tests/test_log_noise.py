import logging
import struct

from iTunesDB_Parser.chunk_parser import (
    log_unknown_chunk_summary,
    parse_chunk,
    reset_unknown_chunk_summary,
)


def test_unknown_itunesdb_chunks_are_summarized(caplog) -> None:
    chunk = struct.pack("<4sII", b"4407", 12, 12)

    reset_unknown_chunk_summary()
    with caplog.at_level(logging.WARNING):
        parse_chunk(chunk, 0)
        parse_chunk(chunk, 0)

        assert "unknown iTunesDB chunk" not in caplog.text

        log_unknown_chunk_summary()

    assert "iTunesDB contained 2 unknown chunk(s)" in caplog.text
    assert "'4407' at 0x0" in caplog.text
