"""Path-free binary content and output buffers supplied by the caller."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterator

CHUNK_BYTES = 1024 * 1024


@runtime_checkable
class ReadableContent(Protocol):
    """Stable captured bytes; the caller owns their lifetime and backing storage."""

    def __len__(self) -> int: ...

    @property
    def sha256(self) -> str:
        """Captured digest for diagnostics; validation independently reads content."""
        ...

    def read_at(self, offset: int, length: int) -> bytes: ...


type FileContentData = bytes | ReadableContent


class ContentBuffer(Protocol):
    """Append-only private output, frozen before it becomes a prepared artifact."""

    def __len__(self) -> int: ...

    def append(self, data: bytes) -> None: ...

    def finish(self) -> FileContentData: ...


class MemoryContentBuffer:
    """Default for callers that prepare entirely in memory."""

    def __init__(self) -> None:
        self._data = bytearray()

    def __len__(self) -> int:
        return len(self._data)

    def append(self, data: bytes) -> None:
        self._data.extend(data)

    def finish(self) -> bytes:
        return bytes(self._data)


def read_content(data: FileContentData, offset: int, length: int) -> bytes:
    if offset < 0 or length < 0 or offset + length > len(data):
        raise ValueError("Content read is outside the captured file.")
    result = (
        data[offset : offset + length]
        if isinstance(data, bytes)
        else data.read_at(offset, length)
    )
    if len(result) != length:
        raise ValueError("Captured content ended before its declared size.")
    return result


def content_chunks(
    data: FileContentData, *, length: int | None = None
) -> Iterator[bytes]:
    size = len(data) if length is None else length
    if not 0 <= size <= len(data):
        raise ValueError("Content extent is outside the captured file.")
    for offset in range(0, size, CHUNK_BYTES):
        yield read_content(data, offset, min(CHUNK_BYTES, size - offset))


def content_sha256(data: FileContentData, *, length: int | None = None) -> str:
    digest = hashlib.sha256()
    for chunk in content_chunks(data, length=length):
        digest.update(chunk)
    return digest.hexdigest()
