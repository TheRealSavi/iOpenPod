"""Device reads and fingerprints must finish at the initially observed size."""

from __future__ import annotations

import hashlib
import io
import os
from typing import TYPE_CHECKING, BinaryIO, cast

import pytest

from storage import (
    AccessMode,
    ConcurrentModificationError,
    DevicePath,
    FilesystemSession,
    HostPath,
    Storage,
    StorageOperationError,
    UnsafeFilesystemPathError,
)
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from pathlib import Path

    from _typeshed import WriteableBuffer


def _session(tmp_path: Path) -> FilesystemSession:
    platform = VirtualStoragePlatform()
    platform.add_volume(tmp_path)
    storage = Storage(platform, writer_lock_directory=tmp_path / "locks")
    return storage.open_session(
        storage.discover().volumes[0], access=AccessMode.READ_ONLY
    )


@pytest.mark.parametrize("operation", ["read", "fingerprint", "capture"])
@pytest.mark.parametrize("size", [0, 9001, 2 * 1024 * 1024 + 11])
@pytest.mark.parametrize("short_reads", [False, True])
def test_device_reads_do_not_cross_observed_eof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    size: int,
    short_reads: bool,
) -> None:
    payload = (b"media\n" * size)[:size]
    (tmp_path / "source.bin").write_bytes(payload)
    session = _session(tmp_path)
    native_fdopen = os.fdopen
    requests: list[tuple[int, int]] = []

    class RangeReader(io.RawIOBase):
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

        def fileno(self) -> int:
            return self.source.fileno()

        def tell(self) -> int:
            return self.source.tell()

        def readable(self) -> bool:
            return True

        def close(self) -> None:
            self.source.close()
            super().close()

    def fdopen(fd: int, mode: str, buffering: int = -1) -> BinaryIO:
        if mode == "wb":
            return native_fdopen(fd, "wb", buffering=buffering)
        assert mode == "rb"
        raw = RangeReader(native_fdopen(fd, "rb", buffering=0))
        return cast("BinaryIO", raw if buffering == 0 else io.BufferedReader(raw))

    monkeypatch.setattr(os, "fdopen", fdopen)
    if operation == "read":
        snapshot = session.read_snapshot(DevicePath("source.bin"))
        assert snapshot.data == payload
        fingerprint = snapshot.fingerprint
    elif operation == "capture":
        destination = tmp_path.parent / f"{tmp_path.name}-captured.bin"
        result = session.copy_to_host(DevicePath("source.bin"), HostPath(destination))
        assert destination.read_bytes() == payload
        fingerprint = result.source_fingerprint
    else:
        fingerprint = session.fingerprint(DevicePath("source.bin"))
    assert fingerprint.size == size
    assert fingerprint.sha256 == hashlib.sha256(payload).hexdigest()
    assert all(offset < size and offset + count <= size for offset, count in requests)


@pytest.mark.parametrize("operation", ["read", "fingerprint", "capture"])
@pytest.mark.parametrize("change", ["growing", "stale-short"])
def test_device_reads_reject_growth_and_stale_short_content_without_chasing_eof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    change: str,
) -> None:
    path = tmp_path / "source.bin"
    payload = b"original"
    path.write_bytes(payload)
    session = _session(tmp_path)
    native_fdopen = os.fdopen
    native_fstat = os.fstat
    source_inode = path.stat().st_ino
    growth = 0
    requests: list[int] = []

    def fstat(fd: int) -> os.stat_result:
        metadata = native_fstat(fd)
        if metadata.st_ino != source_inode or not growth:
            return metadata
        fields = list(metadata)
        fields[6] += growth
        return os.stat_result(
            fields,
            {
                "st_atime_ns": metadata.st_atime_ns,
                "st_mtime_ns": metadata.st_mtime_ns,
                "st_ctime_ns": metadata.st_ctime_ns,
            },
        )

    class ChangingReader(io.BytesIO):
        def __init__(self, source: BinaryIO) -> None:
            super().__init__(payload if change == "growing" else b"short")
            self.source = source

        def fileno(self) -> int:
            return self.source.fileno()

        def read(self, size: int | None = -1) -> bytes:
            nonlocal growth
            assert size is not None and size >= 0
            requests.append(size)
            assert len(requests) <= 2, "A device read kept chasing a growing file"
            if change == "growing":
                # Model a provider changing beneath the open handle, independent
                # of local Windows sharing rules that prevent ordinary writes.
                growth += len(b"growing")
                position = self.tell()
                self.seek(0, os.SEEK_END)
                self.write(b"growing")
                self.seek(position)
            return super().read(size)

        def close(self) -> None:
            self.source.close()
            super().close()

    def fdopen(fd: int, mode: str, buffering: int = -1) -> BinaryIO:
        if mode == "wb":
            return native_fdopen(fd, "wb", buffering=buffering)
        assert mode == "rb"
        return ChangingReader(native_fdopen(fd, "rb", buffering=0))

    monkeypatch.setattr(os, "fdopen", fdopen)
    monkeypatch.setattr(os, "fstat", fstat)
    with pytest.raises(ConcurrentModificationError):
        if operation == "read":
            session.read_snapshot(DevicePath("source.bin"))
        elif operation == "capture":
            destination = tmp_path.parent / f"{tmp_path.name}-captured.bin"
            session.copy_to_host(DevicePath("source.bin"), HostPath(destination))
        else:
            session.fingerprint(DevicePath("source.bin"))
    assert max(requests) <= len(payload)


