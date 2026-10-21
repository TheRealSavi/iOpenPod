"""Bound Host reads below buffering, including its otherwise invisible read-ahead."""

from __future__ import annotations

import io
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

from storage.errors import ConcurrentModificationError

if TYPE_CHECKING:
    from collections.abc import Generator
    from typing import BinaryIO

    from _typeshed import WriteableBuffer


@contextmanager
def bounded_host_reader(source: BinaryIO, size: int) -> Generator[BinaryIO]:
    """Borrow an unbuffered source; the owner must verify its stat facts on exit.

    Mounted providers can mishandle requests crossing EOF, including buffered
    read-ahead. Never probe beyond the observed size to detect growth: the owner's
    final descriptor/path checks detect changed size, timestamps and identity.
    """
    with io.BufferedReader(_ObservedSizeReader(source, size)) as reader:
        yield cast("BinaryIO", reader)


class _ObservedSizeReader(io.RawIOBase):
    """A non-owning raw view, so closing the buffer cannot close the pinned file."""

    def __init__(self, source: BinaryIO, size: int) -> None:
        super().__init__()
        self._source = source
        self._size = size

    def readinto(self, buffer: WriteableBuffer) -> int:
        view = memoryview(buffer).cast("B")
        position = self._source.tell()
        count = min(len(view), max(0, self._size - position))
        if count == 0:
            return 0
        data = self._source.read(count)
        if not data:
            raise ConcurrentModificationError(
                f"Host file ended before its observed size "
                f"(expected={self._size}, offset={position})"
            )
        view[: len(data)] = data
        return len(data)

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        if whence == os.SEEK_END:
            return self._source.seek(self._size + offset)
        return self._source.seek(offset, whence)

    def tell(self) -> int:
        return self._source.tell()

    def fileno(self) -> int:
        return self._source.fileno()

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True
