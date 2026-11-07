"""Compressed input limits and serial fallback for Phase preparation."""

import errno
import time
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager, suppress
from hashlib import sha256
from pathlib import Path
from threading import Event, get_ident
from typing import TYPE_CHECKING

import pytest

from iOpenPod.app import phase_inputs
from storage import (
    CopyResult,
    DevicePath,
    FileFingerprint,
    FilesystemSession,
    HostPath,
    SessionInvalidatedError,
    Storage,
    StorageOperationError,
)
from storage.host_staging import staging_directory
from storage.testing import VirtualStoragePlatform

if TYPE_CHECKING:
    from concurrent.futures import Future


def device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sizes: tuple[int, ...]
) -> tuple[Storage, tuple[DevicePath, ...]]:
    root, staging = tmp_path / "device", tmp_path / "staging"
    root.mkdir()
    staging.mkdir()
    monkeypatch.setenv("TMPDIR", str(staging))
    paths = tuple(DevicePath(f"{index}.m4a") for index in range(len(sizes)))
    for index, (path, size) in enumerate(zip(paths, sizes, strict=True)):
        (root / str(path)).write_bytes(bytes([index + 1]) * size)
    platform = VirtualStoragePlatform()
    platform.add_volume(root)
    return Storage(platform), paths


class Copies:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        after: Callable[[DevicePath], None] = lambda _path: None,
        fail: Callable[[DevicePath], None] = lambda _path: None,
    ) -> None:
        self.started: list[DevicePath] = []
        self.paths: list[Path] = []
        self.peak_bytes = 0
        original = FilesystemSession.copy_to_host

        def copy_to_host(
            session: FilesystemSession,
            source: DevicePath,
            destination: HostPath,
            *,
            prepare_staged: Callable[[HostPath], None] | None = None,
            progress: Callable[[int], None] | None = None,
        ) -> CopyResult:
            self.started.append(source)
            self.paths.append(Path(destination))
            fail(source)
            result = original(
                session,
                source,
                destination,
                prepare_staged=prepare_staged,
                progress=progress,
            )
            retained = 0
            for path in self.paths:
                # The coordinator may release an earlier capture while this
                # read worker finishes the next one.
                with suppress(FileNotFoundError):
                    retained += path.stat().st_size
            self.peak_bytes = max(self.peak_bytes, retained)
            after(source)
            return result

        monkeypatch.setattr(FilesystemSession, "copy_to_host", copy_to_host)

    def assert_cleaned(self) -> None:
        assert all(not path.exists() for path in self.paths)
        assert all(not path.parent.exists() for path in self.paths)


def bounded_checkpoint() -> Callable[[], None]:
    deadline = time.monotonic() + 5
    caller = get_ident()

    def checkpoint() -> None:
        assert get_ident() == caller
        assert time.monotonic() < deadline, "Phase input queue stopped making progress"

    return checkpoint


def test_aggregate_byte_limit_waits_for_consumption_before_next_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, paths = device(tmp_path, monkeypatch, (8, 8, 8))
    monkeypatch.setattr(phase_inputs, "_RETAINED_BYTES", 16)
    second_ready, third_ready = Event(), Event()

    def after(path: DevicePath) -> None:
        if path == paths[1]:
            second_ready.set()
        elif path == paths[2]:
            third_ready.set()

    copies = Copies(monkeypatch, after=after)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        phase_inputs.prefetch_phase_inputs(
            session, paths, checkpoint=bounded_checkpoint()
        ) as inputs,
    ):
        with inputs.capture(paths[0]) as captured:
            assert isinstance(captured.source, HostPath)
            assert second_ready.wait(3)
            assert not third_ready.wait(0.05)
            assert copies.started == list(paths[:2])
        for path in paths[1:]:
            with inputs.capture(path) as captured:
                assert isinstance(captured.source, HostPath)
                assert (
                    Path(captured.source).read_bytes()
                    == bytes([int(path.name[0]) + 1]) * 8
                )
    assert copies.started == list(paths) and copies.peak_bytes == 16
    copies.assert_cleaned()


