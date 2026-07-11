import struct

from iopenpod.itunesdb_shared.field_base import (
    GENERIC_HEADER_SIZE,
    MHLT_HEADER_SIZE,
    write_list_chunk,
    write_list_header,
)


def test_write_list_header_sets_count_and_zero_padding():
    header = write_list_header(b"mhlt", MHLT_HEADER_SIZE, 0)

    assert len(header) == MHLT_HEADER_SIZE
    assert struct.unpack_from("<4sII", header, 0) == (
        b"mhlt",
        MHLT_HEADER_SIZE,
        0,
    )
    assert header[GENERIC_HEADER_SIZE:] == b"\x00" * (
        MHLT_HEADER_SIZE - GENERIC_HEADER_SIZE
    )


def test_write_list_chunk_counts_child_chunks_and_appends_body():
    chunk = write_list_chunk(b"mhlp", MHLT_HEADER_SIZE, [b"one", b"two"])

    assert struct.unpack_from("<4sII", chunk, 0) == (
        b"mhlp",
        MHLT_HEADER_SIZE,
        2,
    )
    assert chunk[MHLT_HEADER_SIZE:] == b"onetwo"
