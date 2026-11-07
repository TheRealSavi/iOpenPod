"""Fingerprint cancellation releases its pinned input and preserves the cause."""

from __future__ import annotations

import io
from contextlib import contextmanager
from typing import TYPE_CHECKING, BinaryIO, cast

import pytest

import storage._filesystem as filesystem
from storage import DevicePath, FilesystemSession, Storage
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from storage.models import VolumeObservation


def session_for(root: Path) -> tuple[VirtualStoragePlatform, FilesystemSession]:
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    storage = Storage(platform)
    return platform, storage.open_session(storage.discover().volumes[0])


@pytest.mark.parametrize("size", [0, 2 * 1024 * 1024 + 17])
def test_checkpoint_preserves_the_complete_fingerprint(
    tmp_path: Path, size: int
) -> None:
    (tmp_path / "audio.bin").write_bytes(b"a" * size)
    _, session = session_for(tmp_path)
    checkpoints: list[bool] = []
    with session:
        expected = session.fingerprint(DevicePath("audio.bin"))
        actual = session.fingerprint(
            DevicePath("audio.bin"), checkpoint=lambda: checkpoints.append(True)
        )
    assert actual == expected
    assert checkpoints


def test_cancellation_before_reading_never_opens_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "audio.bin").write_bytes(b"audio")
    _, session = session_for(tmp_path)
    interrupted = InterruptedError("cancelled before reading")

    def cancel() -> None:
        raise interrupted

    def reject_open(*args: object, **kwargs: object) -> None:
        pytest.fail("A cancelled fingerprint must not open its input")

    monkeypatch.setattr(filesystem, "open_read_no_follow", reject_open)
    with session, pytest.raises(InterruptedError) as caught:
        session.fingerprint(DevicePath("audio.bin"), checkpoint=cancel)
    assert caught.value is interrupted


@pytest.mark.parametrize(
    "interrupted", [InterruptedError("cancelled"), ValueError("stop")]
)
def test_cancellation_between_chunks_closes_the_reader_and_preserves_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: Exception
) -> None:
    source = tmp_path / "audio.bin"
    source.write_bytes(b"a" * (3 * 1024 * 1024 + 17))
    _, session = session_for(tmp_path)
    original_open = filesystem.open_read_no_follow
    bytes_read = 0
    handles: list[BinaryIO] = []

    class ObservedReader(io.RawIOBase):
        def __init__(self, original: BinaryIO) -> None:
            super().__init__()
            self.original = original

        def fileno(self) -> int:
            return self.original.fileno()

        def read(self, size: int | None = -1) -> bytes:
            nonlocal bytes_read
            data = self.original.read(-1 if size is None else size)
            bytes_read += len(data)
            return data

    @contextmanager
    def observe(path: Path, *, buffering: int = -1) -> Generator[BinaryIO]:
        with original_open(path, buffering=buffering) as original:
            handles.append(original)
            yield cast("BinaryIO", ObservedReader(original))

    def cancel() -> None:
        if bytes_read:
            raise interrupted

    monkeypatch.setattr(filesystem, "open_read_no_follow", observe)
    with session, pytest.raises(type(interrupted)) as caught:
        session.fingerprint(DevicePath("audio.bin"), checkpoint=cancel)
    assert caught.value is interrupted
    assert bytes_read == 1024 * 1024
    assert len(handles) == 1 and handles[0].closed
    # Windows also releases the pinned source and ancestor handles on cancellation.
    source.replace(tmp_path / "released.bin")


def test_cancellation_after_final_connection_check_does_not_return_a_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "audio.bin").write_bytes(b"audio")
    platform, session = session_for(tmp_path)
    original_open = filesystem.open_read_no_follow
    original_reinspect = platform.reinspect
    read_finished = False
    cancelled = False
    interrupted = InterruptedError("cancelled at final connection check")

    @contextmanager
    def observe(path: Path, *, buffering: int = -1) -> Generator[BinaryIO]:
        nonlocal read_finished
        with original_open(path, buffering=buffering) as original:
            yield original
        read_finished = True

    def reinspect(retained: VolumeObservation) -> VolumeObservation:
        nonlocal cancelled
        result = original_reinspect(retained)
        cancelled = read_finished
        return result

    def checkpoint() -> None:
        if cancelled:
            raise interrupted

    monkeypatch.setattr(filesystem, "open_read_no_follow", observe)
    monkeypatch.setattr(platform, "reinspect", reinspect)
    with session, pytest.raises(InterruptedError) as caught:
        session.fingerprint(DevicePath("audio.bin"), checkpoint=checkpoint)
    assert caught.value is interrupted
