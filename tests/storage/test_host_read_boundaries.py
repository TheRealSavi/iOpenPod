"""Host reads must not ask a mounted provider for bytes beyond observed EOF."""

from __future__ import annotations

import hashlib
import io
import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, cast

import pytest

from storage import ConcurrentModificationError, HostPath, capture_host_file
from storage.host_input import LocalHostFile

if TYPE_CHECKING:
    from collections.abc import Generator

    from _typeshed import WriteableBuffer


@pytest.mark.parametrize("operation", ["stream", "bytes", "capture", "inspection"])
@pytest.mark.parametrize("size", [0, 9001, 2 * 1024 * 1024 + 11])
@pytest.mark.parametrize("short_reads", [False, True])
def test_host_reads_do_not_cross_eof_even_through_buffered_read_ahead(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    size: int,
    short_reads: bool,
) -> None:
    payload = (b"media\n" * size)[:size]
    path = tmp_path / "source.bin"
    path.write_bytes(payload)
    observed = LocalHostFile.observe(HostPath(path))
    native_fdopen = os.fdopen
    requests: list[tuple[int, int]] = []

    class RangeReader(io.RawIOBase):
        """Model WebDAV's uncached range path returning the requested length."""

        def __init__(self, source: BinaryIO) -> None:
            super().__init__()
            self.source = source

        def readinto(self, buffer: WriteableBuffer) -> int:
            view = memoryview(buffer).cast("B")
            offset = self.source.tell()
            requests.append((offset, len(view)))
            data = self.source.read(min(len(view), 4093) if short_reads else len(view))
            if data and self.source.tell() == size and len(data) < len(view):
                data += b"\xff" * (len(view) - len(data))
            view[: len(data)] = data
            return len(data)

        def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
            return self.source.seek(offset, whence)

        def tell(self) -> int:
            return self.source.tell()

        def fileno(self) -> int:
            return self.source.fileno()

        def readable(self) -> bool:
            return True

        def seekable(self) -> bool:
            return True

        def close(self) -> None:
            self.source.close()
            super().close()

    def fdopen(fd: int, mode: str, buffering: int = -1) -> BinaryIO:
        assert mode == "rb"
        raw = RangeReader(native_fdopen(fd, "rb", buffering=0))
        return cast("BinaryIO", raw if buffering == 0 else io.BufferedReader(raw))

    monkeypatch.setattr(os, "fdopen", fdopen)
    if operation == "stream":
        with observed.open_read() as stream:
            # Format detection seeks to the footer before reading tags.
            offset = max(0, size - 160)
            assert stream.seek(offset) == offset
            assert stream.read() == payload[offset:]
            assert stream.read() == b""
            assert stream.seek(0) == 0
            assert stream.readline() == payload[:6]
            assert stream.seek(size + 10) == size + 10
            assert stream.read() == b""
            assert stream.seek(-min(size, 160), os.SEEK_END) == offset
            buffer = bytearray(160)
            count = cast("io.BufferedIOBase", stream).readinto(buffer)
            assert buffer[:count] == payload[offset:]
    elif operation == "bytes":
        assert (
            observed.read_bytes(max_bytes=size + 100, checkpoint=lambda: None)
            == payload
        )
    elif operation == "capture":
        with observed.capture(checkpoint=lambda: None) as snapshot:
            assert Path(snapshot).read_bytes() == payload
    else:
        with capture_host_file(HostPath(path), checkpoint=lambda: None) as captured:
            assert Path(captured.snapshot).read_bytes() == payload
            assert captured.fingerprint.size == size
            assert captured.fingerprint.sha256 == hashlib.sha256(payload).hexdigest()
    assert all(offset < size and offset + count <= size for offset, count in requests)


@pytest.mark.parametrize("change", ["grow", "shrink", "rewrite"])
@pytest.mark.parametrize("operation", ["stream", "capture", "inspection"])
def test_bounded_host_reads_still_reject_changed_source_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str, operation: str
) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(b"source bytes")
    observed = LocalHostFile.observe(HostPath(path))
    native_fstat = os.fstat
    calls = 0

    def fstat(fd: int) -> os.stat_result:
        nonlocal calls
        metadata = native_fstat(fd)
        if metadata.st_ino != observed.inode:
            return metadata
        calls += 1
        # Inspection also stats the descriptor inside open_read_no_follow.
        if calls <= (2 if operation == "inspection" else 1):
            return metadata
        fields = list(metadata)
        if change in {"grow", "shrink"}:
            fields[6] += 1 if change == "grow" else -1
        else:
            fields[8] += 2
        return os.stat_result(
            fields,
            {
                "st_atime_ns": metadata.st_atime_ns,
                "st_mtime_ns": metadata.st_mtime_ns
                + (2_000_000_000 if change == "rewrite" else 0),
                "st_ctime_ns": metadata.st_ctime_ns,
            },
        )

    monkeypatch.setattr(os, "fstat", fstat)
    with pytest.raises(ConcurrentModificationError):
        if operation == "stream":
            with observed.open_read() as stream:
                assert stream.read() == b"source bytes"
        elif operation == "capture":
            with observed.capture(checkpoint=lambda: None):
                pytest.fail("Changed source was accepted")
        else:
            with capture_host_file(HostPath(path), checkpoint=lambda: None):
                pytest.fail("Changed source was accepted")


def test_truncated_provider_read_fails_even_when_stat_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from storage import host_input

    path = tmp_path / "source.bin"
    path.write_bytes(b"complete")
    observed = LocalHostFile.observe(HostPath(path))
    native_open = host_input.open_local_file

    class TruncatedReader(io.BytesIO):
        def __init__(self, fd: int) -> None:
            super().__init__(b"short")
            self.fd = fd

        def fileno(self) -> int:
            return self.fd

    @contextmanager
    def open_truncated(path: Path, *, buffering: int = -1) -> Generator[BinaryIO]:
        with (
            native_open(path, buffering=buffering) as source,
            TruncatedReader(source.fileno()) as reader,
        ):
            yield reader

    monkeypatch.setattr(host_input, "open_local_file", open_truncated)
    with (
        pytest.raises(ConcurrentModificationError, match="expected=8, offset=5"),
        observed.open_read() as stream,
    ):
        stream.read()