def test_oversize_input_uses_direct_source_between_serialized_captures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, paths = device(tmp_path, monkeypatch, (8, 17, 8))
    monkeypatch.setattr(phase_inputs, "_RETAINED_BYTES", 16)
    copies = Copies(monkeypatch)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        phase_inputs.prefetch_phase_inputs(
            session, paths, checkpoint=bounded_checkpoint()
        ) as inputs,
    ):
        with inputs.capture(paths[0]) as captured:
            assert isinstance(captured.source, HostPath)
        with inputs.capture(paths[1]) as captured:
            assert captured.source == paths[1]
            assert captured.fingerprint == session.fingerprint(paths[1])
            assert copies.started == [paths[0]]
        with inputs.capture(paths[2]) as captured:
            assert isinstance(captured.source, HostPath)
            assert Path(captured.source).read_bytes() == bytes([3]) * 8
    assert copies.started == [paths[0], paths[2]]
    copies.assert_cleaned()


@pytest.mark.parametrize("error_number", [errno.ENOSPC, errno.EDQUOT])
def test_full_host_storage_drains_captures_then_uses_serial_device_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    storage, paths = device(tmp_path, monkeypatch, (8, 8, 8))
    failed_copy, third_fingerprinted = Event(), Event()

    def fail(path: DevicePath) -> None:
        if path == paths[1]:
            failed_copy.set()
            raise StorageOperationError("Host capacity exhausted") from OSError(
                error_number, "Host capacity exhausted"
            )

    original_fingerprint = FilesystemSession.fingerprint
    caller = get_ident()

    def fingerprint(
        session: FilesystemSession,
        path: DevicePath,
        *,
        checkpoint: Callable[[], None] = lambda: None,
    ) -> FileFingerprint:
        if path == paths[2] and get_ident() != caller:
            third_fingerprinted.set()
        return original_fingerprint(session, path, checkpoint=checkpoint)

    monkeypatch.setattr(FilesystemSession, "fingerprint", fingerprint)
    copies = Copies(monkeypatch, fail=fail)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        phase_inputs.prefetch_phase_inputs(
            session, paths, checkpoint=bounded_checkpoint()
        ) as inputs,
    ):
        with inputs.capture(paths[0]) as captured:
            assert isinstance(captured.source, HostPath)
            assert failed_copy.wait(3)
        with inputs.capture(paths[1]) as captured:
            assert captured.source == paths[1]
            assert not third_fingerprinted.wait(0.05)
        with inputs.capture(paths[2]) as captured:
            assert captured.source == paths[2]
            assert third_fingerprinted.is_set()
    assert copies.started == list(paths[:2])
    copies.assert_cleaned()


@pytest.mark.parametrize("error_number", [errno.EIO, errno.EACCES])
def test_noncapacity_storage_errors_propagate_without_direct_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    storage, paths = device(tmp_path, monkeypatch, (8, 8))
    failure = StorageOperationError("Device read failed")

    def fail(_path: DevicePath) -> None:
        raise failure from OSError(error_number, "Device read failed")

    copies = Copies(monkeypatch, fail=fail)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        phase_inputs.prefetch_phase_inputs(
            session, paths, checkpoint=bounded_checkpoint()
        ) as inputs,
        pytest.raises(StorageOperationError) as caught,
        inputs.capture(paths[0]),
    ):
        pytest.fail("A failed device copy was silently accepted")
    assert caught.value is failure
    assert copies.started == [paths[0]]
    copies.assert_cleaned()


class FailedWorkspace(AbstractContextManager[Path]):
    def __init__(self, failure: Exception) -> None:
        self.failure = failure

    def __enter__(self) -> Path:
        raise self.failure

    def __exit__(self, *_args: object) -> None:
        pass