def test_oversized_device_source_is_rejected_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "source.bin").write_bytes(b"oversized")
    session = _session(tmp_path)
    native_fdopen = os.fdopen

    class Unreadable(io.BytesIO):
        def __init__(self, source: BinaryIO) -> None:
            super().__init__()
            self.source = source

        def fileno(self) -> int:
            return self.source.fileno()

        def read(self, size: int | None = -1) -> bytes:
            pytest.fail("An oversized source must be rejected before any data read")

        def close(self) -> None:
            self.source.close()
            super().close()

    def fdopen(fd: int, mode: str, buffering: int = -1) -> BinaryIO:
        assert mode == "rb"
        return Unreadable(native_fdopen(fd, "rb", buffering=0))

    monkeypatch.setattr(os, "fdopen", fdopen)
    with pytest.raises(StorageOperationError, match="allowed read size"):
        session.read(DevicePath("source.bin"), max_bytes=2)


@pytest.mark.parametrize("operation", ["read", "fingerprint"])
def test_device_read_rejects_named_file_replacement_after_handle_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    path = tmp_path / "source.bin"
    path.write_bytes(b"original")
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"replaced")
    metadata = path.stat()
    os.utime(replacement, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    session = _session(tmp_path)
    native_fdopen = os.fdopen

    class ReplacedOnClose(io.BufferedReader):
        def close(self) -> None:
            if self.closed:
                return
            super().close()
            replacement.replace(path)

    def fdopen(fd: int, mode: str, buffering: int = -1) -> BinaryIO:
        assert mode == "rb"
        return cast("BinaryIO", ReplacedOnClose(native_fdopen(fd, "rb", buffering=0)))

    monkeypatch.setattr(os, "fdopen", fdopen)
    with pytest.raises(ConcurrentModificationError):
        if operation == "read":
            session.read_snapshot(DevicePath("source.bin"))
        else:
            session.fingerprint(DevicePath("source.bin"))


@pytest.mark.parametrize("swap", ["parent", "leaf"])
def test_device_read_does_not_follow_link_replacement_after_path_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap: str
) -> None:
    from storage import _filesystem

    root = tmp_path / "volume"
    root.mkdir()
    parent = root / "Music"
    parent.mkdir()
    source = parent / "track.bin"
    source.write_bytes(b"approved")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "track.bin").write_bytes(b"unapproved")
    link_probe = tmp_path / "link-probe"
    try:
        link_probe.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Host cannot create symlinks: {error}")
    link_probe.unlink()
    session = _session(root)
    native_open = _filesystem.open_read_no_follow

    def swapped_open(
        path: Path, *, buffering: int = -1
    ) -> AbstractContextManager[BinaryIO]:
        if swap == "parent":
            parent.rename(root / "previous")
            parent.symlink_to(outside, target_is_directory=True)
        else:
            source.unlink()
            source.symlink_to(outside / "track.bin")
        return native_open(path, buffering=buffering)

    monkeypatch.setattr(_filesystem, "open_read_no_follow", swapped_open)
    # POSIX no-follow opens report ELOOP/ENOTDIR as a typed operation failure;
    # Windows can identify the reparse point from its pinned handle directly.
    with pytest.raises((UnsafeFilesystemPathError, StorageOperationError)):
        session.read(DevicePath("Music/track.bin"))


@pytest.mark.parametrize("cancelled", [False, True])
def test_shared_reader_owns_pins_until_context_exit_and_preserves_caller_errors(
    tmp_path: Path, cancelled: bool
) -> None:
    from storage._filesystem import open_read_no_follow

    parent = tmp_path / "selected"
    parent.mkdir()
    source = parent / "file.bin"
    source.write_bytes(b"approved")
    cancellation = InterruptedError("reader cancelled")
    descriptor = -1
    stream: BinaryIO | None = None

    def read() -> None:
        nonlocal descriptor, stream
        with open_read_no_follow(source) as stream:
            descriptor = stream.fileno()
            assert stream.read() == b"approved"
            assert os.fstat(descriptor).st_size == len(b"approved")
            if os.name == "nt":
                with pytest.raises(PermissionError):
                    parent.rename(tmp_path / "moved")
                with pytest.raises(PermissionError):
                    source.unlink()
            if cancelled:
                raise cancellation

    if cancelled:
        with pytest.raises(InterruptedError) as caught:
            read()
        assert caught.value is cancellation
    else:
        read()
    assert stream is not None and stream.closed
    with pytest.raises(OSError):
        os.fstat(descriptor)
    parent.rename(tmp_path / "released")
