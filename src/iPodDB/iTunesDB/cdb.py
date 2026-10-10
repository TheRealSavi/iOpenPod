"""Pure iTunesCDB framing around the definition-driven iTunesDB codec.

The root ``mhbd`` header remains uncompressed.  Every child byte after that
header is one zlib stream.  Framing is deliberately separate from Chunk
parsing: callers unwrap the physical artifact, use the ordinary iTunesDB
parser/writer, then wrap the verified logical bytes before signing.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from iPodDB.shared.diagnostics import log_unknown_data, report_unknown_data

_MHBD = b"mhbd"
_GENERIC_HEADER_SIZE = 16
_CDB_FLAG_OFFSET = 0xA8
_CDB_FLAG_SIZE = 2
_CDB_FLAG = 1
_COMPRESSED_CAPABILITY = 2
_MAX_LOGICAL_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ITunesCDB:
    """An unwrapped physical iTunesCDB plus its exact retained source bytes."""

    logical_bytes: bytes
    source_bytes: bytes
    stream_trailing_data: bytes = b""
    file_trailing_data: bytes = b""


def is_iTunesCDB(data: bytes | bytearray) -> bool:
    """Return whether *data* has evidenced iTunesCDB framing.

    The runtime compression flag at ``0xA8`` is authoritative when the header
    is long enough.  The older capability marker at ``0x0C`` is accepted only
    together with a valid-looking zlib stream; it also appears in logical
    databases while writers are preparing them.
    """

    if len(data) < _GENERIC_HEADER_SIZE or data[:4] != _MHBD:
        return False
    header_size = int.from_bytes(data[4:8], "little")
    if not _GENERIC_HEADER_SIZE <= header_size < len(data):
        return False
    flagged = (
        header_size >= _CDB_FLAG_OFFSET + _CDB_FLAG_SIZE
        and int.from_bytes(
            data[_CDB_FLAG_OFFSET : _CDB_FLAG_OFFSET + _CDB_FLAG_SIZE], "little"
        )
        == _CDB_FLAG
    )
    capability = int.from_bytes(data[0x0C:0x10], "little")
    return (flagged or capability == _COMPRESSED_CAPABILITY) and data[
        header_size : header_size + 1
    ] == b"x"


@log_unknown_data("iTunesCDB")
def decompress_iTunesCDB(
    data: bytes | bytearray,
    *,
    max_logical_bytes: int = _MAX_LOGICAL_BYTES,
) -> ITunesCDB:
    """Validate and unwrap one physical iTunesCDB artifact.

    The returned logical root has a repaired extent and a cleared runtime CDB
    flag, so the sole definition-driven parser sees an ordinary iTunesDB tree.
    The capability field at ``0x0C`` is retained because it describes the
    target database family rather than the current framing state.
    Bytes after the zlib stream and outside the root extent remain separate
    opaque regions in the returned framing, ready for recompression.
    """

    source = bytes(data)
    if max_logical_bytes <= 0:
        raise ValueError("The iTunesCDB logical-byte limit must be positive.")
    if not is_iTunesCDB(source):
        raise ValueError("The artifact is not a framed iTunesCDB.")
    header_size = int.from_bytes(source[4:8], "little")
    declared_size = int.from_bytes(source[8:12], "little")
    if not header_size < declared_size <= len(source):
        raise ValueError(
            "The iTunesCDB root extent is truncated or smaller than its payload."
        )
    try:
        decompressor = zlib.decompressobj()
        payload_limit = max_logical_bytes - header_size
        if payload_limit < 0:
            raise ValueError(
                "The iTunesCDB root header exceeds the logical-byte limit."
            )
        payload = decompressor.decompress(
            source[header_size:declared_size], payload_limit + 1
        )
        if len(payload) > payload_limit or decompressor.unconsumed_tail:
            raise ValueError("The iTunesCDB exceeds the logical-byte limit.")
        payload += decompressor.flush(payload_limit - len(payload) + 1)
        if len(payload) > payload_limit:
            raise ValueError("The iTunesCDB exceeds the logical-byte limit.")
    except zlib.error as error:
        raise ValueError("The iTunesCDB zlib payload is malformed.") from error
    if not decompressor.eof or decompressor.unconsumed_tail:
        raise ValueError("The iTunesCDB contains an incomplete zlib stream.")

    stream_tail = decompressor.unused_data
    file_tail = source[declared_size:]
    if stream_tail:
        report_unknown_data(
            "compressed-stream suffix",
            declared_size - len(stream_tail),
            len(stream_tail),
        )
    if file_tail:
        report_unknown_data("file suffix", declared_size, len(file_tail))

    logical = bytearray(source[:header_size])
    logical.extend(payload)
    logical[8:12] = len(logical).to_bytes(4, "little")
    if header_size >= _CDB_FLAG_OFFSET + _CDB_FLAG_SIZE:
        logical[_CDB_FLAG_OFFSET : _CDB_FLAG_OFFSET + _CDB_FLAG_SIZE] = b"\0\0"
    return ITunesCDB(bytes(logical), source, stream_tail, file_tail)


def compress_iTunesCDB(
    data: bytes | bytearray, *, framing: ITunesCDB | None = None
) -> bytes:
    """Frame logical iTunesDB bytes as an Apple-compatible iTunesCDB.

    zlib level 1 matches iTunes and libgpod.  Signing intentionally belongs to
    the caller and must happen after this function because firmware verifies
    the physical compressed bytes.
    Pass retained ``framing`` when editing an existing artifact to keep both
    physical suffixes. An unchanged logical input returns the original bytes.
    """

    logical = bytes(data)
    if framing is not None and logical == framing.logical_bytes:
        return framing.source_bytes
    if len(logical) < _GENERIC_HEADER_SIZE or logical[:4] != _MHBD:
        raise ValueError("iTunesCDB compression requires an iTunesDB root.")
    header_size = int.from_bytes(logical[4:8], "little")
    if not _GENERIC_HEADER_SIZE <= header_size <= len(logical):
        raise ValueError("The iTunesDB root header is truncated.")
    if header_size < _CDB_FLAG_OFFSET + _CDB_FLAG_SIZE:
        raise ValueError(
            "The iTunesDB root header cannot represent the iTunesCDB flag."
        )

    output = bytearray(logical[:header_size])
    output.extend(zlib.compress(logical[header_size:], level=1))
    if framing is not None:
        output.extend(framing.stream_trailing_data)
    output[8:12] = len(output).to_bytes(4, "little")
    output[0x0C:0x10] = _COMPRESSED_CAPABILITY.to_bytes(4, "little")
    output[_CDB_FLAG_OFFSET : _CDB_FLAG_OFFSET + _CDB_FLAG_SIZE] = _CDB_FLAG.to_bytes(
        _CDB_FLAG_SIZE, "little"
    )
    if framing is not None:
        output.extend(framing.file_trailing_data)
    return bytes(output)
