"""Overlap bounded, verified Host captures with ordered Phase analysis."""

from __future__ import annotations

import errno
import logging
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Condition, Event, Lock
from typing import TYPE_CHECKING

from storage import (
    DevicePath,
    FileIdentity,
    HostPath,
    SessionInvalidatedError,
    StorageOperationError,
)
from storage.host_input import LocalHostFile
from storage.host_staging import staging_directory

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping

    from storage import FileFingerprint, FilesystemSession

_AHEAD = 5
_RETAINED_BYTES = 256 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PhaseInput:
    source: HostPath | DevicePath
    fingerprint: FileFingerprint


@dataclass(frozen=True, slots=True)
class _Capture:
    device_path: DevicePath
    input: PhaseInput
    retained_bytes: int
    observed: LocalHostFile | None


class _StoppedError(Exception):
    pass


def _capacity_error(error: OSError | StorageOperationError) -> bool:
    cause = error if isinstance(error, OSError) else error.__cause__
    return isinstance(cause, OSError) and cause.errno in (errno.ENOSPC, errno.EDQUOT)


class PhaseInputs:
    """Own one reader, its bounded captures and their source verification."""

    def __init__(
        self,
        session: FilesystemSession,
        checkpoint: Callable[[], None],
        directory: Path | None,
    ) -> None:
        self._session = session
        self._checkpoint = checkpoint
        self._directory = directory
        self._stopped = Event()
        self._foreground = Event()
        self._io = Lock()
        self._condition = Condition()
        self._ready: deque[_Capture] = deque()
        self._count = 0
        self._bytes = 0
        self._in_use = False
        self._direct = False
        self.worker: Future[None] | None = None

    def checkpoint(self) -> None:
        """Run application callbacks only on the preparation's caller thread."""
        self._checkpoint()
        if not self._session.is_active:
            raise SessionInvalidatedError(
                "The Filesystem Session ended during Phase analysis"
            )
        if self.worker is not None and self.worker.done():
            self.worker.result()

    def _worker_checkpoint(self) -> None:
        if self._stopped.is_set():
            raise _StoppedError
        if not self._session.is_active:
            raise SessionInvalidatedError(
                "The Filesystem Session ended during Phase capture"
            )

    @contextmanager
    def _device_io(self, *, foreground: bool = False) -> Generator[None]:
        # Give final source verification priority over admitting another copy.
        # A plain mutex could otherwise make the caller wait for all five files.
        if foreground:
            self._foreground.set()
        try:
            while True:
                if foreground:
                    self.checkpoint()
                else:
                    self._worker_checkpoint()
                    if self._foreground.is_set():
                        self._stopped.wait(0.01)
                        continue
                if self._io.acquire(timeout=0.05):
                    if not foreground and self._foreground.is_set():
                        self._io.release()
                        continue
                    break
            try:
                yield
            finally:
                self._io.release()
        finally:
            if foreground:
                self._foreground.clear()

    def _reserve(self, size: int, *, direct: bool) -> None:
        with self._condition:
            while (
                self._count >= _AHEAD + int(self._in_use)
                or self._direct
                or (direct and self._count != 0)
                or (not direct and self._bytes + size > _RETAINED_BYTES)
            ):
                self._worker_checkpoint()
                self._condition.wait(0.05)
            self._worker_checkpoint()
            self._count += 1
            self._bytes += size
            self._direct = direct

    def _release(self, size: int, *, consumed: bool = False) -> None:
        with self._condition:
            self._count -= 1
            self._bytes -= size
            if consumed:
                self._in_use = False
            self._direct = False
            self._condition.notify_all()

    def read(
        self, paths: tuple[DevicePath, ...], reuse_hashes: Mapping[DevicePath, str]
    ) -> None:
        copy_enabled = self._directory is not None
        try:
            for index, path in enumerate(paths):
                self._worker_checkpoint()
                with self._device_io():
                    identity = self._session.file_identity(path)
                fingerprint: FileFingerprint | None = None
                if expected := reuse_hashes.get(path):
                    with self._device_io():
                        checked = self._session.fingerprint(
                            path, checkpoint=self._worker_checkpoint
                        )
                    if checked.sha256 == expected:
                        fingerprint = checked
                direct = (
                    fingerprint is not None
                    or not copy_enabled
                    or identity.size > _RETAINED_BYTES
                )
                size = 0 if direct else identity.size
                source: HostPath | DevicePath = path
                observed: LocalHostFile | None = None
                if not direct:
                    self._reserve(size, direct=False)
                    assert self._directory is not None
                    destination = HostPath(
                        self._directory / f"{index}{Path(path.name).suffix}"
                    )

                    def progress(copied: int, size: int = identity.size) -> None:
                        self._worker_checkpoint()
                        if copied > size:
                            raise ValueError("Phase audio grew while it was captured.")

                    try:
                        with self._device_io():
                            copied = self._session.copy_to_host(
                                path, destination, progress=progress
                            )
                    except (OSError, StorageOperationError) as error:
                        if not _capacity_error(error):
                            raise
                        # Prefetch is optional. Drain earlier captures before
                        # using the original serial path on a full Host disk.
                        copy_enabled = False
                        self._release(size)
                        direct = True
                    else:
                        fingerprint = copied.source_fingerprint
                        source = destination
                        observed = LocalHostFile.observe(destination)
                if direct:
                    size = 0
                    self._reserve(0, direct=True)
                    if fingerprint is None:
                        with self._device_io():
                            fingerprint = self._session.fingerprint(
                                path, checkpoint=self._worker_checkpoint
                            )
                assert fingerprint is not None
                if (
                    fingerprint.size,
                    fingerprint.modified_ns,
                    fingerprint.device,
                    fingerprint.inode,
                ) != (
                    identity.size,
                    identity.modified_ns,
                    identity.device,
                    identity.inode,
                ):
                    raise ValueError("Phase audio changed while it was captured.")
                with self._condition:
                    self._ready.append(
                        _Capture(path, PhaseInput(source, fingerprint), size, observed)
                    )
                    self._condition.notify_all()
        except _StoppedError:
            return

    @contextmanager
    def capture(
        self, path: DevicePath, *, reuse_sha256: str | None = None
    ) -> Generator[PhaseInput]:
        while True:
            self.checkpoint()
            with self._condition:
                if self._ready:
                    captured = self._ready.popleft()
                    self._in_use = True
                    self._condition.notify_all()
                    break
                if self.worker is not None and self.worker.done():
                    raise ValueError("No queued Phase input remains for this Track.")
                self._condition.wait(0.05)
        failed = True
        try:
            if captured.device_path != path:
                raise ValueError("Phase input order disagrees with the Playlist.")
            if captured.observed is not None:
                captured.observed.validate()
            yield captured.input
            self.checkpoint()
            if captured.observed is not None:
                captured.observed.validate()
            with self._device_io(foreground=True):
                before = captured.input.fingerprint
                if (
                    isinstance(captured.input.source, DevicePath)
                    and before.sha256 == reuse_sha256
                ):
                    # No decoding occurred: the full hash already established
                    # reuse. Keep the content fingerprint as a transaction
                    # precondition; only a cheap identity check is needed here.
                    unchanged = self._session.file_identity(path) == FileIdentity(
                        before.size, before.modified_ns, before.device, before.inode
                    )
                else:
                    unchanged = (
                        self._session.fingerprint(path, checkpoint=self.checkpoint)
                        == before
                    )
            if not unchanged:
                raise ValueError("Phase audio changed during analysis.")
            failed = False
        finally:
            if failed:
                self.stop()
            try:
                if isinstance(captured.input.source, HostPath):
                    Path(captured.input.source).unlink(missing_ok=True)
            except OSError:
                self.stop()
                if not failed:
                    raise
                _LOGGER.warning(
                    "Phase capture cleanup failed after an interrupted analysis",
                    exc_info=True,
                )
            finally:
                self._release(captured.retained_bytes, consumed=True)

    def stop(self) -> None:
        self._stopped.set()
        with self._condition:
            self._condition.notify_all()


@contextmanager
def prefetch_phase_inputs(
    session: FilesystemSession,
    paths: tuple[DevicePath, ...],
    *,
    checkpoint: Callable[[], None],
    reuse_hashes: Mapping[DevicePath, str] | None = None,
) -> Generator[PhaseInputs]:
    with ExitStack() as lifetime:
        directory: Path | None = None
        if paths:
            try:
                directory = lifetime.enter_context(staging_directory("iopenpod-media-"))
            except (OSError, StorageOperationError) as error:
                if not _capacity_error(error):
                    raise
        inputs = PhaseInputs(session, checkpoint, directory)
        if paths:
            worker = lifetime.enter_context(
                ThreadPoolExecutor(max_workers=1, thread_name_prefix="phase-input")
            )
            inputs.worker = worker.submit(inputs.read, paths, dict(reuse_hashes or {}))
        try:
            yield inputs
        except BaseException:
            inputs.stop()
            try:
                lifetime.close()
            except Exception:
                _LOGGER.warning(
                    "Phase workspace cleanup failed after interrupted preparation",
                    exc_info=True,
                )
            raise
        finally:
            inputs.stop()
        # Join the reader before removing any complete or partial capture.