@pytest.mark.parametrize("error_number", [errno.ENOSPC, errno.EDQUOT])
@pytest.mark.parametrize("wrapped", [False, True], ids=["raw", "storage"])
def test_workspace_capacity_failure_uses_verified_serial_device_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_number: int,
    wrapped: bool,
) -> None:
    storage, paths = device(tmp_path, monkeypatch, (8, 8))
    copies = Copies(monkeypatch)
    cause = OSError(error_number, "Cannot create the Host workspace")
    failure: OSError | StorageOperationError = cause
    if wrapped:
        failure = StorageOperationError("Cannot create the Host workspace")
        failure.__cause__ = cause

    def unavailable_workspace(_prefix: str) -> FailedWorkspace:
        return FailedWorkspace(failure)

    monkeypatch.setattr(phase_inputs, "staging_directory", unavailable_workspace)
    second_started = Event()
    original_fingerprint = FilesystemSession.fingerprint
    caller = get_ident()

    def fingerprint(
        session: FilesystemSession,
        path: DevicePath,
        *,
        checkpoint: Callable[[], None] = lambda: None,
    ) -> FileFingerprint:
        if path == paths[1] and get_ident() != caller:
            second_started.set()
        return original_fingerprint(session, path, checkpoint=checkpoint)

    monkeypatch.setattr(FilesystemSession, "fingerprint", fingerprint)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        phase_inputs.prefetch_phase_inputs(
            session, paths, checkpoint=bounded_checkpoint()
        ) as inputs,
    ):
        with inputs.capture(paths[0]) as captured:
            assert captured.source == paths[0]
            assert captured.fingerprint == session.fingerprint(paths[0])
            assert not second_started.wait(0.05)
        with inputs.capture(paths[1]) as captured:
            assert captured.source == paths[1]
            assert captured.fingerprint == session.fingerprint(paths[1])
            assert second_started.is_set()
    assert not copies.started and not copies.paths


@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
@pytest.mark.parametrize("wrapped", [False, True], ids=["raw", "storage"])
def test_workspace_noncapacity_failure_propagates_without_starting_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_number: int,
    wrapped: bool,
) -> None:
    storage, paths = device(tmp_path, monkeypatch, (8,))
    cause = OSError(error_number, "Cannot access the Host workspace")
    failure: OSError | StorageOperationError = cause
    if wrapped:
        failure = StorageOperationError("Cannot access the Host workspace")
        failure.__cause__ = cause

    def unavailable_workspace(_prefix: str) -> FailedWorkspace:
        return FailedWorkspace(failure)

    def unexpected_worker(*_args: object, **_kwargs: object) -> None:
        pytest.fail("A reader started after an invalid Host workspace")

    monkeypatch.setattr(phase_inputs, "staging_directory", unavailable_workspace)
    monkeypatch.setattr(phase_inputs, "ThreadPoolExecutor", unexpected_worker)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        pytest.raises(type(failure)) as caught,
        phase_inputs.prefetch_phase_inputs(
            session, paths, checkpoint=bounded_checkpoint()
        ),
    ):
        pytest.fail("Invalid Host workspace was silently accepted")
    assert caught.value is failure


def test_no_device_inputs_create_neither_workspace_nor_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, _paths = device(tmp_path, monkeypatch, ())

    def unexpected_resource(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Empty device input list acquired a prefetch resource")

    monkeypatch.setattr(phase_inputs, "staging_directory", unexpected_resource)
    monkeypatch.setattr(phase_inputs, "ThreadPoolExecutor", unexpected_resource)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        phase_inputs.prefetch_phase_inputs(
            session, (), checkpoint=bounded_checkpoint()
        ) as inputs,
    ):
        inputs.checkpoint()
        assert inputs.worker is None


@pytest.mark.parametrize("interrupt", ["cancel", "disconnect"])
def test_cached_audio_hashing_stops_and_joins_reader_on_interruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupt: str
) -> None:
    storage, paths = device(tmp_path, monkeypatch, (8,))
    hashing, stopped = Event(), Event()
    caller = get_ident()
    original = FilesystemSession.fingerprint
    workers: list[Future[None]] = []
    copies = Copies(monkeypatch)

    def fingerprint(
        session: FilesystemSession,
        path: DevicePath,
        *,
        checkpoint: Callable[[], None] | None = None,
    ) -> FileFingerprint:
        assert get_ident() != caller
        assert checkpoint is not None
        hashing.set()
        deadline = time.monotonic() + 3
        try:
            while time.monotonic() < deadline:
                checkpoint()
                time.sleep(0.005)
            pytest.fail("Interrupted cached audio hash did not stop")
        finally:
            stopped.set()
        return original(session, path, checkpoint=checkpoint)

    monkeypatch.setattr(FilesystemSession, "fingerprint", fingerprint)
    with storage.open_session(storage.discover().volumes[0]) as session:

        def checkpoint() -> None:
            assert get_ident() == caller
            if hashing.is_set():
                if interrupt == "cancel":
                    raise InterruptedError("Cancelled cache validation")
                session.invalidate("Disconnected during cache validation")

        expected = (
            InterruptedError if interrupt == "cancel" else SessionInvalidatedError
        )
        with (
            pytest.raises(expected),
            phase_inputs.prefetch_phase_inputs(
                session,
                paths,
                checkpoint=checkpoint,
                reuse_hashes={paths[0]: sha256(bytes([1]) * 8).hexdigest()},
            ) as inputs,
        ):
            assert inputs.worker is not None
            workers.append(inputs.worker)
            with inputs.capture(paths[0]):
                pytest.fail("Interrupted cache validation yielded audio")
    assert stopped.is_set()
    assert workers[0].done()
    assert not copies.started


