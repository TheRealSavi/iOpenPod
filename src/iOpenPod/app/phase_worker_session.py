"""Job-scoped optional worker using bounded private file requests."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
from typing import TYPE_CHECKING, cast

from iOpenPod.app.phase_activity import PhaseActivity, PhaseStage
from storage import HostPath
from storage.media_processing import run_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable

_TRACK_TIMEOUT_SECONDS = 3600
_ACCESS_RETRY_SECONDS = 1.0


def _retry_access[T](operation: Callable[[], T], checkpoint: Callable[[], None]) -> T:
    """Allow a briefly retained Windows file handle to close, with a hard limit."""
    deadline = time.monotonic() + _ACCESS_RETRY_SECONDS
    while True:
        checkpoint()
        try:
            return operation()
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


class PhaseWorkerSession:
    """Retain one isolated interpreter until the owning preparation exits.

    Requests are sequential. Only the caller checks application cancellation;
    the runner thread observes a private stop event and owns process cleanup.
    """

    def __init__(self, python: Path, worker: Path, models: Path) -> None:
        self._python = python
        self._worker = worker
        self._models = models
        self._temporary: TemporaryDirectory[str] | None = None
        self._thread: Thread | None = None
        self._stop = Event()
        self._done = Event()
        self._error: Exception | None = None
        self._sequence = 0
        self._closed = False
        self._last_supports_mix_overlap = False
        self._activity = PhaseActivity(PhaseStage.LOADING)
        self._request_lock = Lock()
        self._close_lock = Lock()

    @property
    def activity(self) -> PhaseActivity:
        return self._activity

    def _read_activity(self, directory: Path) -> None:
        # Advisory only: never trust it for scheduling, provenance or completion.
        try:
            with (directory / "activity.json").open("rb") as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                return
            value: object = json.loads(raw)
            if not isinstance(value, dict):
                return
            data = cast("dict[str, object]", value)
            stage, backend, name = (
                data.get("stage"),
                data.get("backend"),
                data.get("device_name"),
            )
            if (
                type(data.get("sequence")) is not int
                or data.get("sequence") != self._sequence
                or stage not in (PhaseStage.LOADING, PhaseStage.SOURCES)
                or backend not in ("", "cpu", "cuda", "mps")
                or not isinstance(name, str)
                or len(name) > 160
                or any(ord(character) < 32 for character in name)
            ):
                return
            self._activity = PhaseActivity(PhaseStage(str(stage)), str(backend), name)
        except (OSError, ValueError):
            return

    @property
    def last_supports_mix_overlap(self) -> bool:
        """Optional capability from the last accepted response, never a receipt."""
        return self._last_supports_mix_overlap

    def _start(self) -> Path:
        if self._closed:
            raise RuntimeError("Phase worker session is closed")
        if self._temporary is not None:
            return Path(self._temporary.name)
        self._temporary = TemporaryDirectory(prefix="iopenpod-phase-job-")
        directory = Path(self._temporary.name)

        def checkpoint() -> None:
            if self._stop.is_set():
                raise InterruptedError("Phase worker stopped")

        def run() -> None:
            try:
                run_media_tool(
                    HostPath(self._python),
                    (
                        "-I",
                        str(self._worker),
                        "--models",
                        str(self._models),
                        "--serve",
                        str(directory),
                    ),
                    checkpoint=checkpoint,
                    timeout_seconds=24 * 3600,
                    max_output_bytes=4096,
                    max_stderr_bytes=4 * 1024 * 1024,
                    low_priority=True,
                    keep_stdin_open=True,
                )
            except Exception as error:
                self._error = error
            finally:
                self._done.set()

        self._thread = Thread(target=run, name="phase-worker")
        self._thread.start()
        return directory

    def request(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
        checkpoint: Callable[[], None],
    ) -> tuple[Path, str]:
        """Return private evidence valid until the next request or close."""
        if not self._request_lock.acquire(blocking=False):
            raise RuntimeError("Phase worker already has a request in progress")
        try:
            return self._request(
                pcm, sample_rate=sample_rate, channels=channels, checkpoint=checkpoint
            )
        except BaseException:
            # Cleanup must not replace a cancellation or the original failure.
            try:
                self.close()
            except OSError:
                logging.getLogger(__name__).exception(
                    "Could not remove the stopped Phase worker's private files"
                )
            raise
        finally:
            self._request_lock.release()

    def _request(
        self,
        pcm: bytes,
        *,
        sample_rate: int,
        channels: int,
        checkpoint: Callable[[], None],
    ) -> tuple[Path, str]:
        checkpoint()
        self._last_supports_mix_overlap = False
        self._activity = PhaseActivity(PhaseStage.LOADING)
        directory = self._start()
        self._sequence += 1
        response = directory / "response.json"
        _retry_access(lambda: response.unlink(missing_ok=True), checkpoint)
        target = directory / "parts.npz"
        _retry_access(lambda: target.unlink(missing_ok=True), checkpoint)
        (directory / "audio.f32").write_bytes(pcm)
        request = directory / "request.pending"
        request.write_text(
            json.dumps(
                {
                    "protocol": 2,
                    "sequence": self._sequence,
                    "rate": sample_rate,
                    "channels": channels,
                }
            ),
            encoding="utf-8",
        )
        _retry_access(lambda: request.replace(directory / "request.json"), checkpoint)
        deadline = time.monotonic() + _TRACK_TIMEOUT_SECONDS
        next_activity = 0.0

        def read_response() -> bytes:
            with response.open("rb") as stream:
                return stream.read(4097)

        while True:
            if time.monotonic() >= next_activity:
                self._read_activity(directory)
                next_activity = time.monotonic() + 0.25
            checkpoint()
            if self._done.is_set():
                if self._error is not None:
                    raise RuntimeError("Phase worker failed") from self._error
                raise RuntimeError("Phase worker exited before completing analysis")
            if response.is_file():
                raw = _retry_access(read_response, checkpoint)
                if len(raw) > 4096:
                    raise ValueError("Invalid Phase worker result size")
                value: object = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError("Invalid Phase worker result")
                result = cast("dict[str, object]", value)
                identity = result.get("identity")
                supports_mix_overlap = result.get("supports_mix_overlap", False)
                if (
                    type(result.get("protocol")) is not int
                    or result.get("protocol") != 2
                    or type(result.get("sequence")) is not int
                    or result.get("sequence") != self._sequence
                    or not isinstance(identity, str)
                    or not 0 < len(identity) <= 512
                    or type(supports_mix_overlap) is not bool
                ):
                    raise ValueError("Invalid Phase worker result")
                checkpoint()
                self._last_supports_mix_overlap = supports_mix_overlap
                return target, identity
            if time.monotonic() >= deadline:
                raise TimeoutError("Phase worker exceeded its Track deadline")
            self._done.wait(0.05)

    def close(self) -> None:
        """Reap the child before removing its private inputs and outputs."""
        with self._close_lock:
            self._closed = True
            self._last_supports_mix_overlap = False
            self._activity = PhaseActivity(PhaseStage.LOADING)
            self._stop.set()
            if self._thread is not None and self._thread.ident is not None:
                self._thread.join()
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None
