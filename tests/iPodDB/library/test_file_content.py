"""Caller-backed resources are validated by content with bounded reads."""

import hashlib

import pytest

from iPodDB.library.file_content import CHUNK_BYTES, content_sha256, read_content


class Captured:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.reads: list[tuple[int, int]] = []

    def __len__(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return "untrusted cached digest"

    def read_at(self, offset: int, length: int) -> bytes:
        self.reads.append((offset, length))
        return self.data[offset : offset + length]


def test_hashes_read_content_in_bounded_chunks_and_respect_prefix_extent() -> None:
    data = b"x" * (2 * CHUNK_BYTES + 17)
    captured = Captured(data)
    assert content_sha256(captured) == hashlib.sha256(data).hexdigest()
    assert captured.reads == [
        (0, CHUNK_BYTES),
        (CHUNK_BYTES, CHUNK_BYTES),
        (2 * CHUNK_BYTES, 17),
    ]
    captured.reads.clear()
    assert content_sha256(captured, length=13) == hashlib.sha256(data[:13]).hexdigest()
    assert captured.reads == [(0, 13)]


def test_short_read_and_out_of_bounds_extent_are_rejected() -> None:
    class ShortRead(Captured):
        def read_at(self, offset: int, length: int) -> bytes:
            return b""

    with pytest.raises(ValueError, match="ended"):
        content_sha256(ShortRead(b"content"))
    with pytest.raises(ValueError, match="outside"):
        read_content(Captured(b"content"), 6, 2)