@pytest.mark.parametrize("primary_kind", ["cancel", "analysis", "none"])
@pytest.mark.parametrize("permanent", [False, True])
def test_capture_unlink_failure_preserves_primary_error_and_stops_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    primary_kind: str,
    permanent: bool,
) -> None:
    storage, paths = device(tmp_path, monkeypatch, (8,) * 7)
    queue_full = Event()

    def after(path: DevicePath) -> None:
        if path == paths[5]:
            queue_full.set()

    copies = Copies(monkeypatch, after=after)
    cleanup_failure = PermissionError("Captured input is still locked")
    primary = (
        InterruptedError("Phase preparation was cancelled")
        if primary_kind == "cancel"
        else ValueError("Phase analysis failed")
        if primary_kind == "analysis"
        else None
    )
    expected = primary if primary is not None else cleanup_failure
    original_unlink = Path.unlink
    failures = 0
    target: Path | None = None
    workers: list[Future[None]] = []

    def unlink(path: Path, missing_ok: bool = False) -> None:
        nonlocal failures
        if path == target and (permanent or failures == 0):
            failures += 1
            raise cleanup_failure
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        pytest.raises(type(expected)) as caught,
        phase_inputs.prefetch_phase_inputs(
            session, paths, checkpoint=bounded_checkpoint()
        ) as inputs,
    ):
        assert inputs.worker is not None
        workers.append(inputs.worker)
        with inputs.capture(paths[0]) as captured:
            assert isinstance(captured.source, HostPath)
            target = Path(captured.source)
            assert queue_full.wait(3)
            if primary is not None:
                raise primary
    assert caught.value is expected
    assert failures >= 1
    assert len(workers) == 1 and workers[0].done()
    assert workers[0].result() is None
    assert len(copies.started) == 6
    if primary is not None:
        assert "Phase capture cleanup failed" in caplog.text
    copies.assert_cleaned()


@pytest.mark.parametrize("cancel", [False, True])
def test_workspace_exit_failure_joins_reader_and_preserves_active_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    storage, paths = device(tmp_path, monkeypatch, (8,) * 7)
    copies = Copies(monkeypatch)
    workers: list[Future[None]] = []
    joined_at_cleanup: list[bool] = []
    cleanup_failure = PermissionError("Workspace cleanup failed")
    cancellation = InterruptedError("Phase preparation was cancelled")
    expected = cancellation if cancel else cleanup_failure

    @contextmanager
    def failing_workspace(prefix: str) -> Generator[Path]:
        try:
            with staging_directory(prefix) as directory:
                yield directory
        finally:
            joined_at_cleanup.append(len(workers) == 1 and workers[0].done())
            raise cleanup_failure

    monkeypatch.setattr(phase_inputs, "staging_directory", failing_workspace)
    with (
        storage.open_session(storage.discover().volumes[0]) as session,
        pytest.raises(type(expected)) as caught,
        phase_inputs.prefetch_phase_inputs(
            session, paths, checkpoint=bounded_checkpoint()
        ) as inputs,
    ):
        assert inputs.worker is not None
        workers.append(inputs.worker)
        with inputs.capture(paths[0]):
            if cancel:
                raise cancellation
    assert caught.value is expected
    assert joined_at_cleanup == [True]
    assert workers[0].done()
    assert workers[0].result() is None
    copies.assert_cleaned()
